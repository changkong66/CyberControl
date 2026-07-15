from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.registry import CONTRACT_REGISTRY
from liyans_contracts.topic2 import (
    Topic2BehaviorEventCommandV1,
    Topic2LearningPathRecordV1,
    Topic2LearningPathSnapshotV1,
    Topic2MemoryStateV1,
    Topic2PathChangeV1,
    Topic2PathNodeV1,
    Topic2ProfileDimension,
    Topic2ProfileFeatureV1,
    Topic2StudentProfileV1,
)
from pydantic import ValidationError

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def test_behavior_command_rejects_payload_tampering() -> None:
    payload = {"question_id": "QUESTION_ATC_001", "answer": "3/(s+2)"}
    command = Topic2BehaviorEventCommandV1(
        event_id=uuid4(),
        source_event_id="tester-event-0000000001",
        learner_ref="subject:student",
        course_id="CRS_ATC_001",
        kp_id="KP_ATC_301_TRANSFER_FUNCTION",
        event_type="ANSWER_SUBMITTED",
        source_type="TESTER",
        correctness=1,
        score=0.9,
        payload=payload,
        payload_sha256=canonical_sha256(payload),
        occurred_at=NOW,
    )
    assert command.schema_version == "topic2.behavior-event-command.v1"
    with pytest.raises(ValidationError, match="payload_sha256"):
        command.model_copy(update={"payload": {"answer": "tampered"}}).model_validate(
            {
                **command.model_dump(mode="json"),
                "payload": {"answer": "tampered"},
            }
        )
    oversized = {"blob": "x" * (64 * 1024)}
    with pytest.raises(ValidationError, match="cannot exceed"):
        Topic2BehaviorEventCommandV1(
            **{
                **command.model_dump(mode="python"),
                "payload": oversized,
                "payload_sha256": canonical_sha256(oversized),
            }
        )


def test_student_profile_contract_binds_six_dimensions_and_digest() -> None:
    profile_id = uuid4()
    dimensions = {
        "knowledge_mastery": 0.7,
        "problem_solving_proficiency": 0.65,
        "misconception_preference": 0.2,
        "learning_pace": 0.55,
        "forgetting_rate": 0.4,
        "learning_goal_tendency": 0.8,
    }
    profile_document = {
        "schema_version": "topic2.student-profile.v1",
        "profile_id": str(profile_id),
        "profile_version": 1,
        "learner_ref": "subject:student",
        "course_id": "CRS_ATC_001",
        "policy_version": "topic2.profile-policy.v1",
        "dimensions": dimensions,
    }
    field_by_dimension = {
        Topic2ProfileDimension.KNOWLEDGE_MASTERY: "knowledge_mastery",
        Topic2ProfileDimension.PROBLEM_SOLVING_PROFICIENCY: ("problem_solving_proficiency"),
        Topic2ProfileDimension.MISCONCEPTION_PREFERENCE: "misconception_preference",
        Topic2ProfileDimension.LEARNING_PACE: "learning_pace",
        Topic2ProfileDimension.FORGETTING_RATE: "forgetting_rate",
        Topic2ProfileDimension.LEARNING_GOAL_TENDENCY: "learning_goal_tendency",
    }
    features = [
        Topic2ProfileFeatureV1(
            feature_id=uuid4(),
            dimension=dimension,
            feature_key="aggregate",
            value_document={},
            normalized_score=dimensions[field],
            confidence=0.8,
            evidence_count=5,
            computed_at=NOW,
        )
        for dimension, field in field_by_dimension.items()
    ]
    profile = Topic2StudentProfileV1(
        profile_id=profile_id,
        learner_ref="subject:student",
        course_id="CRS_ATC_001",
        profile_version=1,
        policy_version="topic2.profile-policy.v1",
        confidence_score=0.8,
        activity_count=5,
        profile_document=profile_document,
        content_sha256=canonical_sha256(profile_document),
        frozen_at=NOW,
        features=features,
        audit_event_id=uuid4(),
        created_by_subject="subject:student",
        created_at=NOW,
        **dimensions,
    )
    assert len(profile.features) == 6
    with pytest.raises(ValidationError, match="content_sha256"):
        Topic2StudentProfileV1.model_validate(
            {**profile.model_dump(mode="json"), "content_sha256": "0" * 64}
        )


