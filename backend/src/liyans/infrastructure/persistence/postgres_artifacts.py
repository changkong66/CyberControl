from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant, current_tenant
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import ArtifactModel, ArtifactStatus
from liyans.infrastructure.database.session import DatabaseSessionManager
from liyans.infrastructure.persistence.artifacts import ArtifactRegistration

ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    ArtifactStatus.STAGED.value: frozenset(
        {ArtifactStatus.VERIFIED.value, ArtifactStatus.REJECTED.value}
    ),
    ArtifactStatus.VERIFIED.value: frozenset(
        {ArtifactStatus.PUBLISHED.value, ArtifactStatus.REJECTED.value}
    ),
    ArtifactStatus.PUBLISHED.value: frozenset({ArtifactStatus.SUPERSEDED.value}),
    ArtifactStatus.REJECTED.value: frozenset({ArtifactStatus.DELETED.value}),
    ArtifactStatus.SUPERSEDED.value: frozenset({ArtifactStatus.DELETED.value}),
    ArtifactStatus.DELETED.value: frozenset(),
}


class PostgresArtifactRepository:
    def __init__(self, database: DatabaseSessionManager) -> None:
        self._database = database

    async def add(self, session: AsyncSession, artifact: ArtifactRegistration) -> None:
        assert_tenant(artifact.tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Artifact registration requires an active transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        self._validate(artifact)
        now = artifact.created_at or datetime.now(UTC)
        session.add(
            ArtifactModel(
                artifact_id=artifact.artifact_id,
                tenant_id=artifact.tenant_id,
                schema_version=artifact.schema_version,
                artifact_version=artifact.artifact_version,
                resource_type=artifact.resource_type,
                status=artifact.status,
                storage_namespace=artifact.storage_namespace,
                object_key=artifact.object_key,
                media_type=artifact.media_type,
                content_encoding=artifact.content_encoding,
                byte_size=artifact.byte_size,
                sha256=artifact.sha256,
                source_envelope_id=artifact.source_envelope_id,
                blueprint_id=artifact.blueprint_id,
                blueprint_version=artifact.blueprint_version,
                candidate_id=artifact.candidate_id,
                candidate_version=artifact.candidate_version,
                block_id=artifact.block_id,
                provenance=dict(artifact.provenance),
                created_by_subject=artifact.created_by_subject,
                created_at=now,
                updated_at=artifact.updated_at or now,
                published_at=artifact.published_at,
            )
        )
        await session.flush()

    async def get(self, artifact_id: UUID) -> ArtifactRegistration:
        tenant_id = current_tenant().tenant_id
        async with self._database.transaction(context=current_session_context()) as session:
            result = await session.execute(
                select(ArtifactModel).where(
                    ArtifactModel.tenant_id == tenant_id,
                    ArtifactModel.artifact_id == artifact_id,
                )
            )
            row = result.scalar_one_or_none()
        if row is None:
            raise self._not_found()
        return self._to_registration(row)

    async def transition_status(
        self,
        artifact_id: UUID,
        *,
        expected_status: str,
        target_status: str,
        changed_at: datetime,
    ) -> ArtifactRegistration:
        tenant_id = current_tenant().tenant_id
        async with self._database.transaction(context=current_session_context()) as session:
            return await self.transition_status_in_transaction(
                session,
                artifact_id,
                tenant_id=tenant_id,
                expected_status=expected_status,
                target_status=target_status,
                changed_at=changed_at,
            )

    async def transition_status_in_transaction(
        self,
        session: AsyncSession,
        artifact_id: UUID,
        *,
        tenant_id: str,
        expected_status: str,
        target_status: str,
        changed_at: datetime,
    ) -> ArtifactRegistration:
        assert_tenant(tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Artifact transition requires an active transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        if changed_at.tzinfo is None:
            raise ValueError("changed_at must be timezone-aware")
        if target_status not in ALLOWED_STATUS_TRANSITIONS.get(expected_status, frozenset()):
            raise LiyanError(
                ErrorCode.ARTIFACT_CONFLICT,
                "The artifact lifecycle transition is not allowed.",
                category=ErrorCategory.CONTRACT,
                status_code=409,
            )
        values: dict[str, object] = {
            "status": target_status,
            "updated_at": changed_at,
        }
        if target_status == ArtifactStatus.PUBLISHED.value:
            values["published_at"] = changed_at
        if target_status == ArtifactStatus.DELETED.value:
            values["deleted_at"] = changed_at
        result = await session.execute(
            update(ArtifactModel)
            .where(
                ArtifactModel.tenant_id == tenant_id,
                ArtifactModel.artifact_id == artifact_id,
                ArtifactModel.status == expected_status,
            )
            .values(**values)
            .returning(ArtifactModel)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise LiyanError(
                ErrorCode.ARTIFACT_CONFLICT,
                "The artifact state changed concurrently or does not exist.",
                category=ErrorCategory.DATABASE,
                status_code=409,
            )
        return self._to_registration(row)

    @staticmethod
    def _validate(artifact: ArtifactRegistration) -> None:
        if artifact.status != ArtifactStatus.STAGED.value:
            raise ValueError("new artifact registrations must start in STAGED state")
        if artifact.byte_size < 1 or len(artifact.sha256) != 64:
            raise ValueError("artifact object metadata is invalid")
        if (artifact.candidate_id is None) != (artifact.candidate_version is None):
            raise ValueError("candidate identity and version must be supplied together")

    @staticmethod
    def _to_registration(row: ArtifactModel) -> ArtifactRegistration:
        return ArtifactRegistration(
            artifact_id=row.artifact_id,
            tenant_id=row.tenant_id,
            schema_version=row.schema_version,
            artifact_version=row.artifact_version,
            resource_type=row.resource_type,
            status=row.status,
            storage_namespace=row.storage_namespace,
            object_key=row.object_key,
            media_type=row.media_type,
            content_encoding=row.content_encoding,
            byte_size=row.byte_size,
            sha256=row.sha256,
            source_envelope_id=row.source_envelope_id,
            blueprint_id=row.blueprint_id,
            blueprint_version=row.blueprint_version,
            candidate_id=row.candidate_id,
            candidate_version=row.candidate_version,
            block_id=row.block_id,
            provenance=dict(row.provenance),
            created_by_subject=row.created_by_subject,
            created_at=row.created_at,
            updated_at=row.updated_at,
            published_at=row.published_at,
        )

    @staticmethod
    def _not_found() -> LiyanError:
        return LiyanError(
            ErrorCode.ARTIFACT_NOT_FOUND,
            "The artifact does not exist in the current tenant.",
            category=ErrorCategory.DATABASE,
            status_code=404,
        )
