from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import CourseStatus, KnowledgePointStatus
from liyans_contracts.topic2 import Topic2AgentContextV1
from sqlalchemy import func, select, text

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.tenant import tenant_scope
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic1.service import Topic1Service
from liyans.domains.topic2.entities import (
    BehaviorEventType,
    BehaviorSourceType,
    LearningBehaviorEventDraft,
    LearningPathSnapshotDraft,
    MemoryRiskLevel,
    MemoryStateDraft,
    PathChangeDraft,
    PathChangeType,
    PathPlanType,
    ProfileDimension,
    ProfileFeatureDraft,
    StudentProfileDraft,
)
from liyans.domains.topic2.memory import EbbinghausMemoryEngine
from liyans.domains.topic2.models import (
    Topic2LearningBehaviorEventModel,
    Topic2LearningPathSnapshotModel,
    Topic2MemoryStateModel,
    Topic2StudentProfileModel,
)
from liyans.domains.topic2.orchestrator import Topic2Orchestrator
from liyans.domains.topic2.path_planning import AdaptivePathPlanner
from liyans.domains.topic2.postgres_repository import PostgresTopic2Repository
from liyans.domains.topic2.profiling import SixDimensionProfileEngine
from liyans.domains.topic2.seed import blank_profile_seed_to_drafts, build_blank_profile_seed
from liyans.domains.topic2.service import Topic2Service
from liyans.infrastructure.database import session_context_from_tenant
from liyans.infrastructure.database.models import AuditEventModel, OutboxMessageModel
from liyans.infrastructure.observability.audit import verify_audit_chain
from liyans.infrastructure.observability.postgres_audit import PostgresAuditStore
from liyans.infrastructure.persistence import PostgresOutboxRepository

pytestmark = pytest.mark.integration


def topic1_service(database) -> Topic1Service:
    return Topic1Service(
        database,
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="topic2-topic1-fixture",
    )


def topic2_service(database) -> Topic2Service:
    return Topic2Service(
        database,
        PostgresTopic2Repository(),
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="topic2-integration",
    )


def topic2_orchestrator(database, persistence: Topic2Service) -> Topic2Orchestrator:
    return Topic2Orchestrator(
        database,
        PostgresTopic1Repository(),
        persistence,
        SixDimensionProfileEngine(),
        EbbinghausMemoryEngine(),
        AdaptivePathPlanner(),
    )


