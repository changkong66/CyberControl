from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1KnowledgePointV1

from .entities import (
    MemoryRiskLevel,
    MemoryStateDraft,
    ProfileDimension,
    ProfileFeatureDraft,
    StudentProfileDraft,
)
from .models import PROFILE_DIMENSIONS

SEED_POLICY_VERSION = "topic2.seed-policy.v1"
MEMORY_MODEL_VERSION = "topic2.memory.exponential.v1"
PROFILE_DIMENSION_SCORE_KEYS = {
    "KNOWLEDGE_MASTERY": "knowledge_mastery",
    "PROBLEM_SOLVING_PROFICIENCY": "problem_solving_proficiency",
    "MISCONCEPTION_PREFERENCE": "misconception_preference",
    "LEARNING_PACE": "learning_pace",
    "FORGETTING_RATE": "forgetting_rate",
    "LEARNING_GOAL_TENDENCY": "learning_goal_tendency",
}


@dataclass(frozen=True, slots=True)
class BlankProfileSeed:
    profile_id: UUID
    profile_document: dict[str, Any]
    profile_content_sha256: str
    features: tuple[dict[str, Any], ...]
    memory_states: tuple[dict[str, Any], ...]


def build_blank_profile_seed(
    *,
    learner_ref: str,
    course_id: str,
    knowledge_points: Sequence[Topic1KnowledgePointV1],
    generated_at: datetime,
    operation_id: UUID | None = None,
    topic1_graph_snapshot_id: UUID | None = None,
    topic1_graph_version: int | None = None,
    topic1_graph_sha256: str | None = None,
) -> BlankProfileSeed:
    """Build the auditable zero-evidence state consumed by the Topic 2 service."""
    graph_binding = (
        topic1_graph_snapshot_id,
        topic1_graph_version,
        topic1_graph_sha256,
    )
    if any(value is not None for value in graph_binding) and not all(
        value is not None for value in graph_binding
    ):
        raise ValueError("Topic 1 graph binding must be provided as a complete tuple")
    profile_id = uuid4() if operation_id is None else uuid5(operation_id, "seed-profile")
    dimensions = {
        "knowledge_mastery": 0.0,
        "problem_solving_proficiency": 0.0,
        "misconception_preference": 0.0,
        "learning_pace": 0.5,
        "forgetting_rate": 0.5,
        "learning_goal_tendency": 0.5,
    }
    profile_document: dict[str, Any] = {
        "schema_version": "topic2.student-profile.v1",
        "profile_id": str(profile_id),
        "profile_version": 1,
        "learner_ref": learner_ref,
        "course_id": course_id,
        "policy_version": SEED_POLICY_VERSION,
        "dimensions": dimensions,
        "confidence_score": 0.0,
        "activity_count": 0,
        "source_window": None,
        "generated_at": generated_at.isoformat(),
    }
    if operation_id is not None:
        profile_document["operation_id"] = str(operation_id)
    if topic1_graph_snapshot_id is not None:
        profile_document.update(
            {
                "topic1_graph_snapshot_id": str(topic1_graph_snapshot_id),
                "topic1_graph_version": topic1_graph_version,
                "topic1_graph_sha256": topic1_graph_sha256,
            }
        )
    features = tuple(
        {
            "feature_id": str(
                uuid4()
                if operation_id is None
                else uuid5(operation_id, f"seed-feature:{dimension}")
            ),
            "profile_id": str(profile_id),
            "dimension": dimension,
            "feature_key": "aggregate",
            "value_document": {
                "state": "UNOBSERVED",
                "seed_policy_version": SEED_POLICY_VERSION,
            },
            "normalized_score": dimensions[PROFILE_DIMENSION_SCORE_KEYS[dimension]],
            "confidence": 0.0,
            "evidence_count": 0,
            "source_event_ids": [],
            "computed_at": generated_at.isoformat(),
        }
        for dimension in PROFILE_DIMENSIONS
    )
    memory_states = tuple(
        _blank_memory_state(
            learner_ref=learner_ref,
            course_id=course_id,
            knowledge_point=knowledge_point,
            generated_at=generated_at,
            memory_state_id=(
                uuid4()
                if operation_id is None
                else uuid5(operation_id, f"seed-memory:{knowledge_point.kp_id}")
            ),
            operation_id=operation_id,
        )
        for knowledge_point in sorted(knowledge_points, key=lambda item: item.kp_id)
        if knowledge_point.course_id == course_id and knowledge_point.status.value == "ACTIVE"
    )
    return BlankProfileSeed(
        profile_id=profile_id,
        profile_document=profile_document,
        profile_content_sha256=canonical_sha256(profile_document),
        features=features,
        memory_states=memory_states,
    )


