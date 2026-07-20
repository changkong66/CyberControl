"""Application-facing Topic 4 runtime composition.

The domain packages intentionally expose small, transaction-oriented ports.  This
module is the composition boundary that turns those ports into a running
verification service: it owns task execution, durable candidate hand-off,
cross-cutting evidence loading, and the public SSE projection.  It does not
alter any frozen Topic 1/2/3 contract or persistence primitive.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.artifacts import (
    ArtifactObjectRefV1,
    BlockSnapshotManifestItemV1,
    SourceSnapshotRefV1,
)
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import VerificationProfile, VerificationTrigger
from liyans_contracts.topic3 import CandidateStatus, CandidateV1
from liyans_contracts.topic4_c1 import (
    ClaimV1,
    HumanReviewDecisionV1,
    HumanReviewTaskV1,
    ModuleDispatchPlanV1,
    ReviewDecision,
    ReviewTaskState,
)
from liyans_contracts.topic4_c2 import RetrievalResponseV1
from liyans_contracts.topic4_c12 import (
    PublicationCommitCommandV2,
    ReleaseDerivationCommandV2,
)
from liyans_contracts.topic4_common import (
    AggregateDecision,
    VerificationModule,
    VerificationVerdict,
)
from liyans_contracts.verification import (
    ReleaseAuthorizationPayloadV1,
    VerificationContextV1,
    VerificationRequestPayloadV1,
    VerificationState,
)
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, current_tenant, tenant_scope
from liyans.domains.academic.evidence_source import PostgresAcademicEvidenceSource
from liyans.domains.academic.handler import C3AcademicHandler
from liyans.domains.code.evidence_source import PostgresCodeEvidenceSource
from liyans.domains.code.handler import C6CodeHandler
from liyans.domains.compliance.evidence_source import ComplianceEvidenceBundle
from liyans.domains.compliance.handler import C11ComplianceHandler
from liyans.domains.compliance.service import (
    ComplianceEvidenceError,
    ComplianceEvidenceService,
)
from liyans.domains.extension.evidence_source import PostgresExtensionEvidenceSource
from liyans.domains.extension.handler import C7ExtensionHandler
from liyans.domains.graph.evidence_source import PostgresGraphEvidenceSource
from liyans.domains.graph.handler import C4GraphHandler
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.domains.knowledge.retrieval_service import KnowledgeRetrievalService
from liyans.domains.privacy.evidence_source import PrivacyEvidenceBundle
from liyans.domains.privacy.handler import C10PrivacyHandler
from liyans.domains.quiz.evidence_source import PostgresQuizEvidenceSource
from liyans.domains.quiz.handler import C5QuizHandler
from liyans.domains.release.engine import (
    AuthorizationConflictError,
    C12ReleaseService,
    PublicationRequest,
    PublicationResult,
    ReleaseError,
)
from liyans.domains.revision.engine import RevisionEngine, RevisionError, RevisionOutcome
from liyans.domains.security.evidence_source import SecurityEvidenceBundle
from liyans.domains.security.handler import C9SecurityHandler
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository
from liyans.domains.topic3.service import Topic3Service
from liyans.domains.verification.aggregation import AggregationError
from liyans.domains.verification.execution import (
    BoundedModuleExecutor,
    ModuleExecutionContext,
    ModuleFinding,
    VerificationModuleHandler,
)
from liyans.domains.verification.models import Topic4HumanReviewTaskModel
from liyans.domains.verification.postgres_repository import PostgresVerificationRepository
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.domains.verification.release_models import (
    Topic4PublicationBatchModel,
    Topic4PublicStreamEventModel,
    Topic4ReleaseAuthorizationConsumptionModel,
    Topic4ReleaseAuthorizationModel,
)
from liyans.domains.verification.service import VerificationService
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import AuditEventModel, Base
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
from liyans.infrastructure.persistence import PostgresOutboxRepository
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore
from liyans.infrastructure.streaming.sse import SSEBroker
from liyans.infrastructure.tasks.queue import AsyncTaskQueue, TaskPriority, TaskRequest

TOPIC4_VERIFICATION_TASK = "topic4.execute-verification"
TOPIC4_RUNTIME_VERSION = "topic4-runtime-v1"
TOPIC4_INTERNAL_OUTBOX_EVENT_TYPES = (
    "topic4.knowledge.source_imported",
    "topic4.knowledge.base_activated",
    "topic4.knowledge.retrieval_completed",
    "topic4.knowledge.index_self_healed",
    "topic4.verification.accepted",
    "topic4.verification.state_changed",
    "topic4.verification.control_plane_prepared",
    "topic4.verification.modules_recorded",
    "topic4.verification.aggregated",
    "topic4.verification.human_review_decided",
)


class Topic4RuntimeMetrics:
    """Low-cardinality Topic 4 process metrics registered in the app registry."""

    def __init__(self, registry) -> None:
        self.verifications = Counter(
            "liyans_topic4_verifications_total",
            "Topic 4 verification task outcomes.",
            ("outcome",),
            registry=registry,
        )
        self.duration = Histogram(
            "liyans_topic4_verification_duration_seconds",
            "Topic 4 end-to-end verification duration.",
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
            registry=registry,
        )
        self.rag_duration = Histogram(
            "liyans_topic4_rag_duration_seconds",
            "Topic 4 local RAG duration.",
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2),
            registry=registry,
        )
        self.publications = Counter(
            "liyans_topic4_publications_total",
            "Topic 4 publication projection outcomes.",
            ("outcome",),
            registry=registry,
        )
        self.ready = Gauge(
            "liyans_topic4_runtime_ready",
            "Whether the Topic 4 runtime is assembled and ready.",
            registry=registry,
        )


class CandidateEvidenceSource:
    """Loads a tenant-bound Candidate and the latest immutable C2 evidence."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        knowledge_repository: PostgresKnowledgeRepository,
        topic3_repository: PostgresTopic3Repository,
    ) -> None:
        self._database = database
        self._knowledge_repository = knowledge_repository
        self._topic3_repository = topic3_repository

    async def _base(
        self,
        claim: ClaimV1,
    ) -> tuple[CandidateV1 | None, tuple[Any, ...], UUID | None]:
        context = current_tenant()
        if context.tenant_id != claim.tenant_id:
            raise ValueError("candidate evidence tenant does not match the trusted context")
        async with self._database.transaction(context=current_session_context()) as session:
            candidate_record = await self._topic3_repository.get_candidate(
                session,
                claim.tenant_id,
                claim.candidate_id,
                claim.candidate_version,
            )
            candidate = None if candidate_record is None else candidate_record.candidate
            bundle = await self._knowledge_repository.latest_evidence_bundle(
                session,
                claim.tenant_id,
                claim.verification_id,
                claim.claim_id,
            )
            if bundle is None:
                return candidate, (), None
            refs = await self._knowledge_repository.list_evidence_refs(
                session,
                claim.tenant_id,
                claim.claim_id,
            )
        by_id = {ref.evidence_ref_id: ref for ref in refs}
        if len(by_id) != len(refs):
            raise ValueError("candidate evidence contains duplicate references")
        if any(ref_id not in by_id for ref_id in bundle.evidence_ref_ids):
            raise ValueError("candidate evidence bundle references a missing immutable ref")
        ordered = tuple(by_id[ref_id] for ref_id in bundle.evidence_ref_ids)
        return candidate, ordered, bundle.knowledge_base_version_id

    async def security(self, claim: ClaimV1) -> SecurityEvidenceBundle:
        candidate, evidence, version = await self._base(claim)
        return SecurityEvidenceBundle(candidate, evidence, version)

    async def privacy(self, claim: ClaimV1) -> PrivacyEvidenceBundle:
        candidate, evidence, version = await self._base(claim)
        return PrivacyEvidenceBundle(candidate, evidence, claim.tenant_id, version)

    async def compliance(self, claim: ClaimV1) -> ComplianceEvidenceBundle:
        # C11 is fail-closed until a trusted C6/SBOM/provenance package exists.
        # The absence of a package is represented as insufficient evidence by the
        # frozen C11 handler; it is never treated as a clean supply-chain scan.
        _candidate, evidence, _version = await self._base(claim)
        return ComplianceEvidenceBundle(
            source_tenant_id=claim.tenant_id,
            code_artifact=None,
            sbom_manifest=None,
            sbom_document=None,
            vulnerabilities=(),
            provenance=None,
            evidence=evidence,
        )