async def seed_topic1(service: Topic1Service) -> None:
    await service.upsert_course(
        course_id="CRS_ATC_001",
        document={
            "course_code": "ATC",
            "title": "Automatic Control Theory",
            "description": "Classical automatic-control foundations.",
            "locale": "zh-CN",
            "academic_level": "UNDERGRADUATE",
            "credit_hours": 64,
            "status": CourseStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="topic2-topic1-course-0001",
    )
    await service.upsert_knowledge_point(
        course_id="CRS_ATC_001",
        kp_id="KP_ATC_301_TRANSFER_FUNCTION",
        document={
            "title": "Transfer Function",
            "aliases": [],
            "summary": "Laplace-domain input-output model.",
            "learning_objectives": ["Derive transfer functions."],
            "category": "MODELING",
            "difficulty_level": 3,
            "difficulty_score": 0.52,
            "estimated_minutes": 120,
            "formula_signatures": ["G(s)=Y(s)/U(s)"],
            "tags": ["transfer-function"],
            "status": KnowledgePointStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="topic2-topic1-kp-0000001",
    )


def behavior(now: datetime, learner_ref: str) -> LearningBehaviorEventDraft:
    payload = {"question_id": "QUESTION_ATC_TRANSFER_001", "answer": "3/(s+2)"}
    return LearningBehaviorEventDraft(
        event_id=uuid4(),
        source_event_id="tester-answer-0000000001",
        event_version=1,
        learner_ref=learner_ref,
        course_id="CRS_ATC_001",
        kp_id="KP_ATC_301_TRANSFER_FUNCTION",
        session_id=uuid4(),
        event_type=BehaviorEventType.ANSWER_SUBMITTED,
        source_type=BehaviorSourceType.TESTER,
        duration_seconds=90,
        response_latency_ms=12000,
        correctness=1,
        score=0.9,
        attempt_count=1,
        interaction_count=2,
        attention_ratio=0.95,
        misconception_ids=(),
        goal_tags=("FOUNDATION",),
        payload=payload,
        payload_sha256=canonical_sha256(payload),
        occurred_at=now,
        received_at=now,
    )


def review_behavior(
    occurred_at: datetime,
    received_at: datetime,
    learner_ref: str,
    *,
    source_event_id: str,
    score: float,
) -> LearningBehaviorEventDraft:
    payload = {"review_mode": "spaced-retrieval", "kp_id": "KP_ATC_301_TRANSFER_FUNCTION"}
    return LearningBehaviorEventDraft(
        event_id=uuid4(),
        source_event_id=source_event_id,
        event_version=1,
        learner_ref=learner_ref,
        course_id="CRS_ATC_001",
        kp_id="KP_ATC_301_TRANSFER_FUNCTION",
        session_id=uuid4(),
        event_type=BehaviorEventType.REVIEW_COMPLETED,
        source_type=BehaviorSourceType.LEARNER_UI,
        duration_seconds=120,
        response_latency_ms=8000,
        correctness=score,
        score=score,
        attempt_count=1,
        interaction_count=1,
        attention_ratio=0.9,
        misconception_ids=(),
        goal_tags=("REVIEW",),
        payload=payload,
        payload_sha256=canonical_sha256(payload),
        occurred_at=occurred_at,
        received_at=received_at,
    )


def profile(now: datetime, learner_ref: str) -> StudentProfileDraft:
    profile_id = uuid4()
    dimensions = {
        "knowledge_mastery": 0.72,
        "problem_solving_proficiency": 0.68,
        "misconception_preference": 0.1,
        "learning_pace": 0.55,
        "forgetting_rate": 0.35,
        "learning_goal_tendency": 0.7,
    }
    document = {
        "schema_version": "topic2.student-profile.v1",
        "profile_id": str(profile_id),
        "profile_version": 1,
        "learner_ref": learner_ref,
        "course_id": "CRS_ATC_001",
        "policy_version": "topic2.profile-policy.v1",
        "dimensions": dimensions,
        "confidence_score": 0.8,
        "activity_count": 1,
        "source_window": {"start": now.isoformat(), "end": now.isoformat()},
        "generated_at": now.isoformat(),
    }
    features = tuple(
        ProfileFeatureDraft(
            feature_id=uuid4(),
            dimension=dimension,
            feature_key="aggregate",
            value_document={"source": "behavior"},
            normalized_score=dimensions[
                {
                    ProfileDimension.KNOWLEDGE_MASTERY: "knowledge_mastery",
                    ProfileDimension.PROBLEM_SOLVING_PROFICIENCY: ("problem_solving_proficiency"),
                    ProfileDimension.MISCONCEPTION_PREFERENCE: "misconception_preference",
                    ProfileDimension.LEARNING_PACE: "learning_pace",
                    ProfileDimension.FORGETTING_RATE: "forgetting_rate",
                    ProfileDimension.LEARNING_GOAL_TENDENCY: "learning_goal_tendency",
                }[dimension]
            ],
            confidence=0.8,
            evidence_count=1,
            source_event_ids=("tester-answer-0000000001",),
            computed_at=now,
        )
        for dimension in ProfileDimension
    )
    return StudentProfileDraft(
        profile_id=profile_id,
        learner_ref=learner_ref,
        course_id="CRS_ATC_001",
        profile_version=1,
        parent_profile_id=None,
        policy_version="topic2.profile-policy.v1",
        confidence_score=0.8,
        activity_count=1,
        last_event_at=now,
        source_window_start=now,
        source_window_end=now,
        profile_document=document,
        content_sha256=canonical_sha256(document),
        frozen_at=now,
        features=features,
        **dimensions,
    )


def memory_state(now: datetime, learner_ref: str, service: Topic2Service) -> MemoryStateDraft:
    state = MemoryStateDraft(
        memory_state_id=uuid4(),
        learner_ref=learner_ref,
        course_id="CRS_ATC_001",
        kp_id="KP_ATC_301_TRANSFER_FUNCTION",
        state_version=1,
        parent_memory_state_id=None,
        model_version="topic2.memory.exponential.v1",
        stability_days=3,
        effective_stability_days=2.2,
        elapsed_days=0,
        retrievability=0.9,
        forgetting_rate=0.35,
        difficulty_factor=1.2,
        review_gain=1.5,
        review_count=1,
        lapse_count=0,
        last_reviewed_at=now,
        last_activity_at=now,
        next_review_at=now + timedelta(days=2),
        risk_level=MemoryRiskLevel.LOW,
        model_parameters={"policy_version": "topic2.memory-policy.v1"},
        content_sha256="0" * 64,
        computed_at=now,
    )
    return replace(state, content_sha256=canonical_sha256(service.memory_hash_document(state)))


def learning_path(
    now: datetime,
    learner_ref: str,
    profile_id,
    graph_snapshot,
    service: Topic2Service,
) -> tuple[LearningPathSnapshotDraft, PathChangeDraft]:
    path_id = uuid4()
    snapshot = LearningPathSnapshotDraft(
        path_snapshot_id=path_id,
        learner_ref=learner_ref,
        course_id="CRS_ATC_001",
        path_version=1,
        parent_path_snapshot_id=None,
        topic1_graph_snapshot_id=graph_snapshot.snapshot_id,
        topic1_graph_version=graph_snapshot.graph_version,
        profile_id=profile_id,
        plan_type=PathPlanType.INITIAL,
        trigger_reason="INITIAL_PROFILE_READY",
        target_goal="Master classical control foundations",
        policy_version="topic2.path-policy.v1",
        path_document={
            "nodes": [
                {
                    "kp_id": "KP_ATC_301_TRANSFER_FUNCTION",
                    "tier": "FOUNDATION",
                    "order": 0,
                }
            ]
        },
        decision_document={"score_components": {"mastery_deficit": 0.28}},
        node_count=1,
        estimated_minutes=120,
        manual_override=False,
        content_sha256="0" * 64,
        frozen_at=now,
    )
    snapshot = replace(
        snapshot,
        content_sha256=canonical_sha256(service.path_hash_document(snapshot)),
    )
    change = PathChangeDraft(
        change_id=uuid4(),
        learner_ref=learner_ref,
        course_id="CRS_ATC_001",
        from_path_snapshot_id=None,
        to_path_snapshot_id=path_id,
        change_type=PathChangeType.INITIALIZED,
        reason="Initial path generated from the accepted Topic 1 graph.",
        policy_version="topic2.path-policy.v1",
        change_document={"added": ["KP_ATC_301_TRANSFER_FUNCTION"]},
        occurred_at=now,
    )
    return snapshot, change


@pytest.mark.asyncio
async def test_topic2_transactional_persistence_chain(postgres_runtime) -> None:
    database, migrator, base_context = postgres_runtime
    context = replace(
        base_context,
        scopes=frozenset({"topic2:learner:any", "topic2:memory:batch"}),
    )
    topic1 = topic1_service(database)
    topic2 = topic2_service(database)
    now = datetime.now(UTC)
    with tenant_scope(context):
        await seed_topic1(topic1)
        graph_snapshot = (await topic1.list_snapshots("CRS_ATC_001"))[0]
        behavior_event = behavior(now, context.subject_ref)
        first = await topic2.record_behavior_event(
            behavior_event,
            idempotency_key="topic2-behavior-record-0001",
        )
        duplicate = await topic2.record_behavior_event(
            behavior_event,
            idempotency_key="topic2-behavior-record-0001",
        )
        assert duplicate == first
        profile_snapshot = profile(now, context.subject_ref)
        await topic2.save_profile(
            profile_snapshot,
            idempotency_key="topic2-profile-save-000001",
        )
        state = memory_state(now, context.subject_ref, topic2)
        await topic2.save_memory_states(
            [state],
            idempotency_key="topic2-memory-save-0000001",
        )
        path_snapshot, change = learning_path(
            now,
            context.subject_ref,
            profile_snapshot.profile_id,
            graph_snapshot,
            topic2,
        )
        await topic2.save_learning_path(
            path_snapshot,
            change,
            idempotency_key="topic2-path-save-00000001",
        )
        assert (await topic2.latest_profile(context.subject_ref, "CRS_ATC_001")) is not None
        assert len(await topic2.latest_memory_states(context.subject_ref, "CRS_ATC_001")) == 1
        assert (await topic2.latest_learning_path(context.subject_ref, "CRS_ATC_001")) is not None

    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        assert (
            await session.scalar(select(func.count()).select_from(Topic2LearningBehaviorEventModel))
            == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(Topic2StudentProfileModel)) == 1
        )
        assert await session.scalar(select(func.count()).select_from(Topic2MemoryStateModel)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(Topic2LearningPathSnapshotModel))
            == 1
        )
        topic2_audits = await session.scalar(
            select(func.count()).where(AuditEventModel.category == "TOPIC2")
        )
        topic2_outbox = await session.scalar(
            select(func.count()).where(OutboxMessageModel.event_type.like("topic2.%"))
        )
    assert topic2_audits == 4
    assert topic2_outbox == 4
    with tenant_scope(context):
        assert verify_audit_chain(await PostgresAuditStore(database).records(context.tenant_id))


