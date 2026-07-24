from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from liyans.infrastructure.observability.metrics import PlatformMetrics
from liyans.infrastructure.persistence import OutboxMessage, OutboxPublisher


class FakeDispatchRepository:
    def __init__(self, messages: list[OutboxMessage] | None = None) -> None:
        self.messages = list(messages or [])
        self.published: list = []
        self.released: list = []
        self.claim_calls = 0

    async def claim_batch(self, worker_id: str, limit: int) -> list[OutboxMessage]:
        del worker_id
        self.claim_calls += 1
        claimed = self.messages[:limit]
        self.messages = self.messages[limit:]
        return claimed

    async def mark_published(self, outbox_id, worker_id, published_at) -> None:
        self.published.append((outbox_id, worker_id, published_at))

    async def release_claim(
        self,
        outbox_id,
        worker_id,
        available_at,
        *,
        error_code=None,
    ) -> None:
        self.released.append((outbox_id, worker_id, available_at, error_code))

    async def published_cursor(self, tenant_id: str, partition_key: str) -> int:
        del tenant_id, partition_key
        return 0


def _message(make_envelope, *, max_attempts: int = 3) -> OutboxMessage:
    now = datetime.now(UTC)
    envelope = make_envelope(0)
    if max_attempts != envelope.delivery.max_attempts:
        envelope = envelope.model_copy(
            update={"delivery": envelope.delivery.model_copy(update={"max_attempts": max_attempts})}
        )
    return OutboxMessage(
        outbox_id=uuid4(),
        tenant_id=envelope.tenant_id,
        envelope=envelope,
        created_at=now,
        available_at=now,
        published_at=None,
        attempts=1,
        max_attempts=max_attempts,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"worker_id": ""}, "worker_id"),
        ({"batch_size": 0}, "batch_size"),
        ({"delivery_timeout_seconds": 0}, "timing"),
    ],
)
def test_outbox_publisher_rejects_invalid_configuration(overrides, message) -> None:
    values = {"worker_id": "unit-worker", **overrides}
    with pytest.raises(ValueError, match=message):
        OutboxPublisher(FakeDispatchRepository(), AsyncMock(), **values)


@pytest.mark.asyncio
async def test_outbox_publisher_marks_success_and_exports_metrics(make_envelope) -> None:
    message = _message(make_envelope)
    repository = FakeDispatchRepository([message])
    delivered: list[OutboxMessage] = []
    metrics = PlatformMetrics()

    async def sink(item: OutboxMessage) -> None:
        delivered.append(item)

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="unit-worker",
        metrics=metrics,
    )

    assert await publisher.run_once() == 1
    assert delivered == [message]
    assert repository.published[0][0] == message.outbox_id
    assert b'operation="delivery",outcome="published"' in metrics.render()


@pytest.mark.asyncio
async def test_outbox_publisher_releases_failure_with_bounded_retry(make_envelope) -> None:
    message = _message(make_envelope, max_attempts=2)
    repository = FakeDispatchRepository([message])

    async def sink(_item: OutboxMessage) -> None:
        raise RuntimeError("injected")

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="unit-worker",
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
    )

    assert await publisher.run_once() == 1
    assert repository.published == []
    assert repository.released[0][0] == message.outbox_id
    assert repository.released[0][3] == "RuntimeError"


@pytest.mark.asyncio
async def test_outbox_publisher_cancellation_releases_claim_immediately(make_envelope) -> None:
    message = _message(make_envelope)
    repository = FakeDispatchRepository([message])
    sink_started = asyncio.Event()

    async def sink(_item: OutboxMessage) -> None:
        sink_started.set()
        await asyncio.Event().wait()

    publisher = OutboxPublisher(repository, sink, worker_id="unit-worker")
    task = asyncio.create_task(publisher.run_once())
    await sink_started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert repository.published == []
    assert repository.released[0][0] == message.outbox_id
    assert repository.released[0][3] == "CancelledError"


