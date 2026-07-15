from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from liyans_contracts.common import MUTABLE_MODEL_CONFIG
from liyans_contracts.topic1 import (
    AuthoritySourceRefV1,
    CourseStatus,
    KnowledgePointStatus,
    PrerequisiteType,
    Topic1ApiEnvelopeV1,
    Topic1ImportBundleV1,
)
from pydantic import BaseModel, Field

from liyans.api.auth import require_scopes
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.domains.topic1.service import MAX_IMPORT_HTTP_BYTES, Topic1Service

router = APIRouter(prefix="/internal/topic1", tags=["topic1"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=160)]


class CourseWriteRequest(BaseModel):
    model_config = MUTABLE_MODEL_CONFIG

    expected_revision: int | None = Field(default=None, ge=1)
    course_code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="zh-CN", min_length=2, max_length=16)
    academic_level: str = Field(default="UNDERGRADUATE", min_length=2, max_length=32)
    credit_hours: float = Field(ge=0, le=256)
    status: CourseStatus = CourseStatus.DRAFT
    authority_sources: list[AuthoritySourceRefV1] = Field(default_factory=list, max_length=64)


class KnowledgePointWriteRequest(BaseModel):
    model_config = MUTABLE_MODEL_CONFIG

    expected_revision: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    summary: str = Field(min_length=1, max_length=4000)
    learning_objectives: list[str] = Field(min_length=1, max_length=32)
    category: str = Field(min_length=1, max_length=128)
    difficulty_level: int = Field(default=1, ge=1, le=5)
    difficulty_score: float = Field(ge=0, le=1)
    estimated_minutes: int = Field(ge=1, le=2400)
    formula_signatures: list[str] = Field(default_factory=list, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=64)
    status: KnowledgePointStatus = KnowledgePointStatus.DRAFT
    authority_sources: list[AuthoritySourceRefV1] = Field(default_factory=list, max_length=64)


class PrerequisiteWriteRequest(BaseModel):
    model_config = MUTABLE_MODEL_CONFIG

    expected_revision: int | None = Field(default=None, ge=1)
    prerequisite_kp_id: str = Field(min_length=6, max_length=120)
    dependent_kp_id: str = Field(min_length=6, max_length=120)
    relation_type: PrerequisiteType = PrerequisiteType.REQUIRED
    strength: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=2000)


def topic1_service(request: Request) -> Topic1Service:
    service = getattr(request.app.state, "topic1_service", None)
    if service is None:
        raise LiyanError(
            ErrorCode.DATABASE_UNAVAILABLE,
            "The Topic 1 service is unavailable.",
            category=ErrorCategory.DATABASE,
            retriable=True,
            status_code=503,
        )
    return cast(Topic1Service, service)


def envelope(request: Request, data: dict[str, Any]) -> dict[str, Any]:
    return Topic1ApiEnvelopeV1(
        request_id=uuid4(),
        trace_id=request.state.trace_id,
        data=data,
    ).model_dump(mode="json")


@router.get(
    "/courses",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:read"))],
)
async def list_courses(request: Request) -> dict[str, Any]:
    courses = await topic1_service(request).list_courses()
    return envelope(request, {"courses": [item.model_dump(mode="json") for item in courses]})


@router.get(
    "/courses/{course_id}",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:read"))],
)
async def get_course(request: Request, course_id: str) -> dict[str, Any]:
    course = await topic1_service(request).get_course(course_id)
    return envelope(request, {"course": course.model_dump(mode="json")})


