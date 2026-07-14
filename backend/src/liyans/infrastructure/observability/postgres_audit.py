from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from uuid import UUID

from sqlalchemy import select, text

from liyans.core.tenant import assert_tenant
from liyans.infrastructure.database.models import AuditEventModel
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    SessionExecutionContext,
)
from liyans.infrastructure.observability.audit import (
    GENESIS_HASH,
    AuditDraft,
    AuditRecord,
    build_audit_record,
)


class PostgresAuditStore:
    def __init__(self, database: DatabaseSessionManager) -> None:
        self._database = database

    async def append(self, draft: AuditDraft) -> AuditRecord:
        if draft.occurred_at.tzinfo is None:
            raise ValueError("audit occurred_at must be timezone-aware")
        draft = replace(draft, occurred_at=draft.occurred_at.astimezone(UTC))
        context = SessionExecutionContext(
            tenant_id=draft.tenant_id,
            subject_ref=draft.actor_ref,
            trace_id=draft.trace_id,
        )
        async with self._database.transaction(context=context) as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": f"audit:{draft.tenant_id}"},
            )
            result = await session.execute(
                select(AuditEventModel)
                .where(AuditEventModel.tenant_id == draft.tenant_id)
                .order_by(AuditEventModel.sequence.desc())
                .limit(1)
            )
            previous = result.scalar_one_or_none()
            sequence = 0 if previous is None else previous.sequence + 1
            previous_hash = GENESIS_HASH if previous is None else previous.event_hash
            record = build_audit_record(draft, sequence, previous_hash)
            session.add(
                AuditEventModel(
                    event_id=record.event_id,
                    tenant_id=record.tenant_id,
                    sequence=record.sequence,
                    category=record.category,
                    action=record.action,
                    outcome=record.outcome,
                    actor_ref=record.actor_ref,
                    target_ref=record.target_ref,
                    trace_id=record.trace_id,
                    envelope_id=self._envelope_uuid(record.envelope_id),
                    event_metadata=record.metadata,
                    occurred_at=record.occurred_at,
                    previous_hash=record.previous_hash,
                    event_hash=record.event_hash,
                )
            )
            await session.flush()
            return record

    async def records(self, tenant_id: str) -> list[AuditRecord]:
        context = assert_tenant(tenant_id)
        session_context = SessionExecutionContext(
            tenant_id=context.tenant_id,
            subject_ref=context.subject_ref,
            trace_id=context.trace_id,
        )
        async with self._database.transaction(context=session_context) as session:
            result = await session.execute(
                select(AuditEventModel)
                .where(AuditEventModel.tenant_id == tenant_id)
                .order_by(AuditEventModel.sequence)
            )
            return [self._to_record(row) for row in result.scalars()]

    @staticmethod
    def _envelope_uuid(value: str | None) -> UUID | None:
        return UUID(value) if value is not None else None

    @staticmethod
    def _to_record(row: AuditEventModel) -> AuditRecord:
        return AuditRecord(
            event_id=row.event_id,
            tenant_id=row.tenant_id,
            sequence=row.sequence,
            category=row.category,
            action=row.action,
            outcome=row.outcome,
            actor_ref=row.actor_ref,
            target_ref=row.target_ref,
            trace_id=row.trace_id,
            envelope_id=str(row.envelope_id) if row.envelope_id is not None else None,
            metadata=dict(row.event_metadata),
            occurred_at=row.occurred_at,
            previous_hash=row.previous_hash,
            event_hash=row.event_hash,
        )
