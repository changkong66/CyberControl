from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.infrastructure.persistence import OutboxMessage, PostgresOutboxRepository


class _Session:
    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.added: list[object] = []
        self.flushed = False

    def in_transaction(self) -> bool:
        return self.active

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed = True


def _context(tenant_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        subject_ref="subject-a",
        roles=frozenset({"system:test"}),
        scopes=frozenset({"topic3:dispatch"}),
        trace_id="a" * 32,
        session_id=uuid4(),
    )


def _message(make_envelope) -> OutboxMessage:
    now = datetime.now(UTC)
    envelope = make_envelope(0)
    return OutboxMessage(
        outbox_id=uuid4(),
        tenant_id=envelope.tenant_id,
        envelope=envelope,
        created_at=now,
        available_at=now,
        published_at=None,
        attempts=0,
        max_attempts=envelope.delivery.max_attempts,
    )


def test_postgres_outbox_repository_rejects_invalid_lease() -> None:
    with pytest.raises(ValueError, match="claim_lease"):
        PostgresOutboxRepository(object(), claim_lease_seconds=0)


@pytest.mark.asyncio
async def test_postgres_outbox_append_enforces_transaction_and_new_message_invariants(
    make_envelope,
) -> None:
    repository = PostgresOutboxRepository(object())
    message = _message(make_envelope)
    context = _context(message.tenant_id)

    with tenant_scope(context):
        with pytest.raises(LiyanError) as inactive:
            await repository.append(_Session(active=False), message)
        assert inactive.value.code == ErrorCode.DATABASE_TRANSACTION_STATE

        with pytest.raises(ValueError, match="pre-published"):
            await repository.append(
                _Session(active=True),
                replace(message, published_at=datetime.now(UTC)),
            )
        with pytest.raises(ValueError, match="max_attempts"):
            await repository.append(
                _Session(active=True),
                replace(message, max_attempts=message.max_attempts + 1),
            )
        with pytest.raises(ValueError, match="timezone-aware"):
            await repository.append(
                _Session(active=True),
                replace(message, created_at=datetime.now()),
            )


@pytest.mark.asyncio
async def test_postgres_outbox_dispatch_inputs_fail_before_database_access() -> None:
    repository = PostgresOutboxRepository(object())

    with pytest.raises(ValueError, match="worker_id"):
        await repository.claim_batch("", 1)
    with pytest.raises(ValueError, match="claim limit"):
        await repository.claim_batch("worker", 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.mark_published(uuid4(), "worker", datetime.now())
    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.release_claim(uuid4(), "worker", datetime.now())

    conflict = repository._claim_conflict()
    assert conflict.code == ErrorCode.DATABASE_TRANSACTION_STATE
    assert conflict.retriable is True
