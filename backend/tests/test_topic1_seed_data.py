import json
from pathlib import Path

from liyans_contracts.topic1 import Topic1ImportBundleV1

from liyans.domains.topic1.topology import TopologyEdge, analyze_topology


def test_automatic_control_seed_is_contract_valid_and_acyclic() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    document = json.loads(
        (repository_root / "data/topic1/automatic-control-principles.v1.json").read_text(
            encoding="utf-8"
        )
    )
    bundle = Topic1ImportBundleV1.model_validate(document)
    content = bundle.content
    metrics = analyze_topology(
        {item.kp_id for item in content.knowledge_points},
        [
            TopologyEdge(item.prerequisite_kp_id, item.dependent_kp_id)
            for item in content.prerequisites
        ],
    )

    assert content.course.course_id == "CRS_ATC_001"
    assert len(content.knowledge_points) == 13
    assert len(content.prerequisites) == 15
    assert len(content.misconceptions) == 5
    assert len(content.golden_questions) == 5
    assert len(metrics.topological_order) == len(content.knowledge_points)
    assert metrics.levels["KP_ATC_802_CONTROLLABILITY_OBSERVABILITY"] > 0
