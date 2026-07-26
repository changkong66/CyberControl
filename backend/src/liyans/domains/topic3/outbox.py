from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol
from uuid import UUID, uuid4

from liyans_contracts.envelope import Topic3EnvelopeV1
from liyans_contracts.topic3 import GenerationSessionState

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, current_tenant, tenant_scope
from liyans.infrastructure.database import (
    DatabaseSessionManager,
    session_context_from_tenant,
)
from liyans.infrastructure.streaming.sse import SSEBroker
from liyans.infrastructure.tasks.queue import AsyncTaskQueue, TaskResult

from .orchestrator import Topic3Orchestrator
from .postgres_repository import PostgresTopic3Repository
from .service import Topic3Service

logger = logging.getLogger(__name__)

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


class Topic3WorkflowTenantCatalog(Protocol):
    async def list_tenant_ids(
        self,
        *,
        event_type: str,
        after_tenant_id: str | None,
        limit: int,
    ) -> list[str]: ...


class Topic3WorkflowMetrics(Protocol):
    def observe_outbox(self, operation: str, outcome: str, count: int = 1) -> None: ...

    def set_outbox_gauge(self, metric: str, value: int) -> None: ...


class Topic3WorkflowAcceptor(Protocol):
    async def accept(self, generation_session_id: UUID, context: TenantContext) -> bool: ...


