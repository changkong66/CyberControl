from __future__ import annotations

from typing import Any
from uuid import UUID

from liyans_contracts.envelope import Topic3EnvelopeV1

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import current_tenant
from liyans.infrastructure.streaming.sse import SSEBroker
from liyans.infrastructure.tasks.queue import AsyncTaskQueue

from .orchestrator import Topic3Orchestrator

DOMAIN_OUTBOX_EVENT_TYPES = (
    "topic1.graph.changed",
    "topic2.behavior.recorded",
    "topic2.learner.initialized",
    "topic2.memory.updated",
    "topic2.path.updated",
    "topic2.profile.updated",
    "topic3.workflow.created",
    "topic3.workflow.started",
    "topic3.agent-task.started",
    "topic3.agent-task.completed",
    "topic3.agent-task.failed",
    "topic3.agent-task.skipped",
    "topic3.workflow.finalized",
)


class Topic3WorkflowOutboxConsumer:
    """Turns the durable workflow-created event into an awaited Agent execution."""

    def __init__(self, orchestrator: Topic3Orchestrator, queue: AsyncTaskQueue) -> None:
        self._orchestrator = orchestrator
        self._queue = queue

    async def __call__(self, envelope: Topic3EnvelopeV1) -> None:
        if envelope.event_type != "topic3.workflow.created":
            raise ValueError("unexpected Topic 3 workflow event")
        raw_session_id = envelope.payload.get("generation_session_id")
        try:
            generation_session_id = UUID(str(raw_session_id))
        except (TypeError, ValueError) as exc:
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "The durable Topic 3 workflow event has no valid generation session ID.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            ) from exc
        result = await self._queue.submit(
            self._orchestrator.queue_request(generation_session_id, current_tenant())
        )
        if not result.succeeded:
            raise LiyanError(
                ErrorCode.TOPIC3_GENERATION_FAILED,
                "The durable Topic 3 workflow execution did not complete.",
                category=ErrorCategory.TASK,
                retriable=True,
                status_code=503,
                details={"task_error_code": result.error_code},
            )


class DurableOutboxSSEBridge:
    """Publishes a bounded, replayable projection of every committed domain event."""

    def __init__(self, broker: SSEBroker) -> None:
        self._broker = broker

    async def __call__(self, envelope: Topic3EnvelopeV1) -> None:
        await self._broker.publish(
            envelope.tenant_id,
            envelope.event_type,
            {
                "schema_version": "outbox.sse-relay.v1",
                "envelope_id": str(envelope.envelope_id),
                "correlation_id": str(envelope.correlation_id),
                "subject_ref": envelope.subject_ref,
                "partition_key": envelope.partition_key,
                "partition_sequence": envelope.sequence,
                "created_at": envelope.created_at.isoformat(),
                "payload": self._bounded_payload(envelope.payload),
            },
        )

    @staticmethod
    def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        candidate = result.pop("candidate", None)
        chunks = result.pop("stream_chunks", None)
        if isinstance(candidate, dict):
            result["candidate"] = {
                key: candidate.get(key)
                for key in (
                    "candidate_id",
                    "candidate_version",
                    "candidate_sha256",
                    "resource_type",
                    "status",
                    "personalization_policy_digest",
                )
            }
        if isinstance(chunks, list):
            stream_ids = sorted(
                {
                    str(chunk.get("stream_id"))
                    for chunk in chunks
                    if isinstance(chunk, dict) and chunk.get("stream_id") is not None
                }
            )
            result["stream_replay"] = {
                "chunk_count": len(chunks),
                "stream_ids": stream_ids,
                "endpoint_template": "/internal/topic3/streams/{stream_id}/chunks",
            }
        return result
