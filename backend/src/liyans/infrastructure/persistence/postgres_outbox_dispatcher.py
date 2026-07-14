from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from liyans_contracts.envelope import Topic3EnvelopeV1
from sqlalchemy import case, exists, func, select, update
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
            earlier = aliased(OutboxMessageModel)
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
            result = await session.execute(
                select(OutboxMessageModel)
                .where(
                    OutboxMessageModel.state == OutboxStatus.PENDING.value,
                    OutboxMessageModel.available_at <= now,
                    OutboxMessageModel.attempts < OutboxMessageModel.max_attempts,
                    OutboxMessageModel.sequence == published_cursor,
                    ~exists(
                        select(1).where(
                            earlier.tenant_id == OutboxMessageModel.tenant_id,
                            earlier.partition_key == OutboxMessageModel.partition_key,
                            earlier.sequence < OutboxMessageModel.sequence,
                            earlier.state != OutboxStatus.PUBLISHED.value,
                        )
                    ),
                )
                .order_by(
                    priority_order,
                    OutboxMessageModel.available_at,
                    OutboxMessageModel.created_at,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = list(result.scalars())
            for row in rows:
                row.state = OutboxStatus.CLAIMED.value
                row.claimed_by = worker_id
                row.claimed_at = now
                row.claim_expires_at = now + self._claim_lease
                row.attempts += 1
                row.updated_at = now
            return [self._to_message(row) for row in rows]

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
                OutboxMessageModel.attempts >= OutboxMessageModel.max_attempts,
            )
            .values(
                state=OutboxStatus.DEAD.value,
                claimed_by=None,
                claimed_at=None,
                claim_expires_at=None,
                updated_at=now,
            )
        )
        await session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.state == OutboxStatus.CLAIMED.value,
                OutboxMessageModel.claim_expires_at <= now,
                OutboxMessageModel.attempts < OutboxMessageModel.max_attempts,
            )
            .values(
                state=OutboxStatus.PENDING.value,
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
    def _to_message(row: OutboxMessageModel) -> OutboxMessage:
        return OutboxMessage(
            outbox_id=row.outbox_id,
            tenant_id=row.tenant_id,
            envelope=Topic3EnvelopeV1.model_validate(row.envelope_document),
            created_at=row.created_at,
            available_at=row.available_at,
            published_at=row.published_at,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
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
