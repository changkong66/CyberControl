from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from liyans.core.errors import ErrorCode, LiyanError
from liyans.infrastructure.messaging.bus import DispatchStatus
from liyans.infrastructure.observability.metrics import PlatformMetrics
from liyans.infrastructure.persistence import MessageBusOutboxSink, OutboxMessage, OutboxPublisher


class FakeDispatchRepository:
    def __init__(self, messages: list[OutboxMessage] | None = None) -> None:
        self.messages = list(messages or [])
        self.published: list = []
        self.released: list = []
        self.renewed: list = []
        self.claim_calls = 0
        self.cursor_calls = 0

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
        restore_attempt=False,
    ) -> None:
        self.released.append((outbox_id, worker_id, available_at, error_code, restore_attempt))

    async def published_cursor(self, tenant_id: str, partition_key: str) -> int:
        del tenant_id, partition_key
        self.cursor_calls += 1
        return 0

    async def renew_claims(self, outbox_ids, worker_id):
        claim_expires_at = datetime.now(UTC) + timedelta(seconds=30)
        self.renewed.append((outbox_ids, worker_id, claim_expires_at))
        return claim_expires_at


def _message(
    make_envelope,
    *,
    sequence: int = 0,
    partition_key: str | None = None,
    max_attempts: int = 3,
    claim_expires_at: datetime | None = None,
) -> OutboxMessage:
    now = datetime.now(UTC)
    envelope = make_envelope(sequence)
    if partition_key is not None:
        envelope = envelope.model_copy(update={"partition_key": partition_key})
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
        claim_expires_at=claim_expires_at,
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
    original = _message(make_envelope)
    message = replace(original, claimed_at=original.created_at)
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
    rendered = metrics.render()
    assert b'operation="delivery",outcome="published"' in rendered
    assert b'stage="claim_batch"' in rendered
    assert b'stage="created_to_claimed"' in rendered
    assert b'stage="claimed_to_published"' in rendered
    assert b'stage="dispatch_to_published"' in rendered


@pytest.mark.asyncio
async def test_outbox_publisher_processes_partition_windows_in_sequence(make_envelope) -> None:
    first = _message(make_envelope, sequence=0)
    second = _message(make_envelope, sequence=1)
    other_partition = _message(
        make_envelope,
        sequence=0,
        partition_key="tenant-a:session-2",
    )
    repository = FakeDispatchRepository([second, other_partition, first])
    delivered: list[tuple[str, int]] = []

    async def sink(item: OutboxMessage) -> None:
        delivered.append((item.envelope.partition_key, item.envelope.sequence))

    publisher = OutboxPublisher(repository, sink, worker_id="unit-worker")

    assert await publisher.run_once() == 3

    assert delivered.index((first.envelope.partition_key, 0)) < delivered.index(
        (second.envelope.partition_key, 1)
    )
    assert {item[0] for item in delivered} == {
        first.envelope.partition_key,
        other_partition.envelope.partition_key,
    }
    assert {item[0] for item in repository.published} == {
        first.outbox_id,
        second.outbox_id,
        other_partition.outbox_id,
    }


@pytest.mark.asyncio
async def test_outbox_publisher_renews_partition_window_before_lease_expires(
    make_envelope,
) -> None:
    claim_expires_at = datetime.now(UTC) + timedelta(milliseconds=10)
    first = _message(
        make_envelope,
        sequence=0,
        claim_expires_at=claim_expires_at,
    )
    second = _message(
        make_envelope,
        sequence=1,
        claim_expires_at=claim_expires_at,
    )
    repository = FakeDispatchRepository([first, second])

    async def sink(_item: OutboxMessage) -> None:
        return None

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="unit-worker",
        delivery_timeout_seconds=1,
    )

    assert await publisher.run_once() == 2
    assert len(repository.renewed) == 1
    assert repository.renewed[0][0] == (first.outbox_id, second.outbox_id)


@pytest.mark.asyncio
async def test_outbox_publisher_releases_partition_tail_after_head_failure(
    make_envelope,
) -> None:
    first = _message(make_envelope, sequence=0)
    second = _message(make_envelope, sequence=1)
    repository = FakeDispatchRepository([first, second])

    async def sink(_item: OutboxMessage) -> None:
        raise RuntimeError("partition blocked")

    publisher = OutboxPublisher(
        repository,
        sink,
        worker_id="unit-worker",
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
    )

    assert await publisher.run_once() == 2

    released = {item[0]: item[3] for item in repository.released}
    assert released[first.outbox_id] == "RuntimeError"
    assert released[second.outbox_id] == "PartitionBlocked"
    restore_attempt = {item[0]: item[4] for item in repository.released}
    assert restore_attempt[first.outbox_id] is False
    assert restore_attempt[second.outbox_id] is True
    assert repository.published == []


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
    messages = [_message(make_envelope, sequence=sequence) for sequence in range(3)]
    repository = FakeDispatchRepository(messages)
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
    released = {item[0]: item for item in repository.released}
    assert set(released) == {message.outbox_id for message in messages}
    assert released[messages[0].outbox_id][3:] == ("CancelledError", False)
    assert released[messages[1].outbox_id][3:] == ("CancelledError", True)
    assert released[messages[2].outbox_id][3:] == ("CancelledError", True)


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


