from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from liyans_contracts.enums import ResourceType
from liyans_contracts.topic3 import GenerationSessionState
from topic3_support import NOW, generation_command, graph_snapshot, personalization_context

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.entities import BlueprintRecord
from liyans.domains.topic3.service import Topic3Service
from liyans.infrastructure.security import AuthenticatedPrincipal
from liyans.infrastructure.tasks.queue import TaskPriority, TaskRequest
from liyans.main import create_app


class StubTokenVerifier:
    def __init__(self, scopes: frozenset[str]) -> None:
        self.scopes = scopes

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        if token != "test-token":
            raise LiyanError(
                ErrorCode.AUTH_TOKEN_INVALID,
                "The bearer token is invalid.",
                category=ErrorCategory.AUTH,
                status_code=401,
            )
        now = datetime.now(UTC)
        return AuthenticatedPrincipal(
            issuer="https://issuer.test",
            subject="subject:student",
            tenant_id="tenant-a",
            roles=frozenset({"student"}),
            scopes=self.scopes,
            token_id="topic3-test-jti",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )


class StubTenantAuthorizer:
    async def authorize(self, principal: AuthenticatedPrincipal, *, trace_id: str) -> TenantContext:
        return TenantContext(
            tenant_id=principal.tenant_id,
            subject_ref=principal.subject,
            roles=principal.roles,
            scopes=principal.scopes,
            trace_id=trace_id,
        )


class StubQueue:
    def __init__(self) -> None:
        self.requests: list[TaskRequest] = []

    async def enqueue(self, request: TaskRequest):
        self.requests.append(request)
        return None


class StubOrchestrator:
    def __init__(self) -> None:
        self.prepared = None

    async def prepare(self, command, *, idempotency_key: str):
        self.prepared = (command, idempotency_key)
        return {
            "generation_session_id": str(command.generation_session_id),
            "session_version": 1,
            "state": "PLANNED",
        }

    def queue_request(self, generation_session_id: UUID, context: TenantContext) -> TaskRequest:
        return TaskRequest(
            task_type="topic3.execute-workflow",
            tenant_id=context.tenant_id,
            task_id=generation_session_id,
            payload={"generation_session_id": str(generation_session_id)},
            priority=TaskPriority.NORMAL,
        )


class StubService:
    def __init__(self) -> None:
        graph = graph_snapshot()
        personalization = personalization_context(graph)
        command = generation_command(resources=[ResourceType.MIND_MAP])
        decision = ImmutableBlueprintPlanner().build(command, graph, personalization)
        self.command = command
        self.session = Topic3Service._session_record(
            command=command,
            graph=graph,
            personalization=personalization,
            session_version=1,
            parent_session_snapshot_id=None,
            state=GenerationSessionState.PLANNED,
            request_document={
                "command": command.model_dump(mode="json"),
                "personalization": personalization.model_dump(mode="json"),
            },
            result_document={
                "blueprint_id": str(decision.blueprint.blueprint_id),
                "blueprint_version": decision.blueprint.blueprint_version,
            },
            subject_ref=command.learner_ref,
            frozen_at=NOW,
        )
        self.blueprint = BlueprintRecord(
            blueprint_snapshot_id=uuid4(),
            blueprint=decision.blueprint,
            activation_document=decision.activation_document,
            created_by_subject=command.learner_ref,
            frozen_at=NOW,
        )
        self.tasks = [
            Topic3Service._pending_task(
                decision.blueprint.steps[0],
                decision.blueprint,
                command,
                NOW,
            )
        ]

    async def load_runtime(self, generation_session_id: UUID):
        if generation_session_id != self.command.generation_session_id:
            raise LiyanError(
                ErrorCode.TOPIC3_NOT_FOUND,
                "Missing generation.",
                category=ErrorCategory.CONTRACT,
                status_code=404,
            )
        return (
            self.session,
            self.command,
            personalization_context(graph_snapshot()),
            self.blueprint,
            self.tasks,
            [],
        )

    async def list_workflows(self, learner_ref: str, course_id: str, *, limit: int):
        del learner_ref, course_id, limit
        return [self.session]

    async def list_stream_chunks(self, stream_id, *, after_index, limit):
        del stream_id, after_index, limit
        return []


