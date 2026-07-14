from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, MessageConflictError
from liyans.core.tenant import current_tenant
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import (
    IdempotencyRecordModel,
    IdempotencyStatus,
)
from liyans.infrastructure.database.session import DatabaseSessionManager
from liyans.infrastructure.messaging.idempotency import (
    IdempotencyRecord,
    IdempotencyState,
    ReservationDecision,
)


class PostgresIdempotencyStore:
    def __init__(
        self,
        database: DatabaseSessionManager,
        *,
        instance_id: str,
        retention_seconds: float = 86_400,
        processing_lease_seconds: float = 120,
    ) -> None:
        if not instance_id or len(instance_id) > 128:
            raise ValueError("instance_id must contain between one and 128 characters")
        if retention_seconds <= 0 or processing_lease_seconds <= 0:
            raise ValueError("idempotency retention and lease durations must be positive")
        self._database = database
        self._instance_id = instance_id
        self._retention = timedelta(seconds=retention_seconds)
        self._processing_lease = timedelta(seconds=processing_lease_seconds)

    async def reserve(self, key: str, digest: str) -> ReservationDecision:
        tenant_id = current_tenant().tenant_id
        now = datetime.now(UTC)
        async with self._database.transaction(context=current_session_context()) as session:
            statement = (
                insert(IdempotencyRecordModel)
                .values(
                    tenant_id=tenant_id,
                    idempotency_key=key,
                    operation="topic3.message",
                    request_digest=digest,
                    state=IdempotencyStatus.BUFFERED.value,
                    lease_owner=self._instance_id,
                    lease_expires_at=now + self._processing_lease,
                    expires_at=now + self._retention,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        IdempotencyRecordModel.tenant_id,
                        IdempotencyRecordModel.idempotency_key,
                    ]
                )
                .returning(IdempotencyRecordModel.idempotency_key)
            )
            inserted = (await session.execute(statement)).scalar_one_or_none()
            if inserted is not None:
                return ReservationDecision.RESERVED

            record = await self._locked_record(session, tenant_id, key)
            if record.expires_at <= now:
                record.operation = "topic3.message"
                record.request_digest = digest
                record.state = IdempotencyStatus.BUFFERED.value
                record.lease_owner = self._instance_id
                record.lease_expires_at = now + self._processing_lease
                record.response_status_code = None
                record.result_payload = None
                record.expires_at = now + self._retention
                record.created_at = now
                record.updated_at = now
                return ReservationDecision.RESERVED

            self._assert_digest(record, digest)
            if (
                record.state
                in {
                    IdempotencyStatus.BUFFERED.value,
                    IdempotencyStatus.PROCESSING.value,
                }
                and record.lease_expires_at is not None
                and record.lease_expires_at <= now
            ):
                record.state = IdempotencyStatus.BUFFERED.value
                record.lease_owner = self._instance_id
                record.lease_expires_at = now + self._processing_lease
                record.updated_at = now
                return ReservationDecision.RESERVED

            return ReservationDecision(f"DUPLICATE_{record.state}")

    async def mark_processing(self, key: str, digest: str) -> None:
        tenant_id = current_tenant().tenant_id
        now = datetime.now(UTC)
        async with self._database.transaction(context=current_session_context()) as session:
            record = await self._locked_record(session, tenant_id, key)
            self._assert_digest(record, digest)
            if record.state == IdempotencyStatus.COMPLETED.value:
                raise LiyanError(
                    ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                    "A completed idempotency record cannot return to processing.",
                    category=ErrorCategory.MESSAGING,
                    status_code=409,
                )
            if (
                record.lease_owner != self._instance_id
                and record.lease_expires_at is not None
                and record.lease_expires_at > now
            ):
                raise LiyanError(
                    ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                    "The idempotent operation is leased by another worker.",
                    category=ErrorCategory.MESSAGING,
                    retriable=True,
                    status_code=409,
                )
            record.state = IdempotencyStatus.PROCESSING.value
            record.lease_owner = self._instance_id
            record.lease_expires_at = now + self._processing_lease
            record.updated_at = now

    async def complete(self, key: str, digest: str) -> None:
        tenant_id = current_tenant().tenant_id
        now = datetime.now(UTC)
        async with self._database.transaction(context=current_session_context()) as session:
            record = await self._locked_record(session, tenant_id, key)
            self._assert_digest(record, digest)
            if record.state == IdempotencyStatus.COMPLETED.value:
                return
            if (
                record.state != IdempotencyStatus.PROCESSING.value
                or record.lease_owner != self._instance_id
            ):
                raise LiyanError(
                    ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                    "Only the active idempotency lease owner can complete the operation.",
                    category=ErrorCategory.MESSAGING,
                    retriable=True,
                    status_code=409,
                )
            record.state = IdempotencyStatus.COMPLETED.value
            record.lease_owner = None
            record.lease_expires_at = None
            record.updated_at = now

    async def abort(self, key: str, digest: str) -> None:
        tenant_id = current_tenant().tenant_id
        async with self._database.transaction(context=current_session_context()) as session:
            result = await session.execute(
                select(IdempotencyRecordModel)
                .where(
                    IdempotencyRecordModel.tenant_id == tenant_id,
                    IdempotencyRecordModel.idempotency_key == key,
                )
                .with_for_update()
            )
            record = result.scalar_one_or_none()
            if record is None:
                return
            self._assert_digest(record, digest)
            if (
                record.state == IdempotencyStatus.PROCESSING.value
                and record.lease_owner != self._instance_id
            ):
                raise LiyanError(
                    ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                    "Only the active idempotency lease owner can abort the operation.",
                    category=ErrorCategory.MESSAGING,
                    retriable=True,
                    status_code=409,
                )
            if record.state != IdempotencyStatus.COMPLETED.value:
                await session.delete(record)

    async def get(self, key: str) -> IdempotencyRecord | None:
        tenant_id = current_tenant().tenant_id
        async with self._database.transaction(context=current_session_context()) as session:
            result = await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.tenant_id == tenant_id,
                    IdempotencyRecordModel.idempotency_key == key,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            return IdempotencyRecord(
                key=record.idempotency_key,
                digest=record.request_digest,
                state=IdempotencyState(record.state),
            )

    @staticmethod
    async def _locked_record(
        session: AsyncSession,
        tenant_id: str,
        key: str,
    ) -> IdempotencyRecordModel:
        result = await session.execute(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise LiyanError(
                ErrorCode.INTERNAL,
                "The idempotency reservation is missing.",
                category=ErrorCategory.MESSAGING,
                status_code=500,
            )
        return record

    @staticmethod
    def _assert_digest(record: IdempotencyRecordModel, digest: str) -> None:
        if record.request_digest != digest:
            raise MessageConflictError(
                ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                "The idempotency key was reused for different message content.",
            )