@pytest.mark.asyncio
async def test_topic2_cross_tenant_profile_is_invisible(postgres_runtime) -> None:
    database, migrator, base_context = postgres_runtime
    owner_context = replace(base_context, scopes=frozenset({"topic2:learner:any"}))
    persistence = topic2_service(database)
    now = datetime.now(UTC)
    with tenant_scope(owner_context):
        await seed_topic1(topic1_service(database))
        await persistence.save_profile(
            profile(now, owner_context.subject_ref),
            idempotency_key="topic2-tenant-owner-profile-01",
        )

    other_context = replace(
        owner_context,
        tenant_id=f"other-{uuid4().hex[:24]}",
        trace_id="d" * 32,
    )
    async with migrator.transaction(context=session_context_from_tenant(other_context)) as session:
        await session.execute(
            text(
                "INSERT INTO tenants "
                "(tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim) "
                "VALUES (:tenant_id, :slug, :display_name, :issuer, :tenant_claim)"
            ),
            {
                "tenant_id": other_context.tenant_id,
                "slug": other_context.tenant_id,
                "display_name": "Other Tenant",
                "issuer": "https://issuer.other.test",
                "tenant_claim": other_context.tenant_id,
            },
        )
    with tenant_scope(other_context):
        hidden = await persistence.latest_profile(owner_context.subject_ref, "CRS_ATC_001")
    assert hidden is None


