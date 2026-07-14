from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant, current_tenant
from liyans.infrastructure.database.context import (
    current_session_context,
    session_context_from_tenant,
)
from liyans.infrastructure.database.session import DatabaseSessionManager
from liyans.infrastructure.persistence.artifacts import (
    ArtifactObjectStore,
    ArtifactRegistration,
    ArtifactRepository,
)

if TYPE_CHECKING:
    from liyans.infrastructure.persistence.outbox import OutboxMessage, OutboxRepository


class ArtifactService:
    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: ArtifactRepository,
        object_store: ArtifactObjectStore,
        *,
        outbox: OutboxRepository | None = None,
    ) -> None:
        self._database = database
        self._repository = repository
        self._object_store = object_store
        self._outbox = outbox

    async def stage(
        self,
        registration: ArtifactRegistration,
        content: bytes,
        *,
        outbox_message: OutboxMessage | None = None,
    ) -> ArtifactRegistration:
        assert_tenant(registration.tenant_id)
        if (outbox_message is None) != (self._outbox is None):
            raise ValueError("outbox repository and message must be supplied together")
        stored = await self._object_store.put(
            tenant_id=registration.tenant_id,
            storage_namespace=registration.storage_namespace,
            object_key=registration.object_key,
            content=content,
        )
        if registration.byte_size not in {0, stored.byte_size} or registration.sha256 not in {
            "",
            stored.sha256,
        }:
            raise LiyanError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "The artifact registration does not match the immutable object content.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            )
        normalized = replace(
            registration,
            byte_size=stored.byte_size,
            sha256=stored.sha256,
        )
        async with self._database.transaction(context=current_session_context()) as session:
            await self._repository.add(session, normalized)
            if self._outbox is not None and outbox_message is not None:
                if outbox_message.tenant_id != normalized.tenant_id:
                    raise ValueError("artifact and outbox tenant identities must match")
                await self._outbox.append(session, outbox_message)
        return normalized

    async def read(self, artifact_id: UUID) -> tuple[ArtifactRegistration, bytes]:
        registration = await self._repository.get(artifact_id)
        content = await self._object_store.read(
            tenant_id=registration.tenant_id,
            storage_namespace=registration.storage_namespace,
            object_key=registration.object_key,
            expected_byte_size=registration.byte_size,
            expected_sha256=registration.sha256,
        )
        return registration, content

    async def transition_status(
        self,
        artifact_id: UUID,
        *,
        expected_status: str,
        target_status: str,
        changed_at: datetime,
        outbox_message: OutboxMessage | None = None,
    ) -> ArtifactRegistration:
        if (outbox_message is None) != (self._outbox is None):
            raise ValueError("outbox repository and message must be supplied together")
        context = current_tenant()
        if outbox_message is not None:
            assert_tenant(outbox_message.tenant_id)
        async with self._database.transaction(
            context=session_context_from_tenant(context)
        ) as session:
            artifact = await self._repository.transition_status_in_transaction(
                session,
                artifact_id,
                tenant_id=context.tenant_id,
                expected_status=expected_status,
                target_status=target_status,
                changed_at=changed_at,
            )
            if self._outbox is not None and outbox_message is not None:
                await self._outbox.append(session, outbox_message)
        return artifact
