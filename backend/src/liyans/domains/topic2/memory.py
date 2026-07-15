from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1KnowledgePointV1

from .entities import (
    LearningBehaviorEventRecord,
    MemoryRiskLevel,
    MemoryStateDraft,
    MemoryStateRecord,
)

MEMORY_POLICY_VERSION = "topic2.memory-policy.v1"
MEMORY_MODEL_VERSION = "topic2.memory.exponential.v1"


@dataclass(frozen=True, slots=True)
class MemoryPolicy:
    version: str = MEMORY_POLICY_VERSION
    model_version: str = MEMORY_MODEL_VERSION
    target_retrievability: float = 0.8
    success_quality_threshold: float = 0.6
    base_stability_days: float = 1.0
    minimum_stability_days: float = 0.5
    maximum_stability_days: float = 36500.0
    maximum_review_interval_days: float = 365.0
    difficulty_base: float = 0.75
    difficulty_scale: float = 1.5
    forgetting_base: float = 0.5
    forgetting_scale: float = 1.5

    def __post_init__(self) -> None:
        if not 0 < self.target_retrievability < 1:
            raise ValueError("target_retrievability must be between zero and one")
        if not 0 <= self.success_quality_threshold <= 1:
            raise ValueError("success_quality_threshold must be between zero and one")
        if not 0 < self.minimum_stability_days <= self.base_stability_days:
            raise ValueError("minimum stability cannot exceed base stability")
        if self.maximum_stability_days < self.base_stability_days:
            raise ValueError("maximum stability cannot be below base stability")
        if (
            min(
                self.maximum_review_interval_days,
                self.difficulty_base,
                self.difficulty_scale,
                self.forgetting_base,
                self.forgetting_scale,
            )
            <= 0
        ):
            raise ValueError("memory policy coefficients must be positive")