@pytest.mark.asyncio
async def test_message_bus_outbox_sink_fails_closed_on_identity_cursor_and_dispatch_state(
    make_envelope,
) -> None:
    class FakeBus:
        def __init__(self, status: DispatchStatus) -> None:
            self.status = status
            self.restored: list[tuple[str, str, int]] = []

        def restore_partition_cursor(self, tenant_id, partition_key, cursor) -> None:
            self.restored.append((tenant_id, partition_key, cursor))

        async def publish(self, _envelope):
            return SimpleNamespace(status=self.status)

    message = _message(make_envelope)
    repository = FakeDispatchRepository()
    sink = MessageBusOutboxSink(FakeBus(DispatchStatus.PROCESSED), repository)

    with pytest.raises(ValueError, match="tenant identities"):
        await sink(replace(message, tenant_id="tenant-b"))

    cursor_gap = _message(make_envelope, sequence=1)
    with pytest.raises(LiyanError) as gap:
        await sink(cursor_gap)
    assert gap.value.code == ErrorCode.MESSAGE_SEQUENCE_GAP

    buffered_bus = FakeBus(DispatchStatus.BUFFERED)
    buffered_sink = MessageBusOutboxSink(buffered_bus, repository)
    with pytest.raises(LiyanError) as buffered:
        await buffered_sink(message)
    assert buffered.value.code == ErrorCode.MESSAGE_SEQUENCE_GAP
    assert buffered_bus.restored == [(message.tenant_id, message.envelope.partition_key, 0)]


@pytest.mark.asyncio
async def test_message_bus_outbox_sink_uses_dispatcher_claim_cursor(make_envelope) -> None:
    class FakeBus:
        def restore_partition_cursor(self, _tenant_id, _partition_key, _cursor) -> None:
            return None

        async def publish(self, _envelope):
            return SimpleNamespace(status=DispatchStatus.PROCESSED)

    repository = FakeDispatchRepository()
    message = replace(_message(make_envelope), published_cursor=0)

    await MessageBusOutboxSink(FakeBus(), repository)(message)

    assert repository.cursor_calls == 0


@pytest.mark.asyncio
async def test_outbox_publisher_releases_partition_when_lease_renewal_fails(
    make_envelope,
) -> None:
    class RenewalFailureRepository(FakeDispatchRepository):
        async def renew_claims(self, outbox_ids, worker_id):
            del outbox_ids, worker_id
            raise RuntimeError("renewal failed")

    claim_expires_at = datetime.now(UTC) + timedelta(milliseconds=1)
    messages = [
        _message(
            make_envelope,
            sequence=sequence,
            claim_expires_at=claim_expires_at,
        )
        for sequence in range(2)
    ]
    repository = RenewalFailureRepository(messages)
    publisher = OutboxPublisher(
        repository,
        AsyncMock(),
        worker_id="unit-worker",
        delivery_timeout_seconds=1,
    )

    with pytest.raises(RuntimeError, match="renewal failed"):
        await publisher.run_once()

    assert {item[0] for item in repository.released} == {message.outbox_id for message in messages}
    assert all(item[3:] == ("LeaseRenewalFailed", True) for item in repository.released)


@pytest.mark.asyncio
async def test_outbox_publisher_logs_partial_tail_release_without_masking_failure(
    make_envelope,
) -> None:
    first = _message(make_envelope, sequence=0)
    second = _message(make_envelope, sequence=1)

    class PartialReleaseRepository(FakeDispatchRepository):
        async def release_claim(
            self,
            outbox_id,
            worker_id,
            available_at,
            *,
            error_code=None,
            restore_attempt=False,
        ) -> None:
            if outbox_id == second.outbox_id:
                raise RuntimeError("tail release failed")
            await super().release_claim(
                outbox_id,
                worker_id,
                available_at,
                error_code=error_code,
                restore_attempt=restore_attempt,
            )

    repository = PartialReleaseRepository([first, second])
    metrics = PlatformMetrics()

    async def fail_sink(_message: OutboxMessage) -> None:
        raise RuntimeError("delivery failed")

    publisher = OutboxPublisher(
        repository,
        fail_sink,
        worker_id="unit-worker",
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
        metrics=metrics,
    )

    assert await publisher.run_once() == 2
    assert {item[0] for item in repository.released} == {first.outbox_id}
    assert b'operation="delivery",outcome="claim_release_failed"' in metrics.render()


@pytest.mark.asyncio
async def test_outbox_publisher_claim_release_failure_is_observed_and_contained(
    make_envelope,
) -> None:
    class ReleaseFailureRepository(FakeDispatchRepository):
        async def release_claim(self, *_args, **_kwargs) -> None:
            raise RuntimeError("release failed")

    message = _message(make_envelope)
    repository = ReleaseFailureRepository([message])
    metrics = PlatformMetrics()

    async def fail_sink(_message: OutboxMessage) -> None:
        raise RuntimeError("delivery failed")

    publisher = OutboxPublisher(
        repository,
        fail_sink,
        worker_id="unit-worker",
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
        metrics=metrics,
    )

    assert await publisher.run_once() == 1
    assert b'operation="delivery",outcome="claim_release_failed"' in metrics.render()


@pytest.mark.asyncio
async def test_outbox_publisher_close_cancels_worker_after_timeout(monkeypatch) -> None:
    publisher = OutboxPublisher(
        FakeDispatchRepository(),
        AsyncMock(),
        worker_id="unit-worker",
    )
    task = asyncio.create_task(asyncio.Event().wait())
    publisher._task = task

    async def immediate_timeout(_awaitable, **kwargs):
        assert kwargs["timeout"] >= 5
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", immediate_timeout)

    await publisher.close()

    assert task.cancelled()
    assert publisher.running is False
