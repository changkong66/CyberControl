from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from liyans.core.errors import ErrorCode
from liyans.infrastructure.persistence.postgres_outbox_dispatcher import (
    PostgresOutboxDispatcherRepository,
)


def test_dispatcher_repository_rejects_invalid_lease_configuration() -> None:
    with pytest.raises(ValueError, match="claim_lease"):
        PostgresOutboxDispatcherRepository(object(), claim_lease_seconds=0)


def test_dispatcher_recovery_probe_is_bounded_by_the_claim_lease() -> None:
    repository = PostgresOutboxDispatcherRepository(object(), claim_lease_seconds=30)

    assert repository._recovery_interval == 1.0
    assert repository._next_recovery_at == 0.0
    assert repository._recovery_interval <= repository._claim_lease.total_seconds() / 2


@pytest.mark.asyncio
async def test_dispatcher_claim_and_renewal_inputs_are_bounded() -> None:
    repository = PostgresOutboxDispatcherRepository(object())

    with pytest.raises(ValueError, match="worker_id"):
        await repository.claim_batch("", 1)
    with pytest.raises(ValueError, match="claim limit"):
        await repository.claim_batch("worker", 0)
    with pytest.raises(ValueError, match="between one and 1000"):
        await repository.renew_claims((), "worker")
    with pytest.raises(ValueError, match="duplicates"):
        outbox_id = uuid4()
        await repository.renew_claims((outbox_id, outbox_id), "worker")
    with pytest.raises(ValueError, match="worker_id"):
        await repository.renew_claims((uuid4(),), "")


@pytest.mark.asyncio
async def test_dispatcher_rejects_naive_timestamps_before_database_access() -> None:
    repository = PostgresOutboxDispatcherRepository(object())

    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.mark_published(uuid4(), "worker", datetime.now())
    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.release_claim(uuid4(), "worker", datetime.now())


@pytest.mark.asyncio
async def test_dispatcher_rejects_empty_cursor_identity_and_exposes_claim_conflict() -> None:
    repository = PostgresOutboxDispatcherRepository(object())

    with pytest.raises(ValueError, match="tenant_id"):
        await repository.published_cursor("", "partition")
    with pytest.raises(ValueError, match="partition_key"):
        await repository.published_cursor("tenant-a", "")

    conflict = repository._claim_conflict()
    assert conflict.code == ErrorCode.DATABASE_TRANSACTION_STATE
    assert conflict.retriable is True
    assert conflict.status_code == 409