@pytest.mark.asyncio
async def test_outbox_publisher_timeout_releases_claim_for_retry(make_envelope) -> None:
    message = _message(make_envelope)
    repository = FakeDispatchRepository([message])

    async def sink(_item: OutboxMessage) -> None:
        await asyncio.Event().wait()

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="unit-worker",
        delivery_timeout_seconds=0.01,
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
    )

    assert await publisher.run_once() == 1
    assert repository.published == []
    assert repository.released[0][0] == message.outbox_id
    assert repository.released[0][3] == "TimeoutError"


@pytest.mark.asyncio
async def test_outbox_publisher_marks_dead_attempts_and_metrics(make_envelope) -> None:
    message = _message(make_envelope, max_attempts=1)
    repository = FakeDispatchRepository([message])
    metrics = PlatformMetrics()

    async def sink(_item: OutboxMessage) -> None:
        raise RuntimeError("terminal")

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="unit-worker",
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
        metrics=metrics,
    )

    assert await publisher.run_once() == 1
    rendered = metrics.render()
    assert repository.released[0][3] == "RuntimeError"
    assert b'operation="delivery",outcome="dead"' in rendered


@pytest.mark.asyncio
async def test_outbox_publisher_captures_loop_failures_and_recovers() -> None:
    class FailingRepository(FakeDispatchRepository):
        def __init__(self) -> None:
            super().__init__()
            self.fail_next = True

        async def claim_batch(self, worker_id: str, limit: int) -> list[OutboxMessage]:
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("claim failed")
            return await super().claim_batch(worker_id, limit)

    repository = FailingRepository()

    async def sink(_item: OutboxMessage) -> None:
        return None

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="background-worker",
        poll_interval_seconds=0.01,
    )
    await publisher.start()
    for _attempt in range(100):
        if publisher.last_error == "RuntimeError":
            break
        await asyncio.sleep(0.001)
    else:
        pytest.fail("publisher did not record the claim failure")
    publisher.wake()
    for _attempt in range(100):
        if publisher.healthy:
            break
        await asyncio.sleep(0.001)
    else:
        pytest.fail("publisher did not recover")
    await publisher.close()


@pytest.mark.asyncio
async def test_outbox_background_worker_becomes_healthy_and_closes() -> None:
    repository = FakeDispatchRepository()

    async def sink(_item: OutboxMessage) -> None:
        return None

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="background-worker",
        poll_interval_seconds=0.01,
    )
    await publisher.start()
    for _attempt in range(100):
        if publisher.healthy:
            break
        await asyncio.sleep(0.001)
    else:
        pytest.fail("publisher did not become healthy")
    publisher.wake()
    await publisher.close()

    assert publisher.running is False
    assert publisher.healthy is False
    assert repository.claim_calls >= 1


@pytest.mark.asyncio
async def test_outbox_background_worker_processes_then_polls_and_start_is_idempotent(
    make_envelope,
) -> None:
    message = _message(make_envelope)
    repository = FakeDispatchRepository([message])

    async def sink(_item: OutboxMessage) -> None:
        return None

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="background-worker",
        poll_interval_seconds=0.005,
    )
    await publisher.close()
    await publisher.start()
    await publisher.start()
    for _attempt in range(100):
        if repository.published:
            break
        await asyncio.sleep(0.001)
    else:
        pytest.fail("publisher did not publish the queued message")
    await asyncio.sleep(0.02)
    await publisher.close()

    assert repository.published[0][0] == message.outbox_id
    assert repository.claim_calls >= 2


@pytest.mark.asyncio
async def test_outbox_wake_during_empty_claim_is_not_lost() -> None:
    second_claim = asyncio.Event()
    publisher: OutboxPublisher

    class WakeDuringClaimRepository(FakeDispatchRepository):
        async def claim_batch(self, worker_id: str, limit: int) -> list[OutboxMessage]:
            result = await super().claim_batch(worker_id, limit)
            if self.claim_calls == 1:
                publisher.wake()
            elif self.claim_calls == 2:
                second_claim.set()
            return result

    repository = WakeDuringClaimRepository()

    async def sink(_item: OutboxMessage) -> None:
        return None

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="background-worker",
        poll_interval_seconds=10,
    )
    await publisher.start()

    await asyncio.wait_for(second_claim.wait(), timeout=0.2)
    await publisher.close()

    assert repository.claim_calls >= 2
