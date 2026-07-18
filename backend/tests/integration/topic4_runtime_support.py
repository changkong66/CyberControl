from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType, VerificationTrigger
from liyans_contracts.topic4_common import ClaimKind, VerificationModule, VerificationVerdict
from liyans_contracts.verification import ReleaseAuthorizationPayloadV1, VerificationState
from prometheus_client import CollectorRegistry
from topic3_support import generation_command

from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.knowledge.lifecycle import KnowledgeBaseBuildCommand
from liyans.domains.release.engine import C12ReleaseService, PublicationRequest
from liyans.domains.release.postgres_repository import PostgresAtomicReleaseRepository
from liyans.domains.revision.engine import RevisionEngine
from liyans.domains.revision.postgres_repository import PostgresRevisionRepository
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic2.memory import EbbinghausMemoryEngine
from liyans.domains.topic2.orchestrator import Topic2Orchestrator
from liyans.domains.topic2.path_planning import AdaptivePathPlanner
from liyans.domains.topic2.postgres_repository import PostgresTopic2Repository
from liyans.domains.topic2.profiling import SixDimensionProfileEngine
from liyans.domains.topic2.service import Topic2Service
from liyans.domains.topic3.agents import Topic3AgentRegistry
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.orchestrator import Topic3Orchestrator
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository
from liyans.domains.topic3.service import Topic3Service
from liyans.domains.topic3.streaming import Topic3StreamCoordinator
from liyans.domains.verification.execution import (
    BoundedModuleExecutor,
    ModuleExecutionContext,
    ModuleFinding,
)
from liyans.domains.verification.postgres_repository import PostgresVerificationRepository
from liyans.domains.verification.records import build_topic4_record
from liyans.domains.verification.reporting import (
    TransactionalVerificationArtifactWriter,
    VerificationReportBuilder,
)
from liyans.domains.verification.runtime import (
    Topic4Runtime,
    Topic4RuntimeMetrics,
    build_topic4_handlers,
)
from liyans.domains.verification.service import VerificationService
from liyans.domains.verification.state_machine import VerificationStateMachine
from liyans.infrastructure.persistence import (
    FileSystemArtifactObjectStore,
    PostgresArtifactRepository,
    PostgresOutboxRepository,
)
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker
from liyans.providers.topic3 import Topic3ProviderRegistry

from .test_postgres_topic4 import _NotApplicableHandler
from .test_postgres_topic4_knowledge import (
    COURSE_ID,
    KP_ID,
    _c2_services,
    _c2_source_command,
    _FixtureSparkProvider,
    _seed_topic1,
    _verifier_versions,
)

ROOT = Path(__file__).resolve().parents[3]


@dataclass(slots=True)
class Topic4RuntimeFixture:
    database: Any
    migrator: Any
    context: TenantContext
    artifact_store: FileSystemArtifactObjectStore
    knowledge_repository: Any
    retrieval_service: Any
    topic1_repository: PostgresTopic1Repository
    topic3_repository: PostgresTopic3Repository
    topic3_service: Topic3Service
    topic3_runtime: Topic3Orchestrator
    outbox: PostgresOutboxRepository
    verification_repository: PostgresVerificationRepository
    verification_service: VerificationService
    runtime: Topic4Runtime
    candidate: Any
    command: Any
    now: datetime