@pytest.mark.asyncio
async def test_topic2_memory_batch_foreign_key_failure_rolls_back_everything(
    postgres_runtime,
) -> None:
    database, migrator, base_context = postgres_runtime
    context = replace(base_context, scopes=frozenset({"topic2:learner:any"}))
    persistence = topic2_service(database)
    now = datetime.now(UTC)
    with tenant_scope(context):
        await seed_topic1(topic1_service(database))
        valid = memory_state(now, context.subject_ref, persistence)
        invalid = replace(
            valid,
            memory_state_id=uuid4(),
            kp_id="KP_ATC_999_MISSING",
            content_sha256="0" * 64,
        )
        invalid = replace(
            invalid,
            content_sha256=canonical_sha256(persistence.memory_hash_document(invalid)),
        )
        with pytest.raises(LiyanError) as error:
            await persistence.save_memory_states(
                [valid, invalid],
                idempotency_key="topic2-memory-rollback-0001",
            )
    assert error.value.code == ErrorCode.CONTRACT_INVALID
    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        memory_count = await session.scalar(
            select(func.count()).select_from(Topic2MemoryStateModel)
        )
        audit_count = await session.scalar(
            select(func.count()).where(AuditEventModel.category == "TOPIC2")
        )
        outbox_count = await session.scalar(
            select(func.count()).where(OutboxMessageModel.event_type.like("topic2.%"))
        )
    assert memory_count == 0
    assert audit_count == 0
    assert outbox_count == 0


