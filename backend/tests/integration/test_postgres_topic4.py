from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from liyans_contracts.artifacts import (
    ArtifactObjectRefV1,
    BlockSnapshotManifestItemV1,
    SourceSnapshotRefV1,
)
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import (
    ResourceType,
    VerificationProfile,
    VerificationTrigger,
)
from liyans_contracts.topic1 import CourseStatus, KnowledgePointStatus
from liyans_contracts.verification import (
    VerificationContextV1,
    VerificationRequestPayloadV1,
    VerificationState,
)
from sqlalchemy import func, select
from topic3_support import generation_command

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.core.tenant import tenant_scope
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic1.service import Topic1Service
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
from liyans.domains.verification.models import Topic4VerificationStateModel
from liyans.domains.verification.postgres_repository import PostgresVerificationRepository
from liyans.domains.verification.records import build_topic4_record
from liyans.domains.verification.service import VerificationService, VerifierRuntimeVersions
from liyans.domains.verification.state_machine import VerificationStateMachine
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import OutboxMessageModel
from liyans.infrastructure.observability.audit import verify_audit_chain
from liyans.infrastructure.observability.postgres_audit import PostgresAuditStore
from liyans.infrastructure.persistence import PostgresOutboxRepository
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker
from liyans.providers.topic3 import Topic3ProviderRegistry

pytestmark = pytest.mark.integration

COURSE_ID = "CRS_ATC_TOPIC4"
KP_ID = "KP_ATC_TOPIC4_STABILITY"
ROOT = Path(__file__).resolve().parents[3]


def _topic1_service(database) -> Topic1Service:
    return Topic1Service(
        database,
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="topic4-topic1-fixture",
    )


def _topic2_runtime(database) -> Topic2Orchestrator:
    topic1_repository = PostgresTopic1Repository()
    service = Topic2Service(
        database,
        PostgresTopic2Repository(),
        topic1_repository,
        PostgresOutboxRepository(database),
        instance_id="topic4-topic2-fixture",
    )
    return Topic2Orchestrator(
        database,
        topic1_repository,
        service,
        SixDimensionProfileEngine(),
        EbbinghausMemoryEngine(),
        AdaptivePathPlanner(),
    )


