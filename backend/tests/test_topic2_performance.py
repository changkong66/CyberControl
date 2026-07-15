from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import (
    CourseStatus,
    KnowledgePointStatus,
    PrerequisiteType,
    Topic1CourseV1,
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1KnowledgePointV1,
    Topic1PrerequisiteV1,
)

from liyans.domains.topic2.entities import (
    BehaviorEventType,
    BehaviorSourceType,
    LearningBehaviorEventDraft,
    LearningBehaviorEventRecord,
    ProfileDimension,
    ProfileFeatureDraft,
    StudentProfileDraft,
    StudentProfileRecord,
)
from liyans.domains.topic2.path_planning import AdaptivePathPlanner
from liyans.domains.topic2.profiling import SixDimensionProfileEngine

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def performance_point(index: int) -> Topic1KnowledgePointV1:
    return Topic1KnowledgePointV1(
        kp_id=f"KP_ATC_PERF_{index:04d}",
        course_id="CRS_ATC_001",
        revision=1,
        title=f"Control Topic {index}",
        summary="Performance-test automatic-control knowledge point.",
        learning_objectives=["Apply the control-theory concept."],
        category="CONTROL_THEORY",
        difficulty_level=1 + index % 5,
        difficulty_score=(index % 100) / 100,
        topology_level=index,
        topology_weight=0.5,
        estimated_minutes=60,
        status=KnowledgePointStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def performance_profile() -> StudentProfileRecord:
    profile_id = uuid4()
    dimensions = {
        "knowledge_mastery": 0.5,
        "problem_solving_proficiency": 0.6,
        "misconception_preference": 0.2,
        "learning_pace": 0.55,
        "forgetting_rate": 0.4,
        "learning_goal_tendency": 0.75,
    }
    document = {
        "schema_version": "topic2.student-profile.v1",
        "profile_id": str(profile_id),
        "profile_version": 1,
        "learner_ref": "subject:performance",
        "course_id": "CRS_ATC_001",
        "policy_version": "topic2.profile-policy.v1",
        "dimensions": dimensions,
    }
    fields = {
        ProfileDimension.KNOWLEDGE_MASTERY: "knowledge_mastery",
        ProfileDimension.PROBLEM_SOLVING_PROFICIENCY: "problem_solving_proficiency",
        ProfileDimension.MISCONCEPTION_PREFERENCE: "misconception_preference",
        ProfileDimension.LEARNING_PACE: "learning_pace",
        ProfileDimension.FORGETTING_RATE: "forgetting_rate",
        ProfileDimension.LEARNING_GOAL_TENDENCY: "learning_goal_tendency",
    }
    draft = StudentProfileDraft(
        profile_id=profile_id,
        learner_ref="subject:performance",
        course_id="CRS_ATC_001",
        profile_version=1,
        parent_profile_id=None,
        policy_version="topic2.profile-policy.v1",
        confidence_score=0.8,
        activity_count=100,
        last_event_at=NOW,
        source_window_start=NOW,
        source_window_end=NOW,
        profile_document=document,
        content_sha256=canonical_sha256(document),
        frozen_at=NOW,
        features=tuple(
            ProfileFeatureDraft(
                feature_id=uuid4(),
                dimension=dimension,
                feature_key="aggregate",
                value_document={},
                normalized_score=dimensions[field],
                confidence=0.8,
                evidence_count=100,
                source_event_ids=(),
                computed_at=NOW,
            )
            for dimension, field in fields.items()
        ),
        **dimensions,
    )
    return StudentProfileRecord(
        draft=draft,
        audit_event_id=uuid4(),
        created_by_subject="subject:performance",
        created_at=NOW,
    )


def test_topic2_profile_engine_processes_maximum_event_window_within_baseline() -> None:
    points = {point.kp_id: point for point in (performance_point(index) for index in range(10))}
    events: list[LearningBehaviorEventRecord] = []
    for index in range(5000):
        payload = {"index": index}
        occurred_at = NOW - timedelta(minutes=5000 - index)
        event = LearningBehaviorEventDraft(
            event_id=uuid4(),
            source_event_id=f"performance-event-{index:08d}",
            event_version=1,
            learner_ref="subject:performance",
            course_id="CRS_ATC_001",
            kp_id=f"KP_ATC_PERF_{index % 10:04d}",
            session_id=None,
            event_type=BehaviorEventType.ANSWER_SUBMITTED,
            source_type=BehaviorSourceType.TESTER,
            duration_seconds=120 + index % 30,
            response_latency_ms=5000 + index % 1000,
            correctness=0.5 + (index % 50) / 100,
            score=0.5 + (index % 50) / 100,
            attempt_count=1 + index % 3,
            interaction_count=1,
            attention_ratio=0.9,
            misconception_ids=(),
            goal_tags=("ADVANCED",),
            payload=payload,
            payload_sha256=canonical_sha256(payload),
            occurred_at=occurred_at,
            received_at=occurred_at,
        )
        events.append(
            LearningBehaviorEventRecord(
                draft=event,
                audit_event_id=uuid4(),
                created_at=occurred_at,
            )
        )

    started = perf_counter()
    profile = SixDimensionProfileEngine().build_profile(
        learner_ref="subject:performance",
        course_id="CRS_ATC_001",
        events=events,
        knowledge_points=points,
        misconceptions={},
        generated_at=NOW,
    )
    elapsed = perf_counter() - started

    assert profile.activity_count == 5000
    assert profile.profile_document["accepted_event_count"] == 5000
    assert elapsed < 5.0


def test_topic2_planner_orders_500_node_graph_within_baseline() -> None:
    points = [performance_point(index) for index in range(500)]
    edges = [
        Topic1PrerequisiteV1(
            edge_id=f"EDGE_ATC_PERF_{index:04d}",
            course_id="CRS_ATC_001",
            prerequisite_kp_id=points[index].kp_id,
            dependent_kp_id=points[index + 1].kp_id,
            relation_type=PrerequisiteType.REQUIRED,
            strength=1,
            rationale="Sequential performance-test prerequisite.",
            revision=1,
            created_at=NOW,
            updated_at=NOW,
        )
        for index in range(499)
    ]
    course = Topic1CourseV1(
        course_id="CRS_ATC_001",
        revision=1,
        course_code="ATC",
        title="Automatic Control Theory",
        description="Performance-test control course.",
        credit_hours=64,
        status=CourseStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    content = Topic1GraphContentV1(
        course=course,
        knowledge_points=points,
        prerequisites=edges,
    )
    snapshot = Topic1GraphSnapshotV1(
        snapshot_id=uuid4(),
        course_id=course.course_id,
        graph_version=1,
        content=content,
        content_sha256=canonical_sha256(content.model_dump(mode="json")),
        node_count=500,
        edge_count=499,
        created_by_subject="subject:performance",
        frozen_at=NOW,
    )

    started = perf_counter()
    path, _change = AdaptivePathPlanner().plan(
        graph_snapshot=snapshot,
        profile=performance_profile(),
        memory_states=[],
        generated_at=NOW,
        target_goal="Master the complete automatic-control sequence",
        target_kp_ids=[points[-1].kp_id],
    )
    elapsed = perf_counter() - started

    assert path.node_count == 500
    assert path.path_document["nodes"][0]["kp_id"] == points[0].kp_id
    assert path.path_document["nodes"][-1]["kp_id"] == points[-1].kp_id
    assert elapsed < 5.0