@pytest.mark.asyncio
async def test_topic2_concurrent_path_version_conflict_keeps_one_snapshot(
    postgres_runtime,
) -> None:
    database, migrator, base_context = postgres_runtime
    context = replace(base_context, scopes=frozenset({"topic2:learner:any"}))
    topic1 = topic1_service(database)
    persistence = topic2_service(database)
    now = datetime.now(UTC)
    with tenant_scope(context):
        await seed_topic1(topic1)
        graph_snapshot = (await topic1.list_snapshots("CRS_ATC_001"))[0]
        profile_snapshot = profile(now, context.subject_ref)
        await persistence.save_profile(
            profile_snapshot,
            idempotency_key="topic2-path-race-profile-0001",
        )
        first_snapshot, first_change = learning_path(
            now,
            context.subject_ref,
            profile_snapshot.profile_id,
            graph_snapshot,
            persistence,
        )
        second_snapshot, second_change = learning_path(
            now,
            context.subject_ref,
            profile_snapshot.profile_id,
            graph_snapshot,
            persistence,
        )
        results = await asyncio.gather(
            persistence.save_learning_path(
                first_snapshot,
                first_change,
                idempotency_key="topic2-path-race-write-0001",
            ),
            persistence.save_learning_path(
                second_snapshot,
                second_change,
                idempotency_key="topic2-path-race-write-0002",
            ),
            return_exceptions=True,
        )
    assert sum(isinstance(item, dict) for item in results) == 1
    failures = [item for item in results if isinstance(item, LiyanError)]
    assert len(failures) == 1
    assert failures[0].code == ErrorCode.TOPIC2_VERSION_CONFLICT
    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        path_count = await session.scalar(
            select(func.count()).select_from(Topic2LearningPathSnapshotModel)
        )
    assert path_count == 1


@pytest.mark.asyncio
async def test_topic2_stale_profile_version_rolls_back(postgres_runtime) -> None:
    database, migrator, base_context = postgres_runtime
    context = replace(base_context, scopes=frozenset({"topic2:learner:any"}))
    topic1 = topic1_service(database)
    topic2 = topic2_service(database)
    now = datetime.now(UTC)
    with tenant_scope(context):
        await seed_topic1(topic1)
        initial = profile(now, context.subject_ref)
        await topic2.save_profile(initial, idempotency_key="topic2-profile-version-0001")
        stale = replace(
            initial,
            profile_id=uuid4(),
            features=tuple(replace(feature, feature_id=uuid4()) for feature in initial.features),
        )
        stale_document = {
            **stale.profile_document,
            "profile_id": str(stale.profile_id),
        }
        stale = replace(
            stale,
            profile_document=stale_document,
            content_sha256=canonical_sha256(stale_document),
        )
        with pytest.raises(LiyanError) as error:
            await topic2.save_profile(stale, idempotency_key="topic2-profile-version-0002")
    assert error.value.code == ErrorCode.TOPIC2_VERSION_CONFLICT
    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        count = await session.scalar(select(func.count()).select_from(Topic2StudentProfileModel))
        audits = await session.scalar(
            select(func.count()).where(AuditEventModel.category == "TOPIC2")
        )
    assert count == 1
    assert audits == 1


@pytest.mark.asyncio
async def test_topic2_orchestrator_replays_deterministic_operations(postgres_runtime) -> None:
    database, migrator, base_context = postgres_runtime
    context = replace(base_context, scopes=frozenset({"topic2:learner:any"}))
    topic1 = topic1_service(database)
    persistence = topic2_service(database)
    orchestrator = topic2_orchestrator(database, persistence)
    now = datetime.now(UTC)
    profile_operation = uuid4()
    memory_operation = uuid4()
    path_operation = uuid4()
    with tenant_scope(context):
        await seed_topic1(topic1)
        await orchestrator.record_behavior(
            behavior(now, context.subject_ref),
            idempotency_key="topic2-orchestrator-event-0001",
        )
        first_profile = await orchestrator.rebuild_profile(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=profile_operation,
            requested_at=now + timedelta(seconds=1),
            idempotency_key="topic2-orchestrator-profile-01",
        )
        replayed_profile = await orchestrator.rebuild_profile(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=profile_operation,
            requested_at=now + timedelta(seconds=1),
            idempotency_key="topic2-orchestrator-profile-01",
        )
        assert replayed_profile == first_profile
        first_memory = await orchestrator.refresh_memory(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=memory_operation,
            requested_at=now + timedelta(seconds=2),
            idempotency_key="topic2-orchestrator-memory-001",
        )
        replayed_memory = await orchestrator.refresh_memory(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=memory_operation,
            requested_at=now + timedelta(seconds=2),
            idempotency_key="topic2-orchestrator-memory-001",
        )
        assert replayed_memory == first_memory
        first_path = await orchestrator.generate_path(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=path_operation,
            requested_at=now + timedelta(seconds=3),
            target_goal="Master transfer-function modeling",
            idempotency_key="topic2-orchestrator-path-0001",
        )
        replayed_path = await orchestrator.generate_path(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=path_operation,
            requested_at=now + timedelta(seconds=3),
            target_goal="Master transfer-function modeling",
            idempotency_key="topic2-orchestrator-path-0001",
        )
        assert replayed_path == first_path
        context_document = await orchestrator.agent_context(
            context.subject_ref,
            "CRS_ATC_001",
        )
        Topic2AgentContextV1.model_validate(context_document)
        assert len(context_document["personalization_policy_digest"]) == 64

    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        assert (
            await session.scalar(select(func.count()).select_from(Topic2StudentProfileModel)) == 1
        )
        assert await session.scalar(select(func.count()).select_from(Topic2MemoryStateModel)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(Topic2LearningPathSnapshotModel))
            == 1
        )