async def build_topic4_runtime_fixture(
    postgres_runtime,
    tmp_path: Path,
    *,
    instance_suffix: str,
) -> Topic4RuntimeFixture:
    database, migrator, base_context = postgres_runtime
    context = TenantContext(
        tenant_id=base_context.tenant_id,
        subject_ref=base_context.subject_ref,
        roles=base_context.roles,
        scopes=frozenset(
            {
                "topic2:learner:any",
                "topic3:learner:any",
                "topic3:admin",
                "topic4:admin",
                "topic4:release",
            }
        ),
        trace_id=base_context.trace_id,
        session_id=base_context.session_id,
    )
    artifact_store = FileSystemArtifactObjectStore(tmp_path / "runtime-artifacts")
    (
        knowledge_repository,
        _writer,
        _transactions,
        _indexes,
        lifecycle,
        retrieval_service,
    ) = _c2_services(
        database,
        tmp_path / "c2-artifacts",
        instance_id=f"topic4-{instance_suffix}-c2",
    )
    topic1_repository = PostgresTopic1Repository()
    topic3_repository = PostgresTopic3Repository()
    outbox = PostgresOutboxRepository(database)
    topic2_service = Topic2Service(
        database,
        PostgresTopic2Repository(),
        topic1_repository,
        outbox,
        instance_id=f"topic4-{instance_suffix}-topic2",
    )
    topic2_runtime = Topic2Orchestrator(
        database,
        topic1_repository,
        topic2_service,
        SixDimensionProfileEngine(),
        EbbinghausMemoryEngine(),
        AdaptivePathPlanner(),
    )
    provider_registry = Topic3ProviderRegistry(
        ProviderPolicyRegistry.load(ROOT / "config" / "providers.toml"),
        {"spark_text": _FixtureSparkProvider()},
    )
    topic3_service = Topic3Service(
        database,
        topic3_repository,
        outbox,
        instance_id=f"topic4-{instance_suffix}-topic3",
    )
    topic3_runtime = Topic3Orchestrator(
        database,
        topic1_repository,
        topic2_runtime,
        topic3_service,
        ImmutableBlueprintPlanner(),
        Topic3AgentRegistry(provider_registry),
        Topic3StreamCoordinator(SSEBroker(InMemorySSEReplayLog(capacity_per_tenant=1000))),
    )
    versions = _verifier_versions()
    verification_repository = PostgresVerificationRepository()
    verification_service = VerificationService(
        database,
        verification_repository,
        topic3_repository,
        outbox,
        VerificationStateMachine(),
        versions,
        instance_id=f"topic4-{instance_suffix}-verifier",
        report_builder=VerificationReportBuilder(
            TransactionalVerificationArtifactWriter(
                PostgresArtifactRepository(database),
                artifact_store,
            ),
            knowledge_base_version=versions.knowledge_base_version,
            policy_version=versions.policy_version,
        ),
    )
    metrics = Topic4RuntimeMetrics(CollectorRegistry())
    handlers = build_topic4_handlers(
        database=database,
        verification_service=verification_service,
        knowledge_repository=knowledge_repository,
        topic1_repository=topic1_repository,
        topic3_repository=topic3_repository,
        retrieval_service=retrieval_service,
        artifact_store=artifact_store,
        metrics=metrics,
    )
    runtime = Topic4Runtime(
        database,
        verification_service,
        verification_repository,
        retrieval_service,
        knowledge_repository,
        topic1_repository,
        topic3_repository,
        RevisionEngine(
            PostgresRevisionRepository(topic3_repository),
            topic3_repository,
            artifact_store,
        ),
        C12ReleaseService(
            PostgresAtomicReleaseRepository(
                database,
                outbox,
                instance_id=f"topic4-{instance_suffix}-c12",
            ),
            artifact_store,
        ),
        artifact_store,
        outbox,
        BoundedModuleExecutor(
            handlers,
            worker_instance_id=f"topic4-{instance_suffix}-worker",
        ),
        metrics,
        instance_id=f"topic4-{instance_suffix}",
    )
    now = datetime.now(UTC)
    command = generation_command(
        resources=[ResourceType.LECTURER_DOC],
        target_kp_ids=[KP_ID],
    ).model_copy(
        update={
            "operation_id": uuid4(),
            "generation_session_id": uuid4(),
            "learner_ref": context.subject_ref,
            "course_id": COURSE_ID,
            "requested_at": now,
        }
    )

    with tenant_scope(context):
        await _seed_topic1(database)
        imported = await lifecycle.import_source(
            _c2_source_command(version="runtime-2026.1", title="Runtime authority"),
            idempotency_key=f"topic4-{instance_suffix}-source-0000000000000001",
        )
        await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=COURSE_ID,
                version="runtime-kb-2026.1",
                source_document_version_ids=(imported.source_version.source_document_version_id,),
            ),
            idempotency_key=f"topic4-{instance_suffix}-build-0000000000000001",
        )
        await topic2_runtime.initialize_learner(
            learner_ref=context.subject_ref,
            course_id=COURSE_ID,
            operation_id=uuid4(),
            requested_at=now,
            idempotency_key=f"topic4-{instance_suffix}-topic2-init-0000000000000001",
        )
        await topic2_runtime.generate_path(
            learner_ref=context.subject_ref,
            course_id=COURSE_ID,
            operation_id=uuid4(),
            requested_at=now,
            target_goal="Master closed-loop stability.",
            target_kp_ids=[KP_ID],
            idempotency_key=f"topic4-{instance_suffix}-topic2-path-0000000000000001",
        )
        await topic3_runtime.prepare(
            command,
            idempotency_key=f"topic4-{instance_suffix}-topic3-prepare-0000000000000001",
        )
        generated = await topic3_runtime.execute(command.generation_session_id)

    return Topic4RuntimeFixture(
        database=database,
        migrator=migrator,
        context=context,
        artifact_store=artifact_store,
        knowledge_repository=knowledge_repository,
        retrieval_service=retrieval_service,
        topic1_repository=topic1_repository,
        topic3_repository=topic3_repository,
        topic3_service=topic3_service,
        topic3_runtime=topic3_runtime,
        outbox=outbox,
        verification_repository=verification_repository,
        verification_service=verification_service,
        runtime=runtime,
        candidate=generated.candidates[0],
        command=command,
        now=now,
    )