def memory_document() -> dict:
    state_id = uuid4()
    document = {
        "schema_version": "topic2.memory-state.v1",
        "memory_state_id": str(state_id),
        "learner_ref": "subject:student",
        "course_id": "CRS_ATC_001",
        "kp_id": "KP_ATC_301_TRANSFER_FUNCTION",
        "state_version": 1,
        "parent_memory_state_id": None,
        "model_version": "topic2.memory.exponential.v1",
        "stability_days": 3.0,
        "effective_stability_days": 2.0,
        "elapsed_days": 1.0,
        "retrievability": 0.606530659713,
        "forgetting_rate": 0.4,
        "difficulty_factor": 1.2,
        "review_gain": 1.5,
        "review_count": 1,
        "lapse_count": 0,
        "last_reviewed_at": NOW.isoformat(),
        "last_activity_at": NOW.isoformat(),
        "next_review_at": (NOW + timedelta(days=1)).isoformat(),
        "risk_level": "HIGH",
        "model_parameters": {"policy_version": "topic2.memory-policy.v1"},
        "computed_at": (NOW + timedelta(days=1)).isoformat(),
    }
    return {
        **document,
        "content_sha256": canonical_sha256(document),
        "audit_event_id": str(uuid4()),
        "created_at": (NOW + timedelta(days=1)).isoformat(),
    }


def test_memory_and_path_contracts_validate_hashes_and_parent_binding() -> None:
    memory = Topic2MemoryStateV1.model_validate(memory_document())
    assert memory.state_version == 1

    path_id = uuid4()
    path_document = {
        "schema_version": "topic2.learning-path.v1",
        "nodes": [
            {
                "order": 0,
                "kp_id": "KP_ATC_301_TRANSFER_FUNCTION",
                "title": "Transfer Function",
                "tier": "FOUNDATION",
                "priority_score": 0.8,
                "score_components": {
                    "mastery_deficit": 0.7,
                    "memory_risk": 1.0,
                    "misconception_severity": 0.2,
                    "goal_alignment": 1.0,
                    "topology_weight": 0.5,
                    "difficulty_pace_fit": 0.8,
                    "prerequisite_readiness": 1.0,
                    "total": 0.8,
                },
                "prerequisite_kp_ids": [],
                "estimated_minutes": 120,
                "rationale_codes": ["TIER_FOUNDATION"],
            }
        ],
        "tiers": {"FOUNDATION": ["KP_ATC_301_TRANSFER_FUNCTION"]},
    }
    Topic2PathNodeV1.model_validate(path_document["nodes"][0])
    snapshot_document = {
        "schema_version": "topic2.learning-path-snapshot.v1",
        "path_snapshot_id": str(path_id),
        "learner_ref": "subject:student",
        "course_id": "CRS_ATC_001",
        "path_version": 1,
        "parent_path_snapshot_id": None,
        "topic1_graph_snapshot_id": str(uuid4()),
        "topic1_graph_version": 1,
        "profile_id": str(uuid4()),
        "plan_type": "INITIAL",
        "trigger_reason": "INITIAL_PROFILE_READY",
        "target_goal": "Master transfer functions",
        "policy_version": "topic2.path-policy.v1",
        "path_document": path_document,
        "decision_document": {"policy_version": "topic2.path-policy.v1"},
        "node_count": 1,
        "estimated_minutes": 120,
        "manual_override": False,
        "frozen_at": NOW.isoformat(),
    }
    snapshot = Topic2LearningPathSnapshotV1.model_validate(
        {**snapshot_document, "content_sha256": canonical_sha256(snapshot_document)}
    )
    change = Topic2PathChangeV1(
        change_id=uuid4(),
        learner_ref="subject:student",
        course_id="CRS_ATC_001",
        to_path_snapshot_id=path_id,
        change_type="INITIALIZED",
        reason="Initial path.",
        policy_version="topic2.path-policy.v1",
        change_document={"added_kp_ids": ["KP_ATC_301_TRANSFER_FUNCTION"]},
        occurred_at=NOW,
    )
    record = Topic2LearningPathRecordV1(
        snapshot=snapshot,
        change=change,
        audit_event_id=uuid4(),
        created_by_subject="subject:student",
        created_at=NOW,
    )
    assert record.snapshot.path_snapshot_id == record.change.to_path_snapshot_id


def test_topic2_registry_is_complete_and_frozen() -> None:
    names = {
        registration.schema_name
        for registration in CONTRACT_REGISTRY
        if registration.owner == "topic2"
    }
    assert names == {
        "topic2.operation-command.v1",
        "topic2.behavior-event-command.v1",
        "topic2.learning-behavior-event.v1",
        "topic2.profile-feature.v1",
        "topic2.student-profile.v1",
        "topic2.memory-state.v1",
        "topic2.path-node.v1",
        "topic2.learning-path-snapshot.v1",
        "topic2.path-change.v1",
        "topic2.learning-path-record.v1",
        "topic2.path-generate-command.v1",
        "topic2.agent-context.v1",
    }
