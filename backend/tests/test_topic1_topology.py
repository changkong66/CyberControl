from dataclasses import dataclass

import pytest
from liyans_contracts.topic1 import (
    CourseStatus,
    KnowledgePointStatus,
    Topic1CourseV1,
    Topic1GraphContentV1,
    Topic1KnowledgePointV1,
)

from liyans.domains.topic1.topology import (
    TopologyCycleError,
    TopologyEdge,
    analyze_topology,
    classify_difficulty,
    rank_misconceptions,
)


@dataclass(frozen=True, slots=True)
class Candidate:
    misconception_id: str
    diagnosis_tags: list[str]


def test_topology_levels_and_weights_are_deterministic() -> None:
    metrics = analyze_topology(
        {"model", "transfer", "response", "stability"},
        [
            TopologyEdge("model", "transfer"),
            TopologyEdge("transfer", "response"),
            TopologyEdge("transfer", "stability"),
        ],
    )
    assert metrics.topological_order == ("model", "transfer", "response", "stability")
    assert metrics.levels == {"model": 0, "transfer": 1, "response": 2, "stability": 2}
    assert metrics.descendant_counts["model"] == 3
    assert metrics.weights["transfer"] > metrics.weights["model"]
    assert metrics.weights["model"] > metrics.weights["response"]


def test_topology_reports_explicit_cycle() -> None:
    with pytest.raises(TopologyCycleError) as error:
        analyze_topology(
            {"a", "b", "c"},
            [TopologyEdge("a", "b"), TopologyEdge("b", "c"), TopologyEdge("c", "a")],
        )
    assert error.value.cycle[0] == error.value.cycle[-1]
    assert set(error.value.cycle[:-1]) == {"a", "b", "c"}


def test_topology_rejects_unknown_endpoint() -> None:
    with pytest.raises(ValueError, match="unknown"):
        analyze_topology({"a"}, [TopologyEdge("a", "missing")])


def test_single_node_receives_full_weight() -> None:
    metrics = analyze_topology({"only"}, [])
    assert metrics.weights == {"only": 1.0}
    assert metrics.levels == {"only": 0}


def test_difficulty_classifier_combines_declared_and_structural_features() -> None:
    simple = classify_difficulty(
        declared_score=0.1,
        prerequisite_count=0,
        formula_count=0,
        objective_count=1,
        estimated_minutes=30,
    )
    hard = classify_difficulty(
        declared_score=0.9,
        prerequisite_count=5,
        formula_count=8,
        objective_count=6,
        estimated_minutes=240,
    )
    assert 1 <= simple.level < hard.level <= 5
    assert simple.score < hard.score
    assert hard.structural_score == 1.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"declared_score": 2.0}, "declared_score"),
        ({"prerequisite_count": -1}, "cannot be negative"),
        ({"estimated_minutes": 0}, "cannot be negative"),
    ],
)
def test_difficulty_classifier_rejects_invalid_features(kwargs, message) -> None:
    values = {
        "declared_score": 0.5,
        "prerequisite_count": 1,
        "formula_count": 1,
        "objective_count": 1,
        "estimated_minutes": 60,
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        classify_difficulty(**values)


def test_misconception_ranking_normalizes_tags_and_breaks_ties_by_id() -> None:
    ranked = rank_misconceptions(
        {"Sign_Error", "Routh Array"},
        [
            Candidate("MIS_B", ["sign-error"]),
            Candidate("MIS_A", ["sign error"]),
            Candidate("MIS_C", ["unrelated"]),
        ],
    )
    assert ranked == ("MIS_A", "MIS_B")


def test_content_normalization_preserves_declared_difficulty_score() -> None:
    from datetime import UTC, datetime

    from liyans.domains.topic1.service import Topic1Service

    now = datetime.now(UTC)
    content = Topic1GraphContentV1(
        course=Topic1CourseV1(
            course_id="CRS_ATC_001",
            revision=1,
            course_code="ATC101",
            title="Automatic Control Principles",
            description="Authoritative automatic-control knowledge topology.",
            credit_hours=64,
            status=CourseStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        ),
        knowledge_points=[
            Topic1KnowledgePointV1(
                kp_id="KP_ATC_301_TRANSFER_FUNCTION",
                course_id="CRS_ATC_001",
                revision=1,
                title="Transfer Function",
                summary="Input-output representation in the Laplace domain.",
                learning_objectives=["Derive transfer functions from differential equations."],
                category="MODELING",
                difficulty_level=1,
                difficulty_score=0.4,
                topology_level=0,
                topology_weight=0,
                estimated_minutes=90,
                formula_signatures=["G(s)=Y(s)/U(s)"],
                status=KnowledgePointStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
        ],
        prerequisites=[],
    )

    first = Topic1Service._normalize_content(content, now)
    second = Topic1Service._normalize_content(first, now)

    assert first.knowledge_points[0].difficulty_score == 0.4
    assert second.knowledge_points[0].difficulty_score == 0.4
    assert second.knowledge_points[0].difficulty_level == first.knowledge_points[0].difficulty_level
    assert second.knowledge_points[0].revision == first.knowledge_points[0].revision