async def finalize_release_report(
    fixture: Topic4RuntimeFixture,
    *,
    verification_id: UUID | None = None,
    handler_overrides: dict[VerificationModule, object] | None = None,
):
    request = await fixture.runtime._request_for_candidate(
        fixture.candidate,
        context=fixture.context,
        source_envelope_id=uuid4(),
        trigger=VerificationTrigger.INITIAL_GENERATION,
        parent_verification_id=None,
        verification_id=verification_id or uuid4(),
        course_id=COURSE_ID,
        target_kp_id=KP_ID,
    )
    accepted = await fixture.verification_service.accept_verification(request)
    prepared = await fixture.verification_service.prepare_control_plane(
        request.verification_id,
        expected_state_version=accepted.state_version,
        idempotency_key=f"topic4:release:prepare:{request.verification_id.hex}",
    )
    verifying = await fixture.verification_service.transition(
        request.verification_id,
        expected_state_version=prepared.state.state_version,
        target_state=VerificationState.VERIFYING,
        reason_code="MODULE_EXECUTION_STARTED",
        idempotency_key=f"topic4:release:verify:{request.verification_id.hex}",
    )
    handlers: dict[VerificationModule, object] = {
        module: _NotApplicableHandler() for module in VerificationModule
    }
    handlers.update(handler_overrides or {})
    bundle = await BoundedModuleExecutor(
        handlers,
        worker_instance_id="topic4-release-fixture-worker",
        retry_backoff_ms=0,
    ).execute(
        prepared.dispatch_plan,
        prepared.claims,
        deadline_at=request.deadline_at,
    )
    await fixture.verification_service.persist_module_execution(
        request.verification_id,
        bundle,
        expected_state_version=verifying.state_version,
        idempotency_key=f"topic4:release:modules:{request.verification_id.hex}",
    )
    finalized = await fixture.verification_service.finalize_control_plane(
        request.verification_id,
        expected_state_version=verifying.state_version,
        idempotency_key=f"topic4:release:finalize:{request.verification_id.hex}",
    )
    return request, finalized


class PartiallySupportedHandler:
    def __init__(self, partial_claim_kinds: frozenset[ClaimKind] | None = None) -> None:
        self._partial_claim_kinds = partial_claim_kinds

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        if (
            self._partial_claim_kinds is not None
            and context.claim.claim_kind not in self._partial_claim_kinds
        ):
            return await _NotApplicableHandler().verify(context)
        digest = canonical_sha256(
            {
                "claim_id": str(context.claim.claim_id),
                "module": context.dispatch_item.module.value,
                "verdict": "PARTIALLY_SUPPORTED",
            }
        )
        return ModuleFinding(
            verdict=VerificationVerdict.PARTIALLY_SUPPORTED,
            confidence=0.8,
            evidence_ref_ids=(),
            finding_codes=("FIXTURE_PARTIAL_SUPPORT",),
            result_artifact=ArtifactObjectRefV1(
                schema_version="artifact.object.ref.v1",
                storage_namespace="verification-artifacts",
                object_key=f"topic4/tests/module-results/{context.module_run_id}.json",
                media_type="application/json",
                content_encoding="identity",
                byte_size=2,
                sha256=digest,
                created_at=datetime.now(UTC),
            ),
            result_sha256=digest,
            deterministic=True,
        )


def build_release_authorization(
    fixture: Topic4RuntimeFixture,
    report,
    *,
    issued_at: datetime,
    expires_at: datetime | None = None,
) -> ReleaseAuthorizationPayloadV1:
    candidate = fixture.candidate
    return build_topic4_record(
        ReleaseAuthorizationPayloadV1,
        trace_id=fixture.context.trace_id,
        tenant_id=fixture.context.tenant_id,
        version_cas=1,
        created_at=issued_at,
        immutable=True,
        schema_version="release.authorization.v1",
        authorization_id=uuid4(),
        verification_id=report.verification_id,
        report_id=report.report_id,
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        candidate_sha256=candidate.candidate_sha256,
        release_mode="FULL",
        allowed_block_ids=[block.block_id for block in candidate.blocks],
        disclosure_codes=[],
        report_sha256=report.report_sha256,
        issued_at=issued_at,
        expires_at=expires_at or issued_at + timedelta(minutes=5),
        one_time_use=True,
    )


def build_publication_request(
    fixture: Topic4RuntimeFixture,
    authorization: ReleaseAuthorizationPayloadV1,
    report,
) -> PublicationRequest:
    candidate = fixture.candidate
    document = {
        "authorization_id": str(authorization.authorization_id),
        "verification_id": str(authorization.verification_id),
        "report_id": str(authorization.report_id),
        "candidate_id": str(authorization.candidate_id),
        "candidate_version": authorization.candidate_version,
        "candidate_sha256": authorization.candidate_sha256,
        "report_sha256": authorization.report_sha256,
        "allowed_block_ids": authorization.allowed_block_ids,
    }
    return PublicationRequest(
        authorization=authorization,
        report=report,
        candidate=candidate,
        request_document=document,
        request_sha256=canonical_sha256(document),
        subject_ref=fixture.context.subject_ref,
    )
