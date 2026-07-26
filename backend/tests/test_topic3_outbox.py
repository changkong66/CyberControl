from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from liyans_contracts.topic3 import GenerationSessionState

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, current_tenant, tenant_scope
from liyans.domains.topic3.outbox import (
    DurableOutboxSSEBridge,
    Topic3WorkflowOutboxConsumer,
    Topic3WorkflowRecoveryCoordinator,
)
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker
from liyans.infrastructure.tasks.queue import TaskPriority, TaskRequest, TaskResult


class StubOrchestrator:
    def __init__(self) -> None:
        self.queued: list[tuple[UUID, TenantContext]] = []

    def queue_request(self, session_id: UUID, context: TenantContext) -> TaskRequest:
        self.queued.append((session_id, context))
        return TaskRequest(
            task_type="topic3.execute-workflow",
            tenant_id=context.tenant_id,
            task_id=uuid4(),
            payload={"generation_session_id": str(session_id)},
            priority=TaskPriority.NORMAL,
        )


class StubCoordinator:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.accepted: list[tuple[UUID, TenantContext]] = []

    async def accept(self, session_id: UUID, tenant: TenantContext) -> bool:
        if self.error is not None:
            raise self.error
        self.accepted.append((session_id, tenant))
        return True


def context() -> TenantContext:
    return TenantContext(
        tenant_id="tenant-a",
        subject_ref="subject:test",
        roles=frozenset({"system:outbox-dispatcher"}),
        scopes=frozenset({"topic3:dispatch"}),
        trace_id="a" * 32,
    )


@pytest.mark.asyncio
async def test_workflow_outbox_consumer_hands_off_to_durable_coordinator(make_envelope) -> None:
    session_id = uuid4()
    coordinator = StubCoordinator()
    envelope = make_envelope(
        0,
        event_type="topic3.workflow.created",
        payload={"generation_session_id": str(session_id)},
    )
    with tenant_scope(context()):
        await Topic3WorkflowOutboxConsumer(coordinator)(envelope)

    assert coordinator.accepted[0][0] == session_id
    assert coordinator.accepted[0][1].tenant_id == envelope.tenant_id


@pytest.mark.asyncio
async def test_workflow_outbox_consumer_propagates_failed_durable_acceptance(
    make_envelope,
) -> None:
    error = LiyanError(
        ErrorCode.TOPIC3_GENERATION_FAILED,
        "The durable Topic 3 workflow was not accepted.",
        category=ErrorCategory.TASK,
        retriable=True,
        status_code=503,
    )
    consumer = Topic3WorkflowOutboxConsumer(StubCoordinator(error))
    envelope = make_envelope(
        0,
        event_type="topic3.workflow.created",
        payload={"generation_session_id": str(uuid4())},
    )
    with tenant_scope(context()), pytest.raises(LiyanError) as raised:
        await consumer(envelope)
    assert raised.value.code == ErrorCode.TOPIC3_GENERATION_FAILED
    assert raised.value.retriable is True


