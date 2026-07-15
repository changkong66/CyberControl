from __future__ import annotations

import statistics
import time

import pytest
from liyans_contracts.enums import ResourceType
from topic3_support import generation_command, graph_snapshot, personalization_context

from liyans.domains.topic3.agents.base import AgentExecutionContext
from liyans.domains.topic3.agents.mindmap import MindMapAgent
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.streaming import Topic3StreamCoordinator
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker


def percentile(values: list[float], ratio: float) -> float:
    return sorted(values)[min(len(values) - 1, int(len(values) * ratio))]


def test_blueprint_planning_p95_stays_below_local_control_plane_budget() -> None:
    graph = graph_snapshot()
    context = personalization_context(graph)
    command = generation_command()
    planner = ImmutableBlueprintPlanner()
    durations: list[float] = []
    for _ in range(300):
        started = time.perf_counter()
        planner.build(command, graph, context)
        durations.append((time.perf_counter() - started) * 1000)
    assert percentile(durations, 0.95) < 10
    assert statistics.mean(durations) < 5


@pytest.mark.asyncio
async def test_local_mindmap_and_chunking_p95_stay_bounded() -> None:
    graph = graph_snapshot()
    personalization = personalization_context(graph)
    command = generation_command(resources=[ResourceType.MIND_MAP])
    blueprint = ImmutableBlueprintPlanner().build(command, graph, personalization).blueprint
    context = AgentExecutionContext(
        command=command,
        graph=graph,
        personalization=personalization,
        blueprint=blueprint,
        step=blueprint.steps[0],
        attempt=1,
    )
    agent = MindMapAgent()
    coordinator = Topic3StreamCoordinator(
        SSEBroker(InMemorySSEReplayLog()),
        max_chunk_bytes=1024,
    )
    mindmap_durations: list[float] = []
    chunk_durations: list[float] = []
    for _ in range(100):
        started = time.perf_counter()
        outcome = await agent.execute(context)
        mindmap_durations.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        chunks = coordinator.candidate_chunks(outcome.candidate)
        chunk_durations.append((time.perf_counter() - started) * 1000)
        assert chunks
    assert percentile(mindmap_durations, 0.95) < 20
    assert percentile(chunk_durations, 0.95) < 20
