from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic3 import CandidateStatus, CandidateV1
from liyans_contracts.topic4_c1 import (
    AggregationResultV1,
    ClaimRiskV1,
    ClaimV1,
    ClaimVerdictV1,
    HumanReviewDecisionV1,
    HumanReviewTaskV1,
    ModuleDispatchPlanV1,
    ModuleRunResultV1,
    ModuleRunV1,
    ReviewDecision,
    ReviewTaskState,
    VerificationReportV1,
)
from liyans_contracts.topic4_common import (
    AggregateDecision,
    ModuleRunState,
    RiskLevel,
    VerificationModule,
    VerificationVerdict,
)
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

from .aggregation import AggregationPolicy, VerificationResultAggregator
from .claim_extraction import ClaimExtractionError, DeterministicClaimExtractor
from .dispatch import DispatchPolicy, ModuleDispatchPlanner
from .entities import VerificationRecord, VerificationStateRecord
from .execution import ModuleExecutionBundle
from .postgres_repository import PostgresVerificationRepository
from .records import build_topic4_record, record_integrity_valid
from .reporting import VerificationReportBuilder
from .risk_scoring import ClaimRiskScorer, RiskScoringPolicy
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


@dataclass(frozen=True, slots=True)
class C1PreparationResult:
    claims: tuple[ClaimV1, ...]
    risks: tuple[ClaimRiskV1, ...]
    dispatch_plan: ModuleDispatchPlanV1
    state: VerificationStateChangedPayloadV1
    review_task: HumanReviewTaskV1 | None


@dataclass(frozen=True, slots=True)
class C1ExecutionPersistenceResult:
    verification_id: UUID
    run_snapshot_count: int
    module_result_count: int


@dataclass(frozen=True, slots=True)
class C1FinalizationResult:
    claim_verdicts: tuple[ClaimVerdictV1, ...]
    aggregation: AggregationResultV1
    report: VerificationReportV1
    state: VerificationStateChangedPayloadV1
    review_task: HumanReviewTaskV1 | None


