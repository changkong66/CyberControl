from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic3 import CandidateV1
from liyans_contracts.topic4_c1 import ClaimV1, RevisionRequestV1, VerificationReportV1
from liyans_contracts.topic4_c8 import RevisionPatchV1
from liyans_contracts.verification import (
    ReleaseAuthorizationPayloadV1,
    VerificationRequestPayloadV1,
)
from pydantic import BaseModel, Field

from liyans.api.auth import require_scopes
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import current_tenant, tenant_scope
from liyans.domains.release.engine import PublicationRequest, ReleasePolicy
from liyans.domains.verification.runtime import Topic4Runtime, map_topic4_error
from liyans.infrastructure.streaming.sse import encode_sse_frame

router = APIRouter(prefix="/internal/topic4", tags=["topic4"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=32, max_length=160)]


class VerificationBatchQuery(BaseModel):
    verification_ids: list[UUID] = Field(min_length=1, max_length=200)


class RAGRetrievalCommand(BaseModel):
    claim: ClaimV1
    course_id: str = Field(min_length=1, max_length=128)


class RevisionCommand(BaseModel):
    request: RevisionRequestV1
    patches: list[RevisionPatchV1] = Field(min_length=1, max_length=2048)
    prompt_bundle_version: str = Field(default="topic4-prompts-v1", min_length=1, max_length=128)


class PublicationCommand(BaseModel):
    authorization: ReleaseAuthorizationPayloadV1
    report: VerificationReportV1
    candidate: CandidateV1


class PublicationBatchCommand(BaseModel):
    publications: list[PublicationCommand] = Field(min_length=1, max_length=100)


def topic4_runtime(request: Request) -> Topic4Runtime:
    value = getattr(request.app.state, "topic4_runtime", None)
    if value is None:
        raise LiyanError(
            ErrorCode.DATABASE_UNAVAILABLE,
            "The Topic 4 verification runtime is unavailable.",
            category=ErrorCategory.DATABASE,
            retriable=True,
            status_code=503,
        )
    return cast(Topic4Runtime, value)


def response_envelope(
    request: Request,
    event_type: str,
    payload: dict[str, Any],
    *,
    correlation_id: UUID | None = None,
) -> dict[str, Any]:
    context = current_tenant()
    now = datetime.now(UTC)
    request_id = uuid4()
    correlation = correlation_id or uuid4()
    envelope = Topic3EnvelopeV1(
        envelope_id=request_id,
        event_type=event_type,
        message_kind=MessageKind.RESULT,
        tenant_id=context.tenant_id,
        session_id=context.session_id or correlation,
        subject_ref=context.subject_ref,
        correlation_id=correlation,
        causation_id=None,
        sequence=0,
        partition_key=f"topic4:api:{context.tenant_id}:{request.state.trace_id}",
        producer=ProducerMetadataV1(
            agent=None,
            service="topic4-api",
            instance_id="request-handler",
            build_version="topic4-runtime-v1",
        ),
        delivery=DeliveryMetadataV1(
            idempotency_key=f"topic4:api:{request_id.hex}",
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


@router.get(
    "/health",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:read"))],
)
async def topic4_health(request: Request) -> dict[str, Any]:
    runtime = topic4_runtime(request)
    return response_envelope(
        request,
        "topic4.api.health",
        {
            "ready": runtime.ready,
            "verification_task_registered": True,
            "local_rag": "enabled",
            "external_embedding": "prohibited",
            "release_isolation": "SERIALIZABLE",
        },
    )


@router.post(
    "/verifications",
    response_model=Topic3EnvelopeV1,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scopes("topic4:verification:write"))],
)
async def create_verification(
    request: Request,
    body: VerificationRequestPayloadV1,
) -> dict[str, Any]:
    try:
        result = await topic4_runtime(request).accept(body)
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.verification.accepted",
        result,
        correlation_id=body.verification_id,
    )


@router.post(
    "/verifications/{verification_id}/execute",
    response_model=Topic3EnvelopeV1,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scopes("topic4:verification:execute"))],
)
async def execute_verification(request: Request, verification_id: UUID) -> dict[str, Any]:
    runtime = topic4_runtime(request)
    await runtime.enqueue(verification_id)
    return response_envelope(
        request,
        "topic4.api.verification.queued",
        {"verification_id": str(verification_id), "state": "QUEUED"},
        correlation_id=verification_id,
    )


