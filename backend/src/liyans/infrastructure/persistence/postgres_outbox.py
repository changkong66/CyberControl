from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from liyans_contracts.envelope import Topic3EnvelopeV1
from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.hashing import sha256_hex
from liyans.core.tenant import assert_tenant, current_tenant
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import OutboxMessageModel, OutboxStatus
from liyans.infrastructure.database.session import DatabaseSessionManager
from liyans.infrastructure.persistence.outbox import OutboxMessage


class PostgresOutboxRepository:
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

    async def append(self, session: AsyncSession, message: OutboxMessage) -> None:
        assert_tenant(message.tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Outbox append requires the active business transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        if message.published_at is not None or message.attempts != 0:
            raise ValueError("new outbox messages cannot be pre-published or pre-attempted")
        if message.max_attempts != message.envelope.delivery.max_attempts:
            raise ValueError("outbox max_attempts must match the Envelope delivery contract")
        if message.created_at.tzinfo is None or message.available_at.tzinfo is None:
            raise ValueError("outbox timestamps must be timezone-aware")
        document = message.envelope.model_dump(mode="json")
        session.add(
            OutboxMessageModel(
                outbox_id=message.outbox_id,
                tenant_id=message.tenant_id,
                envelope_id=message.envelope.envelope_id,
                event_type=message.envelope.event_type,
                message_kind=message.envelope.message_kind.value,
                partition_key=message.envelope.partition_key,
                sequence=message.envelope.sequence,
                envelope_document=document,
                envelope_sha256=sha256_hex(document),
                state=OutboxStatus.PENDING.value,
                priority=message.envelope.delivery.priority.value,
                attempts=message.attempts,
                max_attempts=message.max_attempts,
                available_at=message.available_at,
                published_at=message.published_at,
                created_at=message.created_at,
                updated_at=message.created_at,
            )
        )
        await session.flush()

    async def claim_batch(self, worker_id: str, limit: int) -> list[OutboxMessage]:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain between one and 128 characters")
        if not 1 <= limit <= 1000:
            raise ValueError("outbox claim limit must be between one and 1000")
        tenant_id = current_tenant().tenant_id
        now = datetime.now(UTC)
        async with self._database.transaction(context=current_session_context()) as session:
            await self._recover_expired_claims(session, tenant_id, now)
            priority_order = case(
                (OutboxMessageModel.priority == "CRITICAL", 0),
                (OutboxMessageModel.priority == "HIGH", 1),
                (OutboxMessageModel.priority == "NORMAL", 2),
                else_=3,
            )
            result = await session.execute(
                select(OutboxMessageModel)
                .where(
                    OutboxMessageModel.tenant_id == tenant_id,
                    OutboxMessageModel.state == OutboxStatus.PENDING.value,
                    OutboxMessageModel.available_at <= now,
                    OutboxMessageModel.attempts < OutboxMessageModel.max_attempts,
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
        tenant_id = current_tenant().tenant_id
        result = None
        async with self._database.transaction(context=current_session_context()) as session:
            result = await session.execute(
                update(OutboxMessageModel)
                .where(
                    OutboxMessageModel.tenant_id == tenant_id,
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
        tenant_id = current_tenant().tenant_id
        async with self._database.transaction(context=current_session_context()) as session:
            result = await session.execute(
                select(OutboxMessageModel)
                .where(
                    OutboxMessageModel.tenant_id == tenant_id,
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

    @staticmethod
    async def _recover_expired_claims(
        session: AsyncSession,
        tenant_id: str,
        now: datetime,
    ) -> None:
        await session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.tenant_id == tenant_id,
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
                OutboxMessageModel.tenant_id == tenant_id,
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
