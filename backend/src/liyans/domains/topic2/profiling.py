from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from uuid import UUID, uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1KnowledgePointV1, Topic1MisconceptionV1

from .entities import (
    BehaviorEventType,
    LearningBehaviorEventRecord,
    ProfileDimension,
    ProfileFeatureDraft,
    StudentProfileDraft,
    StudentProfileRecord,
)

PROFILE_POLICY_VERSION = "topic2.profile-policy.v1"
MAX_PROFILE_EVENTS = 5000


@dataclass(frozen=True, slots=True)
class ProfilingPolicy:
    version: str = PROFILE_POLICY_VERSION
    evidence_half_life_days: float = 30.0
    prior_half_life_days: float = 90.0
    confidence_scale: float = 6.0
    max_prior_weight: float = 50.0
    outlier_modified_z_threshold: float = 3.5
    minimum_outlier_sample: int = 5

    def __post_init__(self) -> None:
        if (
            min(
                self.evidence_half_life_days,
                self.prior_half_life_days,
                self.confidence_scale,
                self.max_prior_weight,
                self.outlier_modified_z_threshold,
            )
            <= 0
        ):
            raise ValueError("profiling policy coefficients must be positive")
        if self.minimum_outlier_sample < 3:
            raise ValueError("minimum_outlier_sample must be at least three")


@dataclass(frozen=True, slots=True)
class WeightedObservation:
    value: float
    weight: float
    source_event_id: str


