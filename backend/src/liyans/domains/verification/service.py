from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic3 import CandidateStatus
from liyans_contracts.verification import (
    VerificationAcceptedPayloadV1,
    VerificationBindingV1,
    VerificationRequestPayloadV1,
    VerificationState,
    VerificationStateChangedPayloadV1,
)
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, MessageConflictError
from liyans.core.tenant import TenantContext, current_tenant
from liyans.domains.topic3.entities import CandidateRecord
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
    AuditRecord,
    build_audit_record,
)
from liyans.infrastructure.persistence.outbox import OutboxMessage
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

from .entities import VerificationRecord, VerificationStateRecord
from .postgres_repository import PostgresVerificationRepository
from .records import build_topic4_record, record_integrity_valid
from .state_machine import InvalidVerificationTransition, VerificationStateMachine

IDEMPOTENCY_RETENTION = timedelta(days=1)
OUTBOX_RETENTION = timedelta(days=7)
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9:_\-.]{32,160}$")
MutationCallback = Callable[[AsyncSession, TenantContext], Awaitable[dict[str, Any]]]


class CandidateSnapshotReader(Protocol):
    async def get_candidate(
        self,
        session: AsyncSession,
        tenant_id: str,
        candidate_id: UUID,
        candidate_version: int,
    ) -> CandidateRecord | None: ...


@dataclass(frozen=True, slots=True)
class VerifierRuntimeVersions:
    state_machine_version: str
    verifier_build_version: str
    policy_version: str
    prompt_bundle_version: str
    retrieval_pipeline_version: str
    knowledge_base_version: str
    toolchain_manifest_version: str
    content_security_policy_version: str
    license_policy_version: str

    def __post_init__(self) -> None:
        values = (
            tuple(self.__dict__.values())
            if hasattr(self, "__dict__")
            else (
                self.state_machine_version,
                self.verifier_build_version,
                self.policy_version,
                self.prompt_bundle_version,
                self.retrieval_pipeline_version,
                self.knowledge_base_version,
                self.toolchain_manifest_version,
                self.content_security_policy_version,
                self.license_policy_version,
            )
        )
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("verifier runtime versions must contain 1 to 128 characters")


