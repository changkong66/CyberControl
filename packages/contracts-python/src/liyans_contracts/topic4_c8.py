from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .artifacts import ArtifactObjectRefV1
from .common import Sha256Hex, VersionString
from .enums import SourceAgent
from .topic4_common import BlockId, Topic4RecordV1


class RevisionCycleState(StrEnum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RevisionOperation(StrEnum):
    REPLACE_BLOCK = "REPLACE_BLOCK"
    REMOVE_BLOCK = "REMOVE_BLOCK"


class RevisionCycleV1(Topic4RecordV1):
    schema_version: Literal["revision-cycle.v1"]
    revision_cycle_id: UUID
    verification_id: UUID
    parent_verification_id: UUID
    candidate_id: UUID
    base_candidate_version: int = Field(ge=1)
    base_candidate_sha256: Sha256Hex
    revision_round: int = Field(ge=1, le=2)
    state: RevisionCycleState
    lock_token: UUID
    lock_owner: str = Field(min_length=1, max_length=128)
    lock_expires_at: AwareDatetime
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_cycle(self) -> RevisionCycleV1:
        if self.lock_expires_at <= self.created_at:
            raise ValueError("revision lock must expire after creation")
        if self.state == RevisionCycleState.COMPLETED and self.completed_at is None:
            raise ValueError("completed revision cycle requires completed_at")
        return self


class RevisionPlanV1(Topic4RecordV1):
    schema_version: Literal["revision-plan.v1"]
    revision_plan_id: UUID
    revision_cycle_id: UUID
    verification_id: UUID
    candidate_id: UUID
    base_candidate_version: int = Field(ge=1)
    base_candidate_sha256: Sha256Hex
    revision_round: int = Field(ge=1, le=2)
    target_agent: SourceAgent
    affected_claim_ids: list[UUID] = Field(min_length=1, max_length=4096)
    affected_block_ids: list[BlockId] = Field(min_length=1, max_length=2048)
    patch_ids: list[UUID] = Field(min_length=1, max_length=2048)
    instructions_artifact: ArtifactObjectRefV1
    instructions_sha256: Sha256Hex
    prompt_bundle_version: VersionString


class RevisionPatchV1(Topic4RecordV1):
    schema_version: Literal["revision-patch.v1"]
    revision_patch_id: UUID
    revision_plan_id: UUID
    block_id: BlockId
    operation: RevisionOperation
    base_block_sha256: Sha256Hex
    replacement_artifact: ArtifactObjectRefV1 | None = None
    replacement_sha256: Sha256Hex | None = None
    target_content_schema_version: VersionString
    reason_claim_ids: list[UUID] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_patch(self) -> RevisionPatchV1:
        has_replacement = (
            self.replacement_artifact is not None or self.replacement_sha256 is not None
        )
        if self.operation == RevisionOperation.REPLACE_BLOCK:
            if self.replacement_artifact is None or self.replacement_sha256 is None:
                raise ValueError("replacement patch requires artifact and hash")
        elif has_replacement:
            raise ValueError("remove patch cannot include replacement content")
        return self
