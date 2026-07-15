from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import (
    AgentTaskState,
    CandidateV1,
    GenerationSessionState,
    SSEChunkV1,
    Topic3ExecutionBlueprintV1,
)


@dataclass(frozen=True, slots=True)
class GenerationSessionRecord:
    session_snapshot_id: UUID
    generation_session_id: UUID
    session_version: int
    parent_session_snapshot_id: UUID | None
    learner_ref: str
    course_id: str
    topic1_graph_snapshot_id: UUID
    topic1_graph_version: int
    topic2_profile_id: UUID
    topic2_profile_version: int
    topic2_path_snapshot_id: UUID
    topic2_path_version: int
    personalization_policy_digest: str
    requested_resources: tuple[ResourceType, ...]
    state: GenerationSessionState
    request_document: dict[str, Any]
    result_document: dict[str, Any]
    content_sha256: str
    created_by_subject: str
    frozen_at: datetime


@dataclass(frozen=True, slots=True)
class BlueprintRecord:
    blueprint_snapshot_id: UUID
    blueprint: Topic3ExecutionBlueprintV1
    activation_document: dict[str, Any]
    created_by_subject: str
    frozen_at: datetime


@dataclass(frozen=True, slots=True)
class AgentTaskRecord:
    task_record_id: UUID
    task_id: UUID
    task_version: int
    blueprint_id: UUID
    blueprint_version: str
    agent: SourceAgent
    resource_type: ResourceType
    state: AgentTaskState
    dependency_task_ids: tuple[UUID, ...]
    attempt: int
    max_attempts: int
    timeout_seconds: float
    request_document: dict[str, Any]
    result_document: dict[str, Any]
    error_document: dict[str, Any]
    request_sha256: str
    result_sha256: str | None
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ModelInvocationRecord:
    invocation_id: UUID
    task_id: UUID
    task_version: int
    provider_alias: str
    model_alias: str
    provider_request_id: str
    state: str
    request_sha256: str
    response_sha256: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    error_document: dict[str, Any]
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    candidate_record_id: UUID
    candidate: CandidateV1
    frozen_at: datetime


@dataclass(frozen=True, slots=True)
class StreamChunkRecord:
    stream_chunk_record_id: UUID
    chunk: SSEChunkV1
