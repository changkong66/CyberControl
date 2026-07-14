from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.tenant import tenant_scope
from liyans.infrastructure.database import session_context_from_tenant
from liyans.infrastructure.database.models import ArtifactModel, OutboxMessageModel
from liyans.infrastructure.persistence import (
    ArtifactRegistration,
    ArtifactService,
    FileSystemArtifactObjectStore,
    OutboxMessage,
    PostgresArtifactRepository,
    PostgresOutboxRepository,
)

from .support import make_envelope

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_artifact_object_metadata_and_outbox_commit_atomically(
    postgres_runtime,
    tmp_path,
) -> None:
    database, _migrator, context = postgres_runtime
    repository = PostgresArtifactRepository(database)
    outbox = PostgresOutboxRepository(database)
    service = ArtifactService(
        database,
        repository,
        FileSystemArtifactObjectStore(tmp_path),
        outbox=outbox,
    )
    now = datetime.now(UTC)
    envelope = make_envelope(context.tenant_id, now)
    registration = ArtifactRegistration(
        artifact_id=uuid4(),
        tenant_id=context.tenant_id,
        schema_version="artifact.object.ref.v1",
        artifact_version=1,
        resource_type="Lecturer_Doc",
        storage_namespace="candidate-v1",
        object_key="lecturer/lesson.md",
        media_type="text/markdown",
        content_encoding="identity",
        byte_size=0,
        sha256="",
        created_by_subject=context.subject_ref,
        provenance={"test": "postgres-artifact"},
    )
    outbox_message = OutboxMessage(
        outbox_id=uuid4(),
        tenant_id=context.tenant_id,
        envelope=envelope,
        created_at=now,
        available_at=now,
        published_at=None,
        max_attempts=envelope.delivery.max_attempts,
    )
    transition_envelope = make_envelope(context.tenant_id, now, sequence=1)
    transition_message = OutboxMessage(
        outbox_id=uuid4(),
        tenant_id=context.tenant_id,
        envelope=transition_envelope,
        created_at=now,
        available_at=now,
        published_at=None,
        max_attempts=transition_envelope.delivery.max_attempts,
    )

    with tenant_scope(context):
        stored = await service.stage(
            registration,
            b"# Immutable lesson",
            outbox_message=outbox_message,
        )
        restored, content = await service.read(stored.artifact_id)
        verified = await service.transition_status(
            stored.artifact_id,
            expected_status="STAGED",
            target_status="VERIFIED",
            changed_at=datetime.now(UTC),
            outbox_message=transition_message,
        )

    assert content == b"# Immutable lesson"
    assert restored.sha256 == stored.sha256
    assert verified.status == "VERIFIED"
    async with database.transaction(context=session_context_from_tenant(context)) as session:
        artifact_count = len((await session.execute(select(ArtifactModel))).scalars().all())
        outbox_rows = (
            (
                await session.execute(
                    select(OutboxMessageModel).where(
                        OutboxMessageModel.outbox_id.in_(
                            {outbox_message.outbox_id, transition_message.outbox_id}
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    assert artifact_count >= 1
    assert len(outbox_rows) == 2


@pytest.mark.asyncio
async def test_artifact_repository_hides_other_tenant_rows(
    postgres_runtime,
    tmp_path,
) -> None:
    database, _migrator, context = postgres_runtime
    repository = PostgresArtifactRepository(database)
    service = ArtifactService(
        database,
        repository,
        FileSystemArtifactObjectStore(tmp_path),
    )
    registration = ArtifactRegistration(
        artifact_id=uuid4(),
        tenant_id=context.tenant_id,
        schema_version="artifact.object.ref.v1",
        artifact_version=1,
        resource_type="MindMap",
        storage_namespace="candidate-v1",
        object_key="mindmap/graph.mmd",
        media_type="text/plain",
        content_encoding="identity",
        byte_size=0,
        sha256="",
        created_by_subject=context.subject_ref,
    )
    with tenant_scope(context):
        stored = await service.stage(registration, b"graph TD; A-->B")

    attacker = replace(context, tenant_id=f"other-{uuid4().hex[:16]}")
    with tenant_scope(attacker), pytest.raises(LiyanError) as error:
        await repository.get(stored.artifact_id)

    assert error.value.code == ErrorCode.ARTIFACT_NOT_FOUND
