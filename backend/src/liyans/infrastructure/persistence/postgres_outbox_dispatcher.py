from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from liyans_contracts.envelope import Topic3EnvelopeV1
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.infrastructure.database.models import OutboxMessageModel, OutboxStatus
from liyans.infrastructure.database.session import DatabaseSessionManager
from liyans.infrastructure.persistence.outbox import OutboxMessage


class PostgresOutboxDispatcherRepository:
    """Cross-tenant Outbox access through the least-privilege dispatcher DB role."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        *,
        claim_lease_seconds: float = 30,
    ) -> None:
        if claim_lease_seconds <= 0:
            raise ValueError("claim_lease_seconds must be positive")
        self._database = database
        self._claim_lease = timedelta(seconds=claim_lease_seconds)

    async def claim_batch(self, worker_id: str, limit: int) -> list[OutboxMessage]:
        self._validate_claim_request(worker_id, limit)
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            await self._recover_expired_claims(session, now)
            published = aliased(OutboxMessageModel)
            published_cursor = (
                select(func.coalesce(func.max(published.sequence) + 1, 0))
                .where(
                    published.tenant_id == OutboxMessageModel.tenant_id,
                    published.partition_key == OutboxMessageModel.partition_key,
                    published.state == OutboxStatus.PUBLISHED.value,
                )
                .correlate(OutboxMessageModel)
                .scalar_subquery()
            )
            priority_order = case(
                (OutboxMessageModel.priority == "CRITICAL", 0),
                (OutboxMessageModel.priority == "HIGH", 1),
                (OutboxMessageModel.priority == "NORMAL", 2),
                else_=3,
            )
            candidate_limit = min(10_000, max(limit, limit * 8))
            result = await session.execute(
                select(
                    OutboxMessageModel,
                    published_cursor.label("published_cursor"),
                )
                .where(
                    OutboxMessageModel.state == OutboxStatus.PENDING.value,
                    OutboxMessageModel.available_at <= now,
                    OutboxMessageModel.attempts < OutboxMessageModel.max_attempts,
                )
                .order_by(
                    priority_order,
                    OutboxMessageModel.available_at,
                    OutboxMessageModel.created_at,
                    OutboxMessageModel.tenant_id,
                    OutboxMessageModel.partition_key,
                    OutboxMessageModel.sequence,
                )
                .limit(candidate_limit)
                .with_for_update(skip_locked=True)
            )
            grouped: dict[
                tuple[str, str],
                tuple[int, list[OutboxMessageModel]],
            ] = {}
            for row, cursor in result.all():
                key = (row.tenant_id, row.partition_key)
                if key not in grouped:
                    grouped[key] = (int(cursor), [])
                grouped[key][1].append(row)
            partitions: list[list[OutboxMessageModel]] = []
            published_cursors: dict[UUID, int] = {}
            for cursor, candidates in grouped.values():
                contiguous: list[OutboxMessageModel] = []
                expected = cursor
                for row in sorted(candidates, key=lambda item: item.sequence):
                    if row.sequence < expected:
                        continue
                    if row.sequence != expected:
                        break
                    contiguous.append(row)
                    expected += 1
                if contiguous:
                    published_cursors.update(
                        {row.outbox_id: cursor + index for index, row in enumerate(contiguous)}
                    )
                    partitions.append(contiguous)
            partitions.sort(
                key=lambda items: (
                    {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2}.get(items[0].priority, 3),
                    items[0].available_at,
                    items[0].created_at,
                )
            )
            rows: list[OutboxMessageModel] = []
            while len(rows) < limit:
                progressed = False
                for partition in partitions:
                    if partition and len(rows) < limit:
                        rows.append(partition.pop(0))
                        progressed = True
                if not progressed:
                    break
            for row in rows:
                row.state = OutboxStatus.CLAIMED.value
                row.claimed_by = worker_id
                row.claimed_at = now
                row.claim_expires_at = now + self._claim_lease
                row.attempts += 1
                row.updated_at = now
            return [
                self._to_message(
                    row,
                    published_cursor=published_cursors.get(row.outbox_id),
                )
                for row in rows
            ]

    async def list_tenant_ids(
        self,
        *,
        event_type: str,
        after_tenant_id: str | None,
        limit: int,
    ) -> list[str]:
        """Discover recovery tenants from the dispatcher role's existing Outbox grant."""

        if not event_type or len(event_type) > 128:
            raise ValueError("event_type must contain between one and 128 characters")
        if not 1 <= limit <= 1000:
            raise ValueError("tenant catalog limit must be between one and 1000")
        statement = select(OutboxMessageModel.tenant_id).where(
            OutboxMessageModel.event_type == event_type
        )
        if after_tenant_id is not None:
            statement = statement.where(OutboxMessageModel.tenant_id > after_tenant_id)
        async with self._database.transaction() as session:
            result = await session.execute(
                statement.distinct().order_by(OutboxMessageModel.tenant_id).limit(limit)
            )
            return list(result.scalars())

    async def mark_published(
        self,
        outbox_id: UUID,
        worker_id: str,
        published_at: datetime,
    ) -> None:
        if published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware")
        async with self._database.transaction() as session:
            result = await session.execute(
                update(OutboxMessageModel)
                .where(
                    OutboxMessageModel.outbox_id == outbox_id,
                    OutboxMessageModel.state == OutboxStatus.CLAIMED.value,
                    OutboxMessageModel.claimed_by == worker_id,
                )
                .values(
                    state=OutboxStatus.PUBLISHED.value,
                    published_at=published_at,
                    claimed_by=None,
                    claimed_at=None,
                    claim_expires_at=None,
                    last_error_code=None,
                    updated_at=published_at,
                )
            )
        if result.rowcount != 1:
            raise self._claim_conflict()

    async def release_claim(
        self,
        outbox_id: UUID,
        worker_id: str,
        available_at: datetime,
        *,
        error_code: str | None = None,
        restore_attempt: bool = False,
    ) -> None:
        if available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        async with self._database.transaction() as session:
            result = await session.execute(
                select(OutboxMessageModel)
                .where(
                    OutboxMessageModel.outbox_id == outbox_id,
                    OutboxMessageModel.state == OutboxStatus.CLAIMED.value,
                    OutboxMessageModel.claimed_by == worker_id,
                )
                .with_for_update()
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise self._claim_conflict()
            if restore_attempt:
                row.attempts = max(0, row.attempts - 1)
            row.state = (
                OutboxStatus.DEAD.value
                if row.attempts >= row.max_attempts
                else OutboxStatus.PENDING.value
            )
            row.available_at = available_at
            row.claimed_by = None
            row.claimed_at = None
            row.claim_expires_at = None
            row.last_error_code = error_code
            row.updated_at = datetime.now(UTC)

    async def renew_claims(
        self,
        outbox_ids: tuple[UUID, ...],
        worker_id: str,
    ) -> datetime:
        unique_ids = tuple(dict.fromkeys(outbox_ids))
        if not unique_ids or len(unique_ids) > 1000:
            raise ValueError("outbox_ids must contain between one and 1000 unique values")
        if len(unique_ids) != len(outbox_ids):
            raise ValueError("outbox_ids cannot contain duplicates")
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain between one and 128 characters")
        now = datetime.now(UTC)
        claim_expires_at = now + self._claim_lease
        async with self._database.transaction() as session:
            result = await session.execute(
                update(OutboxMessageModel)
                .where(
                    OutboxMessageModel.outbox_id.in_(unique_ids),
                    OutboxMessageModel.state == OutboxStatus.CLAIMED.value,
                    OutboxMessageModel.claimed_by == worker_id,
                )
                .values(
                    claim_expires_at=claim_expires_at,
                    updated_at=now,
                )
            )
        if result.rowcount != len(unique_ids):
            raise self._claim_conflict()
        return claim_expires_at

    async def published_cursor(self, tenant_id: str, partition_key: str) -> int:
        if not tenant_id or not partition_key:
            raise ValueError("tenant_id and partition_key are required")
        async with self._database.transaction() as session:
            result = await session.execute(
                select(func.coalesce(func.max(OutboxMessageModel.sequence) + 1, 0)).where(
                    OutboxMessageModel.tenant_id == tenant_id,
                    OutboxMessageModel.partition_key == partition_key,
                    OutboxMessageModel.state == OutboxStatus.PUBLISHED.value,
                )
            )
            return int(result.scalar_one())

    @staticmethod
    async def _recover_expired_claims(session: AsyncSession, now: datetime) -> None:
        await session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.state == OutboxStatus.CLAIMED.value,
                OutboxMessageModel.claim_expires_at <= now,
                OutboxMessageModel.attempts >= 0,
            )
            .values(
                state=case(
                    (
                        OutboxMessageModel.attempts >= OutboxMessageModel.max_attempts,
                        OutboxStatus.DEAD.value,
                    ),
                    else_=OutboxStatus.PENDING.value,
                ),
                claimed_by=None,
                claimed_at=None,
                claim_expires_at=None,
                updated_at=now,
            )
        )

    @staticmethod
    def _validate_claim_request(worker_id: str, limit: int) -> None:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain between one and 128 characters")
        if not 1 <= limit <= 1000:
            raise ValueError("outbox claim limit must be between one and 1000")

    @staticmethod
    def _to_message(
        row: OutboxMessageModel,
        *,
        published_cursor: int | None = None,
    ) -> OutboxMessage:
        return OutboxMessage(
            outbox_id=row.outbox_id,
            tenant_id=row.tenant_id,
            envelope=Topic3EnvelopeV1.model_validate(row.envelope_document),
            created_at=row.created_at,
            available_at=row.available_at,
            published_at=row.published_at,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            claimed_at=row.claimed_at,
            claim_expires_at=row.claim_expires_at,
            published_cursor=published_cursor,
        )

    @staticmethod
    def _claim_conflict() -> LiyanError:
        return LiyanError(
            ErrorCode.DATABASE_TRANSACTION_STATE,
            "The outbox claim is missing, expired, or owned by another worker.",
            category=ErrorCategory.MESSAGING,
            retriable=True,
            status_code=409,
        )
