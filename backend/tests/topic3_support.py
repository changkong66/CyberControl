from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType
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
from liyans_contracts.topic2 import Topic2AgentContextV1
from liyans_contracts.topic3 import LecturerDepth, Topic3GenerationCommandV1

from liyans.domains.topic2.entities import (
    LearningPathRecord,
    MemoryStateRecord,
    StudentProfileRecord,
)
from liyans.domains.topic2.path_planning import AdaptivePathPlanner
from liyans.domains.topic2.seed import blank_profile_seed_to_drafts, build_blank_profile_seed
from liyans.domains.topic2.service import Topic2Service

NOW = datetime(2026, 7, 16, 8, tzinfo=UTC)
COURSE_ID = "CRS_ATC_001"
LEARNER_REF = "subject:student"


def graph_snapshot() -> Topic1GraphSnapshotV1:
    course = Topic1CourseV1(
        course_id=COURSE_ID,
        revision=1,
        course_code="ATC",
        title="Automatic Control Theory",
        description="Classical automatic-control foundations.",
        credit_hours=64,
        status=CourseStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    points = [
        _point("KP_ATC_A", "Laplace transform", 0, 0.25),
        _point("KP_ATC_B", "Transfer function", 1, 0.5),
        _point("KP_ATC_C", "Closed-loop stability", 2, 0.8),
    ]
    prerequisites = [
        _edge("EDGE_A_B", "KP_ATC_A", "KP_ATC_B"),
        _edge("EDGE_B_C", "KP_ATC_B", "KP_ATC_C"),
    ]
    misconception = Topic1MisconceptionV1(
        misconception_id="MIS_ATC_SIGN",
        kp_id="KP_ATC_B",
        title="Characteristic-equation sign error",
        description="The learner reverses the feedback sign.",
        trigger_pattern="Uses positive feedback in a negative-feedback derivation.",
        diagnosis_tags=["feedback-sign"],
        remediation_hint="Write the loop equation before simplifying the denominator.",
        severity=MisconceptionSeverity.HIGH,
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )
    content = Topic1GraphContentV1(
        course=course,
        knowledge_points=points,
        prerequisites=prerequisites,
        misconceptions=[misconception],
    )
    return Topic1GraphSnapshotV1(
        snapshot_id=UUID("d35a6343-890d-4a52-ad49-e8f08f244f4f"),
        course_id=COURSE_ID,
        graph_version=3,
        content=content,
        content_sha256=canonical_sha256(content.model_dump(mode="json")),
        node_count=len(points),
        edge_count=len(prerequisites),
        created_by_subject="subject:instructor",
        frozen_at=NOW,
    )


def personalization_context(
    graph: Topic1GraphSnapshotV1 | None = None,
) -> Topic2AgentContextV1:
    graph = graph or graph_snapshot()
    operation_id = UUID("e793fc49-4a36-4a14-8369-c5cbbd2f8f4e")
    seed = build_blank_profile_seed(
        learner_ref=LEARNER_REF,
        course_id=COURSE_ID,
        knowledge_points=graph.content.knowledge_points,
        generated_at=NOW,
        operation_id=operation_id,
        topic1_graph_snapshot_id=graph.snapshot_id,
        topic1_graph_version=graph.graph_version,
        topic1_graph_sha256=graph.content_sha256,
    )
    profile_draft, memory_drafts = blank_profile_seed_to_drafts(seed)
    profile = StudentProfileRecord(
        draft=profile_draft,
        audit_event_id=uuid4(),
        created_by_subject=LEARNER_REF,
        created_at=NOW,
    )
    memory = [
        MemoryStateRecord(draft=draft, audit_event_id=uuid4(), created_at=NOW)
        for draft in memory_drafts
    ]
    path_draft, path_change = AdaptivePathPlanner().plan(
        graph_snapshot=graph,
        profile=profile,
        memory_states=memory,
        generated_at=NOW,
        target_goal="Master closed-loop stability",
        target_kp_ids=["KP_ATC_C"],
    )
    path = LearningPathRecord(
        draft=path_draft,
        change=path_change,
        audit_event_id=uuid4(),
        created_by_subject=LEARNER_REF,
        created_at=NOW,
    )
    digest_document = {
        "profile_id": str(profile.draft.profile_id),
        "profile_version": profile.draft.profile_version,
        "memory_states": [
            {
                "kp_id": record.draft.kp_id,
                "memory_state_id": str(record.draft.memory_state_id),
                "state_version": record.draft.state_version,
            }
            for record in sorted(memory, key=lambda value: value.draft.kp_id)
        ],
        "path_snapshot_id": str(path.draft.path_snapshot_id),
        "path_version": path.draft.path_version,
    }
    return Topic2AgentContextV1(
        schema_version="topic2.agent-context.v1",
        learner_ref=LEARNER_REF,
        course_id=COURSE_ID,
        profile=Topic2Service.profile_record_document(profile),
        memory_states=[Topic2Service.memory_record_document(record) for record in memory],
        learning_path=Topic2Service.path_record_document(path),
        personalization_policy_digest=canonical_sha256(digest_document),
    )


def generation_command(
    *,
    resources: list[ResourceType] | None = None,
    target_kp_ids: list[str] | None = None,
) -> Topic3GenerationCommandV1:
    return Topic3GenerationCommandV1(
        schema_version="topic3.generation-command.v1",
        operation_id=UUID("f478f506-82fc-4a56-b8db-dce4391ef786"),
        generation_session_id=UUID("638da15e-7ad5-4a41-a011-2b50e0fc1782"),
        learner_ref=LEARNER_REF,
        course_id=COURSE_ID,
        target_kp_ids=target_kp_ids or ["KP_ATC_C"],
        requested_resources=resources
        or [
            ResourceType.LECTURER_DOC,
            ResourceType.MIND_MAP,
            ResourceType.GRADIENT_QUIZ,
            ResourceType.SIMULATION_CODE,
            ResourceType.EXTENSION_MATERIAL,
        ],
        lecturer_depth=LecturerDepth.ENGINEERING,
        learning_goal="Master closed-loop stability with engineering simulation.",
        locale="zh-CN",
        max_parallelism=3,
        allow_partial=True,
        requested_at=NOW,
    )


def _point(kp_id: str, title: str, level: int, difficulty: float) -> Topic1KnowledgePointV1:
    return Topic1KnowledgePointV1(
        kp_id=kp_id,
        course_id=COURSE_ID,
        revision=1,
        title=title,
        summary=f"Authoritative summary for {title}.",
        learning_objectives=[f"Explain {title}."],
        category="CONTROL_THEORY",
        difficulty_level=max(1, round(difficulty * 5)),
        difficulty_score=difficulty,
        topology_level=level,
        topology_weight=round((level + 1) / 3, 6),
        estimated_minutes=60,
        formula_signatures=[],
        tags=["automatic-control"],
        status=KnowledgePointStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def _edge(edge_id: str, source: str, target: str) -> Topic1PrerequisiteV1:
    return Topic1PrerequisiteV1(
        edge_id=edge_id,
        course_id=COURSE_ID,
        prerequisite_kp_id=source,
        dependent_kp_id=target,
        relation_type=PrerequisiteType.REQUIRED,
        strength=1.0,
        rationale=f"{source} is required before {target}.",
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )
