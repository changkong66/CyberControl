from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

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
from liyans_contracts.topic4_c1 import (
    ClaimV1,
    ReasonCode,
    ReviewDecision,
    ReviewTaskState,
    RevisionRequestV1,
    VerificationReportV1,
)
from liyans_contracts.topic4_c8 import RevisionPatchV1
from liyans_contracts.topic4_c11 import (
    ComplianceBuildProvenanceInputV1,
    ComplianceEvidenceImportCommandV1,
    ComplianceVulnerabilityInputV1,
)
from liyans_contracts.topic4_c12 import PublicationCommitCommandV2, ReleaseDerivationCommandV2
from liyans_contracts.verification import (
    ReleaseAuthorizationPayloadV1,
    VerificationRequestPayloadV1,
)
from pydantic import BaseModel, ConfigDict, Field

from liyans.api.auth import require_scopes
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import current_tenant, tenant_scope
from liyans.domains.release.engine import PublicationRequest, ReleasePolicy
from liyans.domains.verification.records import build_topic4_record
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


class ComplianceEvidenceImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: UUID
    claim_id: UUID
    sbom_document: dict[str, Any]
    vulnerability_records: list[ComplianceVulnerabilityInputV1] = Field(
        default_factory=list,
        max_length=65_536,
    )
    provenance_document: ComplianceBuildProvenanceInputV1


class ReleaseDerivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: UUID
    requested_release_mode: Literal["FULL", "FULL_WITH_DISCLOSURE"]
    requested_block_ids: list[str] = Field(default_factory=list, max_length=2048)
    ttl_seconds: int = Field(default=300, ge=1, le=300)


class PublicationCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_id: UUID


class HumanReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_task_id: UUID
    decision: ReviewDecision
    rationale: str = Field(min_length=1, max_length=65_536)
    disclosure_codes: list[ReasonCode] = Field(default_factory=list, max_length=32)
    waived_finding_ids: list[UUID] = Field(default_factory=list, max_length=4096)
    expected_task_version: int = Field(ge=1)
    expected_state_version: int = Field(ge=1)


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
    "/compliance/packages",
    response_model=Topic3EnvelopeV1,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scopes("topic4:compliance:write"))],
)
async def import_compliance_package(
    request: Request,
    body: ComplianceEvidenceImportRequest,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    context = current_tenant()
    now = datetime.now(UTC)
    command = build_topic4_record(
        ComplianceEvidenceImportCommandV1,
        trace_id=context.trace_id,
        tenant_id=context.tenant_id,
        version_cas=1,
        created_at=now,
        immutable=True,
        schema_version="compliance-evidence-import.command.v1",
        import_command_id=uuid5(
            NAMESPACE_URL,
            f"topic4:c11:{context.tenant_id}:{idempotency_key}",
        ),
        verification_id=body.verification_id,
        claim_id=body.claim_id,
        sbom_document=body.sbom_document,
        vulnerability_records=body.vulnerability_records,
        provenance_document=body.provenance_document,
        idempotency_key_sha256=canonical_sha256({"idempotency_key": idempotency_key}),
    )
    try:
        package = await topic4_runtime(request).import_compliance(command)
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.compliance.package.imported",
        {"package": package.model_dump(mode="json")},
        correlation_id=body.verification_id,
    )