@router.post(
    "/verifications/batch",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:verification:read"))],
)
async def batch_verifications(
    request: Request,
    body: VerificationBatchQuery,
) -> dict[str, Any]:
    runtime = topic4_runtime(request)
    snapshots = await asyncio.gather(
        *(runtime.snapshot(identifier) for identifier in body.verification_ids)
    )
    return response_envelope(
        request,
        "topic4.api.verification.batch-result",
        {"verifications": snapshots},
    )


@router.get(
    "/verifications/{verification_id}",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:verification:read"))],
)
async def get_verification(request: Request, verification_id: UUID) -> dict[str, Any]:
    result = await topic4_runtime(request).snapshot(verification_id)
    return response_envelope(
        request,
        "topic4.api.verification.result",
        result,
        correlation_id=verification_id,
    )


@router.get(
    "/verifications/{verification_id}/claims",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:claim:read"))],
)
async def list_claims(request: Request, verification_id: UUID) -> dict[str, Any]:
    claims = await topic4_runtime(request).claims(verification_id)
    return response_envelope(
        request,
        "topic4.api.claims.result",
        {"claims": [claim.model_dump(mode="json") for claim in claims]},
        correlation_id=verification_id,
    )


@router.get(
    "/traces/{trace_id}",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:trace:read"))],
)
async def trace_records(
    request: Request,
    trace_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    result = await topic4_runtime(request).trace(trace_id, limit=limit)
    return response_envelope(
        request,
        "topic4.api.trace.result",
        result,
    )


@router.get(
    "/verifications/{verification_id}/report",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:report:read"))],
)
async def get_report(request: Request, verification_id: UUID) -> dict[str, Any]:
    snapshot = await topic4_runtime(request).snapshot(verification_id)
    report = snapshot["report"]
    if report is None:
        raise LiyanError(
            ErrorCode.TOPIC4_NOT_FOUND,
            "The verification report is not available.",
            category=ErrorCategory.CONTRACT,
            status_code=404,
        )
    return response_envelope(
        request,
        "topic4.api.report.result",
        {"report": report},
        correlation_id=verification_id,
    )


@router.post(
    "/rag/retrieve",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:rag:read"))],
)
async def retrieve_evidence(
    request: Request,
    body: RAGRetrievalCommand,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    response = await topic4_runtime(request).retrieve(
        body.claim,
        course_id=body.course_id,
        idempotency_key=idempotency_key,
    )
    return response_envelope(
        request,
        "topic4.api.rag.result",
        {"retrieval": response.model_dump(mode="json")},
        correlation_id=body.claim.verification_id,
    )


@router.get(
    "/claims/{claim_id}/evidence",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:rag:read"))],
)
async def claim_evidence(request: Request, claim_id: UUID) -> dict[str, Any]:
    evidence = await topic4_runtime(request).evidence(claim_id)
    return response_envelope(
        request,
        "topic4.api.evidence.result",
        {"evidence": [item.model_dump(mode="json") for item in evidence]},
    )


@router.post(
    "/revisions",
    response_model=Topic3EnvelopeV1,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scopes("topic4:revision:write"))],
)
async def create_revision(request: Request, body: RevisionCommand) -> dict[str, Any]:
    try:
        outcome = await topic4_runtime(request).revision(
            body.request,
            body.patches,
            prompt_bundle_version=body.prompt_bundle_version,
        )
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.revision.accepted",
        {
            "cycle": outcome.cycle.model_dump(mode="json"),
            "plan": outcome.plan.model_dump(mode="json"),
            "patches": [item.model_dump(mode="json") for item in outcome.patches],
            "candidate": outcome.candidate.candidate.model_dump(mode="json"),
            "response": outcome.response.model_dump(mode="json"),
            "reverification": outcome.reverification.as_document(),
        },
        correlation_id=body.request.verification_id,
    )