class VerificationService:
    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: PostgresVerificationRepository,
        candidate_reader: CandidateSnapshotReader,
        outbox: PostgresOutboxRepository,
        state_machine: VerificationStateMachine,
        versions: VerifierRuntimeVersions,
        *,
        instance_id: str,
    ) -> None:
        self._database = database
        self._repository = repository
        self._candidate_reader = candidate_reader
        self._outbox = outbox
        self._state_machine = state_machine
        self._versions = versions
        self._instance_id = instance_id

    async def accept_verification(
        self,
        request: VerificationRequestPayloadV1,
    ) -> VerificationAcceptedPayloadV1:
        context = current_tenant()
        self._validate_request_context(request, context)
        if not record_integrity_valid(request):
            raise self._integrity_error("Verification request record hash is invalid.")

        request_document = request.model_dump(mode="json")

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._lock(
                session, self._verification_lock(tenant.tenant_id, request.verification_id)
            )
            existing = await self._repository.get_verification(
                session, tenant.tenant_id, request.verification_id
            )
            if existing is not None:
                raise self._conflict("The verification already exists.")

            source = request.source_snapshot_ref
            candidate_record = await self._candidate_reader.get_candidate(
                session,
                tenant.tenant_id,
                source.candidate_id,
                source.candidate_version,
            )
            if candidate_record is None:
                raise self._not_found("Source candidate")
            candidate = candidate_record.candidate
            if candidate.status != CandidateStatus.COMPLETE:
                raise self._integrity_error("Only complete Topic 3 candidates can be verified.")
            if candidate.candidate_sha256 != source.candidate_sha256:
                raise self._integrity_error("Source candidate hash does not match Topic 3.")
            if candidate.resource_type != source.resource_type:
                raise self._integrity_error("Source candidate resource type does not match.")

            now = datetime.now(UTC)
            if request.deadline_at <= now:
                raise self._deadline_error()
            binding = self._build_binding(tenant, now)
            accepted = build_topic4_record(
                VerificationAcceptedPayloadV1,
                trace_id=tenant.trace_id,
                tenant_id=tenant.tenant_id,
                version_cas=1,
                created_at=now,
                immutable=True,
                schema_version="verification.accepted.v1",
                verification_id=request.verification_id,
                idempotency_key=request.idempotency_key,
                state="ACCEPTED",
                state_version=1,
                binding=binding,
                accepted_at=now,
                deadline_at=request.deadline_at,
                source_candidate_id=source.candidate_id,
                source_candidate_version=source.candidate_version,
                source_candidate_sha256=source.candidate_sha256,
                estimated_profile=request.requested_profile,
            )
            state = build_topic4_record(
                VerificationStateChangedPayloadV1,
                trace_id=tenant.trace_id,
                tenant_id=tenant.tenant_id,
                version_cas=1,
                created_at=now,
                immutable=True,
                schema_version="verification.state_changed.v1",
                verification_id=request.verification_id,
                previous_state=None,
                current_state=VerificationState.ACCEPTED,
                state_version=1,
                reason_code="VERIFICATION_ACCEPTED",
                revision_round=0,
                changed_at=now,
            )
            audit = await self._append_audit(
                session,
                tenant,
                action="VERIFICATION_ACCEPTED",
                target_ref=str(request.verification_id),
                metadata={
                    "candidate_id": str(source.candidate_id),
                    "candidate_version": source.candidate_version,
                    "candidate_sha256": source.candidate_sha256,
                    "requested_profile": request.requested_profile.value,
                },
            )
            await self._repository.append_verification(
                session,
                tenant.tenant_id,
                VerificationRecord(
                    verification_record_id=uuid4(),
                    request=request,
                    accepted=accepted,
                ),
                audit.event_id,
            )
            await self._repository.append_state(
                session,
                tenant.tenant_id,
                VerificationStateRecord(state_snapshot_id=uuid4(), change=state),
                audit.event_id,
            )
            await self._append_outbox(
                session,
                tenant,
                verification_id=request.verification_id,
                event_type="topic4.verification.accepted",
                payload={
                    "accepted": accepted.model_dump(mode="json"),
                    "state": state.model_dump(mode="json"),
                },
            )
            return accepted.model_dump(mode="json")

        document = await self._execute_mutation(
            operation="topic4.verification.accept",
            idempotency_key=request.idempotency_key,
            request_document=request_document,
            callback=callback,
        )
        return VerificationAcceptedPayloadV1.model_validate(document)

    async def transition(
        self,
        verification_id: UUID,
        *,
        expected_state_version: int,
        target_state: VerificationState,
        reason_code: str,
        idempotency_key: str,
    ) -> VerificationStateChangedPayloadV1:
        request_document = {
            "verification_id": str(verification_id),
            "expected_state_version": expected_state_version,
            "target_state": target_state.value,
            "reason_code": reason_code,
        }

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._lock(session, self._verification_lock(tenant.tenant_id, verification_id))
            verification = await self._repository.get_verification(
                session, tenant.tenant_id, verification_id
            )
            if verification is None:
                raise self._not_found("Verification")
            current = await self._repository.latest_state(
                session, tenant.tenant_id, verification_id
            )
            if current is None:
                raise self._integrity_error("Verification state history is missing.")
            if current.change.state_version != expected_state_version:
                raise self._version_conflict()

            now = datetime.now(UTC)
            if (
                now >= verification.accepted.deadline_at
                and target_state != VerificationState.EXPIRED
            ):
                raise self._deadline_error()
            try:
                decision = self._state_machine.transition(
                    current.change.current_state,
                    target_state,
                    revision_round=current.change.revision_round,
                )
            except InvalidVerificationTransition as exc:
                raise self._transition_error(str(exc)) from exc

            next_version = current.change.state_version + 1
            change = build_topic4_record(
                VerificationStateChangedPayloadV1,
                trace_id=tenant.trace_id,
                tenant_id=tenant.tenant_id,
                version_cas=next_version,
                created_at=now,
                immutable=True,
                schema_version="verification.state_changed.v1",
                verification_id=verification_id,
                previous_state=decision.previous_state,
                current_state=decision.current_state,
                state_version=next_version,
                reason_code=reason_code,
                revision_round=decision.revision_round,
                changed_at=now,
            )
            audit = await self._append_audit(
                session,
                tenant,
                action="VERIFICATION_STATE_CHANGED",
                target_ref=str(verification_id),
                metadata={
                    "previous_state": decision.previous_state.value,
                    "current_state": decision.current_state.value,
                    "state_version": next_version,
                    "reason_code": reason_code,
                    "revision_round": decision.revision_round,
                },
            )
            await self._repository.append_state(
                session,
                tenant.tenant_id,
                VerificationStateRecord(state_snapshot_id=uuid4(), change=change),
                audit.event_id,
            )
            await self._append_outbox(
                session,
                tenant,
                verification_id=verification_id,
                event_type="topic4.verification.state_changed",
                payload=change.model_dump(mode="json"),
            )
            return change.model_dump(mode="json")

        document = await self._execute_mutation(
            operation="topic4.verification.transition",
            idempotency_key=idempotency_key,
            request_document=request_document,
            callback=callback,
        )
        return VerificationStateChangedPayloadV1.model_validate(document)

    async def get_verification(
        self, verification_id: UUID
    ) -> tuple[VerificationRecord, VerificationStateRecord]:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            verification = await self._repository.get_verification(
                session, context.tenant_id, verification_id
            )
            state = await self._repository.latest_state(session, context.tenant_id, verification_id)
        if verification is None or state is None:
            raise self._not_found("Verification")
        return verification, state

    def _build_binding(self, tenant: TenantContext, now: datetime) -> VerificationBindingV1:
        return build_topic4_record(
            VerificationBindingV1,
            trace_id=tenant.trace_id,
            tenant_id=tenant.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="verification.binding.v1",
            state_machine_version=self._versions.state_machine_version,
            verifier_build_version=self._versions.verifier_build_version,
            policy_version=self._versions.policy_version,
            prompt_bundle_version=self._versions.prompt_bundle_version,
            claim_schema_version="claim.v1",
            retrieval_pipeline_version=self._versions.retrieval_pipeline_version,
            knowledge_base_version=self._versions.knowledge_base_version,
            toolchain_manifest_version=self._versions.toolchain_manifest_version,
            content_security_policy_version=self._versions.content_security_policy_version,
            license_policy_version=self._versions.license_policy_version,
        )

    async def _execute_mutation(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_document: dict[str, Any],
        callback: MutationCallback,
    ) -> dict[str, Any]:
        self._validate_idempotency_key(idempotency_key)
        digest = canonical_sha256({"operation": operation, "request": request_document})
        context = current_tenant()

        async def transaction(session: AsyncSession) -> dict[str, Any]:
            duplicate = await self._reserve_idempotency(
                session, context, idempotency_key, operation, digest
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
                retry_policy=TransactionRetryPolicy(max_attempts=3),
            )
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if sqlstate == "23505":
                raise self._conflict(
                    "The Topic 4 mutation conflicts with an existing version."
                ) from exc
            if sqlstate == "23503":
                raise self._integrity_error(
                    "The Topic 4 mutation references a missing or cross-tenant resource."
                ) from exc
            raise self._integrity_error(
                "The Topic 4 mutation violates a persistence constraint."
            ) from exc

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
                lease_expires_at=now + timedelta(minutes=2),
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
                "The idempotency key was reused for different Topic 4 content.",
            )
        if record.state == IdempotencyStatus.COMPLETED.value:
            if not isinstance(record.result_payload, dict):
                raise self._conflict("The completed Topic 4 result is unavailable.")
            return dict(record.result_payload)
        if record.lease_expires_at is not None and record.lease_expires_at > now:
            raise self._conflict("The idempotent Topic 4 operation is already in progress.")
        record.state = IdempotencyStatus.PROCESSING.value
        record.lease_owner = self._instance_id
        record.lease_expires_at = now + timedelta(minutes=2)
        record.expires_at = now + IDEMPOTENCY_RETENTION
        record.updated_at = now
        return None

    @staticmethod
    async def _complete_idempotency(
        session: AsyncSession,
        context: TenantContext,
        key: str,
        data: dict[str, Any],
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
        record.result_payload = data
        record.updated_at = datetime.now(UTC)

    @staticmethod
    async def _append_audit(
        session: AsyncSession,
        context: TenantContext,
        *,
        action: str,
        target_ref: str,
        metadata: dict[str, Any],
    ) -> AuditRecord:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"audit:{context.tenant_id}"},
        )
        result = await session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.tenant_id == context.tenant_id)
            .order_by(AuditEventModel.sequence.desc())
            .limit(1)
        )
        previous = result.scalar_one_or_none()
        draft = AuditDraft(
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
        )
        record = build_audit_record(
            draft,
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
        return record

    async def _append_outbox(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        verification_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        partition_key = self._partition_key(context.tenant_id, verification_id)
        await self._lock(session, f"outbox:{partition_key}")
        result = await session.execute(
            select(func.coalesce(func.max(OutboxMessageModel.sequence) + 1, 0)).where(
                OutboxMessageModel.tenant_id == context.tenant_id,
                OutboxMessageModel.partition_key == partition_key,
            )
        )
        sequence = int(result.scalar_one())
        now = datetime.now(UTC)
        envelope = Topic3EnvelopeV1(
            envelope_id=uuid4(),
            event_type=event_type,
            message_kind=MessageKind.EVENT,
            tenant_id=context.tenant_id,
            session_id=context.session_id or verification_id,
            subject_ref=context.subject_ref,
            correlation_id=verification_id,
            causation_id=None,
            sequence=sequence,
            partition_key=partition_key,
            producer=ProducerMetadataV1(
                agent=None,
                service="topic4-verification-service",
                instance_id=self._instance_id,
                build_version=self._versions.verifier_build_version,
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=f"topic4:{canonical_sha256(payload)}",
                available_at=now,
                expires_at=now + OUTBOX_RETENTION,
                priority="HIGH",
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
    async def _lock(session: AsyncSession, lock_key: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )

    @staticmethod
    def _verification_lock(tenant_id: str, verification_id: UUID) -> str:
        return f"topic4:verification:{tenant_id}:{verification_id}"

    @staticmethod
    def _partition_key(tenant_id: str, verification_id: UUID) -> str:
        return f"topic4:{tenant_id}:{verification_id}"

    @staticmethod
    def _validate_idempotency_key(value: str) -> None:
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "Topic 4 idempotency key is invalid.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            )

    @staticmethod
    def _validate_request_context(
        request: VerificationRequestPayloadV1,
        context: TenantContext,
    ) -> None:
        if request.tenant_id != context.tenant_id:
            raise LiyanError(
                ErrorCode.TENANT_MISMATCH,
                "Verification request tenant does not match authenticated context.",
                category=ErrorCategory.TENANT,
                status_code=403,
            )
        if request.trace_id.lower() != context.trace_id.lower():
            raise LiyanError(
                ErrorCode.TOPIC4_INTEGRITY_FAILED,
                "Verification trace does not match the authenticated request trace.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            )
        if request.version_cas != 1:
            raise LiyanError(
                ErrorCode.TOPIC4_VERSION_CONFLICT,
                "New verification requests must start at version one.",
                category=ErrorCategory.CONTRACT,
                status_code=409,
            )

    @staticmethod
    def _not_found(resource: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_NOT_FOUND,
            f"{resource} was not found.",
            category=ErrorCategory.CONTRACT,
            status_code=404,
        )

    @staticmethod
    def _conflict(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_CONFLICT,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )

    @staticmethod
    def _version_conflict() -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_VERSION_CONFLICT,
            "Verification transition is based on a stale state version.",
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )

    @staticmethod
    def _transition_error(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_STATE_TRANSITION_INVALID,
            message,
            category=ErrorCategory.TASK,
            status_code=409,
        )

    @staticmethod
    def _integrity_error(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_INTEGRITY_FAILED,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )

    @staticmethod
    def _deadline_error() -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_DEADLINE_EXPIRED,
            "Verification deadline has expired.",
            category=ErrorCategory.TIMEOUT,
            status_code=409,
        )
