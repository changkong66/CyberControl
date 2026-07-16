from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from .common import FROZEN_MODEL_CONFIG, Sha256Hex

TraceId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-fA-F0-9]{16,64}$", min_length=16, max_length=64),
]
TenantId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
BlockId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
ReasonCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_.-]{0,127}$", min_length=1, max_length=128),
]


class Topic4RecordV1(BaseModel):
    """Immutable metadata carried by every registered Topic 4 wire record."""

    model_config = FROZEN_MODEL_CONFIG

    trace_id: TraceId = Field(description="Root trace propagated from Topic 3 ingestion.")
    tenant_id: TenantId = Field(description="Trusted server-side tenant boundary.")
    version_cas: int = Field(ge=1, description="Optimistic concurrency version.")
    record_sha256: Sha256Hex = Field(description="Canonical immutable record digest.")
    created_at: AwareDatetime = Field(description="UTC record creation time.")
    immutable: Literal[True] = Field(description="Records are append-only once emitted.")


class ClaimKind(StrEnum):
    TEXT = "TEXT"
    FORMULA = "FORMULA"
    GRAPH = "GRAPH"
    QUIZ = "QUIZ"
    CODE = "CODE"
    EXTENSION = "EXTENSION"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class VerificationVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSAFE = "UNSAFE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


class AggregateDecision(StrEnum):
    RELEASE = "RELEASE"
    RELEASE_WITH_DISCLOSURE = "RELEASE_WITH_DISCLOSURE"
    REVISE = "REVISE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK = "BLOCK"


class VerificationModule(StrEnum):
    C2_RAG = "C2_RAG"
    C3_ACADEMIC = "C3_ACADEMIC"
    C4_GRAPH = "C4_GRAPH"
    C5_QUIZ = "C5_QUIZ"
    C6_CODE = "C6_CODE"
    C7_EXTENSION = "C7_EXTENSION"
    C9_SECURITY = "C9_SECURITY"
    C10_PRIVACY = "C10_PRIVACY"
    C11_COMPLIANCE = "C11_COMPLIANCE"


class ModuleRunState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
