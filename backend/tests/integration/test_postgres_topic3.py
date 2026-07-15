from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from liyans_contracts.enums import ResourceType
from liyans_contracts.topic1 import CourseStatus, KnowledgePointStatus
from liyans_contracts.topic3 import GenerationSessionState
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from topic3_support import generation_command

from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.core.tenant import tenant_scope
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic1.service import Topic1Service
from liyans.domains.topic2.memory import EbbinghausMemoryEngine
from liyans.domains.topic2.orchestrator import Topic2Orchestrator
from liyans.domains.topic2.path_planning import AdaptivePathPlanner
from liyans.domains.topic2.postgres_repository import PostgresTopic2Repository
from liyans.domains.topic2.profiling import SixDimensionProfileEngine
from liyans.domains.topic2.service import Topic2Service
from liyans.domains.topic3.agents import Topic3AgentRegistry
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.models import (
    Topic3AgentTaskModel,
    Topic3GeneratedCandidateModel,
    Topic3GenerationSessionModel,
    Topic3StreamChunkModel,
)
from liyans.domains.topic3.orchestrator import Topic3Orchestrator
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository
from liyans.domains.topic3.service import Topic3Service
from liyans.domains.topic3.streaming import Topic3StreamCoordinator
from liyans.infrastructure.database import session_context_from_tenant
from liyans.infrastructure.observability.audit import verify_audit_chain
from liyans.infrastructure.observability.postgres_audit import PostgresAuditStore
from liyans.infrastructure.persistence import PostgresOutboxRepository
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker
from liyans.providers.topic3 import Topic3ProviderRegistry

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
COURSE_ID = "CRS_ATC_001"
KP_ID = "KP_ATC_301_TRANSFER_FUNCTION"


def topic1_service(database) -> Topic1Service:
    return Topic1Service(
        database,
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="topic3-topic1-fixture",
    )


def topic2_runtime(database) -> Topic2Orchestrator:
    repository = PostgresTopic1Repository()
    persistence = Topic2Service(
        database,
        PostgresTopic2Repository(),
        repository,
        PostgresOutboxRepository(database),
        instance_id="topic3-topic2-fixture",
    )
    return Topic2Orchestrator(
        database,
        repository,
        persistence,
        SixDimensionProfileEngine(),
        EbbinghausMemoryEngine(),
        AdaptivePathPlanner(),
    )