class SixDimensionProfileEngine:
    def __init__(self, policy: ProfilingPolicy | None = None) -> None:
        self.policy = policy or ProfilingPolicy()

    def build_profile(
        self,
        *,
        learner_ref: str,
        course_id: str,
        events: Sequence[LearningBehaviorEventRecord],
        knowledge_points: Mapping[str, Topic1KnowledgePointV1],
        misconceptions: Mapping[str, Topic1MisconceptionV1],
        generated_at: datetime,
        previous: StudentProfileRecord | None = None,
    ) -> StudentProfileDraft:
        self._validate_inputs(
            learner_ref=learner_ref,
            course_id=course_id,
            events=events,
            generated_at=generated_at,
            previous=previous,
        )
        accepted = self._filter_outliers(events, generated_at)
        observations = self._extract_observations(
            accepted,
            knowledge_points,
            misconceptions,
            generated_at,
        )
        scores: dict[ProfileDimension, float] = {}
        confidences: dict[ProfileDimension, float] = {}
        features: list[ProfileFeatureDraft] = []
        previous_features = self._previous_features(previous)
        for dimension in ProfileDimension:
            dimension_observations = observations[dimension]
            prior_score = self._previous_score(previous, dimension)
            score, confidence = self._aggregate_dimension(
                prior_score=prior_score,
                previous=previous,
                observations=dimension_observations,
                generated_at=generated_at,
            )
            scores[dimension] = score
            confidences[dimension] = confidence
            features.append(
                ProfileFeatureDraft(
                    feature_id=uuid4(),
                    dimension=dimension,
                    feature_key="aggregate",
                    value_document={
                        "policy_version": self.policy.version,
                        "accepted_event_count": len(dimension_observations),
                        "prior_applied": previous is not None,
                    },
                    normalized_score=score,
                    confidence=confidence,
                    evidence_count=len(dimension_observations),
                    source_event_ids=tuple(
                        sorted({item.source_event_id for item in dimension_observations})
                    ),
                    computed_at=generated_at,
                )
            )
        features.extend(
            self._knowledge_point_features(
                accepted,
                knowledge_points,
                previous_features,
                generated_at,
            )
        )
        features.extend(
            self._misconception_features(
                accepted,
                misconceptions,
                previous_features,
                generated_at,
            )
        )
        batch_start = min((record.draft.occurred_at for record in accepted), default=None)
        batch_end = max((record.draft.occurred_at for record in accepted), default=None)
        previous_start = None if previous is None else previous.draft.source_window_start
        previous_end = None if previous is None else previous.draft.source_window_end
        source_start = min(
            (value for value in (previous_start, batch_start) if value is not None),
            default=None,
        )
        source_end = max(
            (value for value in (previous_end, batch_end) if value is not None),
            default=None,
        )
        batch_cursor = max(
            ((record.draft.received_at, record.draft.event_id) for record in accepted),
            default=None,
        )
        previous_cursor = self._previous_ingestion_cursor(previous)
        ingestion_cursor = max(
            (value for value in (previous_cursor, batch_cursor) if value is not None),
            default=None,
        )
        last_event_at = source_end or (None if previous is None else previous.draft.last_event_at)
        activity_count = (0 if previous is None else previous.draft.activity_count) + len(accepted)
        profile_id = uuid4()
        profile_version = 1 if previous is None else previous.draft.profile_version + 1
        parent_profile_id = None if previous is None else previous.draft.profile_id
        dimensions_document = {
            "knowledge_mastery": scores[ProfileDimension.KNOWLEDGE_MASTERY],
            "problem_solving_proficiency": scores[ProfileDimension.PROBLEM_SOLVING_PROFICIENCY],
            "misconception_preference": scores[ProfileDimension.MISCONCEPTION_PREFERENCE],
            "learning_pace": scores[ProfileDimension.LEARNING_PACE],
            "forgetting_rate": scores[ProfileDimension.FORGETTING_RATE],
            "learning_goal_tendency": scores[ProfileDimension.LEARNING_GOAL_TENDENCY],
        }
        confidence_score = round(sum(confidences.values()) / len(confidences), 12)
        document = {
            "schema_version": "topic2.student-profile.v1",
            "profile_id": str(profile_id),
            "profile_version": profile_version,
            "parent_profile_id": (None if parent_profile_id is None else str(parent_profile_id)),
            "learner_ref": learner_ref,
            "course_id": course_id,
            "policy_version": self.policy.version,
            "dimensions": dimensions_document,
            "confidence_score": confidence_score,
            "activity_count": activity_count,
            "accepted_event_count": len(accepted),
            "rejected_event_count": len(events) - len(accepted),
            "source_window": (
                None
                if source_start is None
                else {"start": source_start.isoformat(), "end": source_end.isoformat()}
            ),
            "ingestion_cursor": (
                None
                if ingestion_cursor is None
                else {
                    "received_at": ingestion_cursor[0].isoformat(),
                    "event_id": str(ingestion_cursor[1]),
                }
            ),
            "generated_at": generated_at.isoformat(),
        }
        return StudentProfileDraft(
            profile_id=profile_id,
            learner_ref=learner_ref,
            course_id=course_id,
            profile_version=profile_version,
            parent_profile_id=parent_profile_id,
            policy_version=self.policy.version,
            knowledge_mastery=dimensions_document["knowledge_mastery"],
            problem_solving_proficiency=dimensions_document["problem_solving_proficiency"],
            misconception_preference=dimensions_document["misconception_preference"],
            learning_pace=dimensions_document["learning_pace"],
            forgetting_rate=dimensions_document["forgetting_rate"],
            learning_goal_tendency=dimensions_document["learning_goal_tendency"],
            confidence_score=confidence_score,
            activity_count=activity_count,
            last_event_at=last_event_at,
            source_window_start=source_start,
            source_window_end=source_end,
            profile_document=document,
            content_sha256=canonical_sha256(document),
            frozen_at=generated_at,
            features=tuple(features),
        )

    def _validate_inputs(
        self,
        *,
        learner_ref: str,
        course_id: str,
        events: Sequence[LearningBehaviorEventRecord],
        generated_at: datetime,
        previous: StudentProfileRecord | None,
    ) -> None:
        if generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        if len(events) > MAX_PROFILE_EVENTS:
            raise ValueError(f"profile event count cannot exceed {MAX_PROFILE_EVENTS}")
        if previous is not None and (
            previous.draft.learner_ref != learner_ref or previous.draft.course_id != course_id
        ):
            raise ValueError("previous profile belongs to another learner or course")
        for record in events:
            event = record.draft
            if event.learner_ref != learner_ref or event.course_id != course_id:
                raise ValueError("behavior event belongs to another learner or course")
            if event.occurred_at > generated_at:
                raise ValueError("behavior event occurred after profile generation time")

    def _filter_outliers(
        self,
        events: Sequence[LearningBehaviorEventRecord],
        generated_at: datetime,
    ) -> list[LearningBehaviorEventRecord]:
        eligible = [record for record in events if record.draft.occurred_at <= generated_at]
        durations = [
            record.draft.duration_seconds
            for record in eligible
            if record.draft.duration_seconds is not None
        ]
        latencies = [
            float(record.draft.response_latency_ms)
            for record in eligible
            if record.draft.response_latency_ms is not None
        ]
        duration_bounds = self._robust_bounds(durations)
        latency_bounds = self._robust_bounds(latencies)
        accepted: list[LearningBehaviorEventRecord] = []
        for record in eligible:
            event = record.draft
            if event.duration_seconds is not None and not self._inside(
                event.duration_seconds,
                duration_bounds,
            ):
                continue
            if event.response_latency_ms is not None and not self._inside(
                float(event.response_latency_ms),
                latency_bounds,
            ):
                continue
            accepted.append(record)
        return sorted(accepted, key=lambda item: (item.draft.occurred_at, item.draft.event_id))

    def _robust_bounds(self, values: Sequence[float]) -> tuple[float, float] | None:
        if len(values) < self.policy.minimum_outlier_sample:
            return None
        center = median(values)
        absolute_deviations = [abs(value - center) for value in values]
        mad = median(absolute_deviations)
        if mad == 0:
            return (min(values), max(values))
        radius = self.policy.outlier_modified_z_threshold * mad / 0.6745
        return (max(0.0, center - radius), center + radius)

    @staticmethod
    def _inside(value: float, bounds: tuple[float, float] | None) -> bool:
        return bounds is None or bounds[0] <= value <= bounds[1]

    def _extract_observations(
        self,
        events: Sequence[LearningBehaviorEventRecord],
        knowledge_points: Mapping[str, Topic1KnowledgePointV1],
        misconceptions: Mapping[str, Topic1MisconceptionV1],
        generated_at: datetime,
    ) -> dict[ProfileDimension, list[WeightedObservation]]:
        observations: dict[ProfileDimension, list[WeightedObservation]] = defaultdict(list)
        performance_by_kp: dict[str, list[tuple[datetime, float, str]]] = defaultdict(list)
        for record in events:
            event = record.draft
            recency = self._recency_weight(event.occurred_at, generated_at)
            difficulty = (
                0.5
                if event.kp_id is None or event.kp_id not in knowledge_points
                else knowledge_points[event.kp_id].difficulty_score
            )
            difficulty_weight = 0.75 + 0.5 * difficulty
            performance = self._performance_value(record)
            if performance is not None:
                observations[ProfileDimension.KNOWLEDGE_MASTERY].append(
                    WeightedObservation(
                        performance,
                        recency * difficulty_weight,
                        event.source_event_id,
                    )
                )
                if event.kp_id is not None:
                    performance_by_kp[event.kp_id].append(
                        (event.occurred_at, performance, event.source_event_id)
                    )
            proficiency = self._proficiency_value(record, knowledge_points)
            if proficiency is not None:
                observations[ProfileDimension.PROBLEM_SOLVING_PROFICIENCY].append(
                    WeightedObservation(
                        proficiency,
                        recency * difficulty_weight,
                        event.source_event_id,
                    )
                )
            pace = self._pace_value(record, knowledge_points)
            if pace is not None:
                observations[ProfileDimension.LEARNING_PACE].append(
                    WeightedObservation(pace, recency, event.source_event_id)
                )
            if event.misconception_ids:
                severity = max(
                    (
                        self._misconception_severity(misconceptions[item].severity.value)
                        for item in event.misconception_ids
                        if item in misconceptions
                    ),
                    default=0.5,
                )
                observations[ProfileDimension.MISCONCEPTION_PREFERENCE].append(
                    WeightedObservation(severity, recency, event.source_event_id)
                )
            elif event.event_type == BehaviorEventType.ANSWER_SUBMITTED:
                observations[ProfileDimension.MISCONCEPTION_PREFERENCE].append(
                    WeightedObservation(0.0, recency, event.source_event_id)
                )
            for tag in event.goal_tags:
                observations[ProfileDimension.LEARNING_GOAL_TENDENCY].append(
                    WeightedObservation(
                        self._goal_value(tag),
                        recency,
                        event.source_event_id,
                    )
                )
        for pairs in performance_by_kp.values():
            ordered = sorted(pairs)
            for previous, current in zip(ordered, ordered[1:], strict=False):
                elapsed_days = (current[0] - previous[0]).total_seconds() / 86400
                if elapsed_days < 0.25:
                    continue
                decline = max(0.0, previous[1] - current[1])
                daily_decline = min(1.0, decline / max(1.0, elapsed_days))
                observations[ProfileDimension.FORGETTING_RATE].append(
                    WeightedObservation(
                        daily_decline,
                        self._recency_weight(current[0], generated_at),
                        current[2],
                    )
                )
        return observations

    def _aggregate_dimension(
        self,
        *,
        prior_score: float,
        previous: StudentProfileRecord | None,
        observations: Sequence[WeightedObservation],
        generated_at: datetime,
    ) -> tuple[float, float]:
        elapsed = self._prior_elapsed_days(previous, generated_at)
        prior_decay = math.exp(-math.log(2) * elapsed / self.policy.prior_half_life_days)
        prior_count = 0 if previous is None else previous.draft.activity_count
        prior_weight = min(self.policy.max_prior_weight, float(prior_count)) * prior_decay
        if previous is not None and prior_count == 0:
            prior_weight = prior_decay
        evidence_weight = sum(item.weight for item in observations)
        if evidence_weight > 0:
            estimate = sum(item.value * item.weight for item in observations) / evidence_weight
            denominator = prior_weight + evidence_weight
            score = (
                estimate
                if denominator == 0
                else (prior_score * prior_weight + estimate * evidence_weight) / denominator
            )
        elif previous is not None:
            score = 0.5 + (prior_score - 0.5) * prior_decay
        else:
            score = self._dimension_baseline(observations)
        effective_evidence = evidence_weight + min(prior_weight, self.policy.confidence_scale)
        confidence = 1 - math.exp(-effective_evidence / self.policy.confidence_scale)
        if evidence_weight == 0:
            confidence *= prior_decay
        return round(min(1.0, max(0.0, score)), 12), round(confidence, 12)

    @staticmethod
    def _dimension_baseline(_observations: Sequence[WeightedObservation]) -> float:
        return 0.5

    def _knowledge_point_features(
        self,
        events: Sequence[LearningBehaviorEventRecord],
        knowledge_points: Mapping[str, Topic1KnowledgePointV1],
        previous: Mapping[tuple[ProfileDimension, str], ProfileFeatureDraft],
        generated_at: datetime,
    ) -> list[ProfileFeatureDraft]:
        by_kp: dict[str, list[LearningBehaviorEventRecord]] = defaultdict(list)
        for record in events:
            if (
                record.draft.kp_id in knowledge_points
                and self._performance_value(record) is not None
            ):
                by_kp[record.draft.kp_id].append(record)  # type: ignore[index]
        features: list[ProfileFeatureDraft] = []
        for kp_id, records in sorted(by_kp.items()):
            observations = [
                WeightedObservation(
                    self._performance_value(record) or 0.0,
                    self._recency_weight(record.draft.occurred_at, generated_at),
                    record.draft.source_event_id,
                )
                for record in records
            ]
            prior = previous.get((ProfileDimension.KNOWLEDGE_MASTERY, f"kp:{kp_id}:mastery"))
            score = self._weighted_mean(observations)
            if prior is not None:
                score = (prior.normalized_score * prior.evidence_count + score * len(records)) / (
                    prior.evidence_count + len(records)
                )
            evidence_count = (0 if prior is None else prior.evidence_count) + len(records)
            features.append(
                ProfileFeatureDraft(
                    feature_id=uuid4(),
                    dimension=ProfileDimension.KNOWLEDGE_MASTERY,
                    feature_key=f"kp:{kp_id}:mastery",
                    value_document={"kp_id": kp_id},
                    normalized_score=round(score, 12),
                    confidence=round(1 - math.exp(-evidence_count / 4), 12),
                    evidence_count=evidence_count,
                    source_event_ids=tuple(
                        sorted({record.draft.source_event_id for record in records})
                    ),
                    computed_at=generated_at,
                )
            )
        return features

    def _misconception_features(
        self,
        events: Sequence[LearningBehaviorEventRecord],
        misconceptions: Mapping[str, Topic1MisconceptionV1],
        previous: Mapping[tuple[ProfileDimension, str], ProfileFeatureDraft],
        generated_at: datetime,
    ) -> list[ProfileFeatureDraft]:
        counts: Counter[str] = Counter()
        sources: dict[str, set[str]] = defaultdict(set)
        for record in events:
            for misconception_id in record.draft.misconception_ids:
                if misconception_id in misconceptions:
                    counts[misconception_id] += 1
                    sources[misconception_id].add(record.draft.source_event_id)
        features: list[ProfileFeatureDraft] = []
        for misconception_id, count in sorted(counts.items()):
            misconception = misconceptions[misconception_id]
            key = f"misconception:{misconception_id}"
            prior = previous.get((ProfileDimension.MISCONCEPTION_PREFERENCE, key))
            prior_count = 0 if prior is None else prior.evidence_count
            total = prior_count + count
            severity = self._misconception_severity(misconception.severity.value)
            frequency = 1 - math.exp(-total / 3)
            features.append(
                ProfileFeatureDraft(
                    feature_id=uuid4(),
                    dimension=ProfileDimension.MISCONCEPTION_PREFERENCE,
                    feature_key=key,
                    value_document={
                        "misconception_id": misconception_id,
                        "kp_id": misconception.kp_id,
                        "severity": misconception.severity.value,
                    },
                    normalized_score=round(severity * frequency, 12),
                    confidence=round(1 - math.exp(-total / 3), 12),
                    evidence_count=total,
                    source_event_ids=tuple(sorted(sources[misconception_id])),
                    computed_at=generated_at,
                )
            )
        return features

    def _recency_weight(self, occurred_at: datetime, generated_at: datetime) -> float:
        age_days = max(0.0, (generated_at - occurred_at).total_seconds() / 86400)
        return math.exp(-math.log(2) * age_days / self.policy.evidence_half_life_days)

    @staticmethod
    def _performance_value(record: LearningBehaviorEventRecord) -> float | None:
        event = record.draft
        values = [value for value in (event.correctness, event.score) if value is not None]
        return None if not values else sum(values) / len(values)

    @staticmethod
    def _proficiency_value(
        record: LearningBehaviorEventRecord,
        knowledge_points: Mapping[str, Topic1KnowledgePointV1],
    ) -> float | None:
        event = record.draft
        performance = SixDimensionProfileEngine._performance_value(record)
        if performance is None or event.event_type not in {
            BehaviorEventType.ANSWER_SUBMITTED,
            BehaviorEventType.SIMULATION_RUN,
            BehaviorEventType.CODE_EXECUTED,
            BehaviorEventType.REVIEW_COMPLETED,
        }:
            return None
        first_attempt = 1.0 / max(1, event.attempt_count)
        efficiency = 0.5
        if event.duration_seconds is not None and event.kp_id in knowledge_points:
            expected = knowledge_points[event.kp_id].estimated_minutes * 60
            ratio = expected / max(1.0, event.duration_seconds)
            efficiency = ratio / (1 + ratio)
        return min(1.0, max(0.0, 0.55 * performance + 0.25 * first_attempt + 0.2 * efficiency))

    @staticmethod
    def _pace_value(
        record: LearningBehaviorEventRecord,
        knowledge_points: Mapping[str, Topic1KnowledgePointV1],
    ) -> float | None:
        event = record.draft
        if event.duration_seconds is not None and event.kp_id in knowledge_points:
            expected = knowledge_points[event.kp_id].estimated_minutes * 60
            ratio = expected / max(1.0, event.duration_seconds)
            return min(1.0, max(0.0, ratio / (1 + ratio)))
        if event.response_latency_ms is not None:
            ratio = 30000 / max(1.0, float(event.response_latency_ms))
            return min(1.0, max(0.0, ratio / (1 + ratio)))
        return None

    @staticmethod
    def _misconception_severity(value: str) -> float:
        return {"LOW": 0.25, "MEDIUM": 0.5, "HIGH": 0.75, "CRITICAL": 1.0}.get(
            value,
            0.5,
        )

    @staticmethod
    def _goal_value(tag: str) -> float:
        normalized = tag.strip().upper().replace("-", "_")
        return {
            "FOUNDATION": 0.2,
            "PASS_EXAM": 0.45,
            "CERTIFICATION": 0.5,
            "ENGINEERING": 0.65,
            "THEORY": 0.7,
            "RESEARCH": 0.85,
            "ADVANCED": 0.9,
        }.get(normalized, 0.5)

    @staticmethod
    def _weighted_mean(observations: Sequence[WeightedObservation]) -> float:
        denominator = sum(item.weight for item in observations)
        return (
            0.5
            if denominator == 0
            else sum(item.value * item.weight for item in observations) / denominator
        )

    @staticmethod
    def _previous_score(
        previous: StudentProfileRecord | None,
        dimension: ProfileDimension,
    ) -> float:
        if previous is None:
            return 0.5
        field = {
            ProfileDimension.KNOWLEDGE_MASTERY: "knowledge_mastery",
            ProfileDimension.PROBLEM_SOLVING_PROFICIENCY: "problem_solving_proficiency",
            ProfileDimension.MISCONCEPTION_PREFERENCE: "misconception_preference",
            ProfileDimension.LEARNING_PACE: "learning_pace",
            ProfileDimension.FORGETTING_RATE: "forgetting_rate",
            ProfileDimension.LEARNING_GOAL_TENDENCY: "learning_goal_tendency",
        }[dimension]
        return float(getattr(previous.draft, field))

    @staticmethod
    def _previous_features(
        previous: StudentProfileRecord | None,
    ) -> dict[tuple[ProfileDimension, str], ProfileFeatureDraft]:
        if previous is None:
            return {}
        return {
            (feature.dimension, feature.feature_key): feature for feature in previous.draft.features
        }

    @staticmethod
    def _prior_elapsed_days(
        previous: StudentProfileRecord | None,
        generated_at: datetime,
    ) -> float:
        if previous is None:
            return 0.0
        return max(0.0, (generated_at - previous.draft.frozen_at).total_seconds() / 86400)

    @staticmethod
    def _previous_ingestion_cursor(
        previous: StudentProfileRecord | None,
    ) -> tuple[datetime, UUID] | None:
        if previous is None:
            return None
        cursor = previous.draft.profile_document.get("ingestion_cursor")
        if not isinstance(cursor, dict):
            return None
        received_at = cursor.get("received_at")
        event_id = cursor.get("event_id")
        if not isinstance(received_at, str) or not isinstance(event_id, str):
            return None
        return datetime.fromisoformat(received_at), UUID(event_id)