def install_stubs(app, scopes: frozenset[str]):
    orchestrator = StubOrchestrator()
    service = StubService()
    queue = StubQueue()
    app.state.token_verifier = StubTokenVerifier(scopes)
    app.state.tenant_authorizer = StubTenantAuthorizer()
    app.state.topic3_orchestrator = orchestrator
    app.state.topic3_service = service
    app.state.task_queue = queue
    return orchestrator, service, queue


def headers(*, idempotency_key: str = "topic3-api-idempotency-0001") -> dict[str, str]:
    return {
        "authorization": "Bearer test-token",
        "x-trace-id": "a" * 32,
        "Idempotency-Key": idempotency_key,
    }


@pytest.mark.asyncio
async def test_create_generation_uses_server_tenant_and_enqueues_workflow() -> None:
    app = create_app()
    orchestrator, _, queue = install_stubs(app, frozenset({"topic3:generation:write"}))
    command = generation_command(resources=[ResourceType.MIND_MAP])
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/internal/topic3/generations",
            headers=headers(),
            json=command.model_dump(mode="json"),
        )
    assert response.status_code == 202
    document = response.json()
    assert document["tenant_id"] == "tenant-a"
    assert document["subject_ref"] == "subject:student"
    assert document["payload"]["execution_state"] == "PLANNED"
    assert document["payload"]["dispatch_mode"] == "LOCAL_QUEUE"
    assert orchestrator.prepared[1] == "topic3-api-idempotency-0001"
    assert queue.requests[0].tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_create_generation_defers_to_durable_outbox_when_publisher_is_configured() -> None:
    app = create_app()
    _, _, queue = install_stubs(app, frozenset({"topic3:generation:write"}))
    app.state.outbox_publisher = object()
    command = generation_command(resources=[ResourceType.MIND_MAP])
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/internal/topic3/generations",
            headers=headers(),
            json=command.model_dump(mode="json"),
        )
    assert response.status_code == 202
    assert response.json()["payload"]["dispatch_mode"] == "DURABLE_OUTBOX"
    assert queue.requests == []


@pytest.mark.asyncio
async def test_generation_read_history_retry_and_chunk_endpoints() -> None:
    scopes = frozenset(
        {
            "topic3:generation:read",
            "topic3:generation:retry",
            "topic3:sse:read",
        }
    )
    app = create_app()
    _, service, queue = install_stubs(app, scopes)
    generation_id = service.command.generation_session_id
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        detail = await client.get(
            f"/internal/topic3/generations/{generation_id}",
            headers=headers(),
        )
        history = await client.get(
            "/internal/topic3/learners/subject:student/courses/CRS_ATC_001/generations",
            headers=headers(),
        )
        retry = await client.post(
            f"/internal/topic3/generations/{generation_id}/execute",
            headers=headers(),
        )
        chunks = await client.get(
            f"/internal/topic3/streams/{uuid4()}/chunks?after_index=-1&limit=10",
            headers=headers(),
        )
    assert detail.status_code == 200
    assert detail.json()["payload"]["tasks"][0]["state"] == "PENDING"
    assert history.status_code == 200
    assert len(history.json()["payload"]["sessions"]) == 1
    assert retry.status_code == 202
    assert len(queue.requests) == 1
    assert chunks.status_code == 200
    assert chunks.json()["payload"]["chunks"] == []


@pytest.mark.asyncio
async def test_generation_scope_and_missing_runtime_are_fail_closed() -> None:
    app = create_app()
    install_stubs(app, frozenset())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        forbidden = await client.get(
            f"/internal/topic3/generations/{uuid4()}",
            headers=headers(),
        )
    assert forbidden.status_code == 403

    unavailable_app = create_app()
    unavailable_app.state.token_verifier = StubTokenVerifier(frozenset({"topic3:generation:read"}))
    unavailable_app.state.tenant_authorizer = StubTenantAuthorizer()
    transport = httpx.ASGITransport(app=unavailable_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unavailable = await client.get(
            f"/internal/topic3/generations/{uuid4()}",
            headers=headers(),
        )
    assert unavailable.status_code == 503