async def _seed_topic1(service: Topic1Service) -> None:
    await service.upsert_course(
        course_id=COURSE_ID,
        document={
            "course_code": "ATC-T4",
            "title": "Automatic Control Verification Fixture",
            "description": "Authoritative fixture for Topic 4 integration.",
            "locale": "zh-CN",
            "academic_level": "UNDERGRADUATE",
            "credit_hours": 64,
            "status": CourseStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="topic4-topic1-course-000000000001",
    )
    await service.upsert_knowledge_point(
        course_id=COURSE_ID,
        kp_id=KP_ID,
        document={
            "title": "Closed-loop stability",
            "aliases": [],
            "summary": "Closed-loop poles determine continuous-time stability.",
            "learning_objectives": ["Judge stability from characteristic roots."],
            "category": "STABILITY",
            "difficulty_level": 4,
            "difficulty_score": 0.72,
            "estimated_minutes": 120,
            "formula_signatures": ["1+G(s)H(s)=0"],
            "tags": ["stability", "routh-hurwitz"],
            "status": KnowledgePointStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="topic4-topic1-kp-00000000000001",
    )


def _verification_request(
    candidate,
    *,
    tenant_id: str,
    now: datetime,
) -> VerificationRequestPayloadV1:
    snapshot = ArtifactObjectRefV1(
        schema_version="artifact.object.ref.v1",
        storage_namespace="verification-artifacts",
        object_key=f"topic4/tests/{candidate.candidate_id}/candidate.json",
        media_type="application/json",
        content_encoding="identity",
        byte_size=len(json.dumps(candidate.model_dump(mode="json")).encode("utf-8")),
        sha256=candidate.candidate_sha256,
        created_at=now,
    )
    block_manifest = [
        BlockSnapshotManifestItemV1(
            block_id=block.block_id,
            block_type=block.block_type.value,
            ordinal=block.ordinal,
            json_pointer=f"/blocks/{block.ordinal}",
            sha256=block.content_sha256,
            byte_size=len(json.dumps(block.content).encode("utf-8")),
        )
        for block in candidate.blocks
    ]
    verification_id = uuid4()
    return build_topic4_record(
        VerificationRequestPayloadV1,
        trace_id="e" * 32,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=now,
        immutable=True,
        schema_version="verification.request.v1",
        verification_id=verification_id,
        idempotency_key=f"topic4:verify:{verification_id.hex}",
        trigger=VerificationTrigger.INITIAL_GENERATION,
        parent_verification_id=None,
        source_snapshot_ref=SourceSnapshotRefV1(
            schema_version="source.snapshot.ref.v1",
            source_envelope_id=uuid4(),
            source_envelope_version="topic3.envelope.v1",
            source_envelope_sha256=canonical_sha256(
                {"candidate_id": str(candidate.candidate_id)}
            ),
            blueprint_id=candidate.blueprint_id,
            blueprint_version=candidate.blueprint_version,
            blueprint_sha256=candidate.blueprint_sha256,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            candidate_sha256=candidate.candidate_sha256,
            source_agent=candidate.provenance.agent,
            resource_type=candidate.resource_type,
            full_snapshot=snapshot,
            block_manifest=block_manifest,
        ),
        context=VerificationContextV1(
            schema_version="verification.context.v1",
            course_id=COURSE_ID,
            course_version="1",
            target_kp_id=KP_ID,
            locale="zh-CN",
            subject_domain="AUTOMATION",
            personalization_policy_digest=candidate.personalization_policy_digest,
        ),
        requested_profile=VerificationProfile.STRICT,
        requested_optional_modules=[],
        deadline_at=now + timedelta(minutes=10),
        requested_at=now,
    )


def _versions() -> VerifierRuntimeVersions:
    return VerifierRuntimeVersions(
        state_machine_version="c1-state-machine-v1",
        verifier_build_version="topic4-integration-v1",
        policy_version="topic4-policy-v1",
        prompt_bundle_version="topic4-prompts-v1",
        retrieval_pipeline_version="local-rag-v1",
        knowledge_base_version="topic1-fixture-v1",
        toolchain_manifest_version="toolchain-v1",
        content_security_policy_version="security-v1",
        license_policy_version="license-v1",
    )


@pytest.mark.asyncio
async def test_topic4_accept_transition_replay_and_tenant_isolation(postgres_runtime) -> None:
    database, _migrator, base_context = postgres_runtime
    context = replace(
        base_context,
        trace_id="e" * 32,
        scopes=frozenset({"topic2:learner:any", "topic3:learner:any", "topic3:admin"}),
    )
    topic1 = _topic1_service(database)
    topic2 = _topic2_runtime(database)
    topic3_repository = PostgresTopic3Repository()
    topic3_service = Topic3Service(
        database,
        topic3_repository,
        PostgresOutboxRepository(database),
        instance_id="topic4-topic3-fixture",
    )
    provider_registry = Topic3ProviderRegistry(
        ProviderPolicyRegistry.load(ROOT / "config" / "providers.toml"),
        {},
    )
    orchestrator = Topic3Orchestrator(
        database,
        PostgresTopic1Repository(),
        topic2,
        topic3_service,
        ImmutableBlueprintPlanner(),
        Topic3AgentRegistry(provider_registry),
        Topic3StreamCoordinator(SSEBroker(InMemorySSEReplayLog(capacity_per_tenant=1000))),
    )
    verifier = VerificationService(
        database,
        PostgresVerificationRepository(),
        topic3_repository,
        PostgresOutboxRepository(database),
        VerificationStateMachine(),
        _versions(),
        instance_id="topic4-integration",
    )
    now = datetime.now(UTC)
    command = generation_command(
        resources=[ResourceType.MIND_MAP],
        target_kp_ids=[KP_ID],
    ).model_copy(
        update={
            "operation_id": uuid4(),
            "generation_session_id": uuid4(),
            "learner_ref": context.subject_ref,
            "course_id": COURSE_ID,
            "learning_goal": "Verify a closed-loop stability knowledge map.",
            "requested_at": now,
        }
    )

    with tenant_scope(context):
        await _seed_topic1(topic1)
        await topic2.initialize_learner(
            learner_ref=context.subject_ref,
            course_id=COURSE_ID,
            operation_id=uuid4(),
            requested_at=now,
            idempotency_key="topic4-topic2-init-00000000000001",
        )
        await topic2.generate_path(
            learner_ref=context.subject_ref,
            course_id=COURSE_ID,
            operation_id=uuid4(),
            requested_at=now,
            target_goal="Master closed-loop stability.",
            target_kp_ids=[KP_ID],
            idempotency_key="topic4-topic2-path-00000000000001",
        )
        await orchestrator.prepare(command, idempotency_key="topic4-topic3-prepare-0000000001")
        generation = await orchestrator.execute(command.generation_session_id)
        request = _verification_request(
            generation.candidates[0],
            tenant_id=context.tenant_id,
            now=now,
        )

        accepted = await verifier.accept_verification(request)
        replayed = await verifier.accept_verification(request)
        assert replayed == accepted

        state_version = accepted.state_version
        path = (
            VerificationState.SNAPSHOT_VALIDATING,
            VerificationState.CLAIM_EXTRACTING,
            VerificationState.CLAIMS_READY,
            VerificationState.MODULE_DISPATCHING,
            VerificationState.VERIFYING,
            VerificationState.AGGREGATING,
            VerificationState.RELEASE_PENDING,
            VerificationState.RELEASED,
        )
        for target in path:
            change = await verifier.transition(
                request.verification_id,
                expected_state_version=state_version,
                target_state=target,
                reason_code=f"TEST_{target.value}",
                idempotency_key=f"topic4:transition:{state_version:02d}:{request.verification_id.hex}",
            )
            state_version = change.state_version

        stored, latest = await verifier.get_verification(request.verification_id)
        audit_records = await PostgresAuditStore(database).records(context.tenant_id)
        assert stored.accepted == accepted
        assert latest.change.current_state == VerificationState.RELEASED
        assert latest.change.state_version == 9
        assert verify_audit_chain(audit_records)
        assert sum(record.category == "TOPIC4" for record in audit_records) == 9

        async with database.transaction(context=current_session_context()) as session:
            state_count = await session.scalar(
                select(func.count())
                .select_from(Topic4VerificationStateModel)
                .where(Topic4VerificationStateModel.verification_id == request.verification_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(OutboxMessageModel)
                .where(OutboxMessageModel.partition_key.contains(str(request.verification_id)))
            )
        assert state_count == 9
        assert outbox_count == 9

    other_context = replace(
        context,
        tenant_id=f"other-{uuid4().hex[:24]}",
        trace_id="f" * 32,
    )
    with tenant_scope(other_context):
        with pytest.raises(LiyanError) as denied:
            await verifier.get_verification(request.verification_id)
    assert denied.value.code == ErrorCode.TOPIC4_NOT_FOUND
