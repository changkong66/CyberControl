from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.tenant import tenant_scope
from liyans.infrastructure.database import (
    session_context_from_tenant,
)
from liyans.infrastructure.database.models import (
    OutboxMessageModel,
    OutboxStatus,
    SSEEventModel,
    TenantModel,
    TenantStatus,
)
from liyans.infrastructure.messaging import PostgresIdempotencyStore
from liyans.infrastructure.messaging.idempotency import ReservationDecision
from liyans.infrastructure.observability.audit import AuditService, verify_audit_chain
from liyans.infrastructure.observability.postgres_audit import PostgresAuditStore
from liyans.infrastructure.persistence import OutboxMessage, PostgresOutboxRepository
from liyans.infrastructure.security import (
    AuthenticatedPrincipal,
    PostgresTenantAuthorizer,
)
from liyans.infrastructure.streaming import PostgresSSEReplayLog
from sqlalchemy import select, update

from .support import make_envelope

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_idempotency_persists_and_supports_lease_takeover(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    now = datetime.now(UTC)
    envelope = make_envelope(context.tenant_id, now)
    with tenant_scope(context):
        idempotency = PostgresIdempotencyStore(
            database,
            instance_id="integration-worker",
            retention_seconds=300,
            processing_lease_seconds=30,
        )
        assert (
            await idempotency.reserve(envelope.delivery.idempotency_key, "1" * 64)
            == ReservationDecision.RESERVED
        )
        await idempotency.mark_processing(envelope.delivery.idempotency_key, "1" * 64)
        await idempotency.complete(envelope.delivery.idempotency_key, "1" * 64)
        restarted_idempotency = PostgresIdempotencyStore(
            database,
            instance_id="integration-worker-restarted",
            retention_seconds=300,
            processing_lease_seconds=30,
        )
        assert (
            await restarted_idempotency.reserve(
                envelope.delivery.idempotency_key,
                "1" * 64,
            )
            == ReservationDecision.DUPLICATE_COMPLETED
        )
        with pytest.raises(LiyanError):
            await idempotency.reserve(envelope.delivery.idempotency_key, "2" * 64)

        retry_key = f"retry:{context.tenant_id}:0000000000000000"
        assert await idempotency.reserve(retry_key, "3" * 64) == ReservationDecision.RESERVED
        await idempotency.abort(retry_key, "3" * 64)
        assert await idempotency.reserve(retry_key, "3" * 64) == ReservationDecision.RESERVED

        takeover_key = f"takeover:{context.tenant_id}:0000000000000000"
        short_lease = PostgresIdempotencyStore(
            database,
            instance_id="short-lease-worker",
            retention_seconds=300,
            processing_lease_seconds=0.05,
        )
        assert await short_lease.reserve(takeover_key, "4" * 64) == ReservationDecision.RESERVED
        await asyncio.sleep(0.06)
        takeover = PostgresIdempotencyStore(
            database,
            instance_id="takeover-worker",
            retention_seconds=300,
            processing_lease_seconds=30,
        )
        assert await takeover.reserve(takeover_key, "4" * 64) == ReservationDecision.RESERVED
        with pytest.raises(LiyanError):
            await short_lease.mark_processing(takeover_key, "4" * 64)


@pytest.mark.asyncio
async def test_postgres_idempotency_allows_one_concurrent_reservation(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    key = f"concurrent:{context.tenant_id}:0000000000000000"
    with tenant_scope(context):
        stores = [
            PostgresIdempotencyStore(
                database,
                instance_id=f"concurrent-worker-{index}",
                retention_seconds=300,
                processing_lease_seconds=30,
            )
            for index in range(8)
        ]
        decisions = await asyncio.gather(*(store.reserve(key, "5" * 64) for store in stores))

    assert decisions.count(ReservationDecision.RESERVED) == 1
    assert decisions.count(ReservationDecision.DUPLICATE_BUFFERED) == 7


@pytest.mark.asyncio
async def test_postgres_outbox_is_atomic_and_claims_conditionally(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    now = datetime.now(UTC)
    envelope = make_envelope(context.tenant_id, now)
    with tenant_scope(context):
        outbox = PostgresOutboxRepository(database, claim_lease_seconds=30)
        outbox_message = OutboxMessage(
            outbox_id=uuid4(),
            tenant_id=context.tenant_id,
            envelope=envelope,
            created_at=now,
            available_at=now,
            published_at=None,
            max_attempts=envelope.delivery.max_attempts,
        )
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            await outbox.append(session, outbox_message)
        claimed = await outbox.claim_batch("integration-dispatcher", 10)
        assert [message.outbox_id for message in claimed] == [outbox_message.outbox_id]
        await outbox.mark_published(
            outbox_message.outbox_id,
            "integration-dispatcher",
            datetime.now(UTC),
        )
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            state = await session.scalar(
                select(OutboxMessageModel.state).where(
                    OutboxMessageModel.outbox_id == outbox_message.outbox_id
                )
            )
        assert state == OutboxStatus.PUBLISHED.value

        rolled_back = OutboxMessage(
            outbox_id=uuid4(),
            tenant_id=context.tenant_id,
            envelope=envelope.model_copy(
                update={
                    "envelope_id": uuid4(),
                    "sequence": 1,
                    "delivery": envelope.delivery.model_copy(
                        update={
                            "idempotency_key": (f"rollback:{context.tenant_id}:0000000000000000")
                        }
                    ),
                }
            ),
            created_at=now,
            available_at=now,
            published_at=None,
        )
        with pytest.raises(RuntimeError, match="rollback"):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                await outbox.append(session, rolled_back)
                raise RuntimeError("rollback")
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            rolled_back_state = await session.scalar(
                select(OutboxMessageModel.state).where(
                    OutboxMessageModel.outbox_id == rolled_back.outbox_id
                )
            )
        assert rolled_back_state is None


@pytest.mark.asyncio
async def test_postgres_outbox_competing_workers_never_share_a_claim(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    now = datetime.now(UTC)
    outbox = PostgresOutboxRepository(database, claim_lease_seconds=30)
    with tenant_scope(context):
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            for sequence in range(10):
                envelope = make_envelope(
                    context.tenant_id,
                    now,
                    sequence=sequence,
                )
                await outbox.append(
                    session,
                    OutboxMessage(
                        outbox_id=uuid4(),
                        tenant_id=context.tenant_id,
                        envelope=envelope,
                        created_at=now,
                        available_at=now,
                        published_at=None,
                        max_attempts=envelope.delivery.max_attempts,
                    ),
                )
        first, second = await asyncio.gather(
            outbox.claim_batch("dispatcher-a", 10),
            outbox.claim_batch("dispatcher-b", 10),
        )

    claimed_ids = [message.outbox_id for message in [*first, *second]]
    assert len(claimed_ids) == 10
    assert len(set(claimed_ids)) == 10


@pytest.mark.asyncio
async def test_postgres_audit_chain_survives_store_recreation(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    with tenant_scope(context):
        audit_store = PostgresAuditStore(database)
        audit = AuditService(audit_store)
        await asyncio.gather(
            *(
                audit.record(
                    tenant_id=context.tenant_id,
                    category="INTEGRATION",
                    action=f"CONCURRENT_{index}",
                    outcome="SUCCEEDED",
                    actor_ref=context.subject_ref,
                    trace_id=context.trace_id,
                )
                for index in range(10)
            )
        )
        restarted_store = PostgresAuditStore(database)
        records = await restarted_store.records(context.tenant_id)
        assert [record.sequence for record in records] == list(range(10))
        assert verify_audit_chain(records)


@pytest.mark.asyncio
async def test_postgres_sse_replay_survives_store_recreation(postgres_runtime) -> None:
    database, migrator, context = postgres_runtime
    with tenant_scope(context):
        replay = PostgresSSEReplayLog(database, retention_seconds=300)
        first = await replay.append(context.tenant_id, "progress", {"value": 1})
        async with migrator.transaction(context=session_context_from_tenant(context)) as session:
            await session.execute(
                update(SSEEventModel)
                .where(
                    SSEEventModel.tenant_id == context.tenant_id,
                    SSEEventModel.sequence == first.sequence,
                )
                .values(
                    emitted_at=datetime.now(UTC) - timedelta(seconds=2),
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
        assert await replay.delete_expired(context.tenant_id) == 0
        second = await replay.append(context.tenant_id, "progress", {"value": 2})
        assert second.sequence == first.sequence + 1
        assert await replay.delete_expired(context.tenant_id) == 1
        restarted_replay = PostgresSSEReplayLog(database, retention_seconds=300)
        events = await restarted_replay.replay(context.tenant_id, first.sequence)
        assert [event.sequence for event in events] == [second.sequence]


@pytest.mark.asyncio
async def test_postgres_tenant_authorizer_enforces_binding_and_status(
    postgres_runtime,
) -> None:
    database, migrator, context = postgres_runtime
    authorizer = PostgresTenantAuthorizer(database)
    now = datetime.now(UTC)
    principal = AuthenticatedPrincipal(
        issuer="https://issuer.test",
        subject=context.subject_ref,
        tenant_id=context.tenant_id,
        roles=frozenset({"student"}),
        scopes=frozenset({"topic3:validate"}),
        token_id="integration-token",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    authorized = await authorizer.authorize(principal, trace_id=context.trace_id)
    assert authorized.tenant_id == context.tenant_id
    assert authorized.scopes == principal.scopes

    with pytest.raises(LiyanError):
        await authorizer.authorize(
            replace(principal, issuer="https://wrong-issuer.test"),
            trace_id=context.trace_id,
        )

    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        await session.execute(
            update(TenantModel)
            .where(TenantModel.tenant_id == context.tenant_id)
            .values(status=TenantStatus.SUSPENDED.value)
        )
    with pytest.raises(LiyanError) as suspended:
        await authorizer.authorize(principal, trace_id=context.trace_id)
    assert suspended.value.code == ErrorCode.TENANT_INACTIVE