async def seed_topic1(service: Topic1Service) -> None:
    await service.upsert_course(
        course_id=COURSE_ID,
        document={
            "course_code": "ATC",
            "title": "Automatic Control Theory",
            "description": "Classical automatic-control foundations.",
            "locale": "zh-CN",
            "academic_level": "UNDERGRADUATE",
            "credit_hours": 64,
            "status": CourseStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="topic3-topic1-course-0001",
    )
    await service.upsert_knowledge_point(
        course_id=COURSE_ID,
        kp_id=KP_ID,
        document={
            "title": "Transfer Function",
            "aliases": [],
            "summary": "Laplace-domain input-output model.",
            "learning_objectives": ["Derive transfer functions."],
            "category": "MODELING",
            "difficulty_level": 3,
            "difficulty_score": 0.52,
            "estimated_minutes": 120,
            "formula_signatures": ["G(s)=Y(s)/U(s)"],
            "tags": ["transfer-function"],
            "status": KnowledgePointStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="topic3-topic1-kp-0000001",
    )


@pytest.mark.asyncio
async def test_topic3_postgres_workflow_is_replayable_isolated_and_append_only(
    postgres_runtime,
) -> None:
    database, migrator, base_context = postgres_runtime
    context = replace(
        base_context,
        scopes=frozenset(
            {
                "topic2:learner:any",
                "topic3:learner:any",
                "topic3:admin",
            }
        ),
    )
    topic1 = topic1_service(database)
    topic2 = topic2_runtime(database)
    repository = PostgresTopic3Repository()
    service = Topic3Service(
        database,
        repository,
        PostgresOutboxRepository(database),
        instance_id="topic3-integration",
    )
    replay_log = InMemorySSEReplayLog(capacity_per_tenant=1000)
    provider_registry = Topic3ProviderRegistry(
        ProviderPolicyRegistry.load(ROOT / "config" / "providers.toml"),
        {},
    )
    orchestrator = Topic3Orchestrator(
        database,
        PostgresTopic1Repository(),
        topic2,
        service,
        ImmutableBlueprintPlanner(),
        Topic3AgentRegistry(provider_registry),
        Topic3StreamCoordinator(SSEBroker(replay_log)),
    )
    now = datetime.now(UTC)
    command = generation_command(resources=[ResourceType.MIND_MAP]).model_copy(
        update={
            "operation_id": uuid4(),
            "generation_session_id": uuid4(),
            "learner_ref": context.subject_ref,
            "target_kp_ids": [KP_ID],
            "learning_goal": "Master transfer-function topology.",
            "requested_at": now,
        }
    )
    with tenant_scope(context):
        await seed_topic1(topic1)
        await topic2.initialize_learner(
            learner_ref=context.subject_ref,
            course_id=COURSE_ID,
            operation_id=uuid4(),
            requested_at=now,
            idempotency_key="topic3-init-0000000000000000",
        )
        await topic2.generate_path(
            learner_ref=context.subject_ref,
            course_id=COURSE_ID,
            operation_id=uuid4(),
            requested_at=now,
            target_goal="Master transfer-function topology.",
            target_kp_ids=[KP_ID],
            idempotency_key="topic3-topic2-path-0000001",
        )
        prepared = await orchestrator.prepare(
            command,
            idempotency_key="topic3-workflow-integration-0001",
        )
        replayed = await orchestrator.prepare(
            command,
            idempotency_key="topic3-workflow-integration-0001",
        )
        result = await orchestrator.execute(command.generation_session_id)
        restored = await orchestrator.execute(command.generation_session_id)
        runtime = await service.load_runtime(command.generation_session_id)
        audit_records = await PostgresAuditStore(database).records(context.tenant_id)

    assert replayed == prepared
    assert result.state == GenerationSessionState.COMPLETED
    assert restored.candidates[0].candidate_sha256 == result.candidates[0].candidate_sha256
    assert runtime[0].session_version == 3
    assert len(runtime[4]) == 1
    assert len(runtime[5]) == 1
    assert verify_audit_chain(audit_records)
    assert any(record.category == "TOPIC3" for record in audit_records)
    events = await replay_log.replay(context.tenant_id, None)
    assert {event.event_type for event in events} >= {
        "topic3.generation.progress",
        "topic3.stream.chunk.staged",
    }

    async with database.transaction(context=session_context_from_tenant(context)) as session:
        assert (
            await session.scalar(select(func.count()).select_from(Topic3GenerationSessionModel))
            == 3
        )
        assert await session.scalar(select(func.count()).select_from(Topic3AgentTaskModel)) == 3
        assert (
            await session.scalar(select(func.count()).select_from(Topic3GeneratedCandidateModel))
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(Topic3StreamChunkModel)) >= 1

    other_context = replace(
        context,
        tenant_id=f"other-{uuid4().hex[:24]}",
        trace_id="d" * 32,
    )
    async with migrator.transaction(context=session_context_from_tenant(other_context)) as session:
        await session.execute(
            text(
                "INSERT INTO tenants (tenant_id, slug, display_name) "
                "VALUES (:tenant_id, :slug, :display_name)"
            ),
            {
                "tenant_id": other_context.tenant_id,
                "slug": other_context.tenant_id,
                "display_name": "Other Topic 3 Tenant",
            },
        )
    async with database.transaction(context=session_context_from_tenant(other_context)) as session:
        assert (
            await session.scalar(select(func.count()).select_from(Topic3GenerationSessionModel))
            == 0
        )

    with pytest.raises(DBAPIError):
        async with migrator.transaction(context=session_context_from_tenant(context)) as session:
            await session.execute(
                text(
                    "UPDATE topic3_generation_sessions SET state = 'FAILED' "
                    "WHERE generation_session_id = :session_id"
                ),
                {"session_id": command.generation_session_id},
            )
