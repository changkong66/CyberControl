from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic2 import (
    Topic2BehaviorEventCommandV1,
    Topic2OperationCommandV1,
    Topic2PathGenerateCommandV1,
)

from liyans.api.auth import require_scopes
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import current_tenant
from liyans.domains.topic2.entities import (
    BehaviorEventType,
    BehaviorSourceType,
    LearningBehaviorEventDraft,
    PathChangeType,
)
from liyans.domains.topic2.orchestrator import Topic2Orchestrator
from liyans.domains.topic2.service import Topic2Service

router = APIRouter(prefix="/internal/topic2", tags=["topic2"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=160)]


def topic2_orchestrator(request: Request) -> Topic2Orchestrator:
    value = getattr(request.app.state, "topic2_orchestrator", None)
    if value is None:
        raise _unavailable()
    return cast(Topic2Orchestrator, value)


def topic2_service(request: Request) -> Topic2Service:
    value = getattr(request.app.state, "topic2_service", None)
    if value is None:
        raise _unavailable()
    return cast(Topic2Service, value)


def envelope(request: Request, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    context = current_tenant()
    now = datetime.now(UTC)
    correlation_id = uuid4()
    request_id = uuid4()
    value = Topic3EnvelopeV1(
        envelope_id=request_id,
        event_type=event_type,
        message_kind=MessageKind.RESULT,
        tenant_id=context.tenant_id,
        session_id=context.session_id or correlation_id,
        subject_ref=context.subject_ref,
        correlation_id=correlation_id,
        causation_id=None,
        sequence=0,
        partition_key=f"topic2:api:{context.tenant_id}:{request.state.trace_id}",
        producer=ProducerMetadataV1(
            agent=None,
            service="topic2-api",
            instance_id="request-handler",
            build_version="topic2-v1",
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
    return value.model_dump(mode="json")


@router.post(
    "/behavior-events",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:behavior:write"))],
)
async def record_behavior_event(
    request: Request,
    body: Topic2BehaviorEventCommandV1,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    event = LearningBehaviorEventDraft(
        event_id=body.event_id,
        source_event_id=body.source_event_id,
        event_version=body.event_version,
        learner_ref=body.learner_ref,
        course_id=body.course_id,
        kp_id=body.kp_id,
        session_id=body.session_id,
        event_type=BehaviorEventType(body.event_type.value),
        source_type=BehaviorSourceType(body.source_type.value),
        duration_seconds=body.duration_seconds,
        response_latency_ms=body.response_latency_ms,
        correctness=body.correctness,
        score=body.score,
        attempt_count=body.attempt_count,
        interaction_count=body.interaction_count,
        attention_ratio=body.attention_ratio,
        misconception_ids=tuple(body.misconception_ids),
        goal_tags=tuple(body.goal_tags),
        payload=body.payload,
        payload_sha256=body.payload_sha256,
        occurred_at=body.occurred_at,
        received_at=datetime.now(UTC),
    )
    result = await topic2_orchestrator(request).record_behavior(
        event,
        idempotency_key=idempotency_key,
    )
    return envelope(request, "topic2.api.behavior.result", result)


@router.post(
    "/learners/{learner_ref}/courses/{course_id}/initialize",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:profile:write", "topic2:memory:write"))],
)
async def initialize_learner(
    request: Request,
    learner_ref: str,
    course_id: str,
    body: Topic2OperationCommandV1,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic2_orchestrator(request).initialize_learner(
        learner_ref=learner_ref,
        course_id=course_id,
        operation_id=body.operation_id,
        requested_at=body.requested_at,
        idempotency_key=idempotency_key,
    )
    return envelope(request, "topic2.api.initialization.result", result)


@router.post(
    "/learners/{learner_ref}/courses/{course_id}/profiles/rebuild",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:profile:write"))],
)
async def rebuild_profile(
    request: Request,
    learner_ref: str,
    course_id: str,
    body: Topic2OperationCommandV1,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic2_orchestrator(request).rebuild_profile(
        learner_ref=learner_ref,
        course_id=course_id,
        operation_id=body.operation_id,
        requested_at=body.requested_at,
        idempotency_key=idempotency_key,
    )
    return envelope(request, "topic2.api.profile.result", result)


@router.post(
    "/profiles/{profile_id}/restore",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:profile:write"))],
)
async def restore_profile(
    request: Request,
    profile_id: UUID,
    body: Topic2OperationCommandV1,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic2_orchestrator(request).restore_profile(
        profile_id=profile_id,
        operation_id=body.operation_id,
        requested_at=body.requested_at,
        idempotency_key=idempotency_key,
    )
    return envelope(request, "topic2.api.profile-restore.result", result)


@router.get(
    "/learners/{learner_ref}/courses/{course_id}/profiles/latest",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:profile:read"))],
)
async def latest_profile(request: Request, learner_ref: str, course_id: str) -> dict[str, Any]:
    record = await topic2_service(request).latest_profile(learner_ref, course_id)
    if record is None:
        raise _not_found("student profile")
    return envelope(
        request,
        "topic2.api.profile.result",
        {"profile": Topic2Service.profile_record_document(record)},
    )


@router.get(
    "/learners/{learner_ref}/courses/{course_id}/profiles",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:profile:read"))],
)
async def profile_history(
    request: Request,
    learner_ref: str,
    course_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    records = await topic2_service(request).list_profile_versions(
        learner_ref,
        course_id,
        limit=limit,
    )
    return envelope(
        request,
        "topic2.api.profile-history.result",
        {"profiles": [Topic2Service.profile_record_document(record) for record in records]},
    )


@router.post(
    "/learners/{learner_ref}/courses/{course_id}/memory/refresh",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:memory:write"))],
)
async def refresh_memory(
    request: Request,
    learner_ref: str,
    course_id: str,
    body: Topic2OperationCommandV1,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic2_orchestrator(request).refresh_memory(
        learner_ref=learner_ref,
        course_id=course_id,
        operation_id=body.operation_id,
        requested_at=body.requested_at,
        idempotency_key=idempotency_key,
    )
    return envelope(request, "topic2.api.memory.result", result)


@router.post(
    "/memory/jobs/refresh-due",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:memory:batch"))],
)
async def refresh_due_memory(
    request: Request,
    body: Topic2OperationCommandV1,
    idempotency_key: IdempotencyKey,
    limit: int = Query(default=500, ge=1, le=1000),
) -> dict[str, Any]:
    result = await topic2_orchestrator(request).refresh_due_memory(
        operation_id=body.operation_id,
        requested_at=body.requested_at,
        idempotency_key=idempotency_key,
        limit=limit,
    )
    return envelope(request, "topic2.api.memory-batch.result", result)


@router.get(
    "/learners/{learner_ref}/courses/{course_id}/memory",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:memory:read"))],
)
async def latest_memory(request: Request, learner_ref: str, course_id: str) -> dict[str, Any]:
    records = await topic2_service(request).latest_memory_states(learner_ref, course_id)
    return envelope(
        request,
        "topic2.api.memory.result",
        {"memory_states": [Topic2Service.memory_record_document(record) for record in records]},
    )


@router.post(
    "/learners/{learner_ref}/courses/{course_id}/paths/generate",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:path:write"))],
)
async def generate_path(
    request: Request,
    learner_ref: str,
    course_id: str,
    body: Topic2PathGenerateCommandV1,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic2_orchestrator(request).generate_path(
        learner_ref=learner_ref,
        course_id=course_id,
        operation_id=body.operation_id,
        requested_at=body.requested_at,
        target_goal=body.target_goal,
        target_kp_ids=body.target_kp_ids,
        manual_order=body.manual_order,
        change_type=PathChangeType(body.change_type.value),
        trigger_reason=body.trigger_reason,
        idempotency_key=idempotency_key,
    )
    return envelope(request, "topic2.api.path.result", result)


@router.get(
    "/learners/{learner_ref}/courses/{course_id}/paths/latest",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:path:read"))],
)
async def latest_path(request: Request, learner_ref: str, course_id: str) -> dict[str, Any]:
    record = await topic2_service(request).latest_learning_path(learner_ref, course_id)
    if record is None:
        raise _not_found("learning path")
    return envelope(
        request,
        "topic2.api.path.result",
        {"learning_path": Topic2Service.path_record_document(record)},
    )


@router.get(
    "/learners/{learner_ref}/courses/{course_id}/paths",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:path:read"))],
)
async def path_history(
    request: Request,
    learner_ref: str,
    course_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    records = await topic2_service(request).list_learning_paths(
        learner_ref,
        course_id,
        limit=limit,
    )
    return envelope(
        request,
        "topic2.api.path-history.result",
        {"learning_paths": [Topic2Service.path_record_document(record) for record in records]},
    )


@router.get(
    "/learners/{learner_ref}/courses/{course_id}/agent-context",
    response_model=Topic3EnvelopeV1,
    dependencies=[Depends(require_scopes("topic2:context:read"))],
)
async def agent_context(request: Request, learner_ref: str, course_id: str) -> dict[str, Any]:
    result = await topic2_orchestrator(request).agent_context(learner_ref, course_id)
    return envelope(request, "topic2.api.agent-context.result", result)


def _not_found(resource: str) -> LiyanError:
    return LiyanError(
        ErrorCode.TOPIC2_NOT_FOUND,
        f"The requested Topic 2 {resource} does not exist.",
        category=ErrorCategory.CONTRACT,
        status_code=404,
    )


def _unavailable() -> LiyanError:
    return LiyanError(
        ErrorCode.DATABASE_UNAVAILABLE,
        "The Topic 2 service is unavailable.",
        category=ErrorCategory.DATABASE,
        retriable=True,
        status_code=503,
    )
