from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import KnowledgePointStatus, Topic1KnowledgePointV1

from liyans.domains.topic2.models import PROFILE_DIMENSIONS
from liyans.domains.topic2.seed import (
    blank_profile_seed_to_drafts,
    build_blank_profile_seed,
)
from liyans.domains.topic2.service import Topic2Service


def knowledge_point(kp_id: str, *, status: KnowledgePointStatus) -> Topic1KnowledgePointV1:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    return Topic1KnowledgePointV1(
        kp_id=kp_id,
        course_id="CRS_ATC_001",
        revision=1,
        title=kp_id,
        summary="Authoritative control-theory knowledge point.",
        learning_objectives=["Explain the knowledge point."],
        category="CONTROL_THEORY",
        difficulty_level=3,
        difficulty_score=0.6,
        topology_level=1,
        topology_weight=0.5,
        estimated_minutes=90,
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_blank_profile_seed_is_complete_deterministic_policy_state() -> None:
    generated_at = datetime(2026, 7, 15, 12, tzinfo=UTC)
    seed = build_blank_profile_seed(
        learner_ref="subject:student-001",
        course_id="CRS_ATC_001",
        knowledge_points=[
            knowledge_point("KP_ATC_301_TRANSFER_FUNCTION", status=KnowledgePointStatus.ACTIVE),
            knowledge_point("KP_ATC_999_RETIRED", status=KnowledgePointStatus.DEPRECATED),
        ],
        generated_at=generated_at,
    )

    assert seed.profile_document["dimensions"] == {
        "knowledge_mastery": 0.0,
        "problem_solving_proficiency": 0.0,
        "misconception_preference": 0.0,
        "learning_pace": 0.5,
        "forgetting_rate": 0.5,
        "learning_goal_tendency": 0.5,
    }
    assert seed.profile_content_sha256 == canonical_sha256(seed.profile_document)
    assert {feature["dimension"] for feature in seed.features} == set(PROFILE_DIMENSIONS)
    assert all(feature["feature_key"] == "aggregate" for feature in seed.features)
    assert {feature["dimension"]: feature["normalized_score"] for feature in seed.features} == {
        "KNOWLEDGE_MASTERY": 0.0,
        "PROBLEM_SOLVING_PROFICIENCY": 0.0,
        "MISCONCEPTION_PREFERENCE": 0.0,
        "LEARNING_PACE": 0.5,
        "FORGETTING_RATE": 0.5,
        "LEARNING_GOAL_TENDENCY": 0.5,
    }
    assert len(seed.memory_states) == 1
    memory = seed.memory_states[0]
    assert memory["kp_id"] == "KP_ATC_301_TRANSFER_FUNCTION"
    assert memory["retrievability"] == 0.0
    assert memory["risk_level"] == "CRITICAL"
    content_sha256 = memory.pop("content_sha256")
    assert content_sha256 == canonical_sha256(memory)


def test_blank_profile_seed_produces_replay_stable_domain_drafts() -> None:
    generated_at = datetime(2026, 7, 15, 12, tzinfo=UTC)
    operation_id = UUID("5a425a4c-cd64-4bf8-a2d5-1bc6b80819d4")
    graph_snapshot_id = UUID("c066af92-a132-4f87-86be-58faee58c72e")
    kwargs = {
        "learner_ref": "subject:student-001",
        "course_id": "CRS_ATC_001",
        "knowledge_points": [
            knowledge_point("KP_ATC_301_TRANSFER_FUNCTION", status=KnowledgePointStatus.ACTIVE)
        ],
        "generated_at": generated_at,
        "operation_id": operation_id,
        "topic1_graph_snapshot_id": graph_snapshot_id,
        "topic1_graph_version": 3,
        "topic1_graph_sha256": "a" * 64,
    }
    first = build_blank_profile_seed(**kwargs)
    second = build_blank_profile_seed(**kwargs)
    assert first == second

    profile, memory_states = blank_profile_seed_to_drafts(first)
    assert profile.profile_id == first.profile_id
    assert profile.profile_document["operation_id"] == str(operation_id)
    assert len(memory_states) == 1
    assert memory_states[0].model_parameters["operation_id"] == str(operation_id)
    assert memory_states[0].content_sha256 == canonical_sha256(
        Topic2Service.memory_hash_document(memory_states[0])
    )
