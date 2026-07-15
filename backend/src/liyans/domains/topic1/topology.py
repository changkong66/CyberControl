from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from math import ceil
from typing import Protocol


class TopologyCycleError(ValueError):
    def __init__(self, cycle: tuple[str, ...]) -> None:
        super().__init__("knowledge topology contains a directed cycle")
        self.cycle = cycle


@dataclass(frozen=True, slots=True)
class TopologyEdge:
    prerequisite_kp_id: str
    dependent_kp_id: str


@dataclass(frozen=True, slots=True)
class TopologyMetrics:
    topological_order: tuple[str, ...]
    levels: dict[str, int]
    weights: dict[str, float]
    descendant_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class DifficultyAssessment:
    level: int
    score: float
    structural_score: float


class MisconceptionCandidate(Protocol):
    misconception_id: str
    diagnosis_tags: list[str]


def analyze_topology(node_ids: set[str], edges: list[TopologyEdge]) -> TopologyMetrics:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    indegree = dict.fromkeys(node_ids, 0)
    for edge in edges:
        if edge.prerequisite_kp_id not in node_ids or edge.dependent_kp_id not in node_ids:
            raise ValueError("topology edge references an unknown knowledge point")
        if edge.prerequisite_kp_id == edge.dependent_kp_id:
            raise TopologyCycleError((edge.prerequisite_kp_id, edge.dependent_kp_id))
        dependents = adjacency[edge.prerequisite_kp_id]
        if edge.dependent_kp_id not in dependents:
            dependents.add(edge.dependent_kp_id)
            indegree[edge.dependent_kp_id] += 1

    ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    order: list[str] = []
    levels = dict.fromkeys(node_ids, 0)
    while ready:
        current = ready.popleft()
        order.append(current)
        for dependent in sorted(adjacency[current]):
            levels[dependent] = max(levels[dependent], levels[current] + 1)
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)

    if len(order) != len(node_ids):
        raise TopologyCycleError(_find_cycle(adjacency, node_ids - set(order)))

    descendants = _descendant_counts(tuple(order), adjacency)
    max_level = max(levels.values(), default=0)
    denominator = max(1, len(node_ids) - 1)
    weights: dict[str, float] = {}
    for node_id in node_ids:
        if len(node_ids) == 1:
            weights[node_id] = 1.0
            continue
        influence = descendants[node_id] / denominator
        depth = levels[node_id] / max(1, max_level)
        weights[node_id] = round(min(1.0, 0.55 * influence + 0.45 * depth), 6)
    return TopologyMetrics(tuple(order), levels, weights, descendants)


def classify_difficulty(
    *,
    declared_score: float,
    prerequisite_count: int,
    formula_count: int,
    objective_count: int,
    estimated_minutes: int,
) -> DifficultyAssessment:
    if not 0 <= declared_score <= 1:
        raise ValueError("declared_score must be between zero and one")
    if min(prerequisite_count, formula_count, objective_count) < 0 or estimated_minutes < 1:
        raise ValueError("difficulty features cannot be negative")
    structural = (
        0.35 * min(1.0, prerequisite_count / 5)
        + 0.30 * min(1.0, formula_count / 8)
        + 0.20 * min(1.0, objective_count / 6)
        + 0.15 * min(1.0, estimated_minutes / 240)
    )
    score = round(0.4 * declared_score + 0.6 * structural, 6)
    return DifficultyAssessment(
        level=max(1, min(5, ceil(score * 5))),
        score=score,
        structural_score=round(structural, 6),
    )


def rank_misconceptions(
    observed_tags: set[str],
    candidates: list[MisconceptionCandidate],
) -> tuple[str, ...]:
    normalized_observed = {_normalize_tag(tag) for tag in observed_tags if tag.strip()}
    ranked: list[tuple[float, str]] = []
    for candidate in candidates:
        candidate_tags = {_normalize_tag(tag) for tag in candidate.diagnosis_tags if tag.strip()}
        union = normalized_observed | candidate_tags
        score = len(normalized_observed & candidate_tags) / len(union) if union else 0.0
        if score > 0:
            ranked.append((score, candidate.misconception_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(item[1] for item in ranked)


def _normalize_tag(tag: str) -> str:
    return " ".join(tag.casefold().replace("_", " ").replace("-", " ").split())


def _descendant_counts(
    order: tuple[str, ...],
    adjacency: dict[str, set[str]],
) -> dict[str, int]:
    descendants: dict[str, set[str]] = defaultdict(set)
    for node_id in reversed(order):
        for dependent in adjacency[node_id]:
            descendants[node_id].add(dependent)
            descendants[node_id].update(descendants[dependent])
    return {node_id: len(descendants[node_id]) for node_id in order}


def _find_cycle(adjacency: dict[str, set[str]], candidates: set[str]) -> tuple[str, ...]:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node_id: str) -> tuple[str, ...] | None:
        state[node_id] = 1
        stack.append(node_id)
        for dependent in sorted(adjacency[node_id]):
            if dependent not in candidates:
                continue
            if state.get(dependent, 0) == 0:
                cycle = visit(dependent)
                if cycle is not None:
                    return cycle
            elif state[dependent] == 1:
                start = stack.index(dependent)
                return (*stack[start:], dependent)
        stack.pop()
        state[node_id] = 2
        return None

    for node_id in sorted(candidates):
        if state.get(node_id, 0) == 0:
            cycle = visit(node_id)
            if cycle is not None:
                return cycle
    return tuple(sorted(candidates))
