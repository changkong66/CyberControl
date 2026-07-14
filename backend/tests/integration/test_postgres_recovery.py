from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.settings import get_settings
from liyans.core.tenant import tenant_scope
from liyans.infrastructure.database import session_context_from_tenant
from liyans.infrastructure.database.models import OutboxMessageModel, OutboxStatus
from liyans.infrastructure.messaging import PostgresIdempotencyStore
from liyans.infrastructure.messaging.idempotency import ReservationDecision
from liyans.infrastructure.persistence import OutboxMessage, PostgresOutboxRepository
from liyans.infrastructure.security import AuthenticatedPrincipal
from liyans.main import create_app

from .support import make_envelope

pytestmark = pytest.mark.integration


class StaticTokenVerifier:
    def __init__(self, principal: AuthenticatedPrincipal) -> None:
        self._principal = principal

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        if token != "integration-token":
            raise LiyanError(
                ErrorCode.AUTH_TOKEN_INVALID,
                "The bearer token is invalid or expired.",
                category=ErrorCategory.AUTH,
                status_code=401,
            )
        return self._principal


@pytest.mark.asyncio
async def test_outbox_expired_worker_lease_is_recovered(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    now = datetime.now(UTC)
    envelope = make_envelope(context.tenant_id, now)
    message = OutboxMessage(
        outbox_id=uuid4(),
        tenant_id=context.tenant_id,
        envelope=envelope,
        created_at=now,
        available_at=now,
        published_at=None,
        max_attempts=envelope.delivery.max_attempts,
    )
    repository = PostgresOutboxRepository(database, claim_lease_seconds=0.05)
    with tenant_scope(context):
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            await repository.append(session, message)
        first_claim = await repository.claim_batch("worker-a", 1)
        assert [item.outbox_id for item in first_claim] == [message.outbox_id]
        await asyncio.sleep(0.08)
        second_claim = await repository.claim_batch("worker-b", 1)
        assert [item.outbox_id for item in second_claim] == [message.outbox_id]
        assert second_claim[0].attempts == 2

        with pytest.raises(LiyanError):
            await repository.mark_published(message.outbox_id, "worker-a", datetime.now(UTC))
        await repository.mark_published(
            message.outbox_id,
            "worker-b",
            datetime.now(UTC),
        )
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            state = await session.scalar(
                select(OutboxMessageModel.state).where(
                    OutboxMessageModel.outbox_id == message.outbox_id
                )
            )
    assert state == OutboxStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_concurrent_idempotency_digest_conflict_has_one_winner(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    key = f"conflict:{context.tenant_id}:0000000000000000"
    first = PostgresIdempotencyStore(
        database,
        instance_id="digest-worker-a",
        retention_seconds=300,
        processing_lease_seconds=30,
    )
    second = PostgresIdempotencyStore(
        database,
        instance_id="digest-worker-b",
        retention_seconds=300,
        processing_lease_seconds=30,
    )
    with tenant_scope(context):
        results = await asyncio.gather(
            first.reserve(key, "a" * 64),
            second.reserve(key, "b" * 64),
            return_exceptions=True,
        )

    assert results.count(ReservationDecision.RESERVED) == 1
    failures = [result for result in results if isinstance(result, LiyanError)]
    assert len(failures) == 1
    assert failures[0].code == ErrorCode.MESSAGE_DUPLICATE_CONFLICT


@pytest.mark.asyncio
async def test_fastapi_restart_preserves_sse_sequence(
    postgres_runtime,
    monkeypatch,
) -> None:
    _database, _migrator, context = postgres_runtime
    runtime_url = os.getenv("LIYAN_TEST_DATABASE_URL")
    assert runtime_url is not None
    monkeypatch.setenv("LIYAN_DATABASE_URL", runtime_url)
    monkeypatch.setenv("LIYAN_SSE_CURSOR_SECRET", "s" * 32)
    monkeypatch.setenv("LIYAN_PROVIDER_POLICY_POLL_SECONDS", "60")
    monkeypatch.delenv("LIYAN_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("LIYAN_OIDC_AUDIENCE", raising=False)
    monkeypatch.delenv("LIYAN_OIDC_JWKS_URL", raising=False)
    get_settings.cache_clear()
    now = datetime.now(UTC)
    principal = AuthenticatedPrincipal(
        issuer="https://issuer.test",
        subject=context.subject_ref,
        tenant_id=context.tenant_id,
        roles=frozenset({"student"}),
        scopes=frozenset({"topic3:sse:publish"}),
        token_id="restart-token",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    async def publish(value: int) -> int:
        app = create_app()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
        ):
            app.state.token_verifier = StaticTokenVerifier(principal)
            app.state.auth_configured = True
            response = await client.post(
                "/internal/topic3/sse/events",
                headers={"authorization": "Bearer integration-token"},
                json={"event_type": "progress", "data": {"value": value}},
            )
        assert response.status_code == 200, response.text
        return int(response.json()["sequence"])

    first_sequence = await publish(1)
    second_sequence = await publish(2)
    get_settings.cache_clear()

    assert second_sequence == first_sequence + 1
