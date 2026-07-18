from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .artifacts import ArtifactObjectRefV1, SourceSnapshotRefV1
from .common import FROZEN_MODEL_CONFIG, Sha256Hex
from .enums import VerificationProfile, VerificationTrigger
from .topic4_common import Topic4RecordV1


class VerificationState(StrEnum):
    ACCEPTED = "ACCEPTED"
    SNAPSHOT_VALIDATING = "SNAPSHOT_VALIDATING"
    CLAIM_EXTRACTING = "CLAIM_EXTRACTING"
    CLAIMS_READY = "CLAIMS_READY"
    MODULE_DISPATCHING = "MODULE_DISPATCHING"
    VERIFYING = "VERIFYING"
    AGGREGATING = "AGGREGATING"
    REVISION_PLANNING = "REVISION_PLANNING"
    REVISION_WAITING = "REVISION_WAITING"
    REVERIFYING = "REVERIFYING"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class VerificationBindingV1(Topic4RecordV1):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["verification.binding.v1"]
    state_machine_version: str
    verifier_build_version: str
    policy_version: str
    prompt_bundle_version: str
    claim_schema_version: Literal["claim.v1"]
    retrieval_pipeline_version: str
    knowledge_base_version: str
    toolchain_manifest_version: str
    content_security_policy_version: str
    license_policy_version: str


class VerificationContextV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["verification.context.v1"]
    course_id: str = Field(min_length=1, max_length=128)
    course_version: str = Field(min_length=1, max_length=128)
    target_kp_id: str = Field(min_length=1, max_length=128)
    locale: Literal["zh-CN"]
    subject_domain: Literal["AUTOMATION"]
    profile_snapshot_ref: ArtifactObjectRefV1 | None = None
    path_decision_ref: ArtifactObjectRefV1 | None = None
    personalization_policy_digest: Sha256Hex


class VerificationRequestPayloadV1(Topic4RecordV1):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["verification.request.v1"]
    verification_id: UUID
    idempotency_key: str = Field(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9:_\-.]+$",
    )
    trigger: VerificationTrigger
    parent_verification_id: UUID | None = None
    source_snapshot_ref: SourceSnapshotRefV1
    context: VerificationContextV1
    requested_profile: VerificationProfile
    requested_optional_modules: list[str] = Field(default_factory=list, max_length=12)
    deadline_at: AwareDatetime
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def validate_request(self) -> VerificationRequestPayloadV1:
        if self.deadline_at <= self.requested_at:
            raise ValueError("deadline_at must be after requested_at")

        is_initial = self.trigger == VerificationTrigger.INITIAL_GENERATION
        if is_initial and self.parent_verification_id is not None:
            raise ValueError("initial verification cannot have a parent")
        if not is_initial and self.parent_verification_id is None:
            raise ValueError("reverification requires parent_verification_id")
        return self


class VerificationAcceptedPayloadV1(Topic4RecordV1):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["verification.accepted.v1"]
    verification_id: UUID
    idempotency_key: str
    state: Literal["ACCEPTED"]
    state_version: int = Field(ge=1)
    binding: VerificationBindingV1
    accepted_at: AwareDatetime
    deadline_at: AwareDatetime
    source_candidate_id: UUID
    source_candidate_version: int = Field(ge=1)
    source_candidate_sha256: Sha256Hex
    estimated_profile: VerificationProfile


class VerificationStateChangedPayloadV1(Topic4RecordV1):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["verification.state_changed.v1"]
    verification_id: UUID
    previous_state: VerificationState | None
    current_state: VerificationState
    state_version: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=128)
    revision_round: int = Field(ge=0, le=2)
    changed_at: AwareDatetime


class ReleaseAuthorizationPayloadV1(Topic4RecordV1):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["release.authorization.v1"]
    authorization_id: UUID
    verification_id: UUID
    report_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    candidate_sha256: Sha256Hex
    release_mode: Literal["FULL", "FULL_WITH_DISCLOSURE"]
    allowed_block_ids: list[str] = Field(min_length=1, max_length=2048)
    disclosure_codes: list[str] = Field(default_factory=list, max_length=32)
    report_sha256: Sha256Hex
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    one_time_use: Literal[True]

    @model_validator(mode="after")
    def validate_expiry(self) -> ReleaseAuthorizationPayloadV1:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self
