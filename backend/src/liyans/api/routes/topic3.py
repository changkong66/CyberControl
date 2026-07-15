from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic3 import Topic3GenerationCommandV1

from liyans.api.auth import require_scopes
from liyans.core.errors import ContractError, ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant, current_tenant, tenant_scope
from liyans.domains.generation.compatibility import CompatibilityError, Topic3EnvelopeAdapter
from liyans.domains.topic3.orchestrator import Topic3Orchestrator
from liyans.domains.topic3.service import Topic3Service
from liyans.infrastructure.streaming.sse import encode_sse_frame
from liyans.infrastructure.tasks.queue import AsyncTaskQueue

router = APIRouter(prefix="/internal/topic3", tags=["topic3"])
adapter = Topic3EnvelopeAdapter()
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=160)]


def topic3_orchestrator(request: Request) -> Topic3Orchestrator:
    value = getattr(request.app.state, "topic3_orchestrator", None)
    if value is None:
        raise _unavailable()
    return cast(Topic3Orchestrator, value)


def topic3_service(request: Request) -> Topic3Service:
    value = getattr(request.app.state, "topic3_service", None)
    if value is None:
        raise _unavailable()
    return cast(Topic3Service, value)


def task_queue(request: Request) -> AsyncTaskQueue:
    value = getattr(request.app.state, "task_queue", None)
    if value is None:
        raise _unavailable()
    return cast(AsyncTaskQueue, value)


def response_envelope(
    request: Request,
    event_type: str,
    payload: dict[str, Any],
    *,
    session_id: UUID | None = None,
) -> dict[str, Any]:
    context = current_tenant()
    now = datetime.now(UTC)
    request_id = uuid4()
    correlation_id = session_id or uuid4()
    envelope = Topic3EnvelopeV1(
        envelope_id=request_id,
        event_type=event_type,
        message_kind=MessageKind.RESULT,
        tenant_id=context.tenant_id,
        session_id=context.session_id or correlation_id,
        subject_ref=context.subject_ref,
        correlation_id=correlation_id,
        causation_id=None,
        sequence=0,
        partition_key=f"topic3:api:{context.tenant_id}:{request.state.trace_id}",
        producer=ProducerMetadataV1(
            agent=None,
            service="topic3-api",
            instance_id="request-handler",
            build_version="topic3-v1",
        ),
        delivery=DeliveryMetadataV1(
            idempotency_key=f"api:{request_id.hex}",
            available_at=now,
            expires_at=now + timedelta(minutes=5),
        ),
        resource=None,
        trace_id=request.state.trace_id,
        span_id=None,
        created_at=now,
        error=None,
        payload=payload,
    )
    return envelope.model_dump(mode="json")


@router.post(
    "/generations",
    response_model=Topic3EnvelopeV1,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scopes("topic3:generation:write"))],
)
async def create_generation(
    request: Request,
    body: Topic3GenerationCommandV1,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    orchestrator = topic3_orchestrator(request)
    prepared = await orchestrator.prepare(body, idempotency_key=idempotency_key)
    publisher = getattr(request.app.state, "outbox_publisher", None)
    dispatch_mode = "DURABLE_OUTBOX"
    if publisher is None:
        await task_queue(request).enqueue(
            orchestrator.queue_request(body.generation_session_id, current_tenant())
        )
        dispatch_mode = "LOCAL_QUEUE"
    return response_envelope(
        request,
        "topic3.api.generation.accepted",
        {
            **prepared,
            "execution_state": prepared.get("state", "PLANNED"),
            "dispatch_mode": dispatch_mode,
            "stream_endpoint": "/internal/topic3/sse/stream",
        },
        session_id=body.generation_session_id,
    )


@router.post(
    "/generations/{generation_session_id}/execute",
    response_model=Topic3EnvelopeV1,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scopes("topic3:generation:retry"))],
)
async def retry_generation(
    request: Request,
    generation_session_id: UUID,
) -> dict[str, Any]:
    orchestrator = topic3_orchestrator(request)
    await topic3_service(request).load_runtime(generation_session_id)
    await task_queue(request).enqueue(
        orchestrator.queue_request(generation_session_id, current_tenant())
    )
    return response_envelope(
        request,
        "topic3.api.generation.requeued",
        {
            "generation_session_id": str(generation_session_id),
            "execution_state": "QUEUED",
        },
        session_id=generation_session_id,
    )