def blank_profile_seed_to_drafts(
    seed: BlankProfileSeed,
) -> tuple[StudentProfileDraft, tuple[MemoryStateDraft, ...]]:
    """Convert a validated seed document into append-only Topic 2 domain drafts."""
    document = seed.profile_document
    generated_at = datetime.fromisoformat(str(document["generated_at"]))
    dimensions = document["dimensions"]
    features = tuple(
        ProfileFeatureDraft(
            feature_id=UUID(str(item["feature_id"])),
            dimension=ProfileDimension(str(item["dimension"])),
            feature_key=str(item["feature_key"]),
            value_document=dict(item["value_document"]),
            normalized_score=float(item["normalized_score"]),
            confidence=float(item["confidence"]),
            evidence_count=int(item["evidence_count"]),
            source_event_ids=tuple(str(value) for value in item["source_event_ids"]),
            computed_at=datetime.fromisoformat(str(item["computed_at"])),
        )
        for item in seed.features
    )
    profile = StudentProfileDraft(
        profile_id=seed.profile_id,
        learner_ref=str(document["learner_ref"]),
        course_id=str(document["course_id"]),
        profile_version=int(document["profile_version"]),
        parent_profile_id=None,
        policy_version=str(document["policy_version"]),
        knowledge_mastery=float(dimensions["knowledge_mastery"]),
        problem_solving_proficiency=float(dimensions["problem_solving_proficiency"]),
        misconception_preference=float(dimensions["misconception_preference"]),
        learning_pace=float(dimensions["learning_pace"]),
        forgetting_rate=float(dimensions["forgetting_rate"]),
        learning_goal_tendency=float(dimensions["learning_goal_tendency"]),
        confidence_score=float(document["confidence_score"]),
        activity_count=int(document["activity_count"]),
        last_event_at=None,
        source_window_start=None,
        source_window_end=None,
        profile_document=dict(document),
        content_sha256=seed.profile_content_sha256,
        frozen_at=generated_at,
        features=features,
    )
    memory_states = tuple(
        MemoryStateDraft(
            memory_state_id=UUID(str(item["memory_state_id"])),
            learner_ref=str(item["learner_ref"]),
            course_id=str(item["course_id"]),
            kp_id=str(item["kp_id"]),
            state_version=int(item["state_version"]),
            parent_memory_state_id=(
                None
                if item["parent_memory_state_id"] is None
                else UUID(str(item["parent_memory_state_id"]))
            ),
            model_version=str(item["model_version"]),
            stability_days=float(item["stability_days"]),
            effective_stability_days=float(item["effective_stability_days"]),
            elapsed_days=float(item["elapsed_days"]),
            retrievability=float(item["retrievability"]),
            forgetting_rate=float(item["forgetting_rate"]),
            difficulty_factor=float(item["difficulty_factor"]),
            review_gain=float(item["review_gain"]),
            review_count=int(item["review_count"]),
            lapse_count=int(item["lapse_count"]),
            last_reviewed_at=(
                None
                if item["last_reviewed_at"] is None
                else datetime.fromisoformat(str(item["last_reviewed_at"]))
            ),
            last_activity_at=datetime.fromisoformat(str(item["last_activity_at"])),
            next_review_at=datetime.fromisoformat(str(item["next_review_at"])),
            risk_level=MemoryRiskLevel(str(item["risk_level"])),
            model_parameters=dict(item["model_parameters"]),
            content_sha256=str(item["content_sha256"]),
            computed_at=datetime.fromisoformat(str(item["computed_at"])),
        )
        for item in seed.memory_states
    )
    return profile, memory_states


def _blank_memory_state(
    *,
    learner_ref: str,
    course_id: str,
    knowledge_point: Topic1KnowledgePointV1,
    generated_at: datetime,
    memory_state_id: UUID,
    operation_id: UUID | None,
) -> dict[str, Any]:
    difficulty_factor = 0.75 + 1.5 * knowledge_point.difficulty_score
    forgetting_multiplier = 0.5 + 1.5 * 0.5
    document: dict[str, Any] = {
        "schema_version": "topic2.memory-state.v1",
        "memory_state_id": str(memory_state_id),
        "learner_ref": learner_ref,
        "course_id": course_id,
        "kp_id": knowledge_point.kp_id,
        "state_version": 1,
        "parent_memory_state_id": None,
        "model_version": MEMORY_MODEL_VERSION,
        "stability_days": 1.0,
        "effective_stability_days": round(
            1.0 / (difficulty_factor * forgetting_multiplier),
            12,
        ),
        "elapsed_days": 0.0,
        "retrievability": 0.0,
        "forgetting_rate": 0.5,
        "difficulty_factor": round(difficulty_factor, 12),
        "review_gain": 0.0,
        "review_count": 0,
        "lapse_count": 0,
        "last_reviewed_at": None,
        "last_activity_at": generated_at.isoformat(),
        "next_review_at": generated_at.isoformat(),
        "risk_level": "CRITICAL",
        "model_parameters": {
            "initial_state": "UNOBSERVED",
            "difficulty_score": knowledge_point.difficulty_score,
            "seed_policy_version": SEED_POLICY_VERSION,
        },
        "computed_at": generated_at.isoformat(),
    }
    if operation_id is not None:
        document["model_parameters"]["operation_id"] = str(operation_id)
    document["content_sha256"] = canonical_sha256(document)
    return document
