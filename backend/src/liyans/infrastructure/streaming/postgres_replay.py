from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select, text

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.hashing import sha256_hex
from liyans.core.tenant import assert_tenant
from liyans.infrastructure.database.context import session_context_from_tenant
from liyans.infrastructure.database.models import SSEEventModel
from liyans.infrastructure.database.session import DatabaseSessionManager
from liyans.infrastructure.streaming.sse import SSEEvent


class PostgresSSEReplayLog:
    def __init__(
        self,
        database: DatabaseSessionManager,
        *,
        retention_seconds: float = 86_400,
    ) -> None:
        if retention_seconds <= 0:
            raise ValueError("SSE retention_seconds must be positive")
        self._database = database
        self._retention = timedelta(seconds=retention_seconds)

    async def append(
        self,
        tenant_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> SSEEvent:
        context = assert_tenant(tenant_id)
        now = datetime.now(UTC)
        async with self._database.transaction(
            context=session_context_from_tenant(context)
        ) as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": f"sse:{tenant_id}"},
            )
            result = await session.execute(
                select(func.max(SSEEventModel.sequence)).where(SSEEventModel.tenant_id == tenant_id)
            )
            maximum = result.scalar_one()
            sequence = 0 if maximum is None else maximum + 1
            event = SSEEvent(
                tenant_id=tenant_id,
                sequence=sequence,
                event_type=event_type,
                data=dict(data),
                emitted_at=now,
            )
            session.add(
                SSEEventModel(
                    event_id=uuid4(),
                    tenant_id=tenant_id,
                    sequence=sequence,
                    event_type=event_type,
                    data_document=event.data,
                    data_sha256=sha256_hex(event.data),
                    emitted_at=now,
                    expires_at=now + self._retention,
                )
            )
            await session.flush()
            return event

    async def replay(
        self,
        tenant_id: str,
        after_sequence: int | None,
    ) -> list[SSEEvent]:
        context = assert_tenant(tenant_id)
        now = datetime.now(UTC)
        async with self._database.transaction(
            context=session_context_from_tenant(context)
        ) as session:
            bounds = await session.execute(
                select(
                    func.min(SSEEventModel.sequence).filter(SSEEventModel.expires_at > now),
                    func.max(SSEEventModel.sequence),
                ).where(SSEEventModel.tenant_id == tenant_id)
            )
            minimum_retained, maximum_seen = bounds.one()
            self._validate_cursor(after_sequence, minimum_retained, maximum_seen)
            statement = (
                select(SSEEventModel)
                .where(
                    SSEEventModel.tenant_id == tenant_id,
                    SSEEventModel.expires_at > now,
                )
                .order_by(SSEEventModel.sequence)
            )
            if after_sequence is not None:
                statement = statement.where(SSEEventModel.sequence > after_sequence)
            result = await session.execute(statement)
            return [self._to_event(row) for row in result.scalars()]

    async def delete_expired(self, tenant_id: str, *, limit: int = 1000) -> int:
        if not 1 <= limit <= 10_000:
            raise ValueError("SSE expiry delete limit must be between one and 10000")
        context = assert_tenant(tenant_id)
        now = datetime.now(UTC)
        async with self._database.transaction(
            context=session_context_from_tenant(context)
        ) as session:
            maximum_sequence = (
                select(func.max(SSEEventModel.sequence))
                .where(SSEEventModel.tenant_id == tenant_id)
                .scalar_subquery()
            )
            expired_ids = (
                select(SSEEventModel.event_id)
                .where(
                    SSEEventModel.tenant_id == tenant_id,
                    SSEEventModel.expires_at <= now,
                    SSEEventModel.sequence < maximum_sequence,
                )
                .order_by(SSEEventModel.expires_at)
                .limit(limit)
            )
            result = await session.execute(
                delete(SSEEventModel).where(SSEEventModel.event_id.in_(expired_ids))
            )
            return result.rowcount

    @staticmethod
    def _validate_cursor(
        after_sequence: int | None,
        minimum_retained: int | None,
        maximum_seen: int | None,
    ) -> None:
        if after_sequence is None:
            return
        if maximum_seen is None or after_sequence > maximum_seen:
            raise LiyanError(
                ErrorCode.SSE_REPLAY_CURSOR_INVALID,
                "The SSE replay cursor is outside the known stream range.",
                category=ErrorCategory.MESSAGING,
                status_code=409,
            )
        cursor_is_stale = (
            minimum_retained is not None and after_sequence < minimum_retained - 1
        ) or (minimum_retained is None and after_sequence < maximum_seen)
        if cursor_is_stale:
            raise LiyanError(
                ErrorCode.SSE_REPLAY_CURSOR_INVALID,
                "The SSE replay cursor is older than the retained event window.",
                category=ErrorCategory.MESSAGING,
                status_code=409,
            )

    @staticmethod
    def _to_event(row: SSEEventModel) -> SSEEvent:
        return SSEEvent(
            tenant_id=row.tenant_id,
            sequence=row.sequence,
            event_type=row.event_type,
            data=dict(row.data_document),
            emitted_at=row.emitted_at,
        )
