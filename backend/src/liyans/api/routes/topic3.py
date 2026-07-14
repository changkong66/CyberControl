from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from liyans_contracts.envelope import Topic3EnvelopeV1

from liyans.api.auth import require_scopes
from liyans.core.errors import ContractError
from liyans.core.tenant import assert_tenant, current_tenant, tenant_scope
from liyans.domains.generation.compatibility import CompatibilityError, Topic3EnvelopeAdapter
from liyans.infrastructure.streaming.sse import encode_sse_frame

router = APIRouter(prefix="/internal/topic3", tags=["topic3-internal"])
adapter = Topic3EnvelopeAdapter()


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