@router.put(
    "/courses/{course_id}",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:write"))],
)
async def upsert_course(
    request: Request,
    course_id: str,
    body: CourseWriteRequest,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic1_service(request).upsert_course(
        course_id=course_id,
        document=body.model_dump(mode="json", exclude={"expected_revision"}),
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
    )
    return envelope(request, result)


@router.get(
    "/courses/{course_id}/graph",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:read"))],
)
async def get_graph(request: Request, course_id: str) -> dict[str, Any]:
    graph = await topic1_service(request).get_graph(course_id)
    return envelope(request, {"graph": graph.model_dump(mode="json")})


@router.put(
    "/courses/{course_id}/knowledge-points/{kp_id}",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:write"))],
)
async def upsert_knowledge_point(
    request: Request,
    course_id: str,
    kp_id: str,
    body: KnowledgePointWriteRequest,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic1_service(request).upsert_knowledge_point(
        course_id=course_id,
        kp_id=kp_id,
        document=body.model_dump(mode="json", exclude={"expected_revision"}),
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
    )
    return envelope(request, result)


@router.delete(
    "/courses/{course_id}/knowledge-points/{kp_id}",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:write"))],
)
async def delete_knowledge_point(
    request: Request,
    course_id: str,
    kp_id: str,
    idempotency_key: IdempotencyKey,
    expected_revision: int = Query(ge=1),
) -> dict[str, Any]:
    result = await topic1_service(request).delete_knowledge_point(
        course_id=course_id,
        kp_id=kp_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return envelope(request, result)


@router.put(
    "/courses/{course_id}/prerequisites/{edge_id}",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:write"))],
)
async def upsert_prerequisite(
    request: Request,
    course_id: str,
    edge_id: str,
    body: PrerequisiteWriteRequest,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic1_service(request).upsert_prerequisite(
        course_id=course_id,
        edge_id=edge_id,
        document=body.model_dump(mode="json", exclude={"expected_revision"}),
        expected_revision=body.expected_revision,
        idempotency_key=idempotency_key,
    )
    return envelope(request, result)


@router.delete(
    "/courses/{course_id}/prerequisites/{edge_id}",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:write"))],
)
async def delete_prerequisite(
    request: Request,
    course_id: str,
    edge_id: str,
    idempotency_key: IdempotencyKey,
    expected_revision: int = Query(ge=1),
) -> dict[str, Any]:
    result = await topic1_service(request).delete_prerequisite(
        course_id=course_id,
        edge_id=edge_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return envelope(request, result)


@router.post(
    "/imports",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:import"))],
)
async def import_graph(
    request: Request,
    body: Topic1ImportBundleV1,
    idempotency_key: IdempotencyKey,
    content_length: int | None = Header(default=None, alias="Content-Length"),
) -> dict[str, Any]:
    if content_length is not None and content_length > MAX_IMPORT_HTTP_BYTES:
        raise LiyanError(
            ErrorCode.TOPIC1_IMPORT_LIMIT,
            "The Topic 1 import exceeds the accepted size limit.",
            category=ErrorCategory.CONTRACT,
            status_code=413,
        )
    result = await topic1_service(request).import_bundle(body, idempotency_key=idempotency_key)
    return envelope(request, result)


@router.post(
    "/courses/{course_id}/snapshots",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:freeze"))],
)
async def freeze_graph(
    request: Request,
    course_id: str,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic1_service(request).freeze_graph(
        course_id,
        idempotency_key=idempotency_key,
    )
    return envelope(request, result)


@router.get(
    "/courses/{course_id}/snapshots",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:read"))],
)
async def list_snapshots(request: Request, course_id: str) -> dict[str, Any]:
    snapshots = await topic1_service(request).list_snapshots(course_id)
    return envelope(
        request,
        {"snapshots": [item.model_dump(mode="json") for item in snapshots]},
    )


@router.post(
    "/snapshots/{snapshot_id}/rollback",
    response_model=Topic1ApiEnvelopeV1,
    dependencies=[Depends(require_scopes("topic1:rollback"))],
)
async def rollback_snapshot(
    request: Request,
    snapshot_id: UUID,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await topic1_service(request).rollback_snapshot(
        snapshot_id,
        idempotency_key=idempotency_key,
    )
    return envelope(request, result)
