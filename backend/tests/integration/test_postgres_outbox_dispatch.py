from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from liyans_contracts.envelope import MessagePriority, Topic3EnvelopeV1
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

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
async def test_dispatchers_claim_cross_tenant_partition_heads_without_overlap(
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
    assert claimed_target_ids == {messages[0].outbox_id, messages[2].outbox_id}

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
    for message in (messages[0], messages[2]):
        await repository.mark_published(
            message.outbox_id,
            owners[message.outbox_id],
            datetime.now(UTC),
        )

    next_claim = await repository.claim_batch("dispatcher-next", 1000)
    next_ids = {message.outbox_id for message in next_claim}
    assert {messages[1].outbox_id, messages[3].outbox_id} <= next_ids


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

    publisher = OutboxPublisher(
        PostgresOutboxDispatcherRepository(postgres_dispatcher),
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