@router.get(
    "/verifications/{verification_id}/revisions",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:revision:read"))],
)
async def revision_history(
    request: Request,
    verification_id: UUID,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    revisions = await topic4_runtime(request).revisions(verification_id, limit=limit)
    return response_envelope(
        request,
        "topic4.api.revision-history.result",
        {"revisions": revisions},
        correlation_id=verification_id,
    )


@router.get(
    "/release/history",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:release:read"))],
)
async def release_history(
    request: Request,
    verification_id: Annotated[UUID | None, Query()] = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    history = await topic4_runtime(request).publication_history(
        verification_id=verification_id,
        limit=limit,
    )
    return response_envelope(
        request,
        "topic4.api.release-history.result",
        {"records": history},
        correlation_id=verification_id,
    )


@router.post(
    "/release/authorizations/validate",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:release:read"))],
)
async def validate_authorization(
    request: Request,
    body: ReleaseAuthorizationPayloadV1,
) -> dict[str, Any]:
    try:
        ReleasePolicy.validate_authorization(
            body,
            context=current_tenant(),
            now=datetime.now(UTC),
        )
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.release-authorization.valid",
        {"authorization_id": str(body.authorization_id), "valid": True},
        correlation_id=body.verification_id,
    )


@router.post(
    "/release/authorizations",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:release:write"))],
)
async def issue_authorization(
    request: Request,
    body: ReleaseAuthorizationPayloadV1,
) -> dict[str, Any]:
    try:
        authorization = await topic4_runtime(request).issue_authorization(body)
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.release-authorization.issued",
        {"authorization": authorization.model_dump(mode="json")},
        correlation_id=body.verification_id,
    )


def publication_request(command: PublicationCommand) -> PublicationRequest:
    authorization = command.authorization
    document = {
        "authorization_id": str(authorization.authorization_id),
        "verification_id": str(authorization.verification_id),
        "report_id": str(authorization.report_id),
        "candidate_id": str(authorization.candidate_id),
        "candidate_version": authorization.candidate_version,
        "candidate_sha256": authorization.candidate_sha256,
        "report_sha256": authorization.report_sha256,
        "allowed_block_ids": authorization.allowed_block_ids,
    }
    return PublicationRequest(
        authorization=authorization,
        report=command.report,
        candidate=command.candidate,
        request_document=document,
        request_sha256=canonical_sha256(document),
        subject_ref=current_tenant().subject_ref,
    )


@router.post(
    "/release/publications",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:release:write"))],
)
async def publish(request: Request, body: PublicationCommand) -> dict[str, Any]:
    try:
        result = await topic4_runtime(request).publish(publication_request(body))
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.publication.committed",
        {
            "batch": result.batch.model_dump(mode="json"),
            "public_event": result.public_event.model_dump(mode="json"),
            "public_artifact": result.public_artifact.model_dump(mode="json"),
        },
        correlation_id=body.authorization.verification_id,
    )


@router.post(
    "/release/publications/batch",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:release:write"))],
)
async def publish_batch(request: Request, body: PublicationBatchCommand) -> dict[str, Any]:
    runtime = topic4_runtime(request)
    semaphore = asyncio.Semaphore(16)

    async def publish_one(command: PublicationCommand):
        async with semaphore:
            return await runtime.publish(publication_request(command))

    try:
        results = await asyncio.gather(*(publish_one(item) for item in body.publications))
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.publication.batch-committed",
        {
            "publications": [
                {
                    "batch": result.batch.model_dump(mode="json"),
                    "public_event": result.public_event.model_dump(mode="json"),
                    "public_artifact": result.public_artifact.model_dump(mode="json"),
                }
                for result in results
            ]
        },
    )


@router.get(
    "/sse/replay",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:sse:read"))],
)
async def replay_public_events(
    request: Request,
    after_sequence: int | None = Query(default=None, ge=-1),
) -> dict[str, Any]:
    context = current_tenant()
    events = await request.app.state.sse_replay_log.replay(
        context.tenant_id,
        after_sequence,
    )
    projected = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "data": event.data,
            "emitted_at": event.emitted_at.isoformat(),
            "cursor": request.app.state.sse_cursor_codec.encode(
                context.tenant_id,
                event.sequence,
            ),
        }
        for event in events
        if event.event_type.startswith("topic4.")
    ]
    return response_envelope(
        request,
        "topic4.api.sse-replay.result",
        {"events": projected},
    )


@router.get(
    "/sse/stream",
    dependencies=[Depends(require_scopes("topic4:sse:read"))],
)
async def stream_public_events(
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
                if not event.event_type.startswith("topic4."):
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
