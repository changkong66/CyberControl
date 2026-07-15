from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import (
    CourseStatus,
    KnowledgePointStatus,
    MisconceptionSeverity,
    PrerequisiteType,
    Topic1CourseV1,
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1KnowledgePointV1,
    Topic1MisconceptionV1,
    Topic1PrerequisiteV1,
)

from liyans.domains.topic2.entities import (
    BehaviorEventType,
    BehaviorSourceType,
    LearningBehaviorEventDraft,
    LearningBehaviorEventRecord,
    PathChangeType,
    ProfileDimension,
    ProfileFeatureDraft,
    StudentProfileDraft,
    StudentProfileRecord,
)
from liyans.domains.topic2.memory import EbbinghausMemoryEngine
from liyans.domains.topic2.path_planning import AdaptivePathPlanner
from liyans.domains.topic2.profiling import SixDimensionProfileEngine
from liyans.domains.topic2.service import Topic2Service

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def point(kp_id: str, difficulty: float, minutes: int = 90) -> Topic1KnowledgePointV1:
    return Topic1KnowledgePointV1(
        kp_id=kp_id,
        course_id="CRS_ATC_001",
        revision=1,
        title=kp_id,
        summary=f"Authoritative knowledge for {kp_id}.",
        learning_objectives=[f"Master {kp_id}."],
        category="CONTROL_THEORY",
        difficulty_level=max(1, min(5, round(difficulty * 5))),
        difficulty_score=difficulty,
        topology_level=0,
        topology_weight=0,
        estimated_minutes=minutes,
        status=KnowledgePointStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def graph_snapshot(*, cyclic: bool = False) -> Topic1GraphSnapshotV1:
    course = Topic1CourseV1(
        course_id="CRS_ATC_001",
        revision=1,
        course_code="ATC",
        title="Automatic Control Theory",
        description="Classical control foundations.",
        credit_hours=64,
        status=CourseStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    points = [
        point("KP_ATC_A", 0.3),
        point("KP_ATC_B", 0.55),
        point("KP_ATC_C", 0.75),
    ]
    edges = [
        Topic1PrerequisiteV1(
            edge_id="EDGE_A_B",
            course_id=course.course_id,
            prerequisite_kp_id="KP_ATC_A",
            dependent_kp_id="KP_ATC_B",
            relation_type=PrerequisiteType.REQUIRED,
            strength=1,
            rationale="A precedes B.",
            revision=1,
            created_at=NOW,
            updated_at=NOW,
        ),
        Topic1PrerequisiteV1(
            edge_id="EDGE_B_C",
            course_id=course.course_id,
            prerequisite_kp_id="KP_ATC_B",
            dependent_kp_id="KP_ATC_C",
            relation_type=PrerequisiteType.REQUIRED,
            strength=1,
            rationale="B precedes C.",
            revision=1,
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    if cyclic:
        edges.append(
            Topic1PrerequisiteV1(
                edge_id="EDGE_C_A_RECOMMENDED",
                course_id=course.course_id,
                prerequisite_kp_id="KP_ATC_C",
                dependent_kp_id="KP_ATC_A",
                relation_type=PrerequisiteType.RECOMMENDED,
                strength=0.2,
                rationale="Injected cycle for repair testing.",
                revision=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    content = Topic1GraphContentV1(course=course, knowledge_points=points, prerequisites=edges)
    document = content.model_dump(mode="json")
    return Topic1GraphSnapshotV1(
        snapshot_id=uuid4(),
        course_id=course.course_id,
        graph_version=1,
        content=content,
        content_sha256=canonical_sha256(document),
        node_count=len(points),
        edge_count=len(edges),
        created_by_subject="subject:instructor",
        frozen_at=NOW,
    )


def misconception() -> Topic1MisconceptionV1:
    return Topic1MisconceptionV1(
        misconception_id="MIS_SIGN",
        kp_id="KP_ATC_B",
        title="Sign error",
        description="Incorrect sign handling.",
        trigger_pattern="Reverses the pole sign.",
        diagnosis_tags=["sign-error"],
        remediation_hint="Normalize the factor before reading the time constant.",
        severity=MisconceptionSeverity.HIGH,
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )


def event_record(
    index: int,
    *,
    occurred_at: datetime,
    score: float,
    duration: float,
    misconception_ids: tuple[str, ...] = (),
) -> LearningBehaviorEventRecord:
    payload = {"index": index}
    event = LearningBehaviorEventDraft(
        event_id=uuid4(),
        source_event_id=f"event-{index:016d}",
        event_version=1,
        learner_ref="subject:student",
        course_id="CRS_ATC_001",
        kp_id="KP_ATC_B",
        session_id=uuid4(),
        event_type=BehaviorEventType.ANSWER_SUBMITTED,
        source_type=BehaviorSourceType.TESTER,
        duration_seconds=duration,
        response_latency_ms=10000,
        correctness=score,
        score=score,
        attempt_count=1,
        interaction_count=1,
        attention_ratio=0.9,
        misconception_ids=misconception_ids,
        goal_tags=("ADVANCED",),
        payload=payload,
        payload_sha256=canonical_sha256(payload),
        occurred_at=occurred_at,
        received_at=occurred_at,
    )
    return LearningBehaviorEventRecord(
        draft=event,
        audit_event_id=uuid4(),
        created_at=occurred_at,
    )


def profile_record() -> StudentProfileRecord:
    profile_id = uuid4()
    scores = {
        "knowledge_mastery": 0.65,
        "problem_solving_proficiency": 0.7,
        "misconception_preference": 0.4,
        "learning_pace": 0.6,
        "forgetting_rate": 0.35,
        "learning_goal_tendency": 0.8,
    }
    document = {
        "schema_version": "topic2.student-profile.v1",
        "profile_id": str(profile_id),
        "profile_version": 1,
        "learner_ref": "subject:student",
        "course_id": "CRS_ATC_001",
        "policy_version": "topic2.profile-policy.v1",
        "dimensions": scores,
    }
    dimension_fields = {
        ProfileDimension.KNOWLEDGE_MASTERY: "knowledge_mastery",
        ProfileDimension.PROBLEM_SOLVING_PROFICIENCY: "problem_solving_proficiency",
        ProfileDimension.MISCONCEPTION_PREFERENCE: "misconception_preference",
        ProfileDimension.LEARNING_PACE: "learning_pace",
        ProfileDimension.FORGETTING_RATE: "forgetting_rate",
        ProfileDimension.LEARNING_GOAL_TENDENCY: "learning_goal_tendency",
    }
    features = [
        ProfileFeatureDraft(
            feature_id=uuid4(),
            dimension=dimension,
            feature_key="aggregate",
            value_document={},
            normalized_score=scores[field],
            confidence=0.8,
            evidence_count=5,
            source_event_ids=(),
            computed_at=NOW,
        )
        for dimension, field in dimension_fields.items()
    ]
    features.extend(
        [
            ProfileFeatureDraft(
                feature_id=uuid4(),
                dimension=ProfileDimension.KNOWLEDGE_MASTERY,
                feature_key="kp:KP_ATC_A:mastery",
                value_document={"kp_id": "KP_ATC_A"},
                normalized_score=0.9,
                confidence=0.9,
                evidence_count=4,
                source_event_ids=(),
                computed_at=NOW,
            ),
            ProfileFeatureDraft(
                feature_id=uuid4(),
                dimension=ProfileDimension.KNOWLEDGE_MASTERY,
                feature_key="kp:KP_ATC_B:mastery",
                value_document={"kp_id": "KP_ATC_B"},
                normalized_score=0.45,
                confidence=0.8,
                evidence_count=3,
                source_event_ids=(),
                computed_at=NOW,
            ),
            ProfileFeatureDraft(
                feature_id=uuid4(),
                dimension=ProfileDimension.MISCONCEPTION_PREFERENCE,
                feature_key="misconception:MIS_SIGN",
                value_document={"misconception_id": "MIS_SIGN", "kp_id": "KP_ATC_B"},
                normalized_score=0.8,
                confidence=0.8,
                evidence_count=3,
                source_event_ids=(),
                computed_at=NOW,
            ),
        ]
    )
    draft = StudentProfileDraft(
        profile_id=profile_id,
        learner_ref="subject:student",
        course_id="CRS_ATC_001",
        profile_version=1,
        parent_profile_id=None,
        policy_version="topic2.profile-policy.v1",
        confidence_score=0.8,
        activity_count=5,
        last_event_at=NOW,
        source_window_start=NOW,
        source_window_end=NOW,
        profile_document=document,
        content_sha256=canonical_sha256(document),
        frozen_at=NOW,
        features=tuple(features),
        **scores,
    )
    return StudentProfileRecord(
        draft=draft,
        audit_event_id=uuid4(),
        created_by_subject="subject:student",
        created_at=NOW,
    )


def test_profile_engine_extracts_six_dimensions_and_filters_outlier() -> None:
    events = [
        event_record(
            index,
            occurred_at=NOW - timedelta(days=6 - index),
            score=0.9 - index * 0.03,
            duration=100 + index,
            misconception_ids=("MIS_SIGN",) if index == 2 else (),
        )
        for index in range(1, 6)
    ]
    events.append(
        event_record(
            6,
            occurred_at=NOW,
            score=0.1,
            duration=80000,
        )
    )
    engine = SixDimensionProfileEngine()
    result = engine.build_profile(
        learner_ref="subject:student",
        course_id="CRS_ATC_001",
        events=events,
        knowledge_points={"KP_ATC_B": point("KP_ATC_B", 0.55)},
        misconceptions={"MIS_SIGN": misconception()},
        generated_at=NOW,
    )

    aggregates = {
        feature.dimension: feature
        for feature in result.features
        if feature.feature_key == "aggregate"
    }
    assert set(aggregates) == set(ProfileDimension)
    assert result.profile_document["accepted_event_count"] == 5
    assert result.profile_document["rejected_event_count"] == 1
    assert result.knowledge_mastery > 0.7
    assert result.misconception_preference > 0
    assert result.content_sha256 == canonical_sha256(result.profile_document)


def test_memory_engine_reproduces_exponential_decay_and_review_updates() -> None:
    engine = EbbinghausMemoryEngine()
    kp = point("KP_ATC_B", 0.55)
    initial = engine.initialize_state(
        learner_ref="subject:student",
        knowledge_point=kp,
        forgetting_rate=0.4,
        initialized_at=NOW,
    )
    reviewed = engine.apply_review(
        initial,
        knowledge_point=kp,
        forgetting_rate=0.4,
        review_quality=0.9,
        reviewed_at=NOW + timedelta(days=1),
    )
    refreshed = engine.refresh_state(
        reviewed,
        knowledge_point=kp,
        forgetting_rate=0.4,
        as_of=NOW + timedelta(days=3),
    )

    expected = math.exp(-2 / reviewed.effective_stability_days)
    assert abs(refreshed.retrievability - expected) < 1e-11
    assert reviewed.stability_days > initial.stability_days
    assert reviewed.parent_memory_state_id == initial.memory_state_id
    assert refreshed.risk_level == engine.risk_level(refreshed.retrievability)
    assert refreshed.content_sha256 == canonical_sha256(engine.hash_document(refreshed))
    assert engine.hash_document(refreshed) == Topic2Service.memory_hash_document(refreshed)


def test_path_planner_closes_prerequisites_repairs_manual_order_and_explains_scores() -> None:
    planner = AdaptivePathPlanner()
    snapshot, change = planner.plan(
        graph_snapshot=graph_snapshot(cyclic=True),
        profile=profile_record(),
        memory_states=[],
        generated_at=NOW,
        target_goal="Advanced automatic-control mastery",
        target_kp_ids=["KP_ATC_C"],
        change_type=PathChangeType.TOPOLOGY_REPAIRED,
        trigger_reason="GRAPH_REPAIR_TEST",
        manual_order=["KP_ATC_C", "KP_ATC_B", "KP_ATC_A"],
    )

    nodes = snapshot.path_document["nodes"]
    assert [node["kp_id"] for node in nodes] == ["KP_ATC_A", "KP_ATC_B", "KP_ATC_C"]
    assert all(
        abs(
            sum(node["score_components"][name] * weight for name, weight in planner.policy.weights)
            - node["priority_score"]
        )
        < 1e-10
        for node in nodes
    )
    repair_codes = {item["code"] for item in snapshot.decision_document["repairs"]}
    assert "CYCLE_EDGE_REMOVED" in repair_codes
    assert "MANUAL_ORDER_TOPOLOGY_REPAIRED" in repair_codes
    assert change.change_document["added_kp_ids"] == [
        "KP_ATC_A",
        "KP_ATC_B",
        "KP_ATC_C",
    ]
    assert snapshot.content_sha256 == canonical_sha256(planner.hash_document(snapshot))
    assert planner.hash_document(snapshot) == Topic2Service.path_hash_document(snapshot)


def test_profile_low_activity_decays_confidence_without_nan() -> None:
    previous = profile_record()
    engine = SixDimensionProfileEngine()
    decayed = engine.build_profile(
        learner_ref=previous.draft.learner_ref,
        course_id=previous.draft.course_id,
        events=[],
        knowledge_points={},
        misconceptions={},
        generated_at=NOW + timedelta(days=180),
        previous=previous,
    )
    assert abs(decayed.knowledge_mastery - 0.5) < abs(previous.draft.knowledge_mastery - 0.5)
    assert 0 <= decayed.confidence_score < previous.draft.confidence_score
    assert all(math.isfinite(value) for value in decayed.profile_document["dimensions"].values())


def test_memory_failed_review_records_lapse_and_reduces_stability() -> None:
    engine = EbbinghausMemoryEngine()
    kp = point("KP_ATC_B", 0.55)
    initial = engine.initialize_state(
        learner_ref="subject:student",
        knowledge_point=kp,
        forgetting_rate=0.4,
        initialized_at=NOW,
    )
    successful = engine.apply_review(
        initial,
        knowledge_point=kp,
        forgetting_rate=0.4,
        review_quality=0.9,
        reviewed_at=NOW + timedelta(days=1),
    )
    failed = engine.apply_review(
        successful,
        knowledge_point=kp,
        forgetting_rate=0.4,
        review_quality=0.1,
        reviewed_at=NOW + timedelta(days=2),
    )
    assert failed.lapse_count == successful.lapse_count + 1
    assert failed.review_count == successful.review_count + 1
    assert failed.stability_days < successful.stability_days
    assert failed.parent_memory_state_id == successful.memory_state_id


def test_path_planner_rejects_unknown_target_and_duplicate_manual_nodes() -> None:
    planner = AdaptivePathPlanner()
    graph = graph_snapshot()
    profile = profile_record()
    with pytest.raises(ValueError, match="unknown target"):
        planner.plan(
            graph_snapshot=graph,
            profile=profile,
            memory_states=[],
            generated_at=NOW,
            target_goal="Unknown target",
            target_kp_ids=["KP_ATC_MISSING"],
        )
    with pytest.raises(ValueError, match="duplicate"):
        planner.plan(
            graph_snapshot=graph,
            profile=profile,
            memory_states=[],
            generated_at=NOW,
            target_goal="Duplicate manual order",
            target_kp_ids=["KP_ATC_C"],
            manual_order=["KP_ATC_A", "KP_ATC_A"],
        )


def test_profile_engine_rejects_future_events() -> None:
    future = event_record(
        99,
        occurred_at=NOW + timedelta(seconds=1),
        score=0.8,
        duration=120,
    )
    with pytest.raises(ValueError, match="after profile generation"):
        SixDimensionProfileEngine().build_profile(
            learner_ref="subject:student",
            course_id="CRS_ATC_001",
            events=[future],
            knowledge_points={"KP_ATC_B": point("KP_ATC_B", 0.55)},
            misconceptions={},
            generated_at=NOW,
        )