@dataclass(frozen=True, slots=True)
class C1ReviewResult:
    decision: HumanReviewDecisionV1
    review_task: HumanReviewTaskV1
    state: VerificationStateChangedPayloadV1


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
        claim_extractor: DeterministicClaimExtractor | None = None,
        risk_scorer: ClaimRiskScorer | None = None,
        dispatch_planner: ModuleDispatchPlanner | None = None,
        result_aggregator: VerificationResultAggregator | None = None,
        report_builder: VerificationReportBuilder | None = None,
    ) -> None:
        self._database = database
        self._repository = repository
        self._candidate_reader = candidate_reader
        self._outbox = outbox
        self._state_machine = state_machine
        self._versions = versions
        self._instance_id = instance_id
        self._claim_extractor = claim_extractor or DeterministicClaimExtractor()
        self._risk_scorer = risk_scorer or ClaimRiskScorer(
            RiskScoringPolicy(versions.policy_version)
        )
        self._dispatch_planner = dispatch_planner or ModuleDispatchPlanner(
            DispatchPolicy(versions.policy_version)
        )
        self._result_aggregator = result_aggregator or VerificationResultAggregator(
            AggregationPolicy(versions.policy_version)
        )
        self._report_builder = report_builder

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

    async def prepare_control_plane(
        self,
        verification_id: UUID,
        *,
        expected_state_version: int,
        idempotency_key: str,
    ) -> C1PreparationResult:
        request_document = {
            "verification_id": str(verification_id),
            "expected_state_version": expected_state_version,
        }

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._lock(session, self._verification_lock(tenant.tenant_id, verification_id))
            verification, current = await self._require_verification(
                session, tenant.tenant_id, verification_id
            )
            self._require_state_version(current, expected_state_version)
            if current.change.current_state not in {
                VerificationState.ACCEPTED,
                VerificationState.REVERIFYING,
            }:
                raise self._transition_error(
                    "Claim extraction can only start from ACCEPTED or REVERIFYING."
                )
            if await self._repository.list_claims(session, tenant.tenant_id, verification_id):
                raise self._conflict("The verification control plane is already prepared.")

            candidate = await self._verified_candidate(session, tenant.tenant_id, verification)
            now = datetime.now(UTC)
            self._require_active_deadline(verification, now)
            try:
                claims = self._claim_extractor.extract(
                    candidate,
                    verification_id=verification_id,
                    trace_id=tenant.trace_id,
                    tenant_id=tenant.tenant_id,
                    created_at=now,
                )
            except ClaimExtractionError as exc:
                raise self._integrity_error(str(exc)) from exc
            risks = self._risk_scorer.score_all(
                claims,
                profile=verification.request.requested_profile,
                trace_id=tenant.trace_id,
                tenant_id=tenant.tenant_id,
                created_at=now,
            )
            plan = self._dispatch_planner.plan(
                claims,
                risks,
                profile=verification.request.requested_profile,
                trace_id=tenant.trace_id,
                tenant_id=tenant.tenant_id,
                created_at=now,
            )
            critical_risks = [risk for risk in risks if risk.level == RiskLevel.CRITICAL]
            target = (
                VerificationState.REVIEW_REQUIRED
                if critical_risks
                else VerificationState.MODULE_DISPATCHING
            )
            changes = self._state_sequence(
                current.change,
                (
                    VerificationState.SNAPSHOT_VALIDATING,
                    VerificationState.CLAIM_EXTRACTING,
                    VerificationState.CLAIMS_READY,
                    target,
                ),
                now=now,
                reason_codes=(
                    "SOURCE_SNAPSHOT_VALIDATED",
                    "CLAIM_EXTRACTION_STARTED",
                    "CLAIMS_AND_RISKS_READY",
                    "CRITICAL_RISK_FUSE" if critical_risks else "MODULE_DISPATCH_PLAN_READY",
                ),
            )
            review_task = (
                self._build_risk_review_task(verification, critical_risks, now=now)
                if critical_risks
                else None
            )
            audit = await self._append_audit(
                session,
                tenant,
                action="VERIFICATION_CONTROL_PLANE_PREPARED",
                target_ref=str(verification_id),
                metadata={
                    "claim_count": len(claims),
                    "critical_risk_count": len(critical_risks),
                    "dispatch_item_count": len(plan.items),
                    "dispatch_plan_id": str(plan.dispatch_plan_id),
                    "target_state": target.value,
                },
            )
            await self._repository.append_claims(session, tenant.tenant_id, claims, audit.event_id)
            await self._repository.append_risks(session, tenant.tenant_id, risks, audit.event_id)
            await self._repository.append_dispatch_plan(
                session, tenant.tenant_id, plan, audit.event_id
            )
            for change in changes:
                await self._repository.append_state(
                    session,
                    tenant.tenant_id,
                    VerificationStateRecord(state_snapshot_id=uuid4(), change=change),
                    audit.event_id,
                )
            if review_task is not None:
                await self._repository.append_review_task(
                    session, tenant.tenant_id, review_task, audit.event_id
                )
            await self._append_outbox(
                session,
                tenant,
                verification_id=verification_id,
                event_type="topic4.verification.control_plane_prepared",
                payload={
                    "verification_id": str(verification_id),
                    "claim_ids": [str(claim.claim_id) for claim in claims],
                    "dispatch_plan_id": str(plan.dispatch_plan_id),
                    "state": changes[-1].model_dump(mode="json"),
                    "review_task_id": None
                    if review_task is None
                    else str(review_task.review_task_id),
                },
            )
            return {
                "verification_id": str(verification_id),
                "dispatch_plan_id": str(plan.dispatch_plan_id),
                "state": changes[-1].model_dump(mode="json"),
                "review_task": None if review_task is None else review_task.model_dump(mode="json"),
            }

        document = await self._execute_mutation(
            operation="topic4.verification.prepare_control_plane",
            idempotency_key=idempotency_key,
            request_document=request_document,
            callback=callback,
        )
        return await self._read_preparation_result(document)

    async def persist_module_execution(
        self,
        verification_id: UUID,
        bundle: ModuleExecutionBundle,
        *,
        expected_state_version: int,
        idempotency_key: str,
    ) -> C1ExecutionPersistenceResult:
        self._validate_execution_bundle(verification_id, bundle)
        request_document = {
            "verification_id": str(verification_id),
            "expected_state_version": expected_state_version,
            "run_record_sha256": [run.record_sha256 for run in bundle.run_snapshots],
            "result_record_sha256": [result.record_sha256 for result in bundle.results],
        }

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._lock(session, self._verification_lock(tenant.tenant_id, verification_id))
            _, current = await self._require_verification(
                session, tenant.tenant_id, verification_id
            )
            self._require_state_version(current, expected_state_version)
            if current.change.current_state != VerificationState.VERIFYING:
                raise self._transition_error(
                    "Module execution results can only be persisted while VERIFYING."
                )
            plan = await self._repository.latest_dispatch_plan(
                session, tenant.tenant_id, verification_id
            )
            if plan is None:
                raise self._integrity_error("The verification dispatch plan is missing.")
            self._validate_bundle_against_plan(bundle, plan, tenant)
            if await self._repository.list_latest_module_runs(
                session, tenant.tenant_id, verification_id
            ):
                raise self._conflict("Module execution has already been persisted.")
            audit = await self._append_audit(
                session,
                tenant,
                action="VERIFICATION_MODULE_EXECUTION_RECORDED",
                target_ref=str(verification_id),
                metadata={
                    "run_snapshot_count": len(bundle.run_snapshots),
                    "module_result_count": len(bundle.results),
                },
            )
            await self._repository.append_module_runs(
                session,
                tenant.tenant_id,
                list(bundle.run_snapshots),
                audit.event_id,
            )
            await self._repository.append_module_results(
                session,
                tenant.tenant_id,
                list(bundle.results),
                audit.event_id,
            )
            await self._append_outbox(
                session,
                tenant,
                verification_id=verification_id,
                event_type="topic4.verification.modules_recorded",
                payload={
                    "verification_id": str(verification_id),
                    "run_snapshot_count": len(bundle.run_snapshots),
                    "module_result_count": len(bundle.results),
                },
            )
            return {
                "verification_id": str(verification_id),
                "run_snapshot_count": len(bundle.run_snapshots),
                "module_result_count": len(bundle.results),
            }

        document = await self._execute_mutation(
            operation="topic4.verification.persist_module_execution",
            idempotency_key=idempotency_key,
            request_document=request_document,
            callback=callback,
        )
        return C1ExecutionPersistenceResult(
            verification_id=UUID(document["verification_id"]),
            run_snapshot_count=int(document["run_snapshot_count"]),
            module_result_count=int(document["module_result_count"]),
        )

    async def finalize_control_plane(
        self,
        verification_id: UUID,
        *,
        expected_state_version: int,
        idempotency_key: str,
    ) -> C1FinalizationResult:
        if self._report_builder is None:
            raise self._runtime_error("The Topic 4 report builder is not configured.")
        request_document = {
            "verification_id": str(verification_id),
            "expected_state_version": expected_state_version,
        }

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            await self._lock(session, self._verification_lock(tenant.tenant_id, verification_id))
            verification, current = await self._require_verification(
                session, tenant.tenant_id, verification_id
            )
            self._require_state_version(current, expected_state_version)
            if current.change.current_state != VerificationState.VERIFYING:
                raise self._transition_error(
                    "Verification aggregation can only start from VERIFYING."
                )
            now = datetime.now(UTC)
            self._require_active_deadline(verification, now)
            claims = await self._repository.list_claims(session, tenant.tenant_id, verification_id)
            risks = await self._repository.list_risks(session, tenant.tenant_id, verification_id)
            results = await self._repository.list_module_results(
                session, tenant.tenant_id, verification_id
            )
            verdicts, aggregation = self._result_aggregator.aggregate(
                claims,
                risks,
                results,
                revision_round=current.change.revision_round,
                trace_id=tenant.trace_id,
                tenant_id=tenant.tenant_id,
                created_at=now,
            )
            evidence_ids = {
                evidence_id for result in results for evidence_id in result.evidence_ref_ids
            }
            evidence_digests = await self._repository.evidence_digests(
                session, tenant.tenant_id, evidence_ids
            )
            report = await self._report_builder.build(
                session,
                claims=claims,
                risks=risks,
                module_results=results,
                claim_verdicts=verdicts,
                aggregation=aggregation,
                evidence_digests=evidence_digests,
                subject_ref=tenant.subject_ref,
                trace_id=tenant.trace_id,
                tenant_id=tenant.tenant_id,
                resource_type=verification.request.source_snapshot_ref.resource_type.value,
                completed_at=now,
            )
            target = self._decision_target(aggregation.decision)
            changes = self._state_sequence(
                current.change,
                (VerificationState.AGGREGATING, target),
                now=now,
                reason_codes=(
                    "MODULE_RESULTS_AGGREGATING",
                    f"DECISION_{aggregation.decision.value}",
                ),
            )
            review_task = (
                self._build_result_review_task(
                    verification,
                    risks,
                    results,
                    verdicts,
                    now=now,
                )
                if aggregation.decision == AggregateDecision.REVIEW_REQUIRED
                else None
            )
            audit = await self._append_audit(
                session,
                tenant,
                action="VERIFICATION_AGGREGATED",
                target_ref=str(verification_id),
                metadata={
                    "aggregation_result_id": str(aggregation.aggregation_result_id),
                    "report_id": str(report.report_id),
                    "decision": aggregation.decision.value,
                    "overall_confidence": aggregation.overall_confidence,
                },
            )
            await self._repository.append_claim_verdicts(
                session, tenant.tenant_id, verdicts, audit.event_id
            )
            await self._repository.append_aggregation(
                session, tenant.tenant_id, aggregation, audit.event_id
            )
            await self._repository.append_report(session, tenant.tenant_id, report, audit.event_id)
            for change in changes:
                await self._repository.append_state(
                    session,
                    tenant.tenant_id,
                    VerificationStateRecord(state_snapshot_id=uuid4(), change=change),
                    audit.event_id,
                )
            if review_task is not None:
                await self._repository.append_review_task(
                    session, tenant.tenant_id, review_task, audit.event_id
                )
            await self._append_outbox(
                session,
                tenant,
                verification_id=verification_id,
                event_type="topic4.verification.aggregated",
                payload={
                    "verification_id": str(verification_id),
                    "aggregation_result_id": str(aggregation.aggregation_result_id),
                    "report_id": str(report.report_id),
                    "decision": aggregation.decision.value,
                    "state": changes[-1].model_dump(mode="json"),
                },
            )
            return {
                "claim_verdict_ids": [str(item.claim_verdict_id) for item in verdicts],
                "aggregation": aggregation.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
                "state": changes[-1].model_dump(mode="json"),
                "review_task": None if review_task is None else review_task.model_dump(mode="json"),
            }

        document = await self._execute_mutation(
            operation="topic4.verification.finalize_control_plane",
            idempotency_key=idempotency_key,
            request_document=request_document,
            callback=callback,
        )
        return await self._read_finalization_result(verification_id, document)

    async def submit_human_review(
        self,
        decision: HumanReviewDecisionV1,
        *,
        expected_task_version: int,
        expected_state_version: int,
        idempotency_key: str,
    ) -> C1ReviewResult:
        context = current_tenant()
        if decision.tenant_id != context.tenant_id or decision.trace_id != context.trace_id:
            raise self._integrity_error(
                "Human review decision does not match the authenticated tenant trace."
            )
        if decision.reviewer_subject_ref != context.subject_ref:
            raise self._integrity_error(
                "Human review decision reviewer does not match the authenticated subject."
            )
        if decision.rationale_artifact.sha256 != decision.rationale_sha256:
            raise self._integrity_error(
                "Human review rationale artifact hash does not match rationale_sha256."
            )
        if not record_integrity_valid(decision):
            raise self._integrity_error("Human review decision record hash is invalid.")
        request_document = {
            "decision": decision.model_dump(mode="json"),
            "expected_task_version": expected_task_version,
            "expected_state_version": expected_state_version,
        }

        async def callback(session: AsyncSession, tenant: TenantContext) -> dict[str, Any]:
            verification_id = decision.verification_id
            await self._lock(session, self._verification_lock(tenant.tenant_id, verification_id))
            _, current = await self._require_verification(
                session, tenant.tenant_id, verification_id
            )
            self._require_state_version(current, expected_state_version)
            if current.change.current_state != VerificationState.REVIEW_REQUIRED:
                raise self._transition_error(
                    "Human review decisions require REVIEW_REQUIRED state."
                )
            task = await self._repository.latest_review_task(
                session, tenant.tenant_id, verification_id
            )
            if task is None or task.review_task_id != decision.review_task_id:
                raise self._not_found("Human review task")
            if task.version_cas != expected_task_version:
                raise self._version_conflict()
            if task.state not in {ReviewTaskState.OPEN, ReviewTaskState.CLAIMED}:
                raise self._conflict("Human review task is no longer open.")
            if datetime.now(UTC) > task.due_at:
                raise self._deadline_error()
            if set(decision.waived_finding_ids) & set(task.non_waivable_finding_ids):
                raise self._integrity_error("Non-waivable findings cannot be waived.")
            if task.non_waivable_finding_ids and decision.decision in {
                ReviewDecision.APPROVE,
                ReviewDecision.APPROVE_WITH_DISCLOSURE,
            }:
                raise self._integrity_error(
                    "A review task with non-waivable findings cannot be approved."
                )
            now = datetime.now(UTC)
            decided_task = build_topic4_record(
                HumanReviewTaskV1,
                trace_id=tenant.trace_id,
                tenant_id=tenant.tenant_id,
                version_cas=task.version_cas + 1,
                created_at=now,
                immutable=True,
                schema_version="human-review.task.v1",
                review_task_id=task.review_task_id,
                verification_id=task.verification_id,
                candidate_id=task.candidate_id,
                candidate_version=task.candidate_version,
                candidate_sha256=task.candidate_sha256,
                state=ReviewTaskState.DECIDED,
                risk_level=task.risk_level,
                reason_codes=task.reason_codes,
                claim_ids=task.claim_ids,
                assigned_role=task.assigned_role,
                due_at=task.due_at,
                non_waivable_finding_ids=task.non_waivable_finding_ids,
            )
            target = self._review_decision_target(decision.decision)
            change = self._state_sequence(
                current.change,
                (target,),
                now=now,
                reason_codes=(f"HUMAN_REVIEW_{decision.decision.value}",),
            )[0]
            audit = await self._append_audit(
                session,
                tenant,
                action="HUMAN_REVIEW_DECIDED",
                target_ref=str(decision.review_task_id),
                metadata={
                    "verification_id": str(verification_id),
                    "decision": decision.decision.value,
                    "reviewer_subject_ref": decision.reviewer_subject_ref,
                    "target_state": target.value,
                },
            )
            await self._repository.append_review_decision(
                session,
                tenant.tenant_id,
                decision,
                review_task_version=task.version_cas,
                audit_event_id=audit.event_id,
            )
            await self._repository.append_review_task(
                session, tenant.tenant_id, decided_task, audit.event_id
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
                event_type="topic4.verification.human_review_decided",
                payload={
                    "decision": decision.model_dump(mode="json"),
                    "review_task": decided_task.model_dump(mode="json"),
                    "state": change.model_dump(mode="json"),
                },
            )
            return {
                "decision": decision.model_dump(mode="json"),
                "review_task": decided_task.model_dump(mode="json"),
                "state": change.model_dump(mode="json"),
            }

        document = await self._execute_mutation(
            operation="topic4.verification.submit_human_review",
            idempotency_key=idempotency_key,
            request_document=request_document,
            callback=callback,
        )
        return C1ReviewResult(
            decision=HumanReviewDecisionV1.model_validate(document["decision"]),
            review_task=HumanReviewTaskV1.model_validate(document["review_task"]),
            state=VerificationStateChangedPayloadV1.model_validate(document["state"]),
        )

    async def _read_preparation_result(
        self,
        document: dict[str, Any],
    ) -> C1PreparationResult:
        verification_id = UUID(document["verification_id"])
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            claims = await self._repository.list_claims(session, context.tenant_id, verification_id)
            risks = await self._repository.list_risks(session, context.tenant_id, verification_id)
            plan = await self._repository.latest_dispatch_plan(
                session, context.tenant_id, verification_id
            )
        if plan is None or str(plan.dispatch_plan_id) != document["dispatch_plan_id"]:
            raise self._runtime_error("The persisted Topic 4 dispatch plan is unavailable.")
        return C1PreparationResult(
            claims=tuple(claims),
            risks=tuple(risks),
            dispatch_plan=plan,
            state=VerificationStateChangedPayloadV1.model_validate(document["state"]),
            review_task=None
            if document["review_task"] is None
            else HumanReviewTaskV1.model_validate(document["review_task"]),
        )

    async def _read_finalization_result(
        self,
        verification_id: UUID,
        document: dict[str, Any],
    ) -> C1FinalizationResult:
        context = current_tenant()
        expected_ids = {UUID(value) for value in document["claim_verdict_ids"]}
        async with self._database.transaction(context=current_session_context()) as session:
            persisted = await self._repository.list_claim_verdicts(
                session, context.tenant_id, verification_id
            )
        verdicts = tuple(item for item in persisted if item.claim_verdict_id in expected_ids)
        if {item.claim_verdict_id for item in verdicts} != expected_ids:
            raise self._runtime_error("The persisted Topic 4 claim verdict set is incomplete.")
        return C1FinalizationResult(
            claim_verdicts=verdicts,
            aggregation=AggregationResultV1.model_validate(document["aggregation"]),
            report=VerificationReportV1.model_validate(document["report"]),
            state=VerificationStateChangedPayloadV1.model_validate(document["state"]),
            review_task=None
            if document["review_task"] is None
            else HumanReviewTaskV1.model_validate(document["review_task"]),
        )

    async def _require_verification(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> tuple[VerificationRecord, VerificationStateRecord]:
        verification = await self._repository.get_verification(session, tenant_id, verification_id)
        current = await self._repository.latest_state(session, tenant_id, verification_id)
        if verification is None or current is None:
            raise self._not_found("Verification")
        return verification, current

    async def _verified_candidate(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification: VerificationRecord,
    ) -> CandidateV1:
        accepted = verification.accepted
        record = await self._candidate_reader.get_candidate(
            session,
            tenant_id,
            accepted.source_candidate_id,
            accepted.source_candidate_version,
        )
        if record is None:
            raise self._not_found("Source candidate")
        candidate = record.candidate
        if candidate.status != CandidateStatus.COMPLETE:
            raise self._integrity_error("Only complete Topic 3 candidates can be verified.")
        if candidate.candidate_sha256 != accepted.source_candidate_sha256:
            raise self._integrity_error("Source candidate hash changed after acceptance.")
        if candidate.resource_type != verification.request.source_snapshot_ref.resource_type:
            raise self._integrity_error("Source candidate resource type changed after acceptance.")
        return candidate

    def _state_sequence(
        self,
        current: VerificationStateChangedPayloadV1,
        targets: tuple[VerificationState, ...],
        *,
        now: datetime,
        reason_codes: tuple[str, ...],
    ) -> list[VerificationStateChangedPayloadV1]:
        if len(targets) != len(reason_codes):
            raise ValueError("state targets and reason codes must have equal length")
        changes: list[VerificationStateChangedPayloadV1] = []
        source = current
        for target, reason_code in zip(targets, reason_codes, strict=True):
            try:
                decision = self._state_machine.transition(
                    source.current_state,
                    target,
                    revision_round=source.revision_round,
                )
            except InvalidVerificationTransition as exc:
                raise self._transition_error(str(exc)) from exc
            state_version = source.state_version + 1
            change = build_topic4_record(
                VerificationStateChangedPayloadV1,
                trace_id=source.trace_id,
                tenant_id=source.tenant_id,
                version_cas=state_version,
                created_at=now,
                immutable=True,
                schema_version="verification.state_changed.v1",
                verification_id=source.verification_id,
                previous_state=decision.previous_state,
                current_state=decision.current_state,
                state_version=state_version,
                reason_code=reason_code,
                revision_round=decision.revision_round,
                changed_at=now,
            )
            changes.append(change)
            source = change
        return changes

    def _build_risk_review_task(
        self,
        verification: VerificationRecord,
        risks: list[ClaimRiskV1],
        *,
        now: datetime,
    ) -> HumanReviewTaskV1:
        if not risks:
            raise ValueError("risk review task requires at least one risk")
        accepted = verification.accepted
        claim_ids = sorted({risk.claim_id for risk in risks}, key=str)
        reason_codes = sorted({code for risk in risks for code in risk.reason_codes})[:128]
        review_task_id = uuid5(
            NAMESPACE_URL,
            (
                f"liyans:topic4:risk-review:{accepted.tenant_id}:"
                f"{accepted.verification_id}:{canonical_sha256(reason_codes)}"
            ),
        )
        return build_topic4_record(
            HumanReviewTaskV1,
            trace_id=accepted.trace_id,
            tenant_id=accepted.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="human-review.task.v1",
            review_task_id=review_task_id,
            verification_id=accepted.verification_id,
            candidate_id=accepted.source_candidate_id,
            candidate_version=accepted.source_candidate_version,
            candidate_sha256=accepted.source_candidate_sha256,
            state=ReviewTaskState.OPEN,
            risk_level=max((risk.level for risk in risks), key=self._risk_rank),
            reason_codes=reason_codes or ["CRITICAL_RISK_FUSE"],
            claim_ids=claim_ids,
            assigned_role="TOPIC4_ACADEMIC_SECURITY_REVIEWER",
            due_at=min(accepted.deadline_at, now + timedelta(hours=4)),
            non_waivable_finding_ids=[],
        )

    def _build_result_review_task(
        self,
        verification: VerificationRecord,
        risks: list[ClaimRiskV1],
        results: list[ModuleRunResultV1],
        verdicts: list[ClaimVerdictV1],
        *,
        now: datetime,
    ) -> HumanReviewTaskV1:
        unresolved = [
            verdict
            for verdict in verdicts
            if verdict.verdict
            not in {VerificationVerdict.SUPPORTED, VerificationVerdict.NOT_APPLICABLE}
        ]
        selected = unresolved or verdicts
        risk_by_claim = {risk.claim_id: risk for risk in risks}
        accepted = verification.accepted
        non_waivable_ids = sorted(
            {
                result.module_result_id
                for result in results
                if result.module
                in {
                    VerificationModule.C9_SECURITY,
                    VerificationModule.C10_PRIVACY,
                    VerificationModule.C11_COMPLIANCE,
                }
                and result.verdict in {VerificationVerdict.UNSAFE, VerificationVerdict.CONTRADICTED}
            },
            key=str,
        )
        reason_codes = sorted({code for verdict in selected for code in verdict.reason_codes})
        claim_ids = sorted({verdict.claim_id for verdict in selected}, key=str)
        claim_set_sha256 = canonical_sha256([str(value) for value in claim_ids])
        review_task_id = uuid5(
            NAMESPACE_URL,
            (
                f"liyans:topic4:result-review:{accepted.tenant_id}:"
                f"{accepted.verification_id}:{claim_set_sha256}"
            ),
        )
        return build_topic4_record(
            HumanReviewTaskV1,
            trace_id=accepted.trace_id,
            tenant_id=accepted.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="human-review.task.v1",
            review_task_id=review_task_id,
            verification_id=accepted.verification_id,
            candidate_id=accepted.source_candidate_id,
            candidate_version=accepted.source_candidate_version,
            candidate_sha256=accepted.source_candidate_sha256,
            state=ReviewTaskState.OPEN,
            risk_level=max(
                (risk_by_claim[claim_id].level for claim_id in claim_ids),
                key=self._risk_rank,
            ),
            reason_codes=(reason_codes or ["AGGREGATION_REVIEW_REQUIRED"])[:128],
            claim_ids=claim_ids,
            assigned_role=(
                "TOPIC4_SECURITY_REVIEWER" if non_waivable_ids else "TOPIC4_ACADEMIC_REVIEWER"
            ),
            due_at=min(accepted.deadline_at, now + timedelta(hours=8)),
            non_waivable_finding_ids=non_waivable_ids,
        )

    @staticmethod
    def _risk_rank(level: RiskLevel) -> int:
        return {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }[level]

    @staticmethod
    def _decision_target(decision: AggregateDecision) -> VerificationState:
        return {
            AggregateDecision.RELEASE: VerificationState.RELEASE_PENDING,
            AggregateDecision.RELEASE_WITH_DISCLOSURE: VerificationState.RELEASE_PENDING,
            AggregateDecision.REVISE: VerificationState.REVISION_PLANNING,
            AggregateDecision.REVIEW_REQUIRED: VerificationState.REVIEW_REQUIRED,
            AggregateDecision.BLOCK: VerificationState.BLOCKED,
        }[decision]

    @staticmethod
    def _review_decision_target(decision: ReviewDecision) -> VerificationState:
        return {
            ReviewDecision.APPROVE: VerificationState.RELEASE_PENDING,
            ReviewDecision.APPROVE_WITH_DISCLOSURE: VerificationState.RELEASE_PENDING,
            ReviewDecision.REVISE: VerificationState.REVISION_PLANNING,
            ReviewDecision.BLOCK: VerificationState.BLOCKED,
        }[decision]

    @staticmethod
    def _require_state_version(
        current: VerificationStateRecord,
        expected_state_version: int,
    ) -> None:
        if current.change.state_version != expected_state_version:
            raise VerificationService._version_conflict()

    @staticmethod
    def _require_active_deadline(verification: VerificationRecord, now: datetime) -> None:
        if now >= verification.accepted.deadline_at:
            raise VerificationService._deadline_error()

    @staticmethod
    def _validate_execution_bundle(
        verification_id: UUID,
        bundle: ModuleExecutionBundle,
    ) -> None:
        if not bundle.run_snapshots:
            raise VerificationService._integrity_error("Module execution bundle is empty.")
        run_keys: set[tuple[UUID, int]] = set()
        terminal_runs: dict[tuple[UUID, int], ModuleRunV1] = {}
        for run in bundle.run_snapshots:
            if run.verification_id != verification_id or not record_integrity_valid(run):
                raise VerificationService._integrity_error(
                    "Module run snapshot failed verification binding or hash validation."
                )
            key = (run.module_run_id, run.version_cas)
            if key in run_keys:
                raise VerificationService._integrity_error(
                    "Module execution bundle contains duplicate run snapshots."
                )
            run_keys.add(key)
            if run.state == ModuleRunState.SUCCEEDED:
                terminal_runs[key] = run
        result_ids: set[UUID] = set()
        for result in bundle.results:
            if result.module_result_id in result_ids or not record_integrity_valid(result):
                raise VerificationService._integrity_error(
                    "Module execution bundle contains a duplicate or invalid result."
                )
            result_ids.add(result.module_result_id)
            run = terminal_runs.get((result.module_run_id, result.version_cas))
            if run is None or (run.claim_id, run.module) != (result.claim_id, result.module):
                raise VerificationService._integrity_error(
                    "Module result is not bound to a matching successful run snapshot."
                )

    @staticmethod
    def _validate_bundle_against_plan(
        bundle: ModuleExecutionBundle,
        plan: ModuleDispatchPlanV1,
        tenant: TenantContext,
    ) -> None:
        item_by_id = {item.dispatch_item_id: item for item in plan.items}
        for run in bundle.run_snapshots:
            item = item_by_id.get(run.dispatch_item_id)
            if (
                item is None
                or run.dispatch_plan_id != plan.dispatch_plan_id
                or run.tenant_id != tenant.tenant_id
                or run.trace_id != tenant.trace_id
                or (run.claim_id, run.module) != (item.claim_id, item.module)
            ):
                raise VerificationService._integrity_error(
                    "Module run snapshot does not match the frozen dispatch plan."
                )
        for result in bundle.results:
            if result.tenant_id != tenant.tenant_id or result.trace_id != tenant.trace_id:
                raise VerificationService._integrity_error(
                    "Module result does not match the authenticated tenant trace."
                )

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

    @staticmethod
    def _runtime_error(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_INTEGRITY_FAILED,
            message,
            category=ErrorCategory.DATABASE,
            status_code=500,
        )