@pytest.mark.asyncio
async def test_topic2_initialization_is_atomic_and_replay_stable(postgres_runtime) -> None:
    database, migrator, base_context = postgres_runtime
    context = replace(base_context, scopes=frozenset({"topic2:learner:any"}))
    topic1 = topic1_service(database)
    persistence = topic2_service(database)
    orchestrator = topic2_orchestrator(database, persistence)
    now = datetime.now(UTC)
    operation_id = uuid4()
    with tenant_scope(context):
        await seed_topic1(topic1)
        first = await orchestrator.initialize_learner(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=operation_id,
            requested_at=now,
            idempotency_key="topic2-initialize-learner-0001",
        )
        replay = await orchestrator.initialize_learner(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=operation_id,
            requested_at=now,
            idempotency_key="topic2-initialize-learner-0001",
        )
    assert replay == first
    assert first["profile"]["profile_document"]["operation_id"] == str(operation_id)
    assert len(first["memory_states"]) == 1
    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        assert (
            await session.scalar(select(func.count()).select_from(Topic2StudentProfileModel)) == 1
        )
        assert await session.scalar(select(func.count()).select_from(Topic2MemoryStateModel)) == 1
        assert (
            await session.scalar(
                select(func.count()).where(AuditEventModel.action == "LEARNER_STATE_INITIALIZED")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_topic2_initialization_rolls_back_profile_when_memory_fk_fails(
    postgres_runtime,
) -> None:
    database, migrator, base_context = postgres_runtime
    context = replace(base_context, scopes=frozenset({"topic2:learner:any"}))
    topic1 = topic1_service(database)
    persistence = topic2_service(database)
    now = datetime.now(UTC)
    with tenant_scope(context):
        await seed_topic1(topic1)
        graph = (await topic1.list_snapshots("CRS_ATC_001"))[0]
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            content = await PostgresTopic1Repository().load_graph_content(
                session,
                context.tenant_id,
                "CRS_ATC_001",
            )
        assert content is not None
        seed = build_blank_profile_seed(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            knowledge_points=content.knowledge_points,
            generated_at=now,
            operation_id=uuid4(),
            topic1_graph_snapshot_id=graph.snapshot_id,
            topic1_graph_version=graph.graph_version,
            topic1_graph_sha256=graph.content_sha256,
        )
        profile_draft, memory_states = blank_profile_seed_to_drafts(seed)
        invalid = replace(
            memory_states[0],
            kp_id="KP_ATC_999_MISSING",
            content_sha256="0" * 64,
        )
        invalid = replace(
            invalid,
            content_sha256=canonical_sha256(persistence.memory_hash_document(invalid)),
        )
        with pytest.raises(LiyanError) as error:
            await persistence.initialize_learning_state(
                profile_draft,
                [invalid],
                idempotency_key="topic2-initialize-rollback-01",
            )
    assert error.value.code == ErrorCode.CONTRACT_INVALID
    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        assert (
            await session.scalar(select(func.count()).select_from(Topic2StudentProfileModel)) == 0
        )
        assert await session.scalar(select(func.count()).select_from(Topic2MemoryStateModel)) == 0
        assert (
            await session.scalar(select(func.count()).where(AuditEventModel.category == "TOPIC2"))
            == 0
        )


@pytest.mark.asyncio
async def test_topic2_review_reconciliation_consumes_late_evidence_once(
    postgres_runtime,
) -> None:
    database, _migrator, base_context = postgres_runtime
    context = replace(base_context, scopes=frozenset({"topic2:learner:any"}))
    topic1 = topic1_service(database)
    persistence = topic2_service(database)
    orchestrator = topic2_orchestrator(database, persistence)
    now = datetime.now(UTC)
    with tenant_scope(context):
        await seed_topic1(topic1)
        await orchestrator.initialize_learner(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=uuid4(),
            requested_at=now,
            idempotency_key="topic2-review-seed-0000001",
        )
        first_review = review_behavior(
            now + timedelta(minutes=5),
            now + timedelta(minutes=5),
            context.subject_ref,
            source_event_id="topic2-review-on-time-0001",
            score=0.9,
        )
        await orchestrator.record_behavior(
            first_review,
            idempotency_key="topic2-review-event-on-time-1",
        )
        first_refresh = await orchestrator.refresh_memory(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=uuid4(),
            requested_at=now + timedelta(minutes=6),
            idempotency_key="topic2-review-refresh-000001",
        )
        first_state = first_refresh["memory_states"][0]
        assert first_state["review_count"] == 1
        assert first_state["stability_days"] > 1

        no_duplicate = await orchestrator.refresh_memory(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=uuid4(),
            requested_at=now + timedelta(minutes=7),
            idempotency_key="topic2-review-refresh-000002",
        )
        assert no_duplicate["memory_states"][0]["review_count"] == 1

        late_review = review_behavior(
            now + timedelta(minutes=4),
            now + timedelta(minutes=8),
            context.subject_ref,
            source_event_id="topic2-review-late-0000001",
            score=0.8,
        )
        await orchestrator.record_behavior(
            late_review,
            idempotency_key="topic2-review-event-late-001",
        )
        reconciled = await orchestrator.refresh_memory(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=uuid4(),
            requested_at=now + timedelta(minutes=9),
            idempotency_key="topic2-review-refresh-000003",
        )
    final_state = reconciled["memory_states"][0]
    assert final_state["review_count"] == 2
    assert final_state["model_parameters"]["last_review_source_event_id"] == (
        "topic2-review-late-0000001"
    )
    assert (
        final_state["model_parameters"]["last_review_effective_at"]
        > (final_state["model_parameters"]["last_review_occurred_at"])
    )


@pytest.mark.asyncio
async def test_topic2_profile_restore_and_due_memory_batch_are_replay_safe(
    postgres_runtime,
) -> None:
    database, _migrator, base_context = postgres_runtime
    context = replace(
        base_context,
        scopes=frozenset({"topic2:learner:any", "topic2:memory:batch"}),
    )
    topic1 = topic1_service(database)
    persistence = topic2_service(database)
    orchestrator = topic2_orchestrator(database, persistence)
    now = datetime.now(UTC)
    seed_operation = uuid4()
    restore_operation = uuid4()
    batch_operation = uuid4()
    with tenant_scope(context):
        await seed_topic1(topic1)
        initialized = await orchestrator.initialize_learner(
            learner_ref=context.subject_ref,
            course_id="CRS_ATC_001",
            operation_id=seed_operation,
            requested_at=now,
            idempotency_key="topic2-restore-seed-000001",
        )
        source_profile_id = UUID(initialized["profile"]["profile_id"])
        restored = await orchestrator.restore_profile(
            profile_id=source_profile_id,
            operation_id=restore_operation,
            requested_at=now + timedelta(minutes=1),
            idempotency_key="topic2-profile-restore-0001",
        )
        restore_replay = await orchestrator.restore_profile(
            profile_id=source_profile_id,
            operation_id=restore_operation,
            requested_at=now + timedelta(minutes=1),
            idempotency_key="topic2-profile-restore-0001",
        )
        batch = await orchestrator.refresh_due_memory(
            operation_id=batch_operation,
            requested_at=now + timedelta(minutes=2),
            idempotency_key="topic2-due-memory-batch-001",
            limit=100,
        )
        batch_replay = await orchestrator.refresh_due_memory(
            operation_id=batch_operation,
            requested_at=now + timedelta(minutes=2),
            idempotency_key="topic2-due-memory-batch-001",
            limit=100,
        )
    assert restore_replay == restored
    assert restored["profile"]["profile_version"] == 2
    assert restored["profile"]["profile_document"]["restored_from_profile_id"] == (
        str(source_profile_id)
    )
    assert batch["selected_state_count"] == 1
    assert batch["refreshed_state_count"] == 1
    assert batch_replay["selected_state_count"] == 0
    assert batch_replay["refreshed_state_count"] == 0