@router.get(
    "/compliance/claims/{claim_id}",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:compliance:read"))],
)
async def get_compliance_package(
    request: Request,
    claim_id: UUID,
    verification_id: Annotated[UUID | None, Query()] = None,
) -> dict[str, Any]:
    try:
        package = await topic4_runtime(request).compliance_package(verification_id, claim_id)
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    if package is None:
        raise LiyanError(
            ErrorCode.TOPIC4_NOT_FOUND,
            "The C11 compliance evidence package is not available.",
            category=ErrorCategory.CONTRACT,
            status_code=404,
        )
    return response_envelope(
        request,
        "topic4.api.compliance.package.result",
        {"package": package.model_dump(mode="json")},
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
    deprecated=True,
    dependencies=[Depends(require_scopes("topic4:release:read"))],
)
async def validate_authorization(
    request: Request,
    body: ReleaseAuthorizationPayloadV1,
) -> dict[str, Any]:
    try:
        await topic4_runtime(request).validate_authorization(body)
        ReleasePolicy.validate_authorization(body, context=current_tenant(), now=datetime.now(UTC))
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
    deprecated=True,
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
    deprecated=True,
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
    "/release/authorizations/derive",
    response_model=Topic3EnvelopeV1,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scopes("topic4:release:write"))],
)
async def derive_authorization_v2(
    request: Request,
    body: ReleaseDerivationRequest,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    context = current_tenant()
    command = build_topic4_record(
        ReleaseDerivationCommandV2,
        trace_id=context.trace_id,
        tenant_id=context.tenant_id,
        version_cas=1,
        created_at=datetime.now(UTC),
        immutable=True,
        schema_version="release.derivation.command.v2",
        derivation_command_id=uuid5(
            NAMESPACE_URL,
            f"topic4:c12:derivation-command:{context.tenant_id}:{idempotency_key}",
        ),
        verification_id=body.verification_id,
        requested_release_mode=body.requested_release_mode,
        requested_block_ids=body.requested_block_ids,
        ttl_seconds=body.ttl_seconds,
        idempotency_key_sha256=canonical_sha256({"idempotency_key": idempotency_key}),
    )
    try:
        authorization = await topic4_runtime(request).derive_release_authorization(
            command,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.release-authorization.derived.v2",
        {"authorization": authorization.model_dump(mode="json")},
        correlation_id=body.verification_id,
    )


@router.post(
    "/release/publications/commit",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:release:write"))],
)
async def commit_publication_v2(
    request: Request,
    body: PublicationCommitRequest,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    context = current_tenant()
    command = build_topic4_record(
        PublicationCommitCommandV2,
        trace_id=context.trace_id,
        tenant_id=context.tenant_id,
        version_cas=1,
        created_at=datetime.now(UTC),
        immutable=True,
        schema_version="publication.commit.command.v2",
        commit_command_id=uuid5(
            NAMESPACE_URL,
            f"topic4:c12:commit-command:{context.tenant_id}:{idempotency_key}",
        ),
        authorization_id=body.authorization_id,
        idempotency_key_sha256=canonical_sha256({"idempotency_key": idempotency_key}),
    )
    try:
        result = await topic4_runtime(request).commit_release_v2(
            command,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.publication.committed.v2",
        {
            "batch": result.batch.model_dump(mode="json"),
            "public_event": result.public_event.model_dump(mode="json"),
            "public_artifact": result.public_artifact.model_dump(mode="json"),
            "state": "RELEASED",
        },
        correlation_id=body.authorization_id,
    )


@router.get(
    "/reviews/tasks",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic4:review:read"))],
)
async def list_review_tasks(
    request: Request,
    state: Annotated[ReviewTaskState, Query()] = ReviewTaskState.OPEN,
) -> dict[str, Any]:
    try:
        tasks = await topic4_runtime(request).review_tasks(state)
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.review-tasks.result",
        {"tasks": [task.model_dump(mode="json") for task in tasks]},
    )


@router.post(
    "/verifications/{verification_id}/reviews/decisions",
    response_model=Topic3EnvelopeV1,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scopes("topic4:review:write"))],
)
async def submit_review_decision(
    request: Request,
    verification_id: UUID,
    body: HumanReviewDecisionRequest,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    try:
        result = await topic4_runtime(request).submit_review(
            review_task_id=body.review_task_id,
            verification_id=verification_id,
            decision=body.decision,
            rationale=body.rationale,
            disclosure_codes=body.disclosure_codes,
            waived_finding_ids=body.waived_finding_ids,
            expected_task_version=body.expected_task_version,
            expected_state_version=body.expected_state_version,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise map_topic4_error(exc) from exc
    return response_envelope(
        request,
        "topic4.api.review-decision.committed",
        {
            "decision": result.decision.model_dump(mode="json"),
            "review_task": result.review_task.model_dump(mode="json"),
            "state": result.state.model_dump(mode="json"),
        },
        correlation_id=verification_id,
    )


@router.post(
    "/release/publications/batch",
    response_model=Topic3EnvelopeV1,
    deprecated=True,
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