class EbbinghausMemoryEngine:
    """Deterministic exponential forgetting model with versioned correction terms."""

    def __init__(self, policy: MemoryPolicy | None = None) -> None:
        self.policy = policy or MemoryPolicy()

    def initialize_state(
        self,
        *,
        learner_ref: str,
        knowledge_point: Topic1KnowledgePointV1,
        forgetting_rate: float,
        initialized_at: datetime,
    ) -> MemoryStateDraft:
        self._aware("initialized_at", initialized_at)
        self._score("forgetting_rate", forgetting_rate)
        difficulty_factor = self.difficulty_factor(knowledge_point.difficulty_score)
        effective = self.effective_stability(
            self.policy.base_stability_days,
            difficulty_factor,
            forgetting_rate,
        )
        state = MemoryStateDraft(
            memory_state_id=uuid4(),
            learner_ref=learner_ref,
            course_id=knowledge_point.course_id,
            kp_id=knowledge_point.kp_id,
            state_version=1,
            parent_memory_state_id=None,
            model_version=self.policy.model_version,
            stability_days=self.policy.base_stability_days,
            effective_stability_days=effective,
            elapsed_days=0.0,
            retrievability=0.0,
            forgetting_rate=forgetting_rate,
            difficulty_factor=difficulty_factor,
            review_gain=0.0,
            review_count=0,
            lapse_count=0,
            last_reviewed_at=None,
            last_activity_at=initialized_at,
            next_review_at=initialized_at,
            risk_level=MemoryRiskLevel.CRITICAL,
            model_parameters={
                "policy_version": self.policy.version,
                "initial_state": "UNOBSERVED",
                "difficulty_score": knowledge_point.difficulty_score,
                "target_retrievability": self.policy.target_retrievability,
            },
            content_sha256="0" * 64,
            computed_at=initialized_at,
        )
        return self._with_digest(state)

    def refresh_state(
        self,
        current: MemoryStateRecord | MemoryStateDraft,
        *,
        knowledge_point: Topic1KnowledgePointV1,
        forgetting_rate: float,
        as_of: datetime,
    ) -> MemoryStateDraft:
        state = current.draft if isinstance(current, MemoryStateRecord) else current
        self._validate_identity(state, knowledge_point)
        self._aware("as_of", as_of)
        self._score("forgetting_rate", forgetting_rate)
        anchor = state.last_reviewed_at or state.last_activity_at
        if as_of < anchor:
            raise ValueError("memory refresh cannot precede the latest activity")
        elapsed_days = (as_of - anchor).total_seconds() / 86400
        difficulty_factor = self.difficulty_factor(knowledge_point.difficulty_score)
        effective = self.effective_stability(
            state.stability_days,
            difficulty_factor,
            forgetting_rate,
        )
        retrievability = self.retrievability(elapsed_days, effective)
        due_at = anchor + timedelta(days=self.review_interval(effective))
        refreshed = MemoryStateDraft(
            memory_state_id=uuid4(),
            learner_ref=state.learner_ref,
            course_id=state.course_id,
            kp_id=state.kp_id,
            state_version=state.state_version + 1,
            parent_memory_state_id=state.memory_state_id,
            model_version=self.policy.model_version,
            stability_days=state.stability_days,
            effective_stability_days=effective,
            elapsed_days=round(elapsed_days, 12),
            retrievability=retrievability,
            forgetting_rate=forgetting_rate,
            difficulty_factor=difficulty_factor,
            review_gain=0.0,
            review_count=state.review_count,
            lapse_count=state.lapse_count,
            last_reviewed_at=state.last_reviewed_at,
            last_activity_at=state.last_activity_at,
            next_review_at=max(as_of, due_at),
            risk_level=self.risk_level(retrievability),
            model_parameters={
                "policy_version": self.policy.version,
                "operation": "DECAY_REFRESH",
                "anchor_at": anchor.isoformat(),
                "target_retrievability": self.policy.target_retrievability,
            },
            content_sha256="0" * 64,
            computed_at=as_of,
        )
        return self._with_digest(refreshed)

    def apply_review(
        self,
        current: MemoryStateRecord | MemoryStateDraft,
        *,
        knowledge_point: Topic1KnowledgePointV1,
        forgetting_rate: float,
        review_quality: float,
        reviewed_at: datetime,
    ) -> MemoryStateDraft:
        state = current.draft if isinstance(current, MemoryStateRecord) else current
        self._validate_identity(state, knowledge_point)
        self._score("forgetting_rate", forgetting_rate)
        self._score("review_quality", review_quality)
        self._aware("reviewed_at", reviewed_at)
        anchor = state.last_reviewed_at or state.last_activity_at
        if reviewed_at < anchor:
            raise ValueError("review cannot precede the latest memory activity")
        elapsed_days = (reviewed_at - anchor).total_seconds() / 86400
        difficulty_factor = self.difficulty_factor(knowledge_point.difficulty_score)
        previous_effective = self.effective_stability(
            state.stability_days,
            difficulty_factor,
            forgetting_rate,
        )
        pre_review_retrievability = self.retrievability(elapsed_days, previous_effective)
        successful = review_quality >= self.policy.success_quality_threshold
        if successful:
            repetition_bonus = 1 + min(state.review_count, 20) * 0.03
            review_gain = 1 + review_quality * (1 + (1 - pre_review_retrievability))
            review_gain *= repetition_bonus
            stability = min(
                self.policy.maximum_stability_days,
                max(self.policy.base_stability_days, state.stability_days) * review_gain,
            )
            lapse_count = state.lapse_count
        else:
            review_gain = 0.0
            stability = max(
                self.policy.minimum_stability_days,
                state.stability_days * (0.45 + 0.25 * review_quality),
            )
            lapse_count = state.lapse_count + 1
        effective = self.effective_stability(stability, difficulty_factor, forgetting_rate)
        interval = self.review_interval(effective)
        reviewed = MemoryStateDraft(
            memory_state_id=uuid4(),
            learner_ref=state.learner_ref,
            course_id=state.course_id,
            kp_id=state.kp_id,
            state_version=state.state_version + 1,
            parent_memory_state_id=state.memory_state_id,
            model_version=self.policy.model_version,
            stability_days=round(stability, 12),
            effective_stability_days=effective,
            elapsed_days=0.0,
            retrievability=1.0,
            forgetting_rate=forgetting_rate,
            difficulty_factor=difficulty_factor,
            review_gain=round(review_gain, 12),
            review_count=state.review_count + 1,
            lapse_count=lapse_count,
            last_reviewed_at=reviewed_at,
            last_activity_at=reviewed_at,
            next_review_at=reviewed_at + timedelta(days=interval),
            risk_level=MemoryRiskLevel.LOW,
            model_parameters={
                "policy_version": self.policy.version,
                "operation": "REVIEW",
                "review_quality": review_quality,
                "successful": successful,
                "pre_review_retrievability": pre_review_retrievability,
                "target_retrievability": self.policy.target_retrievability,
            },
            content_sha256="0" * 64,
            computed_at=reviewed_at,
        )
        return self._with_digest(reviewed)

    def refresh_batch(
        self,
        states: Sequence[MemoryStateRecord],
        *,
        knowledge_points: Mapping[str, Topic1KnowledgePointV1],
        forgetting_rates: Mapping[str, float],
        as_of: datetime,
    ) -> list[MemoryStateDraft]:
        refreshed: list[MemoryStateDraft] = []
        for record in sorted(states, key=lambda item: (item.draft.learner_ref, item.draft.kp_id)):
            state = record.draft
            knowledge_point = knowledge_points.get(state.kp_id)
            if knowledge_point is None:
                raise ValueError(f"missing Topic 1 knowledge point {state.kp_id}")
            forgetting_rate = forgetting_rates.get(state.learner_ref, state.forgetting_rate)
            refreshed.append(
                self.refresh_state(
                    record,
                    knowledge_point=knowledge_point,
                    forgetting_rate=forgetting_rate,
                    as_of=as_of,
                )
            )
        return refreshed

    @staticmethod
    def quality_from_event(record: LearningBehaviorEventRecord) -> float:
        event = record.draft
        values = [value for value in (event.correctness, event.score) if value is not None]
        if not values:
            raise ValueError("a review event requires correctness or score evidence")
        quality = sum(values) / len(values)
        attempt_penalty = math.exp(-0.15 * max(0, event.attempt_count - 1))
        attention_factor = (
            1.0 if event.attention_ratio is None else 0.7 + 0.3 * event.attention_ratio
        )
        return round(min(1.0, max(0.0, quality * attempt_penalty * attention_factor)), 12)

    @staticmethod
    def retrievability(elapsed_days: float, effective_stability_days: float) -> float:
        if elapsed_days < 0 or effective_stability_days <= 0:
            raise ValueError("elapsed time must be nonnegative and stability must be positive")
        return round(math.exp(-elapsed_days / effective_stability_days), 12)

    def review_interval(self, effective_stability_days: float) -> float:
        if effective_stability_days <= 0:
            raise ValueError("effective stability must be positive")
        interval = -effective_stability_days * math.log(self.policy.target_retrievability)
        return round(min(self.policy.maximum_review_interval_days, max(0.0, interval)), 12)

    def difficulty_factor(self, difficulty_score: float) -> float:
        self._score("difficulty_score", difficulty_score)
        return round(
            self.policy.difficulty_base + self.policy.difficulty_scale * difficulty_score,
            12,
        )

    def effective_stability(
        self,
        stability_days: float,
        difficulty_factor: float,
        forgetting_rate: float,
    ) -> float:
        if stability_days <= 0 or difficulty_factor <= 0:
            raise ValueError("stability and difficulty factors must be positive")
        self._score("forgetting_rate", forgetting_rate)
        forgetting_multiplier = (
            self.policy.forgetting_base + self.policy.forgetting_scale * forgetting_rate
        )
        effective = stability_days / (difficulty_factor * forgetting_multiplier)
        return round(min(self.policy.maximum_stability_days, max(1e-9, effective)), 12)

    @staticmethod
    def risk_level(retrievability: float) -> MemoryRiskLevel:
        EbbinghausMemoryEngine._score("retrievability", retrievability)
        if retrievability >= 0.85:
            return MemoryRiskLevel.LOW
        if retrievability >= 0.7:
            return MemoryRiskLevel.MEDIUM
        if retrievability >= 0.5:
            return MemoryRiskLevel.HIGH
        return MemoryRiskLevel.CRITICAL

    @staticmethod
    def hash_document(state: MemoryStateDraft) -> dict[str, Any]:
        return {
            "schema_version": "topic2.memory-state.v1",
            "memory_state_id": str(state.memory_state_id),
            "learner_ref": state.learner_ref,
            "course_id": state.course_id,
            "kp_id": state.kp_id,
            "state_version": state.state_version,
            "parent_memory_state_id": (
                None if state.parent_memory_state_id is None else str(state.parent_memory_state_id)
            ),
            "model_version": state.model_version,
            "stability_days": state.stability_days,
            "effective_stability_days": state.effective_stability_days,
            "elapsed_days": state.elapsed_days,
            "retrievability": state.retrievability,
            "forgetting_rate": state.forgetting_rate,
            "difficulty_factor": state.difficulty_factor,
            "review_gain": state.review_gain,
            "review_count": state.review_count,
            "lapse_count": state.lapse_count,
            "last_reviewed_at": (
                None if state.last_reviewed_at is None else state.last_reviewed_at.isoformat()
            ),
            "last_activity_at": state.last_activity_at.isoformat(),
            "next_review_at": state.next_review_at.isoformat(),
            "risk_level": state.risk_level.value,
            "model_parameters": state.model_parameters,
            "computed_at": state.computed_at.isoformat(),
        }

    def _with_digest(self, state: MemoryStateDraft) -> MemoryStateDraft:
        return replace(state, content_sha256=canonical_sha256(self.hash_document(state)))

    @staticmethod
    def _validate_identity(
        state: MemoryStateDraft,
        knowledge_point: Topic1KnowledgePointV1,
    ) -> None:
        if (state.course_id, state.kp_id) != (
            knowledge_point.course_id,
            knowledge_point.kp_id,
        ):
            raise ValueError("memory state and Topic 1 knowledge point do not match")

    @staticmethod
    def _score(name: str, value: float) -> None:
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between zero and one")

    @staticmethod
    def _aware(name: str, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")
