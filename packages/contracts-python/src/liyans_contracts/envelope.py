from __future__ import annotations

from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .common import FROZEN_MODEL_CONFIG, VersionString
from .enums import ResourceType, SourceAgent

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class MessageKind(StrEnum):
    COMMAND = "COMMAND"
    EVENT = "EVENT"
    RESULT = "RESULT"
    ERROR = "ERROR"


class MessagePriority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class DeliveryMode(StrEnum):
    AT_LEAST_ONCE = "AT_LEAST_ONCE"


class ErrorSeverity(StrEnum):
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ProducerMetadataV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    agent: SourceAgent | None = Field(
        default=None,
        description="Producing Topic 3 agent; null for platform infrastructure events.",
    )
    service: str = Field(
        min_length=1,
        max_length=128,
        description="Stable producing service name from deployment metadata.",
    )
    instance_id: str = Field(
        min_length=1,
        max_length=128,
        description="Ephemeral process or worker instance identity.",
    )
    build_version: VersionString = Field(
        description="Immutable producer build version used for provenance.",
    )


class DeliveryMetadataV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    mode: Literal[DeliveryMode.AT_LEAST_ONCE] = Field(
        default=DeliveryMode.AT_LEAST_ONCE,
        description="Delivery guarantee. Consumers must be idempotent.",
    )
    idempotency_key: str = Field(
        min_length=16,
        max_length=160,
        pattern=r"^[A-Za-z0-9:_\-.]+$",
        description="Stable deduplication key produced by the message originator.",
    )
    attempt: int = Field(
        default=1,
        ge=1,
        le=16,
        description="Current delivery attempt, starting from one.",
    )
    max_attempts: int = Field(
        default=3,
        ge=1,
        le=16,
        description="Maximum delivery attempts allowed by the routing policy.",
    )
    priority: MessagePriority = Field(
        default=MessagePriority.NORMAL,
        description="Queue priority assigned by the deterministic routing policy.",
    )
    available_at: AwareDatetime = Field(
        description="Earliest UTC time at which the message may be dispatched.",
    )
    expires_at: AwareDatetime | None = Field(
        default=None,
        description="UTC expiry after which the message must not be executed.",
    )

    @model_validator(mode="after")
    def validate_delivery(self) -> DeliveryMetadataV1:
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        if self.expires_at is not None and self.expires_at <= self.available_at:
            raise ValueError("expires_at must be after available_at")
        return self


class ResourceMetadataV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    resource_type: ResourceType = Field(
        description="Frozen Topic 3 resource family owning the payload.",
    )
    blueprint_id: UUID = Field(
        description="Immutable blueprint identity from Topic 3 orchestration.",
    )
    blueprint_version: VersionString = Field(
        description="Blueprint version bound when generation started.",
    )
    candidate_id: UUID | None = Field(
        default=None,
        description="Logical candidate identity when the message concerns a candidate.",
    )
    candidate_version: int | None = Field(
        default=None,
        ge=1,
        description="Exact candidate version; latest aliases are prohibited.",
    )
    block_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Exact block identity for block-scoped messages.",
    )

    @model_validator(mode="after")
    def validate_candidate_pair(self) -> ResourceMetadataV1:
        if (self.candidate_id is None) != (self.candidate_version is None):
            raise ValueError("candidate_id and candidate_version must be provided together")
        return self


class ErrorReceiptV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic3.error-receipt.v1"] = Field(
        description="Wire version for the standard Topic 3 error receipt.",
    )
    error_code: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_-]+$",
        description="Stable machine-readable error code from the shared error catalog.",
    )
    category: str = Field(
        min_length=1,
        max_length=64,
        description="Error ownership category such as CONTRACT, PROVIDER, or TIMEOUT.",
    )
    severity: ErrorSeverity = Field(
        description="Operational severity; it does not encode academic correctness.",
    )
    retriable: bool = Field(
        description="Whether infrastructure policy permits another delivery attempt.",
    )
    safe_message: str = Field(
        min_length=1,
        max_length=512,
        description="Redacted message safe for logs and authorized clients.",
    )
    details_ref: dict[str, Any] | None = Field(
        default=None,
        description="Restricted artifact reference for diagnostics; never raw secrets.",
    )
    occurred_at: AwareDatetime = Field(
        description="UTC time at which the error occurred.",
    )


class EnvelopeHeaderV1(BaseModel):
    """Canonical Topic 3 envelope header aligned across all five agents."""

    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic3.envelope.v1"] = Field(
        default="topic3.envelope.v1",
        description="Frozen public Envelope wire version.",
    )
    envelope_id: UUID = Field(
        description="Globally unique envelope identity generated at message creation.",
    )
    event_type: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_.-]+$",
        description="Stable event name from the Topic 3 event catalog.",
    )
    message_kind: MessageKind = Field(
        description="Command, event, result, or standardized error receipt.",
    )
    tenant_id: str = Field(
        min_length=1,
        max_length=128,
        description="Tenant boundary sourced only from authenticated server context.",
    )
    session_id: UUID = Field(
        description="Learning-session identity from the frozen Topic 1/2 session model.",
    )
    subject_ref: str = Field(
        min_length=1,
        max_length=256,
        description="Tokenized user or service subject reference; never raw PII.",
    )
    correlation_id: UUID = Field(
        description="Root workflow correlation identity preserved across agents.",
    )
    causation_id: UUID | None = Field(
        default=None,
        description="Envelope identity that directly caused this message.",
    )
    sequence: int = Field(
        ge=0,
        description="Monotonic sequence inside the partition key, assigned by the producer.",
    )
    partition_key: str = Field(
        min_length=1,
        max_length=256,
        description="Ordering partition, normally tenant/session/candidate identity.",
    )
    producer: ProducerMetadataV1 = Field(
        description="Producing agent/service provenance supplied by runtime infrastructure.",
    )
    delivery: DeliveryMetadataV1 = Field(
        description="At-least-once delivery, retry, priority, and expiry metadata.",
    )
    resource: ResourceMetadataV1 | None = Field(
        default=None,
        description="Optional blueprint/candidate/block identity for resource messages.",
    )
    trace_id: str = Field(
        min_length=16,
        max_length=64,
        pattern=r"^[a-fA-F0-9]+$",
        description="Distributed trace identity generated or propagated by infrastructure.",
    )
    span_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=32,
        pattern=r"^[a-fA-F0-9]+$",
        description="Current trace span identity when tracing is enabled.",
    )
    created_at: AwareDatetime = Field(
        description="UTC message creation time from the producing service clock.",
    )
    error: ErrorReceiptV1 | None = Field(
        default=None,
        description="Standard error receipt, required only when message_kind is ERROR.",
    )

    @model_validator(mode="after")
    def validate_error_semantics(self) -> EnvelopeHeaderV1:
        if self.message_kind == MessageKind.ERROR and self.error is None:
            raise ValueError("ERROR messages require an error receipt")
        if self.message_kind != MessageKind.ERROR and self.error is not None:
            raise ValueError("non-ERROR messages cannot contain an error receipt")
        if self.delivery.available_at < self.created_at:
            raise ValueError("delivery.available_at cannot be before created_at")
        return self


class Topic3EnvelopeV1(EnvelopeHeaderV1):
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent-specific versioned payload; validated by the owning payload schema.",
    )


class EnvelopeV1(EnvelopeHeaderV1, Generic[PayloadT]):
    payload: PayloadT = Field(
        description="Strongly typed payload used inside Python service boundaries.",
    )
