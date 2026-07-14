from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ArtifactRegistration:
    artifact_id: UUID
    tenant_id: str
    schema_version: str
    artifact_version: int
    resource_type: str
    storage_namespace: str
    object_key: str
    media_type: str
    content_encoding: str
    byte_size: int
    sha256: str
    created_by_subject: str
    status: str = "STAGED"
    source_envelope_id: UUID | None = None
    blueprint_id: UUID | None = None
    blueprint_version: str | None = None
    candidate_id: UUID | None = None
    candidate_version: int | None = None
    block_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredArtifactObject:
    tenant_id: str
    storage_namespace: str
    object_key: str
    byte_size: int
    sha256: str
    created: bool


class ArtifactObjectStore(Protocol):
    async def put(
        self,
        *,
        tenant_id: str,
        storage_namespace: str,
        object_key: str,
        content: bytes,
    ) -> StoredArtifactObject: ...

    async def read(
        self,
        *,
        tenant_id: str,
        storage_namespace: str,
        object_key: str,
        expected_byte_size: int,
        expected_sha256: str,
    ) -> bytes: ...


class ArtifactRepository(Protocol):
    async def add(self, session: AsyncSession, artifact: ArtifactRegistration) -> None: ...

    async def get(self, artifact_id: UUID) -> ArtifactRegistration: ...

    async def transition_status(
        self,
        artifact_id: UUID,
        *,
        expected_status: str,
        target_status: str,
        changed_at: datetime,
    ) -> ArtifactRegistration: ...

    async def transition_status_in_transaction(
        self,
        session: AsyncSession,
        artifact_id: UUID,
        *,
        tenant_id: str,
        expected_status: str,
        target_status: str,
        changed_at: datetime,
    ) -> ArtifactRegistration: ...
