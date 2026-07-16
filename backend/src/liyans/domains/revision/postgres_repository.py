from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository

from .models import (
    Topic4RevisionCycleModel,
    Topic4RevisionPatchModel,
    Topic4RevisionPlanModel,
)


class PostgresRevisionRepository:
    """Append-only C8 persistence boundary owned by the verifier domain."""

    def __init__(self, topic3_repository: PostgresTopic3Repository | None = None) -> None:
        self._topic3_repository = topic3_repository or PostgresTopic3Repository()

    @asynccontextmanager
    async def candidate_lock(
        self,
        session: AsyncSession,
        tenant_id: str,
        candidate_id: UUID,
    ) -> AsyncIterator[None]:
        self._assert_write(session, tenant_id)
        lock_key = f"liyans:topic4:c8:{tenant_id}:{candidate_id}"
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )
        yield

    async def find_completed_request(
        self,
        session: AsyncSession,
        tenant_id: str,
        revision_request_id: UUID,
    ) -> dict[str, Any] | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4RevisionCycleModel.cycle_document)
            .where(
                Topic4RevisionCycleModel.tenant_id == tenant_id,
                Topic4RevisionCycleModel.state == "COMPLETED",
                Topic4RevisionCycleModel.cycle_document["revision_request_id"].as_string()
                == str(revision_request_id),
            )
            .order_by(Topic4RevisionCycleModel.cycle_version.desc())
            .limit(1)
        )
        document = result.scalar_one_or_none()
        return None if document is None else dict(document)

    async def append_cycle(
        self,
        session: AsyncSession,
        tenant_id: str,
        cycle: Any,
        audit_event_id: UUID,
        document: dict[str, Any] | None = None,
    ) -> None:
        self._assert_write(session, tenant_id)
        session.add(
            Topic4RevisionCycleModel(
                revision_cycle_snapshot_id=uuid5(
                    cycle.revision_cycle_id,
                    f"cycle-snapshot:{cycle.version_cas}",
                ),
                tenant_id=tenant_id,
                revision_cycle_id=cycle.revision_cycle_id,
                cycle_version=cycle.version_cas,
                verification_id=cycle.verification_id,
                parent_verification_id=cycle.parent_verification_id,
                candidate_id=cycle.candidate_id,
                base_candidate_version=cycle.base_candidate_version,
                base_candidate_sha256=cycle.base_candidate_sha256,
                revision_round=cycle.revision_round,
                state=cycle.state.value,
                lock_token=cycle.lock_token,
                lock_owner=cycle.lock_owner,
                lock_expires_at=cycle.lock_expires_at,
                completed_at=cycle.completed_at,
                cycle_document={
                    "cycle": cycle.model_dump(mode="json"),
                    **(document or {}),
                },
                trace_id=cycle.trace_id,
                version_cas=cycle.version_cas,
                record_sha256=cycle.record_sha256,
                immutable=cycle.immutable,
                audit_event_id=audit_event_id,
                created_at=cycle.created_at,
            )
        )
        await session.flush()

    async def append_plan(
        self,
        session: AsyncSession,
        tenant_id: str,
        plan: Any,
        revision_cycle_version: int,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        session.add(
            Topic4RevisionPlanModel(
                revision_plan_record_id=uuid5(plan.revision_plan_id, "plan-record"),
                tenant_id=tenant_id,
                revision_plan_id=plan.revision_plan_id,
                revision_cycle_id=plan.revision_cycle_id,
                revision_cycle_version=revision_cycle_version,
                verification_id=plan.verification_id,
                candidate_id=plan.candidate_id,
                base_candidate_version=plan.base_candidate_version,
                base_candidate_sha256=plan.base_candidate_sha256,
                revision_round=plan.revision_round,
                target_agent=plan.target_agent.value,
                plan_sha256=plan.record_sha256,
                plan_document=plan.model_dump(mode="json"),
                trace_id=plan.trace_id,
                version_cas=plan.version_cas,
                record_sha256=plan.record_sha256,
                immutable=plan.immutable,
                audit_event_id=audit_event_id,
                created_at=plan.created_at,
            )
        )
        await session.flush()

    async def append_patch(
        self,
        session: AsyncSession,
        tenant_id: str,
        patch: Any,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        session.add(
            Topic4RevisionPatchModel(
                revision_patch_record_id=uuid5(patch.revision_patch_id, "patch-record"),
                tenant_id=tenant_id,
                revision_patch_id=patch.revision_patch_id,
                revision_plan_id=patch.revision_plan_id,
                block_id=patch.block_id,
                operation=patch.operation.value,
                base_block_sha256=patch.base_block_sha256,
                replacement_sha256=patch.replacement_sha256,
                patch_document=patch.model_dump(mode="json"),
                trace_id=patch.trace_id,
                version_cas=patch.version_cas,
                record_sha256=patch.record_sha256,
                immutable=patch.immutable,
                audit_event_id=audit_event_id,
                created_at=patch.created_at,
            )
        )
        await session.flush()

    @staticmethod
    def _assert_write(session: AsyncSession, tenant_id: str) -> None:
        assert_tenant(tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "C8 persistence requires an active transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