class Topic3WorkflowRecoveryCoordinator:
    """Durably accepts Topic 3 work and reconciles non-terminal sessions.

    PostgreSQL session snapshots are the recovery authority. The in-memory task
    queue is only an execution mechanism, so a process restart cannot silently
    lose a workflow after its Outbox trigger has been acknowledged.
    """

    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: PostgresTopic3Repository,
        service: Topic3Service,
        orchestrator: Topic3Orchestrator,
        queue: AsyncTaskQueue,
        tenant_catalog: Topic3WorkflowTenantCatalog,
        *,
        reconciliation_interval_seconds: float = 5.0,
        tenant_page_size: int = 100,
        workflow_batch_size: int = 128,
        metrics: Topic3WorkflowMetrics | None = None,
    ) -> None:
        if reconciliation_interval_seconds <= 0:
            raise ValueError("reconciliation interval must be positive")
        if not 1 <= tenant_page_size <= 1000:
            raise ValueError("tenant page size must be between one and 1000")
        if not 1 <= workflow_batch_size <= 1000:
            raise ValueError("workflow batch size must be between one and 1000")
        self._database = database
        self._repository = repository
        self._service = service
        self._orchestrator = orchestrator
        self._queue = queue
        self._tenant_catalog = tenant_catalog
        self._interval = reconciliation_interval_seconds
        self._tenant_page_size = tenant_page_size
        self._workflow_batch_size = workflow_batch_size
        self._metrics = metrics
        self._stopping = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._schedule_lock = asyncio.Lock()
        self._executions: dict[tuple[str, UUID], asyncio.Task[None]] = {}
        self._retry_after: dict[tuple[str, UUID], float] = {}
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def active_count(self) -> int:
        return len(self._executions)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        await self.reconcile_once()
        self._task = asyncio.create_task(
            self._run(),
            name="topic3-workflow-reconciler",
        )

    async def close(self) -> None:
        self._stopping.set()
        self._wake.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        observers = list(self._executions.values())
        for observer in observers:
            observer.cancel()
        if observers:
            await asyncio.gather(*observers, return_exceptions=True)
        self._executions.clear()
        self._retry_after.clear()
        self._update_gauge()

    async def accept(self, generation_session_id: UUID, context: TenantContext) -> bool:
        """Persist RUNNING intent before accepting execution into the bounded queue."""

        current = await self._service.start_workflow(generation_session_id)
        if current.state not in {
            GenerationSessionState.PLANNED,
            GenerationSessionState.RUNNING,
        }:
            self._observe("already_terminal")
            return False
        accepted = await self._schedule(generation_session_id, context)
        self._observe("accepted" if accepted else "already_active")
        return accepted

    async def reconcile_once(self) -> int:
        scheduled = 0
        after_tenant_id: str | None = None
        while True:
            tenant_ids = await self._tenant_catalog.list_tenant_ids(
                event_type="topic3.workflow.created",
                after_tenant_id=after_tenant_id,
                limit=self._tenant_page_size,
            )
            if not tenant_ids:
                break
            for tenant_id in tenant_ids:
                scheduled += await self._reconcile_tenant(tenant_id)
            if len(tenant_ids) < self._tenant_page_size:
                break
            after_tenant_id = tenant_ids[-1]
        self._last_error = None
        self._observe("scan_completed")
        return scheduled

    async def _reconcile_tenant(self, tenant_id: str) -> int:
        context = TenantContext(
            tenant_id=tenant_id,
            subject_ref="system:topic3-workflow-reconciler",
            roles=frozenset({"topic3-worker"}),
            scopes=frozenset({"topic3:admin", "topic3:learner:any"}),
            trace_id=uuid4().hex,
        )
        with tenant_scope(context):
            async with self._database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                recoverable = await self._repository.list_recoverable_generation_sessions(
                    session,
                    tenant_id,
                    limit=self._workflow_batch_size,
                )
        scheduled = 0
        for record in recoverable:
            if await self._schedule(record.generation_session_id, context):
                scheduled += 1
        if scheduled:
            self._observe("recovered", scheduled)
        return scheduled

    async def _schedule(
        self,
        generation_session_id: UUID,
        context: TenantContext,
    ) -> bool:
        key = (context.tenant_id, generation_session_id)
        now = asyncio.get_running_loop().time()
        async with self._schedule_lock:
            current = self._executions.get(key)
            if current is not None and not current.done():
                return False
            if self._retry_after.get(key, 0.0) > now:
                return False
            future = await self._queue.enqueue(
                self._orchestrator.queue_request(generation_session_id, context)
            )
            observer = asyncio.create_task(
                self._observe_execution(key, future),
                name="topic3-workflow-execution",
            )
            self._executions[key] = observer
            self._retry_after.pop(key, None)
            self._update_gauge()
        return True

    async def _observe_execution(
        self,
        key: tuple[str, UUID],
        future: asyncio.Future[TaskResult],
    ) -> None:
        try:
            result = await future
            if result.succeeded:
                self._observe("execution_succeeded")
                return
            delay = min(30.0, float(2 ** min(5, max(0, result.attempts))))
            self._retry_after[key] = asyncio.get_running_loop().time() + delay
            self._observe("execution_retry")
            self._wake.set()
            logger.warning(
                "Topic 3 durable workflow execution requires reconciliation error_code=%s",
                result.error_code or ErrorCode.TASK_FAILED.value,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._retry_after[key] = asyncio.get_running_loop().time() + 1.0
            self._observe("execution_observer_failed")
            self._wake.set()
            logger.warning(
                "Topic 3 durable workflow observer failed error=%s",
                type(exc).__name__,
            )
        finally:
            async with self._schedule_lock:
                if self._executions.get(key) is asyncio.current_task():
                    self._executions.pop(key, None)
                self._update_gauge()

    async def _run(self) -> None:
        while not self._stopping.is_set():
            self._wake.clear()
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = type(exc).__name__
                self._observe("scan_failed")
                logger.exception("Topic 3 workflow reconciliation scan failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except TimeoutError:
                continue

    def _observe(self, outcome: str, count: int = 1) -> None:
        if self._metrics is not None and count > 0:
            self._metrics.observe_outbox("topic3_workflow", outcome, count)

    def _update_gauge(self) -> None:
        if self._metrics is not None:
            self._metrics.set_outbox_gauge(
                "topic3_workflow_in_flight",
                len(self._executions),
            )


class Topic3WorkflowOutboxConsumer:
    """Durably hands a workflow trigger to the recoverable execution coordinator."""

    def __init__(self, coordinator: Topic3WorkflowAcceptor) -> None:
        self._coordinator = coordinator

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
        await self._coordinator.accept(generation_session_id, current_tenant())


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
