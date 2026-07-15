from __future__ import annotations

import heapq
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import (
    PrerequisiteType,
    Topic1GraphSnapshotV1,
    Topic1KnowledgePointV1,
    Topic1PrerequisiteV1,
)

from liyans.domains.topic1.topology import TopologyCycleError, TopologyEdge, analyze_topology

from .entities import (
    LearningPathRecord,
    LearningPathSnapshotDraft,
    MemoryStateRecord,
    PathChangeDraft,
    PathChangeType,
    PathPlanType,
    ProfileDimension,
    StudentProfileRecord,
)

PATH_POLICY_VERSION = "topic2.path-policy.v1"


class LearningTier(StrEnum):
    FOUNDATION = "FOUNDATION"
    REINFORCEMENT = "REINFORCEMENT"
    EXTENSION = "EXTENSION"


@dataclass(frozen=True, slots=True)
class PathPolicy:
    version: str = PATH_POLICY_VERSION
    prerequisite_mastery_threshold: float = 0.6
    extension_mastery_threshold: float = 0.8
    reinforcement_memory_risk: float = 0.3
    weights: tuple[tuple[str, float], ...] = (
        ("mastery_deficit", 0.25),
        ("memory_risk", 0.20),
        ("misconception_severity", 0.15),
        ("goal_alignment", 0.15),
        ("topology_weight", 0.10),
        ("difficulty_pace_fit", 0.08),
        ("prerequisite_readiness", 0.07),
    )

    def __post_init__(self) -> None:
        if not all(
            0 <= value <= 1
            for value in (
                self.prerequisite_mastery_threshold,
                self.extension_mastery_threshold,
                self.reinforcement_memory_risk,
            )
        ):
            raise ValueError("path thresholds must be between zero and one")
        if abs(sum(weight for _, weight in self.weights) - 1.0) > 1e-12:
            raise ValueError("path score weights must sum to one")
        if len({name for name, _ in self.weights}) != len(self.weights):
            raise ValueError("path score weight names must be unique")


@dataclass(frozen=True, slots=True)
class GraphRepair:
    code: str
    edge_id: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class SanitizedGraph:
    knowledge_points: Mapping[str, Topic1KnowledgePointV1]
    prerequisites: tuple[Topic1PrerequisiteV1, ...]
    levels: Mapping[str, int]
    topology_weights: Mapping[str, float]
    repairs: tuple[GraphRepair, ...]