@pytest.mark.asyncio
async def test_workflow_outbox_consumer_rejects_unexpected_or_invalid_events(
    make_envelope,
) -> None:
    consumer = Topic3WorkflowOutboxConsumer(StubCoordinator())
    unexpected = make_envelope(
        0,
        event_type="topic3.agent-task.started",
        payload={"generation_session_id": str(uuid4())},
    )
    invalid = make_envelope(
        1,
        event_type="topic3.workflow.created",
        payload={"generation_session_id": "not-a-uuid"},
    )

    with (
        tenant_scope(context()),
        pytest.raises(
            ValueError,
            match="unexpected Topic 3 workflow event",
        ),
    ):
        await consumer(unexpected)
    with tenant_scope(context()), pytest.raises(LiyanError) as raised:
        await consumer(invalid)

    assert raised.value.code == ErrorCode.CONTRACT_INVALID
    assert raised.value.category == ErrorCategory.CONTRACT
    assert raised.value.status_code == 422


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"reconciliation_interval_seconds": 0.0}, "interval must be positive"),
        ({"tenant_page_size": 0}, "tenant page size"),
        ({"tenant_page_size": 1001}, "tenant page size"),
        ({"workflow_batch_size": 0}, "workflow batch size"),
        ({"workflow_batch_size": 1001}, "workflow batch size"),
    ],
)
def test_workflow_coordinator_rejects_invalid_recovery_bounds(
    kwargs: dict[str, float | int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Topic3WorkflowRecoveryCoordinator(
            SimpleNamespace(),
            PostgresTopic3Repository(),
            SimpleNamespace(),
            StubOrchestrator(),
            SimpleNamespace(),
            SimpleNamespace(),
            **kwargs,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 1001])
async def test_recoverable_workflow_query_rejects_unbounded_limits(limit: int) -> None:
    repository = PostgresTopic3Repository()

    with tenant_scope(context()), pytest.raises(ValueError, match="between one and 1000"):
        await repository.list_recoverable_generation_sessions(
            SimpleNamespace(),
            context().tenant_id,
            limit=limit,
        )


@pytest.mark.asyncio
async def test_workflow_coordinator_returns_after_persist_and_queue_acceptance() -> None:
    class StubService:
        async def start_workflow(self, _session_id: UUID):
            return SimpleNamespace(state=GenerationSessionState.RUNNING)

    class AcceptingQueue:
        def __init__(self) -> None:
            self.future: asyncio.Future[TaskResult] | None = None

        async def enqueue(self, request: TaskRequest) -> asyncio.Future[TaskResult]:
            self.future = asyncio.get_running_loop().create_future()
            self.request = request
            return self.future

    class EmptyCatalog:
        async def list_tenant_ids(self, **_kwargs) -> list[str]:
            return []

    queue = AcceptingQueue()
    orchestrator = StubOrchestrator()
    coordinator = Topic3WorkflowRecoveryCoordinator(
        SimpleNamespace(),
        PostgresTopic3Repository(),
        StubService(),
        orchestrator,
        queue,
        EmptyCatalog(),
    )
    session_id = uuid4()

    assert await coordinator.accept(session_id, context()) is True
    assert coordinator.active_count == 1
    assert queue.future is not None and not queue.future.done()
    assert queue.request.task_type == "topic3.execute-workflow"

    queue.future.set_result(
        TaskResult(
            task_id=queue.request.task_id,
            succeeded=True,
            attempts=1,
            output={},
            error_code=None,
            completed_at=datetime.now(UTC),
        )
    )
    for _attempt in range(100):
        if coordinator.active_count == 0:
            break
        await asyncio.sleep(0)
    assert coordinator.active_count == 0


@pytest.mark.asyncio
async def test_workflow_coordinator_does_not_reschedule_terminal_or_active_work() -> None:
    class StubService:
        def __init__(self) -> None:
            self.state = GenerationSessionState.RUNNING

        async def start_workflow(self, _session_id: UUID):
            return SimpleNamespace(state=self.state)

    class AcceptingQueue:
        def __init__(self) -> None:
            self.requests: list[TaskRequest] = []
            self.futures: list[asyncio.Future[TaskResult]] = []

        async def enqueue(self, request: TaskRequest) -> asyncio.Future[TaskResult]:
            self.requests.append(request)
            future: asyncio.Future[TaskResult] = asyncio.get_running_loop().create_future()
            self.futures.append(future)
            return future

    class EmptyCatalog:
        async def list_tenant_ids(self, **_kwargs) -> list[str]:
            return []

    service = StubService()
    queue = AcceptingQueue()
    coordinator = Topic3WorkflowRecoveryCoordinator(
        SimpleNamespace(),
        PostgresTopic3Repository(),
        service,
        StubOrchestrator(),
        queue,
        EmptyCatalog(),
    )
    session_id = uuid4()

    assert await coordinator.accept(session_id, context()) is True
    assert await coordinator.accept(session_id, context()) is False
    assert len(queue.requests) == 1

    service.state = GenerationSessionState.COMPLETED
    assert await coordinator.accept(uuid4(), context()) is False
    assert len(queue.requests) == 1
    await coordinator.close()


@pytest.mark.asyncio
async def test_workflow_coordinator_backs_off_failed_execution_without_losing_recovery() -> None:
    class StubService:
        async def start_workflow(self, _session_id: UUID):
            return SimpleNamespace(state=GenerationSessionState.RUNNING)

    class AcceptingQueue:
        async def enqueue(self, request: TaskRequest) -> asyncio.Future[TaskResult]:
            self.request = request
            self.future: asyncio.Future[TaskResult] = asyncio.get_running_loop().create_future()
            return self.future

    class EmptyCatalog:
        async def list_tenant_ids(self, **_kwargs) -> list[str]:
            return []

    class Metrics:
        def __init__(self) -> None:
            self.outcomes: list[tuple[str, str, int]] = []
            self.gauges: dict[str, int] = {}

        def observe_outbox(self, operation: str, outcome: str, count: int = 1) -> None:
            self.outcomes.append((operation, outcome, count))

        def set_outbox_gauge(self, metric: str, value: int) -> None:
            self.gauges[metric] = value

    queue = AcceptingQueue()
    metrics = Metrics()
    coordinator = Topic3WorkflowRecoveryCoordinator(
        SimpleNamespace(),
        PostgresTopic3Repository(),
        StubService(),
        StubOrchestrator(),
        queue,
        EmptyCatalog(),
        metrics=metrics,
    )
    session_id = uuid4()
    assert await coordinator.accept(session_id, context()) is True
    queue.future.set_result(
        TaskResult(
            task_id=queue.request.task_id,
            succeeded=False,
            attempts=2,
            output=None,
            error_code=ErrorCode.TASK_FAILED.value,
            completed_at=datetime.now(UTC),
        )
    )
    for _attempt in range(100):
        if coordinator.active_count == 0:
            break
        await asyncio.sleep(0)

    assert coordinator.active_count == 0
    assert await coordinator.accept(session_id, context()) is False
    assert ("topic3_workflow", "execution_retry", 1) in metrics.outcomes
    assert metrics.gauges["topic3_workflow_in_flight"] == 0
    await coordinator.close()


@pytest.mark.asyncio
async def test_workflow_coordinator_recovers_from_observer_and_scan_failures() -> None:
    class StubService:
        async def start_workflow(self, _session_id: UUID):
            return SimpleNamespace(state=GenerationSessionState.RUNNING)

    class AcceptingQueue:
        async def enqueue(self, request: TaskRequest) -> asyncio.Future[TaskResult]:
            self.request = request
            self.future: asyncio.Future[TaskResult] = asyncio.get_running_loop().create_future()
            return self.future

    class FailingAfterReadinessCatalog:
        def __init__(self) -> None:
            self.calls = 0

        async def list_tenant_ids(self, **_kwargs) -> list[str]:
            self.calls += 1
            if self.calls == 1:
                return []
            raise RuntimeError("transient catalog failure")

    class Metrics:
        def __init__(self) -> None:
            self.outcomes: list[tuple[str, str, int]] = []

        def observe_outbox(self, operation: str, outcome: str, count: int = 1) -> None:
            self.outcomes.append((operation, outcome, count))

        def set_outbox_gauge(self, _metric: str, _value: int) -> None:
            return None

    queue = AcceptingQueue()
    catalog = FailingAfterReadinessCatalog()
    metrics = Metrics()
    coordinator = Topic3WorkflowRecoveryCoordinator(
        SimpleNamespace(),
        PostgresTopic3Repository(),
        StubService(),
        StubOrchestrator(),
        queue,
        catalog,
        reconciliation_interval_seconds=0.01,
        metrics=metrics,
    )

    await coordinator.start()
    session_id = uuid4()
    assert await coordinator.accept(session_id, context()) is True
    queue.future.set_exception(RuntimeError("observer lost task result"))

    for _attempt in range(100):
        if coordinator.last_error == "RuntimeError" and coordinator.active_count == 0:
            break
        await asyncio.sleep(0.001)

    assert coordinator.last_error == "RuntimeError"
    assert coordinator.active_count == 0
    assert await coordinator.accept(session_id, context()) is False
    assert ("topic3_workflow", "execution_observer_failed", 1) in metrics.outcomes
    assert ("topic3_workflow", "scan_failed", 1) in metrics.outcomes
    await coordinator.close()


@pytest.mark.asyncio
async def test_workflow_coordinator_pages_tenants_under_normal_tenant_context() -> None:
    tenant_ids = ["tenant-a", "tenant-b"]

    class FakeDatabase:
        @asynccontextmanager
        async def transaction(self, **_kwargs):
            yield object()

    class FakeRepository:
        def __init__(self) -> None:
            self.seen: list[str] = []

        async def list_recoverable_generation_sessions(
            self,
            _session,
            tenant_id: str,
            *,
            limit: int,
        ):
            assert limit == 1
            assert tenant_id == current_tenant().tenant_id
            self.seen.append(tenant_id)
            return [SimpleNamespace(generation_session_id=uuid4())]

    class PagedCatalog:
        async def list_tenant_ids(
            self,
            *,
            event_type: str,
            after_tenant_id: str | None,
            limit: int,
        ) -> list[str]:
            assert event_type == "topic3.workflow.created"
            assert limit == 1
            if after_tenant_id is None:
                return [tenant_ids[0]]
            if after_tenant_id == tenant_ids[0]:
                return [tenant_ids[1]]
            return []

    class AcceptingQueue:
        def __init__(self) -> None:
            self.futures: list[asyncio.Future[TaskResult]] = []

        async def enqueue(self, _request: TaskRequest) -> asyncio.Future[TaskResult]:
            future: asyncio.Future[TaskResult] = asyncio.get_running_loop().create_future()
            self.futures.append(future)
            return future

    repository = FakeRepository()
    coordinator = Topic3WorkflowRecoveryCoordinator(
        FakeDatabase(),
        repository,
        SimpleNamespace(),
        StubOrchestrator(),
        AcceptingQueue(),
        PagedCatalog(),
        tenant_page_size=1,
        workflow_batch_size=1,
    )

    assert await coordinator.reconcile_once() == 2
    assert repository.seen == tenant_ids
    assert coordinator.active_count == 2
    await coordinator.close()


@pytest.mark.asyncio
async def test_workflow_coordinator_start_and_close_are_idempotent() -> None:
    class EmptyCatalog:
        async def list_tenant_ids(self, **_kwargs) -> list[str]:
            return []

    coordinator = Topic3WorkflowRecoveryCoordinator(
        SimpleNamespace(),
        PostgresTopic3Repository(),
        SimpleNamespace(),
        StubOrchestrator(),
        SimpleNamespace(),
        EmptyCatalog(),
        reconciliation_interval_seconds=0.001,
    )
    await coordinator.start()
    await coordinator.start()
    assert coordinator.running is True
    assert coordinator.last_error is None
    await coordinator.close()
    await coordinator.close()
    assert coordinator.running is False


@pytest.mark.asyncio
async def test_outbox_sse_bridge_removes_large_candidate_and_chunk_bodies(make_envelope) -> None:
    replay = InMemorySSEReplayLog()
    bridge = DurableOutboxSSEBridge(SSEBroker(replay))
    stream_id = uuid4()
    envelope = make_envelope(
        3,
        event_type="topic3.agent-task.completed",
        payload={
            "candidate": {
                "candidate_id": str(uuid4()),
                "candidate_version": 1,
                "candidate_sha256": "a" * 64,
                "resource_type": "Lecturer_Doc",
                "status": "COMPLETE",
                "blocks": [{"content": "x" * 100_000}],
            },
            "stream_chunks": [
                {
                    "stream_id": str(stream_id),
                    "fragment_id": str(uuid4()),
                    "data": "x" * 64_000,
                }
            ],
        },
    )
    with tenant_scope(context()):
        await bridge(envelope)
    event = (await replay.replay("tenant-a", None))[0]

    assert event.data["envelope_id"] == str(envelope.envelope_id)
    assert "blocks" not in event.data["payload"]["candidate"]
    assert event.data["payload"]["stream_replay"] == {
        "chunk_count": 1,
        "stream_ids": [str(stream_id)],
        "endpoint_template": "/internal/topic3/streams/{stream_id}/chunks",
    }
