from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .common import (
    FROZEN_MODEL_CONFIG,
    OpaqueObjectKey,
    Sha256Hex,
    VersionString,
)
from .enums import AGENT_RESOURCE_MATRIX, ResourceType, SourceAgent


class ArtifactObjectRefV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["artifact.object.ref.v1"]
    storage_namespace: Literal["verification-artifacts"]
    object_key: OpaqueObjectKey
    media_type: Literal[
        "application/json",
        "application/x-ndjson",
        "text/markdown",
        "text/plain",
        "application/octet-stream",
    ]
    content_encoding: Literal["identity", "gzip"]
    byte_size: int = Field(ge=1, le=33_554_432)
    sha256: Sha256Hex
    created_at: AwareDatetime

    @model_validator(mode="after")
    def reject_unsafe_object_keys(self) -> ArtifactObjectRefV1:
        segments = self.object_key.split("/")
        if ".." in segments or "\\" in self.object_key or "://" in self.object_key:
            raise ValueError("object_key must be an opaque internal object key")
        return self


class BlockSnapshotManifestItemV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    block_id: str = Field(min_length=1, max_length=128)
    block_type: str = Field(min_length=1, max_length=64)
    ordinal: int = Field(ge=0)
    json_pointer: str = Field(min_length=1, max_length=1024)
    sha256: Sha256Hex
    byte_size: int = Field(ge=0, le=16_777_216)


class SourceSnapshotRefV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["source.snapshot.ref.v1"]

    source_envelope_id: UUID
    source_envelope_version: VersionString
    source_envelope_sha256: Sha256Hex

    blueprint_id: UUID
    blueprint_version: VersionString
    blueprint_sha256: Sha256Hex

    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    candidate_sha256: Sha256Hex

    source_agent: SourceAgent
    resource_type: ResourceType

    full_snapshot: ArtifactObjectRefV1
    block_manifest: list[BlockSnapshotManifestItemV1] = Field(
        min_length=1,
        max_length=2048,
    )

    @model_validator(mode="after")
    def validate_snapshot(self) -> SourceSnapshotRefV1:
        if self.resource_type not in AGENT_RESOURCE_MATRIX[self.source_agent]:
            raise ValueError("source_agent does not own resource_type")

        block_ids = [item.block_id for item in self.block_manifest]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("duplicate block_id in block_manifest")

        ordinals = [item.ordinal for item in self.block_manifest]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("duplicate ordinal in block_manifest")

        return self
