from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, MessageConflictError
from liyans.core.tenant import TenantContext, current_tenant
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import (
    AuditEventModel,
    IdempotencyRecordModel,
    IdempotencyStatus,
    OutboxMessageModel,
)
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    TransactionIsolation,
    TransactionRetryPolicy,
)
from liyans.infrastructure.observability.audit import (
    GENESIS_HASH,
    AuditDraft,
    build_audit_record,
)
from liyans.infrastructure.persistence.outbox import OutboxMessage
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

IDEMPOTENCY_RETENTION = timedelta(days=1)
OUTBOX_RETENTION = timedelta(days=7)
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9:_\-.]{32,160}$")
MutationCallback = Callable[[AsyncSession, TenantContext], Awaitable[dict[str, Any]]]


class KnowledgeTransactionCoordinator:
    def __init__(
        self,
        database: DatabaseSessionManager,
        outbox: PostgresOutboxRepository,
        *,
        instance_id: str,
        build_version: str,
    ) -> None:
        self._database = database
        self._outbox = outbox
        self._instance_id = instance_id
        self._build_version = build_version

    async def execute(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_document: dict[str, Any],
        callback: MutationCallback,
    ) -> dict[str, Any]:
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "Idempotency-Key must contain 32 to 160 safe characters.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            )
        digest = canonical_sha256({"operation": operation, "request": request_document})
        context = current_tenant()

        async def transaction(session: AsyncSession) -> dict[str, Any]:
            duplicate = await self._reserve_idempotency(
                session,
                context,
                idempotency_key,
                operation,
                digest,
            )
            if duplicate is not None:
                return duplicate
            result = await callback(session, context)
            await self._complete_idempotency(session, context, idempotency_key, result)
            return result

        try:
            return await self._database.run_transaction(
                transaction,
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=8),
            )
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if sqlstate == "23505":
                raise self.conflict(
                    "The Topic 4 knowledge mutation violates an immutable uniqueness rule."
                ) from exc
            raise LiyanError(
                ErrorCode.TOPIC4_INTEGRITY_FAILED,
                "The Topic 4 knowledge mutation violates a persistence constraint.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            ) from exc

    async def append_audit(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        action: str,
        target_ref: str,
        metadata: dict[str, Any],
    ) -> UUID:
        await self.lock(session, f"audit:{context.tenant_id}")
        result = await session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.tenant_id == context.tenant_id)
            .order_by(AuditEventModel.sequence.desc())
            .limit(1)
        )
        previous = result.scalar_one_or_none()
        record = build_audit_record(
            AuditDraft(
                tenant_id=context.tenant_id,
                category="TOPIC4",
                action=action,
                outcome="SUCCEEDED",
                actor_ref=context.subject_ref,
                target_ref=target_ref,
                trace_id=context.trace_id,
                envelope_id=None,
                metadata=metadata,
                occurred_at=datetime.now(UTC),
            ),
            0 if previous is None else previous.sequence + 1,
            GENESIS_HASH if previous is None else previous.event_hash,
        )
        session.add(
            AuditEventModel(
                event_id=record.event_id,
                tenant_id=record.tenant_id,
                sequence=record.sequence,
                category=record.category,
                action=record.action,
                outcome=record.outcome,
                actor_ref=record.actor_ref,
                target_ref=record.target_ref,
                trace_id=record.trace_id,
                envelope_id=None,
                event_metadata=record.metadata,
                occurred_at=record.occurred_at,
                previous_hash=record.previous_hash,
                event_hash=record.event_hash,
            )
        )
        await session.flush()
        return record.event_id

    async def completed_result(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_document: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "Idempotency-Key must contain 32 to 160 safe characters.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            )
        context = current_tenant()
        digest = canonical_sha256({"operation": operation, "request": request_document})
        async with self._database.transaction(context=current_session_context()) as session:
            result = await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.tenant_id == context.tenant_id,
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
                )
            )
            record = result.scalar_one_or_none()
        if record is None:
            return None
        if record.operation != operation or record.request_digest != digest:
            raise MessageConflictError(
                ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                "The idempotency key was reused for different request content.",
            )
        if record.state == IdempotencyStatus.COMPLETED.value:
            if not isinstance(record.result_payload, dict):
                raise self.conflict("The completed idempotency result is unavailable.")
            return dict(record.result_payload)
        now = datetime.now(UTC)
        if record.lease_expires_at is not None and record.lease_expires_at > now:
            raise self.conflict("The idempotent Topic 4 knowledge operation is in progress.")
        return None

    async def append_outbox(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        partition_key: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        await self.lock(session, f"outbox:{partition_key}")
        result = await session.execute(
            select(func.coalesce(func.max(OutboxMessageModel.sequence) + 1, 0)).where(
                OutboxMessageModel.tenant_id == context.tenant_id,
                OutboxMessageModel.partition_key == partition_key,
            )
        )
        sequence = int(result.scalar_one())
        now = datetime.now(UTC)
        correlation_id = uuid4()
        envelope = Topic3EnvelopeV1(
            schema_version="topic3.envelope.v1",
            envelope_id=uuid4(),
            event_type=event_type,
            message_kind=MessageKind.EVENT,
            tenant_id=context.tenant_id,
            session_id=context.session_id or correlation_id,
            subject_ref=context.subject_ref,
            correlation_id=correlation_id,
            causation_id=None,
            sequence=sequence,
            partition_key=partition_key,
            producer=ProducerMetadataV1(
                agent=None,
                service="topic4-knowledge-service",
                instance_id=self._instance_id,
                build_version=self._build_version,
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=f"topic4-c2:{canonical_sha256(payload)}",
                available_at=now,
                expires_at=now + OUTBOX_RETENTION,
            ),
            resource=None,
            trace_id=context.trace_id,
            span_id=None,
            created_at=now,
            error=None,
            payload=payload,
        )
        await self._outbox.append(
            session,
            OutboxMessage(
                outbox_id=uuid4(),
                tenant_id=context.tenant_id,
                envelope=envelope,
                created_at=now,
                available_at=now,
                published_at=None,
                max_attempts=envelope.delivery.max_attempts,
            ),
        )

    @staticmethod
    async def lock(session: AsyncSession, key: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": key},
        )

    async def _reserve_idempotency(
        self,
        session: AsyncSession,
        context: TenantContext,
        key: str,
        operation: str,
        digest: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        statement = (
            insert(IdempotencyRecordModel)
            .values(
                tenant_id=context.tenant_id,
                idempotency_key=key,
                operation=operation,
                request_digest=digest,
                state=IdempotencyStatus.PROCESSING.value,
                lease_owner=self._instance_id,
                lease_expires_at=now + timedelta(minutes=5),
                expires_at=now + IDEMPOTENCY_RETENTION,
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
            return None
        result = await session.execute(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        record = result.scalar_one()
        if record.request_digest != digest or record.operation != operation:
            raise MessageConflictError(
                ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                "The idempotency key was reused for different request content.",
            )
        if record.state == IdempotencyStatus.COMPLETED.value:
            if not isinstance(record.result_payload, dict):
                raise self.conflict("The completed idempotency result is unavailable.")
            return dict(record.result_payload)
        if record.lease_expires_at is not None and record.lease_expires_at > now:
            raise self.conflict("The idempotent Topic 4 knowledge operation is in progress.")
        record.state = IdempotencyStatus.PROCESSING.value
        record.lease_owner = self._instance_id
        record.lease_expires_at = now + timedelta(minutes=5)
        record.expires_at = now + IDEMPOTENCY_RETENTION
        record.updated_at = now
        return None

    @staticmethod
    async def _complete_idempotency(
        session: AsyncSession,
        context: TenantContext,
        key: str,
        result_payload: dict[str, Any],
    ) -> None:
        result = await session.execute(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        record = result.scalar_one()
        record.state = IdempotencyStatus.COMPLETED.value
        record.lease_owner = None
        record.lease_expires_at = None
        record.response_status_code = 200
        record.result_payload = result_payload
        record.updated_at = datetime.now(UTC)

    @staticmethod
    def conflict(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_CONFLICT,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )

    @staticmethod
    def not_found(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_NOT_FOUND,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=404,
        )

    @staticmethod
    def integrity(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_INTEGRITY_FAILED,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )
