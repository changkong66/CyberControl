from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from liyans_contracts.envelope import MessagePriority, Topic3EnvelopeV1
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.infrastructure.database import SessionExecutionContext, session_context_from_tenant
from liyans.infrastructure.database.models import OutboxMessageModel, OutboxStatus
from liyans.infrastructure.messaging import PostgresIdempotencyStore
from liyans.infrastructure.messaging.bus import AsyncMessageBus
from liyans.infrastructure.persistence import (
    MessageBusOutboxSink,
    OutboxMessage,
    OutboxPublisher,
    PostgresOutboxDispatcherRepository,
    PostgresOutboxRepository,
)

from .support import make_envelope

pytestmark = pytest.mark.integration

DISPATCHER_UPDATE_COLUMNS = {
    "attempts",
    "available_at",
    "claim_expires_at",
    "claimed_at",
    "claimed_by",
    "last_error_code",
    "published_at",
    "state",
    "updated_at",
}


async def _provision_tenant(migrator, tenant_id: str) -> TenantContext:
    context = TenantContext(
        tenant_id=tenant_id,
        subject_ref="subject:dispatch-integration",
        roles=frozenset({"integration"}),
        scopes=frozenset({"test"}),
        trace_id="d" * 32,
    )
    async with migrator.transaction(
        context=SessionExecutionContext(
            tenant_id=tenant_id,
            subject_ref="system:integration-provisioner",
            trace_id=context.trace_id,
        )
    ) as session:
        await session.execute(
            text(
                "INSERT INTO tenants "
                "(tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim) "
                "VALUES (:tenant_id, :slug, :display_name, :issuer, :tenant_claim)"
            ),
            {
                "tenant_id": tenant_id,
                "slug": tenant_id,
                "display_name": "Dispatcher Integration Tenant",
                "issuer": "https://issuer.test",
                "tenant_claim": tenant_id,
            },
        )
    return context


def _dispatch_envelope(
    tenant_id: str,
    now: datetime,
    *,
    partition: str,
    sequence: int,
    max_attempts: int = 3,
) -> Topic3EnvelopeV1:
    envelope = make_envelope(tenant_id, now, sequence=sequence)
    document = envelope.model_dump(mode="python")
    document["partition_key"] = partition
    document["delivery"]["idempotency_key"] = (
        f"dispatch:{tenant_id}:{partition.rsplit(':', 1)[-1]}:{sequence:016d}"
    )
    document["delivery"]["priority"] = MessagePriority.CRITICAL
    document["delivery"]["max_attempts"] = max_attempts
    return Topic3EnvelopeV1.model_validate(document)


async def _append(
    database,
    context: TenantContext,
    *,
    partition: str,
    sequence: int,
    max_attempts: int = 3,
) -> OutboxMessage:
    now = datetime.now(UTC)
    envelope = _dispatch_envelope(
        context.tenant_id,
        now,
        partition=partition,
        sequence=sequence,
        max_attempts=max_attempts,
    )
    message = OutboxMessage(
        outbox_id=uuid4(),
        tenant_id=context.tenant_id,
        envelope=envelope,
        created_at=now,
        available_at=now,
        published_at=None,
        max_attempts=max_attempts,
    )
    repository = PostgresOutboxRepository(database)
    with tenant_scope(context):
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            await repository.append(session, message)
    return message


