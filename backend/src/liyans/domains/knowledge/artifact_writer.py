from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from liyans_contracts.artifacts import ArtifactObjectRefV1
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.infrastructure.database.models import ArtifactStatus
from liyans.infrastructure.persistence.artifacts import (
    ArtifactObjectStore,
    ArtifactRegistration,
)
from liyans.infrastructure.persistence.postgres_artifacts import PostgresArtifactRepository

from .entities import StagedArtifact


class KnowledgeArtifactWriter:
    def __init__(
        self,
        repository: PostgresArtifactRepository,
        object_store: ArtifactObjectStore,
    ) -> None:
        self._repository = repository
        self._object_store = object_store

    async def stage(
        self,
        *,
        artifact_id: UUID,
        tenant_id: str,
        object_key: str,
        media_type: Literal[
            "application/json",
            "application/x-ndjson",
            "text/markdown",
            "text/plain",
            "application/octet-stream",
        ],
        content_encoding: Literal["identity", "gzip"],
        content: bytes,
        created_by_subject: str,
        created_at: datetime,
        provenance: dict[str, object],
    ) -> StagedArtifact:
        stored = await self._object_store.put(
            tenant_id=tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        reference = ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=object_key,
            media_type=media_type,
            content_encoding=content_encoding,
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=created_at,
        )
        return StagedArtifact(
            registration=ArtifactRegistration(
                artifact_id=artifact_id,
                tenant_id=tenant_id,
                schema_version="topic4.c2-artifact.v1",
                artifact_version=1,
                resource_type="Lecturer_Doc",
                storage_namespace=reference.storage_namespace,
                object_key=reference.object_key,
                media_type=reference.media_type,
                content_encoding=reference.content_encoding,
                byte_size=reference.byte_size,
                sha256=reference.sha256,
                created_by_subject=created_by_subject,
                provenance=dict(provenance),
                created_at=created_at,
                updated_at=created_at,
            ),
            reference=reference,
        )

    async def register_verified(
        self,
        session: AsyncSession,
        artifacts: tuple[StagedArtifact, ...],
        *,
        tenant_id: str,
        verified_at: datetime,
    ) -> None:
        for artifact in artifacts:
            if artifact.registration.tenant_id != tenant_id:
                raise ValueError("artifact registration crosses the transaction tenant")
            await self._repository.add(session, artifact.registration)
            await self._repository.transition_status_in_transaction(
                session,
                artifact.registration.artifact_id,
                tenant_id=tenant_id,
                expected_status=ArtifactStatus.STAGED.value,
                target_status=ArtifactStatus.VERIFIED.value,
                changed_at=verified_at,
            )

    async def read(self, tenant_id: str, reference: ArtifactObjectRefV1) -> bytes:
        return await self._object_store.read(
            tenant_id=tenant_id,
            storage_namespace=reference.storage_namespace,
            object_key=reference.object_key,
            expected_byte_size=reference.byte_size,
            expected_sha256=reference.sha256,
        )
