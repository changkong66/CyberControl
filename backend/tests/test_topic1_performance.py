from time import perf_counter

from liyans.domains.topic1.topology import TopologyEdge, analyze_topology


def test_topic1_maximum_import_topology_analysis_completes_within_baseline() -> None:
    node_ids = {f"KP_ATC_PERF_{index:04d}" for index in range(500)}
    ordered = sorted(node_ids)
    edges = [
        TopologyEdge(ordered[source], ordered[target])
        for source in range(len(ordered))
        for target in range(source + 1, min(len(ordered), source + 6))
    ]

    started = perf_counter()
    metrics = analyze_topology(node_ids, edges)
    elapsed_seconds = perf_counter() - started

    assert len(edges) == 2485
    assert len(metrics.topological_order) == 500
    assert metrics.levels[ordered[-1]] == 499
    assert elapsed_seconds < 5.0