@pytest.mark.asyncio
async def test_dispatcher_role_has_only_required_outbox_permissions(
    postgres_dispatcher,
) -> None:
    async with postgres_dispatcher.transaction() as session:
        role = (
            await session.execute(
                text(
                    "SELECT rolsuper, rolinherit, rolcreaterole, rolcreatedb, "
                    "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
        table_grants = set(
            (
                await session.execute(
                    text(
                        "SELECT table_name, privilege_type "
                        "FROM information_schema.role_table_grants "
                        "WHERE grantee = current_user"
                    )
                )
            ).all()
        )
        update_columns = set(
            (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.role_column_grants "
                        "WHERE grantee = current_user AND table_name = 'outbox_messages' "
                        "AND privilege_type = 'UPDATE'"
                    )
                )
            ).scalars()
        )

    assert role == (False, False, False, False, False, False)
    assert table_grants == {("outbox_messages", "SELECT")}
    assert update_columns == DISPATCHER_UPDATE_COLUMNS

    with pytest.raises(DBAPIError):
        async with postgres_dispatcher.transaction() as session:
            await session.execute(text("SELECT count(*) FROM tenants"))
    with pytest.raises(DBAPIError):
        async with postgres_dispatcher.transaction() as session:
            await session.execute(
                text("UPDATE outbox_messages SET tenant_id = tenant_id WHERE false")
            )


@pytest.mark.asyncio
async def test_dispatchers_claim_cross_tenant_partition_windows_without_overlap(
    postgres_runtime,
    postgres_dispatcher,
) -> None:
    database, migrator, first_context = postgres_runtime
    second_context = await _provision_tenant(
        migrator,
        f"it-{uuid4().hex[:24]}",
    )
    first_partition = f"{first_context.tenant_id}:ordered"
    second_partition = f"{second_context.tenant_id}:ordered"
    messages = [
        await _append(database, first_context, partition=first_partition, sequence=0),
        await _append(database, first_context, partition=first_partition, sequence=1),
        await _append(database, second_context, partition=second_partition, sequence=0),
        await _append(database, second_context, partition=second_partition, sequence=1),
    ]
    repository = PostgresOutboxDispatcherRepository(postgres_dispatcher)
    first_claim, second_claim = await asyncio.gather(
        repository.claim_batch("dispatcher-a", 1000),
        repository.claim_batch("dispatcher-b", 1000),
    )
    first_ids = {message.outbox_id for message in first_claim}
    second_ids = {message.outbox_id for message in second_claim}
    target_ids = {message.outbox_id for message in messages}
    claimed_target_ids = (first_ids | second_ids) & target_ids

    assert first_ids.isdisjoint(second_ids)
    assert claimed_target_ids == target_ids

    owners = {
        message.outbox_id: "dispatcher-a"
        for message in first_claim
        if message.outbox_id in target_ids
    }
    owners.update(
        {
            message.outbox_id: "dispatcher-b"
            for message in second_claim
            if message.outbox_id in target_ids
        }
    )
    for message in messages:
        await repository.mark_published(
            message.outbox_id,
            owners[message.outbox_id],
            datetime.now(UTC),
        )

    next_claim = await repository.claim_batch("dispatcher-next", 1000)
    next_ids = {message.outbox_id for message in next_claim}
    assert target_ids.isdisjoint(next_ids)


@pytest.mark.asyncio
async def test_dispatcher_claims_contiguous_partition_window_in_one_batch(
    postgres_runtime,
    postgres_dispatcher,
) -> None:
    database, _migrator, context = postgres_runtime
    partition = f"{context.tenant_id}:contiguous-window"
    messages = [
        await _append(database, context, partition=partition, sequence=sequence)
        for sequence in range(4)
    ]

    repository = PostgresOutboxDispatcherRepository(postgres_dispatcher)
    claimed = await repository.claim_batch("window-worker", 1000)
    target_ids = {item.outbox_id for item in messages}
    target = [message for message in claimed if message.outbox_id in target_ids]

    assert [message.envelope.sequence for message in target] == [0, 1, 2, 3]
    for message in target:
        await repository.mark_published(
            message.outbox_id,
            "window-worker",
            datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_dispatcher_does_not_claim_follower_while_partition_head_is_claimed(
    postgres_runtime,
    postgres_dispatcher,
) -> None:
    database, _migrator, context = postgres_runtime
    partition = f"{context.tenant_id}:claimed-head"
    head = await _append(database, context, partition=partition, sequence=0)
    repository = PostgresOutboxDispatcherRepository(postgres_dispatcher)
    first_claim = await repository.claim_batch("head-worker", 1000)
    assert head.outbox_id in {message.outbox_id for message in first_claim}

    followers = [
        await _append(database, context, partition=partition, sequence=sequence)
        for sequence in (1, 2)
    ]
    blocked_claim = await repository.claim_batch("blocked-worker", 1000)
    follower_ids = {message.outbox_id for message in followers}
    assert follower_ids.isdisjoint(message.outbox_id for message in blocked_claim)

    await repository.mark_published(head.outbox_id, "head-worker", datetime.now(UTC))
    follower_claim = await repository.claim_batch("follower-worker", 1000)
    target = [message for message in follower_claim if message.outbox_id in follower_ids]
    assert [message.envelope.sequence for message in target] == [1, 2]
    for message in target:
        await repository.mark_published(
            message.outbox_id,
            "follower-worker",
            datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_dispatcher_never_claims_a_partition_with_missing_sequence_zero(
    postgres_runtime,
    postgres_dispatcher,
) -> None:
    database, _migrator, context = postgres_runtime
    gap_message = await _append(
        database,
        context,
        partition=f"{context.tenant_id}:missing-head",
        sequence=1,
    )

    repository = PostgresOutboxDispatcherRepository(postgres_dispatcher)
    claimed = await repository.claim_batch("gap-probe", 1000)

    assert gap_message.outbox_id not in {message.outbox_id for message in claimed}


@pytest.mark.asyncio
async def test_dispatcher_claim_mutations_require_the_current_worker_lease(
    postgres_runtime,
    postgres_dispatcher,
) -> None:
    database, _migrator, context = postgres_runtime
    message = await _append(
        database,
        context,
        partition=f"{context.tenant_id}:claim-owner",
        sequence=0,
    )
    repository = PostgresOutboxDispatcherRepository(postgres_dispatcher)
    claimed = await repository.claim_batch("owner-worker", 1000)
    assert message.outbox_id in {item.outbox_id for item in claimed}

    with pytest.raises(LiyanError) as publish_conflict:
        await repository.mark_published(
            message.outbox_id,
            "other-worker",
            datetime.now(UTC),
        )
    assert publish_conflict.value.code == ErrorCode.DATABASE_TRANSACTION_STATE

    with pytest.raises(LiyanError) as release_conflict:
        await repository.release_claim(
            message.outbox_id,
            "other-worker",
            datetime.now(UTC),
        )
    assert release_conflict.value.code == ErrorCode.DATABASE_TRANSACTION_STATE

    with pytest.raises(LiyanError) as renewal_conflict:
        await repository.renew_claims((message.outbox_id,), "other-worker")
    assert renewal_conflict.value.code == ErrorCode.DATABASE_TRANSACTION_STATE

    await repository.mark_published(
        message.outbox_id,
        "owner-worker",
        datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_outbox_failure_retries_then_enters_dead_state(
    postgres_runtime,
    postgres_dispatcher,
) -> None:
    database, _migrator, context = postgres_runtime
    message = await _append(
        database,
        context,
        partition=f"{context.tenant_id}:dead-letter",
        sequence=0,
        max_attempts=2,
    )

    async def failing_sink(_message: OutboxMessage) -> None:
        raise RuntimeError("injected delivery failure")

    repository = PostgresOutboxDispatcherRepository(postgres_dispatcher)
    publisher = OutboxPublisher(
        repository,
        failing_sink,
        worker_id="failure-injection",
        batch_size=1000,
        poll_interval_seconds=0.01,
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
    )
    await publisher.run_once()
    await asyncio.sleep(0.02)
    await publisher.run_once()

    with tenant_scope(context):
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            state, attempts = (
                await session.execute(
                    select(OutboxMessageModel.state, OutboxMessageModel.attempts).where(
                        OutboxMessageModel.outbox_id == message.outbox_id
                    )
                )
            ).one()
    assert state == OutboxStatus.DEAD.value
    assert attempts == 2


@pytest.mark.asyncio
async def test_cancelled_outbox_delivery_returns_claim_to_pending_immediately(
    postgres_runtime,
    postgres_dispatcher,
) -> None:
    database, _migrator, context = postgres_runtime
    partition = f"{context.tenant_id}:cancelled-delivery"
    messages = [
        await _append(database, context, partition=partition, sequence=sequence)
        for sequence in range(3)
    ]
    sink_started = asyncio.Event()

    async def blocking_sink(_message: OutboxMessage) -> None:
        sink_started.set()
        await asyncio.Event().wait()

    repository = PostgresOutboxDispatcherRepository(postgres_dispatcher)
    publisher = OutboxPublisher(
        repository,
        blocking_sink,
        worker_id="cancelled-delivery-worker",
        batch_size=1000,
    )
    task = asyncio.create_task(publisher.run_once())
    await sink_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with tenant_scope(context):
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            states = (
                await session.execute(
                    select(
                        OutboxMessageModel.outbox_id,
                        OutboxMessageModel.state,
                        OutboxMessageModel.attempts,
                        OutboxMessageModel.claimed_by,
                        OutboxMessageModel.claimed_at,
                        OutboxMessageModel.claim_expires_at,
                        OutboxMessageModel.last_error_code,
                    )
                    .where(
                        OutboxMessageModel.outbox_id.in_(
                            [message.outbox_id for message in messages]
                        )
                    )
                    .order_by(OutboxMessageModel.sequence)
                )
            ).all()
    assert states == [
        (
            messages[0].outbox_id,
            OutboxStatus.PENDING.value,
            1,
            None,
            None,
            None,
            "CancelledError",
        ),
        *[
            (
                message.outbox_id,
                OutboxStatus.PENDING.value,
                0,
                None,
                None,
                None,
                "CancelledError",
            )
            for message in messages[1:]
        ],
    ]

    cleanup_claim = await repository.claim_batch("cancel-cleanup-worker", 1000)
    target_ids = {message.outbox_id for message in messages}
    for message in cleanup_claim:
        if message.outbox_id in target_ids:
            await repository.mark_published(
                message.outbox_id,
                "cancel-cleanup-worker",
                datetime.now(UTC),
            )


@pytest.mark.asyncio
async def test_restart_recovers_claim_and_duplicate_completion_marks_outbox_published(
    postgres_runtime,
    postgres_dispatcher,
) -> None:
    database, _migrator, context = postgres_runtime
    message = await _append(
        database,
        context,
        partition=f"{context.tenant_id}:crash-window",
        sequence=0,
    )
    first_repository = PostgresOutboxDispatcherRepository(
        postgres_dispatcher,
        claim_lease_seconds=0.05,
    )
    claimed = await first_repository.claim_batch("crashed-worker", 1000)
    claimed_message = next(item for item in claimed if item.outbox_id == message.outbox_id)
    handler_calls = 0

    async def handler(_envelope: Topic3EnvelopeV1) -> None:
        nonlocal handler_calls
        handler_calls += 1

    first_bus = AsyncMessageBus(
        idempotency_store=PostgresIdempotencyStore(
            database,
            instance_id="before-crash",
        )
    )
    first_bus.register(message.envelope.event_type, handler)
    await MessageBusOutboxSink(first_bus, first_repository)(claimed_message)
    await first_bus.close()

    await asyncio.sleep(0.08)
    recovered_repository = PostgresOutboxDispatcherRepository(
        postgres_dispatcher,
        claim_lease_seconds=0.05,
    )
    restarted_bus = AsyncMessageBus(
        idempotency_store=PostgresIdempotencyStore(
            database,
            instance_id="after-crash",
        )
    )
    publisher = OutboxPublisher(
        recovered_repository,
        MessageBusOutboxSink(restarted_bus, recovered_repository),
        worker_id="recovered-worker",
        batch_size=1000,
        poll_interval_seconds=0.01,
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
    )
    await publisher.run_once()
    await restarted_bus.close()

    with tenant_scope(context):
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            state = await session.scalar(
                select(OutboxMessageModel.state).where(
                    OutboxMessageModel.outbox_id == message.outbox_id
                )
            )
    assert state == OutboxStatus.PUBLISHED.value
    assert handler_calls == 1