class AdaptivePathPlanner:
    def __init__(self, policy: PathPolicy | None = None) -> None:
        self.policy = policy or PathPolicy()

    def plan(
        self,
        *,
        graph_snapshot: Topic1GraphSnapshotV1,
        profile: StudentProfileRecord,
        memory_states: Sequence[MemoryStateRecord],
        generated_at: datetime,
        target_goal: str,
        target_kp_ids: Sequence[str] | None = None,
        previous_path: LearningPathRecord | None = None,
        change_type: PathChangeType = PathChangeType.INITIALIZED,
        trigger_reason: str = "INITIAL_PROFILE_READY",
        manual_order: Sequence[str] | None = None,
    ) -> tuple[LearningPathSnapshotDraft, PathChangeDraft]:
        self._validate_inputs(
            graph_snapshot=graph_snapshot,
            profile=profile,
            memory_states=memory_states,
            generated_at=generated_at,
            target_goal=target_goal,
            previous_path=previous_path,
        )
        graph = self.sanitize_graph(graph_snapshot)
        selected = self._select_nodes(graph, target_kp_ids)
        mastery = self._mastery_by_kp(profile)
        memory = {record.draft.kp_id: record for record in memory_states}
        misconception = self._misconception_by_kp(profile)
        scores: dict[str, dict[str, float]] = {}
        tiers: dict[str, LearningTier] = {}
        for kp_id in selected:
            point = graph.knowledge_points[kp_id]
            components = self._score_components(
                kp_id,
                point,
                graph,
                selected,
                profile,
                mastery,
                memory,
                misconception,
                target_kp_ids,
            )
            components["total"] = round(
                sum(dict(self.policy.weights)[name] * value for name, value in components.items()),
                12,
            )
            scores[kp_id] = components
            tiers[kp_id] = self._tier(point, components, profile)
        order, ordering_repairs = self._ordered_nodes(
            selected,
            graph.prerequisites,
            scores,
            tiers,
            manual_order,
        )
        all_repairs = (*graph.repairs, *ordering_repairs)
        prerequisites = self._incoming_edges(graph.prerequisites, selected)
        nodes = [
            {
                "order": index,
                "kp_id": kp_id,
                "title": graph.knowledge_points[kp_id].title,
                "tier": tiers[kp_id].value,
                "priority_score": scores[kp_id]["total"],
                "score_components": scores[kp_id],
                "prerequisite_kp_ids": [
                    edge.prerequisite_kp_id for edge in prerequisites.get(kp_id, ())
                ],
                "estimated_minutes": graph.knowledge_points[kp_id].estimated_minutes,
                "rationale_codes": self._rationale_codes(scores[kp_id], tiers[kp_id]),
            }
            for index, kp_id in enumerate(order)
        ]
        path_id = uuid4()
        path_version = 1 if previous_path is None else previous_path.draft.path_version + 1
        parent_id = None if previous_path is None else previous_path.draft.path_snapshot_id
        plan_type = (
            PathPlanType.MANUAL_OVERRIDE
            if manual_order is not None
            else PathPlanType.INITIAL
            if previous_path is None
            else PathPlanType.REPLANNED
        )
        path_document = {
            "schema_version": "topic2.learning-path.v1",
            "nodes": nodes,
            "tiers": {
                tier.value: [node["kp_id"] for node in nodes if node["tier"] == tier.value]
                for tier in LearningTier
            },
        }
        decision_document = {
            "schema_version": "topic2.path-decision.v1",
            "policy_version": self.policy.version,
            "weights": dict(self.policy.weights),
            "target_kp_ids": sorted(target_kp_ids or selected),
            "profile_id": str(profile.draft.profile_id),
            "topic1_graph_snapshot_id": str(graph_snapshot.snapshot_id),
            "topic1_graph_version": graph_snapshot.graph_version,
            "memory_state_ids": [
                str(record.draft.memory_state_id)
                for record in sorted(memory_states, key=lambda item: item.draft.kp_id)
            ],
            "repairs": [self._repair_document(repair) for repair in all_repairs],
            "manual_order_requested": None if manual_order is None else list(manual_order),
        }
        snapshot = LearningPathSnapshotDraft(
            path_snapshot_id=path_id,
            learner_ref=profile.draft.learner_ref,
            course_id=profile.draft.course_id,
            path_version=path_version,
            parent_path_snapshot_id=parent_id,
            topic1_graph_snapshot_id=graph_snapshot.snapshot_id,
            topic1_graph_version=graph_snapshot.graph_version,
            profile_id=profile.draft.profile_id,
            plan_type=plan_type,
            trigger_reason=trigger_reason,
            target_goal=target_goal,
            policy_version=self.policy.version,
            path_document=path_document,
            decision_document=decision_document,
            node_count=len(nodes),
            estimated_minutes=sum(node["estimated_minutes"] for node in nodes),
            manual_override=manual_order is not None,
            content_sha256="0" * 64,
            frozen_at=generated_at,
        )
        snapshot = replace(snapshot, content_sha256=canonical_sha256(self.hash_document(snapshot)))
        change_document = self._change_document(previous_path, nodes, all_repairs)
        change = PathChangeDraft(
            change_id=uuid4(),
            learner_ref=snapshot.learner_ref,
            course_id=snapshot.course_id,
            from_path_snapshot_id=parent_id,
            to_path_snapshot_id=path_id,
            change_type=change_type,
            reason=trigger_reason,
            policy_version=self.policy.version,
            change_document=change_document,
            occurred_at=generated_at,
        )
        return snapshot, change

    def sanitize_graph(self, snapshot: Topic1GraphSnapshotV1) -> SanitizedGraph:
        active = {
            point.kp_id: point
            for point in snapshot.content.knowledge_points
            if point.status.value == "ACTIVE"
        }
        if not active:
            raise ValueError("Topic 1 graph has no active knowledge points")
        repairs: list[GraphRepair] = []
        edges: list[Topic1PrerequisiteV1] = []
        for edge in sorted(snapshot.content.prerequisites, key=lambda item: item.edge_id):
            if edge.prerequisite_kp_id == edge.dependent_kp_id:
                repairs.append(
                    GraphRepair("SELF_EDGE_REMOVED", edge.edge_id, edge.prerequisite_kp_id)
                )
                continue
            missing = {
                endpoint
                for endpoint in (edge.prerequisite_kp_id, edge.dependent_kp_id)
                if endpoint not in active
            }
            if missing:
                repairs.append(
                    GraphRepair(
                        "UNKNOWN_ENDPOINT_REMOVED",
                        edge.edge_id,
                        ",".join(sorted(missing)),
                    )
                )
                continue
            edges.append(edge)
        while True:
            try:
                metrics = analyze_topology(
                    set(active),
                    [TopologyEdge(edge.prerequisite_kp_id, edge.dependent_kp_id) for edge in edges],
                )
                break
            except TopologyCycleError as exc:
                cycle_nodes = set(exc.cycle)
                candidates = [
                    edge
                    for edge in edges
                    if edge.prerequisite_kp_id in cycle_nodes
                    and edge.dependent_kp_id in cycle_nodes
                ]
                if not candidates:
                    raise RuntimeError("cycle repair could not identify a removable edge") from exc
                removed = min(candidates, key=self._edge_removal_key)
                edges.remove(removed)
                repairs.append(
                    GraphRepair(
                        "CYCLE_EDGE_REMOVED",
                        removed.edge_id,
                        f"{removed.prerequisite_kp_id}->{removed.dependent_kp_id}",
                    )
                )
        return SanitizedGraph(
            knowledge_points=active,
            prerequisites=tuple(edges),
            levels=metrics.levels,
            topology_weights=metrics.weights,
            repairs=tuple(repairs),
        )

    def _select_nodes(
        self,
        graph: SanitizedGraph,
        target_kp_ids: Sequence[str] | None,
    ) -> set[str]:
        if target_kp_ids is None:
            return set(graph.knowledge_points)
        target = set(target_kp_ids)
        unknown = target - set(graph.knowledge_points)
        if unknown:
            raise ValueError(f"unknown target knowledge points: {sorted(unknown)}")
        incoming = self._incoming_edges(graph.prerequisites, set(graph.knowledge_points))
        selected = set(target)
        queue = deque(sorted(target))
        while queue:
            current = queue.popleft()
            for edge in incoming.get(current, ()):
                if edge.relation_type == PrerequisiteType.SUPPORTING:
                    continue
                if edge.prerequisite_kp_id not in selected:
                    selected.add(edge.prerequisite_kp_id)
                    queue.append(edge.prerequisite_kp_id)
        return selected

    def _score_components(
        self,
        kp_id: str,
        point: Topic1KnowledgePointV1,
        graph: SanitizedGraph,
        selected: set[str],
        profile: StudentProfileRecord,
        mastery: Mapping[str, float],
        memory: Mapping[str, MemoryStateRecord],
        misconception: Mapping[str, float],
        target_kp_ids: Sequence[str] | None,
    ) -> dict[str, float]:
        kp_mastery = mastery.get(kp_id, profile.draft.knowledge_mastery)
        memory_risk = 1.0 - memory[kp_id].draft.retrievability if kp_id in memory else 1.0
        incoming = self._incoming_edges(graph.prerequisites, selected).get(kp_id, ())
        required = [edge for edge in incoming if edge.relation_type == PrerequisiteType.REQUIRED]
        readiness_values = []
        for edge in required:
            prerequisite_mastery = mastery.get(
                edge.prerequisite_kp_id,
                profile.draft.knowledge_mastery,
            )
            prerequisite_memory = (
                memory[edge.prerequisite_kp_id].draft.retrievability
                if edge.prerequisite_kp_id in memory
                else 0.0
            )
            readiness_values.append(0.7 * prerequisite_mastery + 0.3 * prerequisite_memory)
        prerequisite_readiness = (
            1.0 if not readiness_values else sum(readiness_values) / len(readiness_values)
        )
        capability = (
            0.6 * profile.draft.problem_solving_proficiency + 0.4 * profile.draft.learning_pace
        )
        goal_alignment = (
            1.0
            if target_kp_ids is not None and kp_id in set(target_kp_ids)
            else 1 - abs(point.difficulty_score - profile.draft.learning_goal_tendency)
        )
        return {
            "mastery_deficit": round(1 - kp_mastery, 12),
            "memory_risk": round(memory_risk, 12),
            "misconception_severity": round(misconception.get(kp_id, 0.0), 12),
            "goal_alignment": round(goal_alignment, 12),
            "topology_weight": round(graph.topology_weights.get(kp_id, 0.0), 12),
            "difficulty_pace_fit": round(1 - abs(point.difficulty_score - capability), 12),
            "prerequisite_readiness": round(prerequisite_readiness, 12),
        }

    def _tier(
        self,
        point: Topic1KnowledgePointV1,
        components: Mapping[str, float],
        profile: StudentProfileRecord,
    ) -> LearningTier:
        mastery = 1 - components["mastery_deficit"]
        if (
            components["memory_risk"] >= self.policy.reinforcement_memory_risk
            or components["misconception_severity"] >= 0.4
            or 0.4 <= mastery < self.policy.extension_mastery_threshold
        ):
            return LearningTier.REINFORCEMENT
        if (
            mastery >= self.policy.extension_mastery_threshold
            and profile.draft.learning_goal_tendency >= 0.65
            and components["prerequisite_readiness"] >= self.policy.prerequisite_mastery_threshold
            and point.difficulty_score >= 0.55
        ):
            return LearningTier.EXTENSION
        return LearningTier.FOUNDATION

    def _ordered_nodes(
        self,
        selected: set[str],
        edges: Sequence[Topic1PrerequisiteV1],
        scores: Mapping[str, Mapping[str, float]],
        tiers: Mapping[str, LearningTier],
        manual_order: Sequence[str] | None,
    ) -> tuple[list[str], tuple[GraphRepair, ...]]:
        selected_edges = [
            edge
            for edge in edges
            if edge.prerequisite_kp_id in selected and edge.dependent_kp_id in selected
        ]
        outgoing: dict[str, list[str]] = defaultdict(list)
        indegree = {kp_id: 0 for kp_id in selected}
        for edge in selected_edges:
            outgoing[edge.prerequisite_kp_id].append(edge.dependent_kp_id)
            indegree[edge.dependent_kp_id] += 1
        manual_index = {kp_id: index for index, kp_id in enumerate(manual_order or ())}
        unknown_manual = set(manual_index) - selected
        if unknown_manual:
            raise ValueError(
                f"manual path contains unknown knowledge points: {sorted(unknown_manual)}"
            )
        if len(manual_index) != len(manual_order or ()):
            raise ValueError("manual path contains duplicate knowledge points")
        tier_rank = {
            LearningTier.REINFORCEMENT: 0,
            LearningTier.FOUNDATION: 1,
            LearningTier.EXTENSION: 2,
        }

        def key(kp_id: str) -> tuple[int, int, float, str]:
            return (
                manual_index.get(kp_id, len(selected) + 1),
                tier_rank[tiers[kp_id]],
                -scores[kp_id]["total"],
                kp_id,
            )

        ready = [(key(kp_id), kp_id) for kp_id, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        ordered: list[str] = []
        while ready:
            _, kp_id = heapq.heappop(ready)
            ordered.append(kp_id)
            for dependent in sorted(outgoing.get(kp_id, ())):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, (key(dependent), dependent))
        if len(ordered) != len(selected):
            raise RuntimeError("sanitized path graph unexpectedly remains cyclic")
        repairs: list[GraphRepair] = []
        if manual_order is not None:
            requested = [kp_id for kp_id in manual_order if kp_id in selected]
            actual_positions = {kp_id: index for index, kp_id in enumerate(ordered)}
            if any(
                actual_positions[left] > actual_positions[right]
                for left, right in zip(requested, requested[1:], strict=False)
            ):
                repairs.append(
                    GraphRepair(
                        "MANUAL_ORDER_TOPOLOGY_REPAIRED",
                        None,
                        "Prerequisite constraints took precedence over manual ordering.",
                    )
                )
        return ordered, tuple(repairs)

    @staticmethod
    def _incoming_edges(
        edges: Sequence[Topic1PrerequisiteV1],
        selected: set[str],
    ) -> dict[str, tuple[Topic1PrerequisiteV1, ...]]:
        incoming: dict[str, list[Topic1PrerequisiteV1]] = defaultdict(list)
        for edge in edges:
            if edge.prerequisite_kp_id in selected and edge.dependent_kp_id in selected:
                incoming[edge.dependent_kp_id].append(edge)
        return {
            kp_id: tuple(sorted(values, key=lambda item: (item.relation_type.value, item.edge_id)))
            for kp_id, values in incoming.items()
        }

    @staticmethod
    def _mastery_by_kp(profile: StudentProfileRecord) -> dict[str, float]:
        result: dict[str, float] = {}
        for feature in profile.draft.features:
            prefix = "kp:"
            suffix = ":mastery"
            if (
                feature.dimension == ProfileDimension.KNOWLEDGE_MASTERY
                and feature.feature_key.startswith(prefix)
                and feature.feature_key.endswith(suffix)
            ):
                result[feature.feature_key[len(prefix) : -len(suffix)]] = feature.normalized_score
        return result

    @staticmethod
    def _misconception_by_kp(profile: StudentProfileRecord) -> dict[str, float]:
        result: dict[str, float] = defaultdict(float)
        for feature in profile.draft.features:
            if feature.dimension != ProfileDimension.MISCONCEPTION_PREFERENCE:
                continue
            kp_id = feature.value_document.get("kp_id")
            if isinstance(kp_id, str):
                result[kp_id] = max(result[kp_id], feature.normalized_score)
        return dict(result)

    @staticmethod
    def _rationale_codes(
        components: Mapping[str, float],
        tier: LearningTier,
    ) -> list[str]:
        codes = [f"TIER_{tier.value}"]
        if components["memory_risk"] >= 0.3:
            codes.append("MEMORY_REVIEW_DUE")
        if components["mastery_deficit"] >= 0.4:
            codes.append("MASTERY_DEFICIT")
        if components["misconception_severity"] >= 0.4:
            codes.append("MISCONCEPTION_RISK")
        if components["goal_alignment"] >= 0.8:
            codes.append("GOAL_ALIGNED")
        if components["prerequisite_readiness"] < 0.6:
            codes.append("PREREQUISITE_GAP")
        return codes

    @staticmethod
    def _edge_removal_key(edge: Topic1PrerequisiteV1) -> tuple[int, float, str]:
        relation_rank = {
            PrerequisiteType.SUPPORTING: 0,
            PrerequisiteType.RECOMMENDED: 1,
            PrerequisiteType.REQUIRED: 2,
        }
        return relation_rank[edge.relation_type], edge.strength, edge.edge_id

    @staticmethod
    def _change_document(
        previous: LearningPathRecord | None,
        nodes: Sequence[dict[str, Any]],
        repairs: Sequence[GraphRepair],
    ) -> dict[str, Any]:
        current = {node["kp_id"]: node for node in nodes}
        previous_nodes = (
            {}
            if previous is None
            else {
                node["kp_id"]: node
                for node in previous.draft.path_document.get("nodes", [])
                if isinstance(node, dict) and isinstance(node.get("kp_id"), str)
            }
        )
        return {
            "added_kp_ids": sorted(set(current) - set(previous_nodes)),
            "removed_kp_ids": sorted(set(previous_nodes) - set(current)),
            "moved": [
                {
                    "kp_id": kp_id,
                    "from_order": previous_nodes[kp_id].get("order"),
                    "to_order": current[kp_id].get("order"),
                }
                for kp_id in sorted(set(current) & set(previous_nodes))
                if previous_nodes[kp_id].get("order") != current[kp_id].get("order")
            ],
            "tier_changes": [
                {
                    "kp_id": kp_id,
                    "from_tier": previous_nodes[kp_id].get("tier"),
                    "to_tier": current[kp_id].get("tier"),
                }
                for kp_id in sorted(set(current) & set(previous_nodes))
                if previous_nodes[kp_id].get("tier") != current[kp_id].get("tier")
            ],
            "repairs": [AdaptivePathPlanner._repair_document(repair) for repair in repairs],
        }

    @staticmethod
    def _repair_document(repair: GraphRepair) -> dict[str, str | None]:
        return {"code": repair.code, "edge_id": repair.edge_id, "detail": repair.detail}

    @staticmethod
    def hash_document(snapshot: LearningPathSnapshotDraft) -> dict[str, Any]:
        return {
            "schema_version": "topic2.learning-path-snapshot.v1",
            "path_snapshot_id": str(snapshot.path_snapshot_id),
            "learner_ref": snapshot.learner_ref,
            "course_id": snapshot.course_id,
            "path_version": snapshot.path_version,
            "parent_path_snapshot_id": (
                None
                if snapshot.parent_path_snapshot_id is None
                else str(snapshot.parent_path_snapshot_id)
            ),
            "topic1_graph_snapshot_id": str(snapshot.topic1_graph_snapshot_id),
            "topic1_graph_version": snapshot.topic1_graph_version,
            "profile_id": str(snapshot.profile_id),
            "plan_type": snapshot.plan_type.value,
            "trigger_reason": snapshot.trigger_reason,
            "target_goal": snapshot.target_goal,
            "policy_version": snapshot.policy_version,
            "path_document": snapshot.path_document,
            "decision_document": snapshot.decision_document,
            "node_count": snapshot.node_count,
            "estimated_minutes": snapshot.estimated_minutes,
            "manual_override": snapshot.manual_override,
            "frozen_at": snapshot.frozen_at.isoformat(),
        }

    @staticmethod
    def _validate_inputs(
        *,
        graph_snapshot: Topic1GraphSnapshotV1,
        profile: StudentProfileRecord,
        memory_states: Sequence[MemoryStateRecord],
        generated_at: datetime,
        target_goal: str,
        previous_path: LearningPathRecord | None,
    ) -> None:
        if generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        if not target_goal or len(target_goal) > 512:
            raise ValueError("target_goal must contain between one and 512 characters")
        if profile.draft.course_id != graph_snapshot.course_id:
            raise ValueError("profile and Topic 1 graph belong to different courses")
        if previous_path is not None and (
            previous_path.draft.learner_ref != profile.draft.learner_ref
            or previous_path.draft.course_id != profile.draft.course_id
        ):
            raise ValueError("previous path belongs to another learner or course")
        for record in memory_states:
            if (
                record.draft.learner_ref != profile.draft.learner_ref
                or record.draft.course_id != profile.draft.course_id
            ):
                raise ValueError("memory state belongs to another learner or course")
