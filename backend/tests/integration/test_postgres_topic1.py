from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from liyans_contracts.topic1 import (
    AuthoritySourceRefV1,
    CourseStatus,
    GoldenQuestionType,
    KnowledgePointStatus,
    MisconceptionSeverity,
    PrerequisiteType,
    TextbookMappingType,
    Topic1CourseV1,
    Topic1GoldenQuestionV1,
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1ImportBundleV1,
    Topic1KnowledgePointV1,
    Topic1MisconceptionV1,
    Topic1PrerequisiteV1,
    Topic1TextbookMappingV1,
    Topic1TextbookSectionV1,
    Topic1TextbookV1,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.tenant import tenant_scope
from liyans.domains.topic1.models import Topic1GraphSnapshotModel
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic1.service import Topic1Service
from liyans.infrastructure.database import session_context_from_tenant
from liyans.infrastructure.database.models import AuditEventModel, OutboxMessageModel
from liyans.infrastructure.observability.audit import verify_audit_chain
from liyans.infrastructure.observability.postgres_audit import PostgresAuditStore
from liyans.infrastructure.persistence import PostgresOutboxRepository

pytestmark = pytest.mark.integration


def course_document() -> dict:
    return {
        "course_code": "ATC",
        "title": "Automatic Control Theory",
        "description": "Classical control foundations.",
        "locale": "zh-CN",
        "academic_level": "UNDERGRADUATE",
        "credit_hours": 64,
        "status": CourseStatus.ACTIVE,
        "authority_sources": [],
    }


def kp_document(title: str, score: float) -> dict:
    return {
        "title": title,
        "aliases": [],
        "summary": f"Canonical knowledge for {title}.",
        "learning_objectives": [f"Explain {title}."],
        "category": "CONTROL_THEORY",
        "difficulty_level": 2,
        "difficulty_score": score,
        "estimated_minutes": 90,
        "formula_signatures": ["G(s)=Y(s)/U(s)"],
        "tags": ["automatic-control"],
        "status": KnowledgePointStatus.ACTIVE,
        "authority_sources": [],
    }


def service_for(database) -> Topic1Service:
    return Topic1Service(
        database,
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="topic1-integration",
    )


def authority_source() -> AuthoritySourceRefV1:
    return AuthoritySourceRefV1(
        source_id="TEXTBOOK_ATC",
        source_version="5e",
        locator="chapter-2",
        content_sha256="a" * 64,
    )


def import_bundle() -> Topic1ImportBundleV1:
    now = datetime.now(UTC)
    course = Topic1CourseV1(
        course_id="CRS_ATC_001",
        revision=1,
        course_code="ATC",
        title="Automatic Control Theory",
        description="Classical control foundations.",
        credit_hours=64,
        status=CourseStatus.ACTIVE,
        authority_sources=[authority_source()],
        created_at=now,
        updated_at=now,
    )
    first = Topic1KnowledgePointV1(
        schema_version="topic1.knowledge-point.v1",
        kp_id="KP_ATC_301_传递函数",
        course_id=course.course_id,
        revision=1,
        title="Transfer Function",
        summary="Laplace-domain input-output model.",
        learning_objectives=["Derive transfer functions."],
        category="MODELING",
        difficulty_level=2,
        difficulty_score=0.4,
        topology_level=0,
        topology_weight=0,
        estimated_minutes=90,
        formula_signatures=["G(s)=Y(s)/U(s)"],
        status=KnowledgePointStatus.ACTIVE,
        authority_sources=[authority_source()],
        created_at=now,
        updated_at=now,
    )
    second = first.model_copy(
        update={
            "kp_id": "KP_ATC_302_时域响应",
            "title": "Time-Domain Response",
            "summary": "Transient and steady-state response analysis.",
        }
    )
    edge = Topic1PrerequisiteV1(
        edge_id="EDGE_ATC_001",
        course_id=course.course_id,
        prerequisite_kp_id=first.kp_id,
        dependent_kp_id=second.kp_id,
        relation_type=PrerequisiteType.REQUIRED,
        strength=1,
        rationale="Transfer functions precede response analysis.",
        revision=1,
        created_at=now,
        updated_at=now,
    )
    misconception = Topic1MisconceptionV1(
        misconception_id="MISCONCEPTION_ATC_001",
        kp_id=second.kp_id,
        title="Confusing pole and time constant signs",
        description="The sign of the pole is copied directly as the time constant.",
        trigger_pattern="Uses tau = pole instead of tau = -1/pole.",
        diagnosis_tags=["sign-error", "time-constant"],
        remediation_hint="Rewrite the first-order factor as tau*s + 1.",
        severity=MisconceptionSeverity.HIGH,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    textbook = Topic1TextbookV1(
        textbook_id="TEXTBOOK_ATC_001",
        title="Principles of Automatic Control",
        authors=["Control Faculty"],
        publisher="Higher Education Press",
        edition="5",
        isbn="9780000000001",
        publication_year=2025,
        authority_level=5,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    section = Topic1TextbookSectionV1(
        section_id="SECTION_ATC_001",
        textbook_id=textbook.textbook_id,
        chapter_number="2.1",
        title="Transfer Functions",
        start_page=30,
        end_page=48,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    mapping = Topic1TextbookMappingV1(
        mapping_id="MAPPING_ATC_001",
        kp_id=first.kp_id,
        section_id=section.section_id,
        mapping_type=TextbookMappingType.PRIMARY,
        coverage=1,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    question = Topic1GoldenQuestionV1(
        question_id="QUESTION_ATC_001",
        primary_kp_id=second.kp_id,
        related_kp_ids=[first.kp_id],
        question_type=GoldenQuestionType.CALCULATION,
        stem_markdown="Find the unit-step response of $1/(s+1)$.",
        answer_document={"expression": "1-exp(-t)"},
        solution_markdown="Use partial fractions and the inverse Laplace transform.",
        difficulty_level=2,
        discrimination=0.8,
        diagnostic_tags=["laplace", "step-response"],
        misconception_ids=[misconception.misconception_id],
        authority_sources=[authority_source()],
        revision=1,
        created_at=now,
        updated_at=now,
    )
    return Topic1ImportBundleV1(
        import_id=uuid4(),
        expected_parent_version=None,
        content=Topic1GraphContentV1(
            course=course,
            knowledge_points=[first, second],
            prerequisites=[edge],
            misconceptions=[misconception],
            textbooks=[textbook],
            textbook_sections=[section],
            textbook_mappings=[mapping],
            golden_questions=[question],
        ),
        requested_at=now,
    )


@pytest.fixture
def authoritative_seed_bundle() -> Topic1ImportBundleV1:
    repository_root = Path(__file__).resolve().parents[3]
    return Topic1ImportBundleV1.model_validate(
        json.loads(
            (repository_root / "data/topic1/automatic-control-principles.v1.json").read_text(
                encoding="utf-8"
            )
        )
    )


@pytest.mark.asyncio
async def test_topic1_service_commits_graph_audit_outbox_and_idempotency(
    postgres_runtime,
) -> None:
    database, migrator, context = postgres_runtime
    service = service_for(database)
    with tenant_scope(context):
        first = await service.upsert_course(
            course_id="CRS_ATC_001",
            document=course_document(),
            expected_revision=None,
            idempotency_key="topic1-course-create-0001",
        )
        duplicate = await service.upsert_course(
            course_id="CRS_ATC_001",
            document=course_document(),
            expected_revision=None,
            idempotency_key="topic1-course-create-0001",
        )
        assert duplicate == first
        await service.upsert_knowledge_point(
            course_id="CRS_ATC_001",
            kp_id="KP_ATC_301_传递函数",
            document=kp_document("Transfer Function", 0.35),
            expected_revision=None,
            idempotency_key="topic1-kp-create-0000001",
        )
        await service.upsert_knowledge_point(
            course_id="CRS_ATC_001",
            kp_id="KP_ATC_302_时域响应",
            document=kp_document("Time-Domain Response", 0.5),
            expected_revision=None,
            idempotency_key="topic1-kp-create-0000002",
        )
        await service.upsert_prerequisite(
            course_id="CRS_ATC_001",
            edge_id="EDGE_ATC_001",
            document={
                "prerequisite_kp_id": "KP_ATC_301_传递函数",
                "dependent_kp_id": "KP_ATC_302_时域响应",
                "relation_type": PrerequisiteType.REQUIRED,
                "strength": 1,
                "rationale": "Modeling precedes response analysis.",
            },
            expected_revision=None,
            idempotency_key="topic1-edge-create-00001",
        )
        graph = await service.get_graph("CRS_ATC_001")
        snapshots = await service.list_snapshots("CRS_ATC_001")

    levels = {item.kp_id: item.topology_level for item in graph.knowledge_points}
    assert levels == {"KP_ATC_301_传递函数": 0, "KP_ATC_302_时域响应": 1}
    assert [item.graph_version for item in snapshots] == [4, 3, 2, 1]
    async with migrator.transaction(context=session_context_from_tenant(context)) as session:
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.tenant_id == context.tenant_id)
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxMessageModel)
            .where(
                OutboxMessageModel.tenant_id == context.tenant_id,
                OutboxMessageModel.event_type == "topic1.graph.changed",
            )
        )
    assert audit_count == 4
    assert outbox_count == 4
    with tenant_scope(context):
        records = await PostgresAuditStore(database).records(context.tenant_id)
    assert verify_audit_chain(records)


@pytest.mark.asyncio
async def test_topic1_cycle_failure_rolls_back_without_new_snapshot(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    service = service_for(database)
    with tenant_scope(context):
        await service.upsert_course(
            course_id="CRS_ATC_001",
            document=course_document(),
            expected_revision=None,
            idempotency_key="cycle-course-create-0001",
        )
        for index, kp_id in enumerate(("KP_ATC_301_A", "KP_ATC_302_B"), start=1):
            await service.upsert_knowledge_point(
                course_id="CRS_ATC_001",
                kp_id=kp_id,
                document=kp_document(kp_id, 0.4),
                expected_revision=None,
                idempotency_key=f"cycle-kp-create-{index:012d}",
            )
        await service.upsert_prerequisite(
            course_id="CRS_ATC_001",
            edge_id="EDGE_ATC_001",
            document={
                "prerequisite_kp_id": "KP_ATC_301_A",
                "dependent_kp_id": "KP_ATC_302_B",
                "relation_type": PrerequisiteType.REQUIRED,
                "strength": 1,
                "rationale": "Forward edge.",
            },
            expected_revision=None,
            idempotency_key="cycle-edge-create-000001",
        )
        before = await service.list_snapshots("CRS_ATC_001")
        with pytest.raises(LiyanError) as error:
            await service.upsert_prerequisite(
                course_id="CRS_ATC_001",
                edge_id="EDGE_ATC_002",
                document={
                    "prerequisite_kp_id": "KP_ATC_302_B",
                    "dependent_kp_id": "KP_ATC_301_A",
                    "relation_type": PrerequisiteType.REQUIRED,
                    "strength": 1,
                    "rationale": "Reverse edge.",
                },
                expected_revision=None,
                idempotency_key="cycle-edge-create-000002",
            )
        after = await service.list_snapshots("CRS_ATC_001")
    assert error.value.code == ErrorCode.TOPIC1_CYCLE
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_topic1_import_round_trip_and_snapshot_immutability(postgres_runtime) -> None:
    database, migrator, context = postgres_runtime
    service = service_for(database)
    bundle = import_bundle()
    with tenant_scope(context):
        result = await service.import_bundle(
            bundle,
            idempotency_key="topic1-import-bundle-0001",
        )
        graph = await service.get_graph(bundle.content.course.course_id)
        snapshot_id = result["snapshot"]["snapshot_id"]
    assert len(graph.knowledge_points) == 2
    assert len(graph.misconceptions) == 1
    assert len(graph.textbooks) == 1
    assert len(graph.textbook_mappings) == 1
    assert len(graph.golden_questions) == 1
    with pytest.raises(DBAPIError):
        async with migrator.transaction(context=session_context_from_tenant(context)) as session:
            await session.execute(
                update(Topic1GraphSnapshotModel)
                .where(Topic1GraphSnapshotModel.snapshot_id == UUID(snapshot_id))
                .values(node_count=99)
            )


@pytest.mark.asyncio
async def test_topic1_rls_and_concurrent_revision_conflict(postgres_runtime) -> None:
    database, migrator, context = postgres_runtime
    service = service_for(database)
    with tenant_scope(context):
        await service.upsert_course(
            course_id="CRS_ATC_001",
            document=course_document(),
            expected_revision=None,
            idempotency_key="concurrency-course-00001",
        )
        outcomes = await asyncio.gather(
            service.upsert_course(
                course_id="CRS_ATC_001",
                document={**course_document(), "title": "Revision A"},
                expected_revision=1,
                idempotency_key="concurrency-course-a-001",
            ),
            service.upsert_course(
                course_id="CRS_ATC_001",
                document={**course_document(), "title": "Revision B"},
                expected_revision=1,
                idempotency_key="concurrency-course-b-001",
            ),
            return_exceptions=True,
        )
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    conflicts = [item for item in outcomes if isinstance(item, LiyanError)]
    assert len(conflicts) == 1
    assert conflicts[0].code == ErrorCode.TOPIC1_CONFLICT

    other = replace(
        context,
        tenant_id=f"other-{uuid4().hex[:20]}",
        subject_ref="subject:other",
    )
    async with migrator.transaction(context=session_context_from_tenant(other)) as session:
        await session.execute(
            text(
                "INSERT INTO tenants "
                "(tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim) "
                "VALUES (:tenant_id, :slug, 'Other Tenant', 'https://issuer.test', :tenant_id)"
            ),
            {"tenant_id": other.tenant_id, "slug": other.tenant_id},
        )
    with tenant_scope(other):
        assert await service.list_courses() == []


@pytest.mark.asyncio
async def test_topic1_full_mutation_lifecycle_and_error_boundaries(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    service = service_for(database)
    with tenant_scope(context):
        await service.upsert_course(
            course_id="CRS_ATC_001",
            document=course_document(),
            expected_revision=None,
            idempotency_key="lifecycle-course-000001",
        )
        for index, kp_id in enumerate(("KP_ATC_301_A", "KP_ATC_302_B"), start=1):
            await service.upsert_knowledge_point(
                course_id="CRS_ATC_001",
                kp_id=kp_id,
                document=kp_document(kp_id, 0.4),
                expected_revision=None,
                idempotency_key=f"lifecycle-kp-{index:013d}",
            )
        await service.upsert_prerequisite(
            course_id="CRS_ATC_001",
            edge_id="EDGE_ATC_001",
            document={
                "prerequisite_kp_id": "KP_ATC_301_A",
                "dependent_kp_id": "KP_ATC_302_B",
                "relation_type": PrerequisiteType.REQUIRED,
                "strength": 1,
                "rationale": "Forward edge.",
            },
            expected_revision=None,
            idempotency_key="lifecycle-edge-0000001",
        )
        assert (await service.get_course("CRS_ATC_001")).status == CourseStatus.ACTIVE
        graph = await service.get_graph("CRS_ATC_001")
        edge_revision = graph.prerequisites[0].revision
        snapshot_to_restore = (await service.list_snapshots("CRS_ATC_001"))[0]
        await service.delete_prerequisite(
            course_id="CRS_ATC_001",
            edge_id="EDGE_ATC_001",
            expected_revision=edge_revision,
            idempotency_key="lifecycle-edge-delete-01",
        )
        await service.freeze_graph(
            "CRS_ATC_001",
            idempotency_key="lifecycle-freeze-000001",
        )
        rollback = await service.rollback_snapshot(
            snapshot_to_restore.snapshot_id,
            idempotency_key="lifecycle-rollback-00001",
        )
        assert rollback["snapshot"]["restored_from_snapshot_id"] == str(
            snapshot_to_restore.snapshot_id
        )
        restored = await service.get_graph("CRS_ATC_001")
        second = next(item for item in restored.knowledge_points if item.kp_id == "KP_ATC_302_B")
        await service.delete_knowledge_point(
            course_id="CRS_ATC_001",
            kp_id=second.kp_id,
            expected_revision=second.revision,
            idempotency_key="lifecycle-kp-delete-0001",
        )
        with pytest.raises(LiyanError) as missing_kp:
            await service.delete_knowledge_point(
                course_id="CRS_ATC_001",
                kp_id=second.kp_id,
                expected_revision=second.revision,
                idempotency_key="lifecycle-kp-delete-0002",
            )
        with pytest.raises(LiyanError) as missing_edge:
            await service.delete_prerequisite(
                course_id="CRS_ATC_001",
                edge_id="EDGE_ATC_404",
                expected_revision=1,
                idempotency_key="lifecycle-edge-delete-02",
            )
        with pytest.raises(LiyanError) as missing_snapshot:
            await service.rollback_snapshot(
                uuid4(),
                idempotency_key="lifecycle-rollback-00002",
            )
        with pytest.raises(LiyanError):
            await service.get_course("CRS_ATC_404")
        with pytest.raises(LiyanError):
            await service.get_graph("CRS_ATC_404")
        with pytest.raises(LiyanError) as invalid_key:
            await service.upsert_course(
                course_id="CRS_ATC_002",
                document=course_document(),
                expected_revision=None,
                idempotency_key="short",
            )
        with pytest.raises(LiyanError) as missing_expected:
            await service.upsert_course(
                course_id="CRS_ATC_404",
                document=course_document(),
                expected_revision=1,
                idempotency_key="lifecycle-course-missing-1",
            )
    assert missing_kp.value.code == ErrorCode.TOPIC1_NOT_FOUND
    assert missing_edge.value.code == ErrorCode.TOPIC1_NOT_FOUND
    assert missing_snapshot.value.code == ErrorCode.TOPIC1_NOT_FOUND
    assert invalid_key.value.code == ErrorCode.CONTRACT_INVALID
    assert missing_expected.value.code == ErrorCode.TOPIC1_CONFLICT


@pytest.mark.asyncio
async def test_topic1_repository_direct_crud_and_missing_snapshot(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    service = service_for(database)
    repository = PostgresTopic1Repository()
    with tenant_scope(context):
        await service.upsert_course(
            course_id="CRS_ATC_001",
            document=course_document(),
            expected_revision=None,
            idempotency_key="repository-course-000001",
        )
        await service.upsert_knowledge_point(
            course_id="CRS_ATC_001",
            kp_id="KP_ATC_301_A",
            document=kp_document("A", 0.4),
            expected_revision=None,
            idempotency_key="repository-kp-create-001",
        )
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            kp = await repository.get_knowledge_point(
                session,
                context.tenant_id,
                "KP_ATC_301_A",
            )
            assert kp is not None
            await repository.put_knowledge_point(
                session,
                context.tenant_id,
                kp.model_copy(update={"revision": kp.revision + 1}),
                context.subject_ref,
            )
            assert await repository.get_snapshot(session, context.tenant_id, uuid4()) is None
            assert await repository.delete_knowledge_point(
                session,
                context.tenant_id,
                kp.kp_id,
            )
            assert not await repository.delete_knowledge_point(
                session,
                context.tenant_id,
                kp.kp_id,
            )


@pytest.mark.asyncio
async def test_topic1_import_stale_parent_limit_and_idempotency_conflict(
    postgres_runtime,
    monkeypatch,
) -> None:
    database, _migrator, context = postgres_runtime
    service = service_for(database)
    bundle = import_bundle()
    with tenant_scope(context):
        await service.import_bundle(bundle, idempotency_key="import-boundary-key-0001")
        with pytest.raises(LiyanError) as stale:
            await service.import_bundle(
                bundle.model_copy(update={"import_id": uuid4()}),
                idempotency_key="import-boundary-key-0002",
            )
        with pytest.raises(LiyanError) as key_conflict:
            await service.import_bundle(
                bundle.model_copy(update={"import_id": uuid4(), "expected_parent_version": 1}),
                idempotency_key="import-boundary-key-0001",
            )
        monkeypatch.setattr("liyans.domains.topic1.service.MAX_IMPORT_KNOWLEDGE_POINTS", 1)
        with pytest.raises(LiyanError) as too_large:
            await service.import_bundle(
                bundle.model_copy(update={"expected_parent_version": 1}),
                idempotency_key="import-boundary-key-0003",
            )
    assert stale.value.code == ErrorCode.TOPIC1_CONFLICT
    assert key_conflict.value.code == ErrorCode.MESSAGE_DUPLICATE_CONFLICT
    assert too_large.value.code == ErrorCode.TOPIC1_IMPORT_LIMIT


@pytest.mark.asyncio
async def test_topic1_unique_constraint_is_mapped_and_fully_rolled_back(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    service = service_for(database)
    with tenant_scope(context):
        await service.upsert_course(
            course_id="CRS_ATC_001",
            document=course_document(),
            expected_revision=None,
            idempotency_key="unique-course-create-0001",
        )
        with pytest.raises(LiyanError) as duplicate_code:
            await service.upsert_course(
                course_id="CRS_ATC_002",
                document=course_document(),
                expected_revision=None,
                idempotency_key="unique-course-create-0002",
            )
        courses = await service.list_courses()
        second_snapshots = await service.list_snapshots("CRS_ATC_002")

    assert duplicate_code.value.code == ErrorCode.TOPIC1_CONFLICT
    assert [item.course_id for item in courses] == ["CRS_ATC_001"]
    assert second_snapshots == []


@pytest.mark.asyncio
async def test_topic1_authoritative_seed_imports_into_postgres(
    postgres_runtime,
    authoritative_seed_bundle,
) -> None:
    database, _migrator, context = postgres_runtime
    service = service_for(database)
    bundle = authoritative_seed_bundle

    with tenant_scope(context):
        result = await service.import_bundle(
            bundle,
            idempotency_key="topic1-authoritative-seed-0001",
        )
        graph = await service.get_graph(bundle.content.course.course_id)

    assert result["snapshot"]["graph_version"] == 1
    assert graph == Topic1GraphSnapshotV1.model_validate(result["snapshot"]).content
    assert len(graph.knowledge_points) == 13
    assert len(graph.prerequisites) == 15
    assert len(graph.textbook_sections) == 7
    assert len(graph.textbook_mappings) == 13
    assert len(graph.golden_questions) == 5
    assert max(item.topology_level for item in graph.knowledge_points) >= 3