@router.get(
    "/generations/{generation_session_id}",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic3:generation:read"))],
)
async def get_generation(
    request: Request,
    generation_session_id: UUID,
) -> dict[str, Any]:
    current, _, _, blueprint, tasks, candidates = await topic3_service(request).load_runtime(
        generation_session_id
    )
    return response_envelope(
        request,
        "topic3.api.generation.result",
        {
            "session": Topic3Service.session_document(current),
            "blueprint": blueprint.blueprint.model_dump(mode="json"),
            "tasks": [Topic3Service.task_document(task) for task in tasks],
            "candidates": [record.candidate.model_dump(mode="json") for record in candidates],
        },
        session_id=generation_session_id,
    )


@router.get(
    "/learners/{learner_ref}/courses/{course_id}/generations",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic3:generation:read"))],
)
async def list_generations(
    request: Request,
    learner_ref: str,
    course_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    records = await topic3_service(request).list_workflows(
        learner_ref,
        course_id,
        limit=limit,
    )
    return response_envelope(
        request,
        "topic3.api.generation-history.result",
        {"sessions": [Topic3Service.session_document(record) for record in records]},
    )


@router.get(
    "/streams/{stream_id}/chunks",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic3:sse:read"))],
)
async def list_persisted_chunks(
    request: Request,
    stream_id: UUID,
    after_index: int | None = Query(default=None, ge=-1),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> dict[str, Any]:
    chunks = await topic3_service(request).list_stream_chunks(
        stream_id,
        after_index=after_index,
        limit=limit,
    )
    return response_envelope(
        request,
        "topic3.api.stream-chunks.result",
        {
            "stream_id": str(stream_id),
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
        },
    )


@router.post(
    "/envelopes/validate",
    dependencies=[Depends(require_scopes("topic3:validate"))],
)
async def validate_envelope(body: dict[str, Any]) -> dict[str, Any]:
    try:
        envelope = Topic3EnvelopeV1.model_validate(body)
    except Exception as exc:
        raise ContractError("The Topic 3 Envelope is invalid.") from exc
    assert_tenant(envelope.tenant_id)
    return {"envelope": envelope.model_dump(mode="json"), "warnings": []}


@router.post(
    "/envelopes/adapt",
    dependencies=[Depends(require_scopes("topic3:validate"))],
)
async def adapt_envelope(body: dict[str, Any]) -> dict[str, Any]:
    try:
        result = adapter.adapt(body)
    except CompatibilityError as exc:
        raise ContractError(str(exc)) from exc
    assert_tenant(result.envelope.tenant_id)
    return {
        "envelope": result.envelope.model_dump(mode="json"),
        "warnings": [
            {"code": warning.code, "field": warning.field, "message": warning.message}
            for warning in result.warnings
        ],
    }


@router.post(
    "/sse/events",
    dependencies=[Depends(require_scopes("topic3:sse:publish"))],
)
async def publish_sse_event(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    context = current_tenant()
    event_type = str(body.get("event_type", "")).strip()
    data = body.get("data")
    if not event_type or not isinstance(data, dict):
        raise ContractError("event_type and object data are required")
    event = await request.app.state.sse_broker.publish(context.tenant_id, event_type, data)
    cursor = request.app.state.sse_cursor_codec.encode(context.tenant_id, event.sequence)
    return {"cursor": cursor, "sequence": event.sequence}


@router.get(
    "/sse/stream",
    dependencies=[Depends(require_scopes("topic3:sse:read"))],
)
async def stream_sse(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    context = current_tenant()
    after_sequence = None
    if last_event_id:
        after_sequence = request.app.state.sse_cursor_codec.decode(
            last_event_id,
            context.tenant_id,
        )

    async def events() -> AsyncIterator[bytes]:
        with tenant_scope(context):
            async for event in request.app.state.sse_broker.subscribe(
                context.tenant_id,
                after_sequence=after_sequence,
            ):
                if await request.is_disconnected():
                    return
                if event is None:
                    yield b": heartbeat\n\n"
                    continue
                cursor = request.app.state.sse_cursor_codec.encode(
                    context.tenant_id,
                    event.sequence,
                )
                yield encode_sse_frame(event, cursor)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _unavailable() -> LiyanError:
    return LiyanError(
        ErrorCode.DATABASE_UNAVAILABLE,
        "The Topic 3 generation runtime is unavailable.",
        category=ErrorCategory.DATABASE,
        retriable=True,
        status_code=503,
    )
