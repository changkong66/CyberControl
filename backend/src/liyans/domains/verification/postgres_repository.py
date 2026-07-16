from __future__ import annotations

from uuid import UUID

from liyans_contracts.verification import (
    VerificationAcceptedPayloadV1,
    VerificationRequestPayloadV1,
    VerificationStateChangedPayloadV1,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant

from .entities import VerificationRecord, VerificationStateRecord
from .models import Topic4VerificationModel, Topic4VerificationStateModel


class PostgresVerificationRepository:
    async def append_verification(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: VerificationRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        request = record.request
        accepted = record.accepted
        source = request.source_snapshot_ref
        session.add(
            Topic4VerificationModel(
                verification_record_id=record.verification_record_id,
                verification_id=request.verification_id,
                idempotency_key=request.idempotency_key,
                trigger=request.trigger.value,
                parent_verification_id=request.parent_verification_id,
                source_candidate_id=source.candidate_id,
                source_candidate_version=source.candidate_version,
                source_candidate_sha256=source.candidate_sha256,
                requested_profile=request.requested_profile.value,
                binding_document=accepted.binding.model_dump(mode="json"),
                accepted_document=accepted.model_dump(mode="json"),
                request_document=request.model_dump(mode="json"),
                accepted_at=accepted.accepted_at,
                deadline_at=accepted.deadline_at,
                tenant_id=tenant_id,
                trace_id=accepted.trace_id,
                version_cas=accepted.version_cas,
                record_sha256=accepted.record_sha256,
                immutable=accepted.immutable,
                audit_event_id=audit_event_id,
                created_at=accepted.created_at,
            )
        )
        await session.flush()

    async def get_verification(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> VerificationRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4VerificationModel).where(
                Topic4VerificationModel.tenant_id == tenant_id,
                Topic4VerificationModel.verification_id == verification_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return VerificationRecord(
            verification_record_id=row.verification_record_id,
            request=VerificationRequestPayloadV1.model_validate(row.request_document),
            accepted=VerificationAcceptedPayloadV1.model_validate(row.accepted_document),
        )

    async def append_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: VerificationStateRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        change = record.change
        session.add(
            Topic4VerificationStateModel(
                state_snapshot_id=record.state_snapshot_id,
                verification_id=change.verification_id,
                state_version=change.state_version,
                previous_state=None
                if change.previous_state is None
                else change.previous_state.value,
                current_state=change.current_state.value,
                reason_code=change.reason_code,
                revision_round=change.revision_round,
                state_document=change.model_dump(mode="json"),
                changed_at=change.changed_at,
                tenant_id=tenant_id,
                trace_id=change.trace_id,
                version_cas=change.version_cas,
                record_sha256=change.record_sha256,
                immutable=change.immutable,
                audit_event_id=audit_event_id,
                created_at=change.created_at,
            )
        )
        await session.flush()

    async def latest_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> VerificationStateRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4VerificationStateModel)
            .where(
                Topic4VerificationStateModel.tenant_id == tenant_id,
                Topic4VerificationStateModel.verification_id == verification_id,
            )
            .order_by(Topic4VerificationStateModel.state_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return VerificationStateRecord(
            state_snapshot_id=row.state_snapshot_id,
            change=VerificationStateChangedPayloadV1.model_validate(row.state_document),
        )

    @staticmethod
    def _assert_write(session: AsyncSession, tenant_id: str) -> None:
        assert_tenant(tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Topic 4 persistence requires an active transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
