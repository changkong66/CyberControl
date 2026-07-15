from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.topic3.outbox import DurableOutboxSSEBridge, Topic3WorkflowOutboxConsumer
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


class StubQueue:
    def __init__(self, *, succeeded: bool = True) -> None:
        self.succeeded = succeeded
        self.requests: list[TaskRequest] = []

    async def submit(self, request: TaskRequest) -> TaskResult:
        self.requests.append(request)
        return TaskResult(
            task_id=request.task_id,
            succeeded=self.succeeded,
            attempts=1,
            output={} if self.succeeded else None,
            error_code=None if self.succeeded else "LIYAN-TASK-FAILED",
            completed_at=datetime.now(UTC),
        )


def context() -> TenantContext:
    return TenantContext(
        tenant_id="tenant-a",
        subject_ref="subject:test",
        roles=frozenset({"system:outbox-dispatcher"}),
        scopes=frozenset({"topic3:dispatch"}),
        trace_id="a" * 32,
    )


@pytest.mark.asyncio
async def test_workflow_outbox_consumer_awaits_the_durable_task(make_envelope) -> None:
    session_id = uuid4()
    orchestrator = StubOrchestrator()
    queue = StubQueue()
    envelope = make_envelope(
        0,
        event_type="topic3.workflow.created",
        payload={"generation_session_id": str(session_id)},
    )
    with tenant_scope(context()):
        await Topic3WorkflowOutboxConsumer(orchestrator, queue)(envelope)

    assert orchestrator.queued[0][0] == session_id
    assert orchestrator.queued[0][1].tenant_id == envelope.tenant_id
    assert queue.requests[0].task_type == "topic3.execute-workflow"


@pytest.mark.asyncio
async def test_workflow_outbox_consumer_retries_failed_queue_execution(make_envelope) -> None:
    consumer = Topic3WorkflowOutboxConsumer(StubOrchestrator(), StubQueue(succeeded=False))
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