class C2RetrievalHandler:
    """Adapts the durable C2 retrieval service to the frozen C1 handler port."""

    def __init__(
        self,
        retrieval: KnowledgeRetrievalService,
        verification_service: VerificationService,
        artifact_store: ArtifactObjectStore,
        metrics: Topic4RuntimeMetrics,
    ) -> None:
        self._retrieval = retrieval
        self._verification_service = verification_service
        self._artifact_store = artifact_store
        self._metrics = metrics

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        started = asyncio.get_running_loop().time()
        claim = context.claim
        try:
            verification, _state = await self._verification_service.get_verification(
                context.verification_id
            )
            if verification.request.context.locale != "zh-CN":
                return await self._finding(
                    context,
                    VerificationVerdict.UNSAFE,
                    "C2_LOCALE_NOT_SUPPORTED",
                    (),
                )
            response = await self._retrieval.retrieve_claim(
                claim,
                course_id=verification.request.context.course_id,
                target_kp_id=verification.request.context.target_kp_id,
                idempotency_key=(f"topic4:c2:{claim.verification_id.hex}:{claim.claim_id.hex}:v1"),
            )
            evidence_ids = ()
            if response.evidence_bundle is not None:
                evidence_ids = tuple(response.evidence_bundle.evidence_ref_ids)
            if response.status.value == "SUCCEEDED" and evidence_ids:
                verdict = VerificationVerdict.SUPPORTED
                code = "C2_LOCAL_EVIDENCE_FOUND"
                confidence = max(0.5, response.evidence_bundle.coverage_score)
            elif response.status.value == "DEGRADED" and evidence_ids:
                verdict = VerificationVerdict.PARTIALLY_SUPPORTED
                code = "C2_LOCAL_EVIDENCE_DEGRADED"
                confidence = max(0.25, response.evidence_bundle.coverage_score)
            else:
                verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
                code = "C2_LOCAL_EVIDENCE_MISSING"
                confidence = 0.0
            return await self._finding(
                context,
                verdict,
                code,
                evidence_ids,
                response=response,
                confidence=confidence,
            )
        except Exception:
            return await self._finding(
                context,
                VerificationVerdict.ERROR,
                "C2_RETRIEVAL_FAILED",
                (),
            )
        finally:
            self._metrics.rag_duration.observe(asyncio.get_running_loop().time() - started)

    async def _finding(
        self,
        context: ModuleExecutionContext,
        verdict: VerificationVerdict,
        code: str,
        evidence_ids: Iterable[UUID],
        *,
        response: RetrievalResponseV1 | None = None,
        confidence: float = 0.0,
    ) -> ModuleFinding:
        document = {
            "schema_version": "c2-module-finding.v1",
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "verdict": verdict.value,
            "finding_codes": [code],
            "evidence_ref_ids": [str(value) for value in evidence_ids],
            "retrieval": None if response is None else response.model_dump(mode="json"),
        }
        content = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest = canonical_sha256(document)
        object_key = f"c2/results/{context.verification_id}/{context.claim.claim_id}/{digest}.json"
        stored = await self._artifact_store.put(
            tenant_id=context.claim.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise LiyanError(
                ErrorCode.TOPIC4_INTEGRITY_FAILED,
                "C2 result artifact integrity validation failed.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        artifact = ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=object_key,
            media_type="application/json",
            content_encoding="identity",
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=context.claim.created_at,
        )
        return ModuleFinding(
            verdict=verdict,
            confidence=confidence,
            evidence_ref_ids=tuple(evidence_ids),
            finding_codes=(code,),
            result_artifact=artifact,
            result_sha256=artifact.sha256,
            deterministic=True,
        )


class Topic4Runtime:
    """Coordinates C1 state transitions, module execution, C8, and C12."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        verification_service: VerificationService,
        verification_repository: PostgresVerificationRepository,
        retrieval_service: KnowledgeRetrievalService,
        knowledge_repository: PostgresKnowledgeRepository,
        topic1_repository: PostgresTopic1Repository,
        topic3_repository: PostgresTopic3Repository,
        revision_engine: RevisionEngine,
        release_service: C12ReleaseService,
        artifact_store: ArtifactObjectStore,
        outbox: PostgresOutboxRepository,
        executor: BoundedModuleExecutor,
        metrics: Topic4RuntimeMetrics,
        *,
        instance_id: str,
        task_queue: AsyncTaskQueue | None = None,
        prompt_bundle_version: str = "topic4-prompts-v1",
        compliance_service: ComplianceEvidenceService | None = None,
    ) -> None:
        self.database = database
        self.verification_service = verification_service
        self.verification_repository = verification_repository
        self.retrieval_service = retrieval_service
        self.knowledge_repository = knowledge_repository
        self.topic1_repository = topic1_repository
        self.topic3_repository = topic3_repository
        self.revision_engine = revision_engine
        self.release_service = release_service
        self.artifact_store = artifact_store
        self.outbox = outbox
        self.executor = executor
        self.metrics = metrics
        self.instance_id = instance_id
        self.prompt_bundle_version = prompt_bundle_version
        self.task_queue = task_queue
        self.compliance_service = compliance_service
        self._ready = False
        self._locks: dict[tuple[str, UUID], asyncio.Lock] = {}

    @property
    def ready(self) -> bool:
        return self._ready

    def mark_ready(self) -> None:
        """Mark the runtime ready after all queue and message handlers are registered."""
        self._ready = True

    def queue_request(self, verification_id: UUID, context: TenantContext) -> TaskRequest:
        return TaskRequest(
            task_type=TOPIC4_VERIFICATION_TASK,
            tenant_id=context.tenant_id,
            task_id=uuid5(verification_id, "topic4-verification-task"),
            payload={
                "verification_id": str(verification_id),
                "subject_ref": context.subject_ref,
                "trace_id": context.trace_id,
                "session_id": None if context.session_id is None else str(context.session_id),
            },
            priority=TaskPriority.HIGH,
            timeout_seconds=900.0,
            max_attempts=2,
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            correlation_id=verification_id,
        )

    async def handle_queue_task(self, request: TaskRequest) -> dict[str, Any]:
        if request.task_type != TOPIC4_VERIFICATION_TASK:
            raise ValueError("unexpected Topic 4 task type")
        session_value = request.payload.get("session_id")
        context = TenantContext(
            tenant_id=request.tenant_id,
            subject_ref=str(request.payload["subject_ref"]),
            roles=frozenset({"topic4-worker"}),
            scopes=frozenset({"topic4:admin", "topic4:verification:write"}),
            trace_id=str(request.payload["trace_id"]),
            session_id=None if session_value is None else UUID(str(session_value)),
        )
        with tenant_scope(context):
            result = await self.execute(UUID(str(request.payload["verification_id"])))
        return result

    async def accept(
        self,
        request: VerificationRequestPayloadV1,
        *,
        enqueue: bool = True,
    ) -> dict[str, Any]:
        accepted = await self.verification_service.accept_verification(request)
        dispatch_mode = "NOT_QUEUED"
        if enqueue:
            await self.enqueue(request.verification_id)
            dispatch_mode = "LOCAL_QUEUE"
        return {"accepted": accepted.model_dump(mode="json"), "dispatch_mode": dispatch_mode}

    async def execute(self, verification_id: UUID) -> dict[str, Any]:
        tenant_id = current_tenant().tenant_id
        lock = self._locks.setdefault((tenant_id, verification_id), asyncio.Lock())
        async with lock:
            started = asyncio.get_running_loop().time()
            try:
                result = await self._execute_locked(verification_id)
                self.metrics.verifications.labels("completed").inc()
                return result
            except Exception:
                self.metrics.verifications.labels("failed").inc()
                raise
            finally:
                self.metrics.duration.observe(asyncio.get_running_loop().time() - started)

    async def _execute_locked(self, verification_id: UUID) -> dict[str, Any]:
        verification, state = await self.verification_service.get_verification(verification_id)
        current_version = state.change.state_version
        if state.change.current_state in {
            VerificationState.ACCEPTED,
            VerificationState.REVERIFYING,
        }:
            preparation = await self.verification_service.prepare_control_plane(
                verification_id,
                expected_state_version=current_version,
                idempotency_key=f"topic4:prepare:{verification_id.hex}:v1",
            )
            state = await self._state_record(verification_id)
            current_version = state.change.state_version
            if preparation.state.current_state == VerificationState.REVIEW_REQUIRED:
                return await self.snapshot(verification_id)

        if state.change.current_state == VerificationState.MODULE_DISPATCHING:
            await self.verification_service.transition(
                verification_id,
                expected_state_version=current_version,
                target_state=VerificationState.VERIFYING,
                reason_code="MODULE_EXECUTION_STARTED",
                idempotency_key=f"topic4:verify:{verification_id.hex}:v1",
            )
            state = await self._state_record(verification_id)
            current_version = state.change.state_version

        if state.change.current_state == VerificationState.VERIFYING:
            claims, plan, existing_runs = await self._execution_inputs(verification_id)
            if not existing_runs:
                bundle = await self.executor.execute(
                    plan,
                    claims,
                    deadline_at=verification.accepted.deadline_at,
                )
                await self.verification_service.persist_module_execution(
                    verification_id,
                    bundle,
                    expected_state_version=current_version,
                    idempotency_key=f"topic4:modules:{verification_id.hex}:v1",
                )
            state = await self._state_record(verification_id)
            if state.change.current_state == VerificationState.VERIFYING:
                await self.verification_service.finalize_control_plane(
                    verification_id,
                    expected_state_version=state.change.state_version,
                    idempotency_key=f"topic4:finalize:{verification_id.hex}:v1",
                )
        return await self.snapshot(verification_id)

    async def snapshot(self, verification_id: UUID) -> dict[str, Any]:
        verification, state = await self.verification_service.get_verification(verification_id)
        context = current_tenant()
        async with self.database.transaction(context=current_session_context()) as session:
            claims = await self.verification_repository.list_claims(
                session, context.tenant_id, verification_id
            )
            risks = await self.verification_repository.list_risks(
                session, context.tenant_id, verification_id
            )
            plan = await self.verification_repository.latest_dispatch_plan(
                session, context.tenant_id, verification_id
            )
            runs = await self.verification_repository.list_latest_module_runs(
                session, context.tenant_id, verification_id
            )
            results = await self.verification_repository.list_module_results(
                session, context.tenant_id, verification_id
            )
            verdicts = await self.verification_repository.list_claim_verdicts(
                session, context.tenant_id, verification_id
            )
            aggregation = await self.verification_repository.latest_aggregation(
                session, context.tenant_id, verification_id
            )
            report = await self.verification_repository.latest_report(
                session, context.tenant_id, verification_id
            )
            review = await self.verification_repository.latest_review_task(
                session, context.tenant_id, verification_id
            )
        return {
            "verification": verification.accepted.model_dump(mode="json"),
            "state": state.change.model_dump(mode="json"),
            "claims": [item.model_dump(mode="json") for item in claims],
            "risks": [item.model_dump(mode="json") for item in risks],
            "dispatch_plan": None if plan is None else plan.model_dump(mode="json"),
            "module_runs": [item.model_dump(mode="json") for item in runs],
            "module_results": [item.model_dump(mode="json") for item in results],
            "claim_verdicts": [item.model_dump(mode="json") for item in verdicts],
            "aggregation": None if aggregation is None else aggregation.model_dump(mode="json"),
            "report": None if report is None else report.model_dump(mode="json"),
            "review_task": None if review is None else review.model_dump(mode="json"),
        }

    async def retrieve(
        self,
        claim: ClaimV1,
        *,
        course_id: str,
        idempotency_key: str,
    ) -> RetrievalResponseV1:
        return await self.retrieval_service.retrieve_claim(
            claim,
            course_id=course_id,
            target_kp_id=None,
            idempotency_key=idempotency_key,
        )

    async def evidence(self, claim_id: UUID) -> list[Any]:
        context = current_tenant()
        async with self.database.transaction(context=current_session_context()) as session:
            return await self.knowledge_repository.list_evidence_refs(
                session, context.tenant_id, claim_id
            )

    async def import_compliance(self, command: Any) -> Any:
        if self.compliance_service is None:
            raise LiyanError(
                ErrorCode.DATABASE_UNAVAILABLE,
                "The Topic 4 compliance evidence service is unavailable.",
                category=ErrorCategory.DATABASE,
                status_code=503,
            )
        return await self.compliance_service.import_package(command)

    async def compliance_package(self, verification_id: UUID | None, claim_id: UUID) -> Any:
        if self.compliance_service is None:
            raise LiyanError(
                ErrorCode.DATABASE_UNAVAILABLE,
                "The Topic 4 compliance evidence service is unavailable.",
                category=ErrorCategory.DATABASE,
                status_code=503,
            )
        if verification_id is None:
            return await self.compliance_service.package_for_claim_id(claim_id)
        return await self.compliance_service.package_for_claim(verification_id, claim_id)

    async def review_tasks(self, state: ReviewTaskState) -> list[HumanReviewTaskV1]:
        context = current_tenant()
        async with self.database.transaction(context=current_session_context()) as session:
            result = await session.execute(
                select(Topic4HumanReviewTaskModel)
                .where(Topic4HumanReviewTaskModel.tenant_id == context.tenant_id)
                .order_by(
                    Topic4HumanReviewTaskModel.review_task_id,
                    Topic4HumanReviewTaskModel.task_version.desc(),
                )
            )
            latest: dict[UUID, HumanReviewTaskV1] = {}
            for row in result.scalars():
                latest.setdefault(
                    row.review_task_id,
                    HumanReviewTaskV1.model_validate(row.task_document),
                )
        return [task for task in latest.values() if task.state == state]

    async def submit_review(
        self,
        *,
        review_task_id: UUID,
        verification_id: UUID,
        decision: ReviewDecision,
        rationale: str,
        disclosure_codes: list[str],
        waived_finding_ids: list[UUID],
        expected_task_version: int,
        expected_state_version: int,
        idempotency_key: str,
    ) -> Any:
        context = current_tenant()
        now = datetime.now(UTC)
        rationale_document = {
            "schema_version": "human-review.rationale.v1",
            "trace_id": context.trace_id,
            "tenant_id": context.tenant_id,
            "review_task_id": str(review_task_id),
            "verification_id": str(verification_id),
            "decision": decision.value,
            "rationale": rationale,
            "disclosure_codes": list(disclosure_codes),
            "waived_finding_ids": [str(item) for item in waived_finding_ids],
            "expected_task_version": expected_task_version,
            "expected_state_version": expected_state_version,
        }
        content = json.dumps(
            rationale_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = canonical_sha256(rationale_document)
        key = f"human-review/{verification_id}/{review_task_id}/{digest}.json"
        stored = await self.artifact_store.put(
            tenant_id=context.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise LiyanError(
                ErrorCode.TOPIC4_INTEGRITY_FAILED,
                "Human review rationale artifact integrity failed.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        rationale_artifact = ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=key,
            media_type="application/json",
            content_encoding="identity",
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=now,
        )
        review_decision = build_topic4_record(
            HumanReviewDecisionV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=expected_task_version + 1,
            created_at=now,
            immutable=True,
            schema_version="human-review.decision.v1",
            review_decision_id=uuid5(
                NAMESPACE_URL,
                f"topic4:review:{context.tenant_id}:{idempotency_key}",
            ),
            review_task_id=review_task_id,
            verification_id=verification_id,
            decision=decision,
            reviewer_subject_ref=context.subject_ref,
            rationale_artifact=rationale_artifact,
            rationale_sha256=stored.sha256,
            disclosure_codes=disclosure_codes,
            waived_finding_ids=waived_finding_ids,
            decided_at=now,
            decision_context={"idempotency_key_sha256": canonical_sha256({"key": idempotency_key})},
        )
        return await self.verification_service.submit_human_review(
            review_decision,
            expected_task_version=expected_task_version,
            expected_state_version=expected_state_version,
            idempotency_key=idempotency_key,
        )

    async def claims(self, verification_id: UUID) -> list[ClaimV1]:
        context = current_tenant()
        async with self.database.transaction(context=current_session_context()) as session:
            return await self.verification_repository.list_claims(
                session, context.tenant_id, verification_id
            )

    async def revisions(self, verification_id: UUID, *, limit: int = 100) -> list[dict[str, Any]]:
        context = current_tenant()
        async with self.database.transaction(context=current_session_context()) as session:
            from liyans.domains.revision.models import Topic4RevisionCycleModel

            result = await session.execute(
                select(Topic4RevisionCycleModel.cycle_document)
                .where(
                    Topic4RevisionCycleModel.tenant_id == context.tenant_id,
                    Topic4RevisionCycleModel.verification_id == verification_id,
                )
                .order_by(Topic4RevisionCycleModel.created_at.desc())
                .limit(limit)
            )
            return [dict(document) for document in result.scalars()]

    async def trace(self, trace_id: str, *, limit: int = 500) -> dict[str, Any]:
        """Return tenant-scoped immutable records carrying a distributed trace id."""
        if not 16 <= len(trace_id) <= 128:
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "TraceID must contain between 16 and 128 characters.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            )
        context = current_tenant()
        bounded_limit = min(limit, 2000)
        records: list[dict[str, Any]] = []
        async with self.database.transaction(context=current_session_context()) as session:
            for mapper in sorted(Base.registry.mappers, key=lambda item: item.local_table.name):
                table = mapper.local_table
                column_names = {column.name for column in table.columns}
                if not {"tenant_id", "trace_id", "created_at"} <= column_names:
                    continue
                result = await session.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant_id,
                        table.c.trace_id == trace_id,
                    )
                    .order_by(table.c.created_at.asc())
                    .limit(bounded_limit)
                )
                for row in result.mappings():
                    records.append(self._trace_row(table, row))
        records.sort(key=lambda item: (item["created_at"], item["table"], item["record_id"]))
        return {
            "trace_id": trace_id,
            "tenant_id": context.tenant_id,
            "records": records[:bounded_limit],
            "record_count": min(len(records), bounded_limit),
        }

    async def publication_history(
        self,
        *,
        verification_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read only the current tenant's append-only C12 authorization/publication history."""
        context = current_tenant()
        bounded_limit = min(limit, 1000)
        rows: list[dict[str, Any]] = []
        async with self.database.transaction(context=current_session_context()) as session:
            authorization_ids: set[UUID] = set()
            batch_ids: set[UUID] = set()
            authorization_query = select(Topic4ReleaseAuthorizationModel).where(
                Topic4ReleaseAuthorizationModel.tenant_id == context.tenant_id
            )
            if verification_id is not None:
                authorization_query = authorization_query.where(
                    Topic4ReleaseAuthorizationModel.verification_id == verification_id
                )
            authorization_result = await session.execute(authorization_query)
            for model in authorization_result.scalars():
                authorization_ids.add(model.authorization_id)
                rows.append(self._model_row(model, Topic4ReleaseAuthorizationModel.__tablename__))

            batch_query = select(Topic4PublicationBatchModel).where(
                Topic4PublicationBatchModel.tenant_id == context.tenant_id
            )
            if verification_id is not None:
                batch_query = batch_query.where(
                    Topic4PublicationBatchModel.verification_id == verification_id
                )
            elif authorization_ids:
                batch_query = batch_query.where(
                    Topic4PublicationBatchModel.authorization_id.in_(authorization_ids)
                )
            batch_result = await session.execute(batch_query)
            for model in batch_result.scalars():
                batch_ids.add(model.publication_batch_id)
                rows.append(self._model_row(model, Topic4PublicationBatchModel.__tablename__))

            if authorization_ids:
                consumption_result = await session.execute(
                    select(Topic4ReleaseAuthorizationConsumptionModel).where(
                        Topic4ReleaseAuthorizationConsumptionModel.tenant_id == context.tenant_id,
                        Topic4ReleaseAuthorizationConsumptionModel.authorization_id.in_(
                            authorization_ids
                        ),
                    )
                )
                rows.extend(
                    self._model_row(model, Topic4ReleaseAuthorizationConsumptionModel.__tablename__)
                    for model in consumption_result.scalars()
                )

            if batch_ids:
                event_result = await session.execute(
                    select(Topic4PublicStreamEventModel).where(
                        Topic4PublicStreamEventModel.tenant_id == context.tenant_id,
                        Topic4PublicStreamEventModel.publication_batch_id.in_(batch_ids),
                    )
                )
                rows.extend(
                    self._model_row(model, Topic4PublicStreamEventModel.__tablename__)
                    for model in event_result.scalars()
                )
        rows.sort(key=lambda item: (item["created_at"], item["table"], item["record_id"]))
        return rows[-bounded_limit:]

    @staticmethod
    def _trace_row(table, row) -> dict[str, Any]:
        values = {column.name: row[column] for column in table.columns}
        primary_key = next((column.name for column in table.primary_key.columns), None)
        document = next(
            (
                values[name]
                for name in values
                if name.endswith("_document") or name in {"event_metadata", "metadata"}
            ),
            None,
        )
        return {
            "table": table.name,
            "record_id": str(values.get(primary_key)) if primary_key else "",
            "trace_id": str(values["trace_id"]),
            "version_cas": values.get("version_cas"),
            "record_sha256": values.get("record_sha256"),
            "created_at": values["created_at"].isoformat(),
            "document": json.loads(json.dumps(document, ensure_ascii=False, default=str))
            if document is not None
            else None,
        }

    @staticmethod
    def _model_row(model: Any, table_name: str) -> dict[str, Any]:
        document = None
        for name in dir(model):
            if name.endswith("_document") or name in {"event_metadata", "metadata"}:
                candidate = getattr(model, name, None)
                if candidate is not None:
                    document = candidate
                    break
        return {
            "table": table_name,
            "record_id": str(
                getattr(model, "authorization_record_id", None)
                or getattr(model, "consumption_record_id", None)
                or getattr(model, "publication_batch_snapshot_id", None)
                or getattr(model, "public_event_record_id", None)
            ),
            "trace_id": str(model.trace_id),
            "version_cas": model.version_cas,
            "record_sha256": model.record_sha256,
            "created_at": model.created_at.isoformat(),
            "document": json.loads(json.dumps(document, ensure_ascii=False, default=str))
            if document is not None
            else None,
        }

    async def issue_authorization(
        self, authorization: ReleaseAuthorizationPayloadV1
    ) -> ReleaseAuthorizationPayloadV1:
        await self._validate_persisted_release_authority(authorization, require_pending=True)
        return await self.release_service.issue_authorization(authorization)

    async def validate_authorization(self, authorization: ReleaseAuthorizationPayloadV1) -> None:
        await self._validate_persisted_release_authority(authorization, require_pending=True)

    async def publish(self, request: PublicationRequest) -> PublicationResult:
        await self._validate_persisted_release_authority(
            request.authorization,
            report=request.report,
            candidate=request.candidate,
            require_pending=False,
        )
        return await self.release_service.publish(request)

    async def derive_release_authorization(
        self,
        command: ReleaseDerivationCommandV2,
        *,
        idempotency_key: str,
    ) -> ReleaseAuthorizationPayloadV1:
        context = current_tenant()
        expected_key_sha = canonical_sha256({"idempotency_key": idempotency_key})
        if (
            command.tenant_id != context.tenant_id
            or command.trace_id != context.trace_id
            or command.idempotency_key_sha256 != expected_key_sha
            or not record_integrity_valid(command)
        ):
            raise ReleaseError("C12 v2 derivation command does not match trusted context")
        authorization_id = uuid5(
            NAMESPACE_URL,
            f"topic4:c12:derive:{context.tenant_id}:{idempotency_key}",
        )
        existing = await self.release_service.get_authorization(authorization_id)
        if existing is not None:
            if existing.verification_id != command.verification_id:
                raise ReleaseError(
                    "C12 v2 Idempotency-Key was reused for a different verification"
                ) from None
            expected_blocks = await self._requested_release_blocks(
                command.verification_id,
                command.requested_block_ids,
            )
            if (
                existing.release_mode != command.requested_release_mode
                or existing.allowed_block_ids != expected_blocks
                or int((existing.expires_at - existing.issued_at).total_seconds())
                != command.ttl_seconds
            ):
                raise ReleaseError(
                    "C12 v2 Idempotency-Key was reused with different release content"
                ) from None
            return existing
        report, candidate, aggregation, state = await self._release_authority(
            command.verification_id
        )
        if state.change.current_state != VerificationState.RELEASE_PENDING:
            raise ReleaseError("C12 authorization derivation requires RELEASE_PENDING state")
        expected_decision = (
            AggregateDecision.RELEASE
            if command.requested_release_mode == "FULL"
            else AggregateDecision.RELEASE_WITH_DISCLOSURE
        )
        if report.decision != expected_decision or aggregation.decision != expected_decision:
            raise ReleaseError("C12 requested release mode disagrees with persisted decisions")
        allowed_blocks = await self._requested_release_blocks(
            command.verification_id,
            command.requested_block_ids,
            candidate=candidate,
        )
        disclosure_codes = (
            list(aggregation.disclosure_codes)
            if command.requested_release_mode == "FULL_WITH_DISCLOSURE"
            else []
        )
        now = datetime.now(UTC)
        authorization = build_topic4_record(
            ReleaseAuthorizationPayloadV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="release.authorization.v1",
            authorization_id=authorization_id,
            verification_id=command.verification_id,
            report_id=report.report_id,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            candidate_sha256=candidate.candidate_sha256,
            release_mode=command.requested_release_mode,
            allowed_block_ids=allowed_blocks,
            disclosure_codes=disclosure_codes,
            report_sha256=report.report_sha256,
            issued_at=now,
            expires_at=now + timedelta(seconds=command.ttl_seconds),
            one_time_use=True,
        )
        await self._validate_persisted_release_authority(
            authorization,
            report=report,
            candidate=candidate,
            state=state,
        )
        try:
            return await self.release_service.issue_authorization(authorization)
        except AuthorizationConflictError:
            existing = await self.release_service.get_authorization(authorization_id)
            if existing is None:
                raise
            if existing.verification_id != command.verification_id:
                raise ReleaseError(
                    "C12 v2 Idempotency-Key was reused for a different verification"
                ) from None
            expected_blocks = await self._requested_release_blocks(
                command.verification_id,
                command.requested_block_ids,
            )
            if (
                existing.release_mode != command.requested_release_mode
                or existing.allowed_block_ids != expected_blocks
                or int((existing.expires_at - existing.issued_at).total_seconds())
                != command.ttl_seconds
            ):
                raise ReleaseError(
                    "C12 v2 Idempotency-Key was reused with different release content"
                ) from None
            return existing

    async def commit_release_v2(
        self,
        command: PublicationCommitCommandV2,
        *,
        idempotency_key: str,
    ) -> PublicationResult:
        context = current_tenant()
        expected_key_sha = canonical_sha256({"idempotency_key": idempotency_key})
        if (
            command.tenant_id != context.tenant_id
            or command.trace_id != context.trace_id
            or command.idempotency_key_sha256 != expected_key_sha
            or not record_integrity_valid(command)
        ):
            raise ReleaseError("C12 v2 commit command does not match trusted context")
        authorization = await self.release_service.get_authorization(command.authorization_id)
        if authorization is None:
            raise ReleaseError("C12 authorization does not exist in the current tenant")
        report, candidate, _aggregation, _state = await self._release_authority(
            authorization.verification_id
        )
        if (
            report.report_id != authorization.report_id
            or candidate.candidate_id != authorization.candidate_id
            or candidate.candidate_version != authorization.candidate_version
        ):
            raise ReleaseError("C12 authorization authority changed")
        await self._validate_persisted_release_authority(
            authorization,
            report=report,
            candidate=candidate,
            state=_state,
            require_pending=False,
        )
        request_document = {
            "publication": {
                "authorization_id": str(authorization.authorization_id),
                "verification_id": str(authorization.verification_id),
                "report_id": str(authorization.report_id),
                "candidate_id": str(authorization.candidate_id),
                "candidate_version": authorization.candidate_version,
                "candidate_sha256": authorization.candidate_sha256,
                "report_sha256": authorization.report_sha256,
                "allowed_block_ids": authorization.allowed_block_ids,
            },
            "commit_command_id": str(command.commit_command_id),
            "idempotency_key_sha256": command.idempotency_key_sha256,
        }
        request = PublicationRequest(
            authorization=authorization,
            report=report,
            candidate=candidate,
            request_document=request_document,
            request_sha256=canonical_sha256(request_document),
            subject_ref=context.subject_ref,
        )
        return await self.release_service.publish(request)

    async def _release_authority(self, verification_id: UUID):
        context = current_tenant()
        async with self.database.transaction(context=current_session_context()) as session:
            report = await self.verification_repository.latest_report(
                session, context.tenant_id, verification_id
            )
            aggregation = await self.verification_repository.latest_aggregation(
                session, context.tenant_id, verification_id
            )
            state = await self.verification_repository.latest_state(
                session, context.tenant_id, verification_id
            )
            if report is None or aggregation is None or state is None:
                raise ReleaseError("C12 persisted report, aggregation, or state is missing")
            candidate_record = await self.topic3_repository.get_candidate(
                session,
                context.tenant_id,
                report.candidate_id,
                report.candidate_version,
            )
        if candidate_record is None:
            raise ReleaseError("C12 persisted Candidate is missing")
        return report, candidate_record.candidate, aggregation, state

    async def _validate_persisted_release_authority(
        self,
        authorization: ReleaseAuthorizationPayloadV1,
        *,
        report: Any | None = None,
        candidate: CandidateV1 | None = None,
        state: Any | None = None,
        require_pending: bool = False,
    ) -> None:
        context = current_tenant()
        (
            persisted_report,
            persisted_candidate,
            aggregation,
            persisted_state,
        ) = await self._release_authority(authorization.verification_id)
        report = persisted_report if report is None else report
        candidate = persisted_candidate if candidate is None else candidate
        state = persisted_state if state is None else state
        if (
            authorization.tenant_id != context.tenant_id
            or not record_integrity_valid(authorization)
            or not record_integrity_valid(report)
            or not record_integrity_valid(aggregation)
            or persisted_report.model_dump(mode="json") != report.model_dump(mode="json")
            or persisted_candidate.model_dump(mode="json") != candidate.model_dump(mode="json")
            or (require_pending and state.change.current_state != VerificationState.RELEASE_PENDING)
            or authorization.verification_id != report.verification_id
            or authorization.report_id != report.report_id
            or authorization.candidate_id != candidate.candidate_id
            or authorization.candidate_version != candidate.candidate_version
            or authorization.candidate_sha256 != candidate.candidate_sha256
            or authorization.report_sha256 != report.report_sha256
            or report.report_artifact.sha256 != report.report_sha256
            or report.aggregation_result_id != aggregation.aggregation_result_id
            or aggregation.verification_id != report.verification_id
            or aggregation.candidate_id != candidate.candidate_id
            or aggregation.candidate_version != candidate.candidate_version
            or aggregation.candidate_sha256 != candidate.candidate_sha256
            or canonical_sha256(candidate.model_dump(mode="json", exclude={"candidate_sha256"}))
            != candidate.candidate_sha256
        ):
            raise ReleaseError("C12 request does not match persisted release authority")
        expected_decision = (
            AggregateDecision.RELEASE
            if authorization.release_mode == "FULL"
            else AggregateDecision.RELEASE_WITH_DISCLOSURE
        )
        if report.decision != expected_decision or aggregation.decision != expected_decision:
            raise ReleaseError("C12 release mode disagrees with persisted decision")
        block_ids = {block.block_id for block in candidate.blocks}
        allowed = set(authorization.allowed_block_ids)
        if not allowed or not allowed <= block_ids:
            raise ReleaseError("C12 authorization contains a non-persisted block")
        if authorization.release_mode == "FULL" and allowed != block_ids:
            raise ReleaseError("C12 FULL authorization does not cover the persisted Candidate")
        expected_disclosures = (
            list(aggregation.disclosure_codes)
            if authorization.release_mode == "FULL_WITH_DISCLOSURE"
            else []
        )
        if authorization.disclosure_codes != expected_disclosures:
            raise ReleaseError("C12 authorization disclosure binding does not match aggregation")

    async def _requested_release_blocks(
        self,
        verification_id: UUID,
        requested_block_ids: list[str],
        *,
        candidate: CandidateV1 | None = None,
    ) -> list[str]:
        if candidate is None:
            _report, candidate, _aggregation, _state = await self._release_authority(
                verification_id
            )
        all_blocks = [block.block_id for block in candidate.blocks]
        if not requested_block_ids:
            return all_blocks
        requested = set(requested_block_ids)
        if not requested <= set(all_blocks):
            raise ReleaseError("C12 requested block set exceeds persisted Candidate blocks")
        return [block_id for block_id in all_blocks if block_id in requested]

    async def revision(
        self,
        request: Any,
        patches: list[Any],
        *,
        prompt_bundle_version: str | None = None,
    ) -> RevisionOutcome:
        context = current_tenant()
        parent, _state = await self.verification_service.get_verification(request.verification_id)

        async def operation(session: AsyncSession) -> RevisionOutcome:
            candidate = await self.topic3_repository.get_candidate(
                session,
                context.tenant_id,
                request.original_candidate_id,
                request.original_candidate_version,
            )
            if candidate is None:
                raise RevisionError("the original Candidate does not exist")
            audit_event_id = await self._append_audit(
                session,
                context,
                action="REVISION_STARTED",
                target_ref=str(request.revision_request_id),
                metadata={
                    "verification_id": str(request.verification_id),
                    "candidate_id": str(request.original_candidate_id),
                    "revision_round": request.revision_round,
                },
            )
            return await self.revision_engine.revise(
                session,
                tenant_id=context.tenant_id,
                request=request,
                candidate=candidate,
                patches=patches,
                audit_event_id=audit_event_id,
                lock_owner=self.instance_id,
                prompt_bundle_version=prompt_bundle_version or self.prompt_bundle_version,
            )

        outcome = await self.database.run_transaction(
            operation,
            context=current_session_context(),
            isolation=TransactionIsolation.SERIALIZABLE,
            retry_policy=TransactionRetryPolicy(max_attempts=3),
        )
        child_request = await self._request_for_candidate(
            outcome.candidate.candidate,
            context=context,
            source_envelope_id=uuid5(request.revision_request_id, "reverification-source"),
            trigger=VerificationTrigger.REVISION_REVERIFY,
            parent_verification_id=request.verification_id,
            parent_request=parent.request,
            verification_id=outcome.reverification.verification_id,
        )
        try:
            await self.verification_service.accept_verification(child_request)
        except LiyanError as exc:
            if exc.code != ErrorCode.TOPIC4_CONFLICT:
                raise
        await self.enqueue(child_request.verification_id)
        return outcome

    async def enqueue(self, verification_id: UUID) -> None:
        queue = self.task_queue
        if queue is None:
            return
        context = current_tenant()
        await queue.enqueue(self.queue_request(verification_id, context))

    async def _execution_inputs(
        self, verification_id: UUID
    ) -> tuple[list[ClaimV1], ModuleDispatchPlanV1, list[Any]]:
        context = current_tenant()
        async with self.database.transaction(context=current_session_context()) as session:
            claims = await self.verification_repository.list_claims(
                session, context.tenant_id, verification_id
            )
            plan = await self.verification_repository.latest_dispatch_plan(
                session, context.tenant_id, verification_id
            )
            runs = await self.verification_repository.list_latest_module_runs(
                session, context.tenant_id, verification_id
            )
        if plan is None:
            raise LiyanError(
                ErrorCode.TOPIC4_INTEGRITY_FAILED,
                "The Topic 4 dispatch plan is missing.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        return claims, plan, runs

    async def _state_record(self, verification_id: UUID):
        _verification, state = await self.verification_service.get_verification(verification_id)
        return state

    async def _request_for_candidate(
        self,
        candidate: CandidateV1,
        *,
        context: TenantContext,
        source_envelope_id: UUID,
        trigger: VerificationTrigger,
        parent_verification_id: UUID | None,
        parent_request: VerificationRequestPayloadV1 | None = None,
        verification_id: UUID | None = None,
        course_id: str | None = None,
        target_kp_id: str | None = None,
        profile: VerificationProfile | None = None,
    ) -> VerificationRequestPayloadV1:
        now = datetime.now(UTC)
        candidate_document = candidate.model_dump(mode="json")
        content = json.dumps(
            candidate_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = sha256(content).hexdigest()
        object_key = (
            f"topic4/candidates/{candidate.candidate_id}/"
            f"v{candidate.candidate_version}/{digest}.json"
        )
        stored = await self.artifact_store.put(
            tenant_id=context.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise LiyanError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "The Topic 4 Candidate snapshot failed immutable object validation.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        block_manifest = [
            BlockSnapshotManifestItemV1(
                block_id=block.block_id,
                block_type=block.block_type.value,
                ordinal=block.ordinal,
                json_pointer=f"/blocks/{block.ordinal}",
                sha256=block.content_sha256,
                byte_size=len(
                    json.dumps(
                        block.content,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ),
            )
            for block in candidate.blocks
        ]
        full_snapshot = ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=object_key,
            media_type="application/json",
            content_encoding="identity",
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=now,
        )
        if parent_request is None:
            if course_id is None or target_kp_id is None:
                raise ValueError("initial Topic 4 verification requires course and knowledge point")
            selected_profile = profile or VerificationProfile.STRICT
            personalization_digest = candidate.personalization_policy_digest
            deadline = now + timedelta(minutes=15)
            source_version = candidate.blueprint_version
        else:
            course_id = parent_request.context.course_id
            target_kp_id = parent_request.context.target_kp_id
            selected_profile = parent_request.requested_profile
            personalization_digest = parent_request.context.personalization_policy_digest
            deadline = max(now + timedelta(minutes=5), parent_request.deadline_at)
            source_version = parent_request.source_snapshot_ref.source_envelope_version
        request_id = verification_id or uuid5(
            candidate.candidate_id,
            f"topic4-verification:{candidate.candidate_version}:{candidate.candidate_sha256}",
        )
        source_document = {
            "candidate_id": str(candidate.candidate_id),
            "candidate_version": candidate.candidate_version,
            "candidate_sha256": candidate.candidate_sha256,
            "source_envelope_id": str(source_envelope_id),
        }
        return build_topic4_record(
            VerificationRequestPayloadV1,
            schema_version="verification.request.v1",
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            verification_id=request_id,
            idempotency_key=f"topic4:accept:{request_id.hex}:v1",
            trigger=trigger,
            parent_verification_id=parent_verification_id,
            source_snapshot_ref=SourceSnapshotRefV1(
                schema_version="source.snapshot.ref.v1",
                source_envelope_id=source_envelope_id,
                source_envelope_version=source_version,
                source_envelope_sha256=canonical_sha256(source_document),
                blueprint_id=candidate.blueprint_id,
                blueprint_version=candidate.blueprint_version,
                blueprint_sha256=candidate.blueprint_sha256,
                candidate_id=candidate.candidate_id,
                candidate_version=candidate.candidate_version,
                candidate_sha256=candidate.candidate_sha256,
                source_agent=candidate.provenance.agent,
                resource_type=candidate.resource_type,
                full_snapshot=full_snapshot,
                block_manifest=block_manifest,
            ),
            context=VerificationContextV1(
                schema_version="verification.context.v1",
                course_id=course_id,
                course_version=candidate.blueprint_version,
                target_kp_id=target_kp_id,
                locale="zh-CN",
                subject_domain="AUTOMATION",
                personalization_policy_digest=personalization_digest,
            ),
            requested_profile=selected_profile,
            requested_optional_modules=[],
            deadline_at=deadline,
            requested_at=now,
        )

    async def _append_audit(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        action: str,
        target_ref: str,
        metadata: dict[str, Any],
    ) -> UUID:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"audit:{context.tenant_id}"},
        )
        previous = (
            await session.execute(
                select(AuditEventModel)
                .where(AuditEventModel.tenant_id == context.tenant_id)
                .order_by(AuditEventModel.sequence.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
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


class Topic3CandidateVerificationConsumer:
    """Converts a committed Topic 3 workflow into durable C1 verification tasks."""

    def __init__(self, runtime: Topic4Runtime, topic3_service: Topic3Service) -> None:
        self._runtime = runtime
        self._topic3_service = topic3_service

    async def __call__(self, envelope) -> None:
        if envelope.event_type != "topic3.workflow.finalized":
            raise ValueError("unexpected Topic 3 event for Topic 4 consumer")
        generation_session_id = UUID(str(envelope.payload["generation_session_id"]))
        (
            _session,
            command,
            _personalization,
            _blueprint,
            _tasks,
            candidates,
        ) = await self._topic3_service.load_runtime(generation_session_id)
        if command.locale != "zh-CN":
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "Topic 4 currently accepts only the frozen zh-CN verification contract.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            )
        context = current_tenant()
        for record in candidates:
            candidate = record.candidate
            if candidate.status != CandidateStatus.COMPLETE:
                continue
            request = await self._runtime._request_for_candidate(
                candidate,
                context=context,
                source_envelope_id=envelope.envelope_id,
                trigger=VerificationTrigger.INITIAL_GENERATION,
                parent_verification_id=None,
                verification_id=None,
                course_id=command.course_id,
                target_kp_id=command.target_kp_ids[0],
                profile=VerificationProfile.STRICT,
            )
            try:
                await self._runtime.accept(request)
            except LiyanError as exc:
                if exc.code != ErrorCode.TOPIC4_CONFLICT:
                    raise


class Topic4PublicationSSEConsumer:
    """Projects committed C12 events into the durable public SSE broker."""

    def __init__(self, broker: SSEBroker, metrics: Topic4RuntimeMetrics) -> None:
        self._broker = broker
        self._metrics = metrics

    async def __call__(self, envelope) -> None:
        if envelope.event_type != "topic4.publication.committed":
            raise ValueError("unexpected publication event")
        await self._broker.publish(
            envelope.tenant_id,
            "topic4.publication.committed",
            {
                "schema_version": "topic4.publication.sse.v1",
                "trace_id": envelope.trace_id,
                "tenant_id": envelope.tenant_id,
                "envelope_id": str(envelope.envelope_id),
                "partition_key": envelope.partition_key,
                "partition_sequence": envelope.sequence,
                "payload": dict(envelope.payload),
            },
        )
        self._metrics.publications.labels("committed").inc()


def build_topic4_handlers(
    *,
    database: DatabaseSessionManager,
    verification_service: VerificationService,
    knowledge_repository: PostgresKnowledgeRepository,
    topic1_repository: PostgresTopic1Repository,
    topic3_repository: PostgresTopic3Repository,
    retrieval_service: KnowledgeRetrievalService,
    artifact_store: ArtifactObjectStore,
    metrics: Topic4RuntimeMetrics,
    compliance_service: ComplianceEvidenceService | None = None,
) -> dict[VerificationModule, VerificationModuleHandler]:
    evidence = CandidateEvidenceSource(database, knowledge_repository, topic3_repository)
    handlers: dict[VerificationModule, VerificationModuleHandler] = {
        VerificationModule.C2_RAG: C2RetrievalHandler(
            retrieval_service,
            verification_service,
            artifact_store,
            metrics,
        ),
        VerificationModule.C3_ACADEMIC: C3AcademicHandler(
            PostgresAcademicEvidenceSource(database, knowledge_repository),
            artifact_store,
        ),
        VerificationModule.C4_GRAPH: C4GraphHandler(
            PostgresGraphEvidenceSource(database, knowledge_repository, topic1_repository),
            artifact_store,
        ),
        VerificationModule.C5_QUIZ: C5QuizHandler(
            PostgresQuizEvidenceSource(
                database,
                knowledge_repository,
                topic1_repository,
                topic3_repository,
            ),
            artifact_store,
        ),
        VerificationModule.C6_CODE: C6CodeHandler(
            PostgresCodeEvidenceSource(
                database,
                knowledge_repository,
                topic1_repository,
                topic3_repository,
            ),
            artifact_store,
        ),
        VerificationModule.C7_EXTENSION: C7ExtensionHandler(
            PostgresExtensionEvidenceSource(
                database,
                knowledge_repository,
                topic1_repository,
                topic3_repository,
            ),
            artifact_store,
        ),
        VerificationModule.C9_SECURITY: C9SecurityHandler(evidence.security, artifact_store),
        VerificationModule.C10_PRIVACY: C10PrivacyHandler(evidence.privacy, artifact_store),
        VerificationModule.C11_COMPLIANCE: C11ComplianceHandler(
            evidence.compliance if compliance_service is None else compliance_service,
            artifact_store,
        ),
    }
    return handlers


def map_topic4_error(exc: Exception) -> LiyanError:
    if isinstance(exc, LiyanError):
        return exc
    if isinstance(exc, ComplianceEvidenceError):
        return LiyanError(
            ErrorCode.TOPIC4_INTEGRITY_FAILED,
            "The Topic 4 compliance evidence failed its trusted integrity checks.",
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )
    if isinstance(exc, (ReleaseError, RevisionError, AggregationError)):
        return LiyanError(
            ErrorCode.TOPIC4_RELEASE_DENIED
            if isinstance(exc, ReleaseError)
            else ErrorCode.TOPIC4_INTEGRITY_FAILED,
            "The Topic 4 operation was rejected by its immutable integrity policy.",
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )
    return LiyanError(
        ErrorCode.TOPIC4_INTEGRITY_FAILED,
        "The Topic 4 operation could not be completed.",
        category=ErrorCategory.INTERNAL,
        status_code=500,
    )
