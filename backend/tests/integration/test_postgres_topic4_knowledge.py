from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from liyans_contracts.artifacts import (
    ArtifactObjectRefV1,
    BlockSnapshotManifestItemV1,
    SourceSnapshotRefV1,
)
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import (
    ResourceType,
    SourceAgent,
    VerificationProfile,
    VerificationTrigger,
)
from liyans_contracts.providers import ResponsesLiteRequestV1
from liyans_contracts.topic1 import CourseStatus, KnowledgePointStatus
from liyans_contracts.topic3 import CandidateV1
from liyans_contracts.topic4_c1 import ClaimV1, ExtractionMethod
from liyans_contracts.topic4_c2 import IndexBuildState, SourceAuthorityTier
from liyans_contracts.topic4_common import ClaimKind
from liyans_contracts.verification import VerificationContextV1, VerificationRequestPayloadV1
from sqlalchemy import select
from topic3_support import generation_command

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.core.tenant import tenant_scope
from liyans.domains.knowledge.artifact_writer import KnowledgeArtifactWriter
from liyans.domains.knowledge.ingestion import SourceImportCommand
from liyans.domains.knowledge.lifecycle import (
    KnowledgeBaseBuildCommand,
    KnowledgeBaseLifecycleService,
)
from liyans.domains.knowledge.models import Topic4IndexBuildManifestModel
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.domains.knowledge.retrieval import HotReloadableRAGIndex
from liyans.domains.knowledge.retrieval_service import KnowledgeRetrievalService
from liyans.domains.knowledge.transactions import KnowledgeTransactionCoordinator
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
from liyans.domains.topic3.orchestrator import Topic3Orchestrator
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository
from liyans.domains.topic3.service import Topic3Service
from liyans.domains.topic3.streaming import Topic3StreamCoordinator
from liyans.domains.verification.postgres_repository import PostgresVerificationRepository
from liyans.domains.verification.records import build_topic4_record
from liyans.domains.verification.service import VerificationService, VerifierRuntimeVersions
from liyans.domains.verification.state_machine import VerificationStateMachine
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.persistence import (
    FileSystemArtifactObjectStore,
    PostgresArtifactRepository,
    PostgresOutboxRepository,
)
from liyans.infrastructure.streaming.sse import InMemorySSEReplayLog, SSEBroker
from liyans.providers.topic3 import ProviderExecutionResult, Topic3ProviderRegistry

pytestmark = pytest.mark.integration

COURSE_ID = "CRS_ATC_C2_INTEGRATION"
KP_ID = "KP_ATC_C2_STABILITY"
NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


async def _seed_topic1(database) -> None:
    service = Topic1Service(
        database,
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="topic4-c2-topic1-fixture",
    )
    await service.upsert_course(
        course_id=COURSE_ID,
        document={
            "course_code": "ATC-C2",
            "title": "C2 RAG Integration Course",
            "description": "Authoritative C2 integration fixture.",
            "locale": "zh-CN",
            "academic_level": "UNDERGRADUATE",
            "credit_hours": 64,
            "status": CourseStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="topic4-c2-course-seed-00001",
    )
    await service.upsert_knowledge_point(
        course_id=COURSE_ID,
        kp_id=KP_ID,
        document={
            "title": "Closed-loop stability",
            "aliases": ["stability"],
            "summary": "Closed-loop poles determine continuous-time stability.",
            "learning_objectives": ["Judge stability from characteristic roots."],
            "category": "STABILITY",
            "difficulty_level": 4,
            "difficulty_score": 0.72,
            "estimated_minutes": 120,
            "formula_signatures": ["1+G(s)H(s)=0"],
            "tags": ["stability", "routh-hurwitz"],
            "status": KnowledgePointStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="topic4-c2-kp-seed-0000001",
    )


def _verification_request(
    candidate: CandidateV1,
    now: datetime,
    tenant_id: str,
    trace_id: str = "e" * 32,
):
    verification_id = uuid4()
    full_snapshot = ArtifactObjectRefV1(
        schema_version="artifact.object.ref.v1",
        storage_namespace="verification-artifacts",
        object_key=f"topic4/c2-tests/{candidate.candidate_id}.json",
        media_type="application/json",
        content_encoding="identity",
        byte_size=2,
        sha256=candidate.candidate_sha256,
        created_at=now,
    )
    return build_topic4_record(
        VerificationRequestPayloadV1,
        trace_id=trace_id,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=now,
        immutable=True,
        schema_version="verification.request.v1",
        verification_id=verification_id,
        idempotency_key=f"topic4:c2:verification:{verification_id.hex}",
        trigger=VerificationTrigger.INITIAL_GENERATION,
        parent_verification_id=None,
        source_snapshot_ref=SourceSnapshotRefV1(
            schema_version="source.snapshot.ref.v1",
            source_envelope_id=uuid4(),
            source_envelope_version="topic3.envelope.v1",
            source_envelope_sha256=canonical_sha256({"candidate": str(candidate.candidate_id)}),
            blueprint_id=candidate.blueprint_id,
            blueprint_version=candidate.blueprint_version,
            blueprint_sha256=candidate.blueprint_sha256,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            candidate_sha256=candidate.candidate_sha256,
            source_agent=SourceAgent.LECTURER,
            resource_type=ResourceType.LECTURER_DOC,
            full_snapshot=full_snapshot,
            block_manifest=[
                BlockSnapshotManifestItemV1(
                    block_id=candidate.blocks[0].block_id,
                    block_type=candidate.blocks[0].block_type.value,
                    ordinal=0,
                    json_pointer="/blocks/0",
                    sha256=candidate.blocks[0].content_sha256,
                    byte_size=2,
                )
            ],
        ),
        context=VerificationContextV1(
            schema_version="verification.context.v1",
            course_id=COURSE_ID,
            course_version="1",
            target_kp_id=KP_ID,
            locale="zh-CN",
            subject_domain="AUTOMATION",
            personalization_policy_digest=candidate.personalization_policy_digest,
        ),
        requested_profile=VerificationProfile.STRICT,
        requested_optional_modules=[],
        deadline_at=now + timedelta(minutes=10),
        requested_at=now,
    )


def _verifier_versions() -> VerifierRuntimeVersions:
    return VerifierRuntimeVersions(
        state_machine_version="c1-state-machine-v1",
        verifier_build_version="topic4-c2-integration-v1",
        policy_version="topic4-policy-v1",
        prompt_bundle_version="topic4-prompts-v1",
        retrieval_pipeline_version="local-hybrid-rag-v1",
        knowledge_base_version="topic4-c2-kb-v1",
        toolchain_manifest_version="toolchain-v1",
        content_security_policy_version="security-v1",
        license_policy_version="license-v1",
    )


class _FixtureSparkProvider:
    alias = "spark_text"
    model_alias = "fixture-spark"

    async def execute(self, request: ResponsesLiteRequestV1) -> ProviderExecutionResult:
        started = datetime.now(UTC)
        return ProviderExecutionResult(
            request_id=str(request.request_id),
            structured_output={
                "schema_version": "topic3.lecturer-content.v1",
                "title": "Closed-loop stability",
                "learning_objectives": ["Judge stability from characteristic roots."],
                "sections": [
                    {
                        "section_id": "stability",
                        "title": "Stability",
                        "depth": "ENGINEERING",
                        "markdown": "Closed-loop stability follows from 1+G(s)H(s)=0.",
                        "target_kp_ids": [KP_ID],
                    }
                ],
                "summary": ["Pole location determines continuous-time stability."],
                "misconception_alerts": [],
                "personalization_notes": ["Reinforce the characteristic equation."],
            },
            input_tokens=10,
            output_tokens=20,
            started_at=started,
            completed_at=datetime.now(UTC),
        )

    async def close(self) -> None:
        return None


def _c2_source_command(*, version: str, title: str) -> SourceImportCommand:
    return SourceImportCommand(
        course_id=COURSE_ID,
        title=title,
        authors=("Integration Author",),
        publisher="Authoritative Press",
        authority_tier=SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK,
        source_type="TEXTBOOK",
        canonical_citation=f"Integration Author. {title}. {version}.",
        license_expression="LicenseRef-Educational-Authorized",
        version=version,
        content=(
            b'{"sections":[{"section_id":"stability","title":"Closed-loop stability",'
            b'"text":"Closed-loop stability follows from 1+G(s)H(s)=0 and pole location.",'
            b'"topic1_knowledge_point_ids":["KP_ATC_C2_STABILITY"]}]}'
        ),
        media_type="application/json",
        effective_from=NOW,
    )


def _c2_services(database, artifact_root: Path, *, instance_id: str):
    object_store = FileSystemArtifactObjectStore(artifact_root)
    repository = PostgresKnowledgeRepository()
    writer = KnowledgeArtifactWriter(
        PostgresArtifactRepository(database),
        object_store,
    )
    transactions = KnowledgeTransactionCoordinator(
        database,
        PostgresOutboxRepository(database),
        instance_id=instance_id,
        build_version="topic4-c2-test-v1",
    )
    indexes = HotReloadableRAGIndex()
    lifecycle = KnowledgeBaseLifecycleService(
        database,
        repository,
        PostgresTopic1Repository(),
        writer,
        transactions,
        indexes,
    )
    retrieval = KnowledgeRetrievalService(
        database,
        repository,
        PostgresTopic1Repository(),
        writer,
        transactions,
        indexes,
    )
    return repository, writer, transactions, indexes, lifecycle, retrieval


@pytest.mark.asyncio
async def test_c2_import_build_activate_reload_and_tenant_isolation(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    database, _migrator, context = postgres_runtime
    object_store = FileSystemArtifactObjectStore(tmp_path / "artifacts")
    repository = PostgresKnowledgeRepository()
    artifact_repository = PostgresArtifactRepository(database)
    writer = KnowledgeArtifactWriter(artifact_repository, object_store)
    transactions = KnowledgeTransactionCoordinator(
        database,
        PostgresOutboxRepository(database),
        instance_id="topic4-c2-integration",
        build_version="topic4-c2-test-v1",
    )
    indexes = HotReloadableRAGIndex()
    lifecycle = KnowledgeBaseLifecycleService(
        database,
        repository,
        PostgresTopic1Repository(),
        writer,
        transactions,
        indexes,
    )
    command = SourceImportCommand(
        course_id=COURSE_ID,
        title="Automatic Control Theory Authoritative Notes",
        authors=("Integration Author",),
        publisher="Authoritative Press",
        authority_tier=SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK,
        source_type="TEXTBOOK",
        canonical_citation="Integration Author. Automatic Control Theory. 2026.",
        license_expression="LicenseRef-Educational-Authorized",
        version="2026.1",
        content=(
            b'{"sections":[{"section_id":"stability","title":"Closed-loop stability",'
            b'"text":"Closed-loop stability follows from 1+G(s)H(s)=0 and pole location.",'
            b'"topic1_knowledge_point_ids":["KP_ATC_C2_STABILITY"]}]}'
        ),
        media_type="application/json",
        effective_from=NOW,
    )

    context = replace(
        context,
        scopes=frozenset({"topic2:learner:any", "topic3:learner:any", "topic3:admin"}),
    )
    with tenant_scope(context):
        await _seed_topic1(database)
        imported = await lifecycle.import_source(
            command,
            idempotency_key="topic4-c2-source-import-00000001",
        )
        replay = await lifecycle.import_source(
            command,
            idempotency_key="topic4-c2-source-import-00000001",
        )
        assert replay.source_version.record_sha256 == imported.source_version.record_sha256
        built = await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=COURSE_ID,
                version="kb-2026.1",
                source_document_version_ids=(imported.source_version.source_document_version_id,),
            ),
            idempotency_key="topic4-c2-kb-build-activate-00000001",
        )
        assert built.chunk_count >= 1
        assert built.ready_manifest.state.value == "READY"
        assert indexes.active_version(context.tenant_id, COURSE_ID) == (
            built.knowledge_base.knowledge_base_version_id
        )

        # A fresh service instance must reconstruct the active index from immutable artifacts.
        fresh_indexes = HotReloadableRAGIndex()
        from liyans.domains.knowledge.retrieval_service import KnowledgeRetrievalService

        retrieval = KnowledgeRetrievalService(
            database,
            repository,
            PostgresTopic1Repository(),
            writer,
            transactions,
            fresh_indexes,
        )
        loaded = await retrieval.load_active(COURSE_ID)
        assert loaded.manifest.state.value == "READY"
        assert loaded.index.entries

    other = context.__class__(
        tenant_id=f"other-{context.tenant_id}",
        subject_ref=context.subject_ref,
        roles=context.roles,
        scopes=context.scopes,
        trace_id="d" * 32,
    )
    with tenant_scope(other):
        from liyans.domains.knowledge.retrieval_service import KnowledgeRetrievalService

        retrieval = KnowledgeRetrievalService(
            database,
            repository,
            PostgresTopic1Repository(),
            writer,
            transactions,
            HotReloadableRAGIndex(),
        )
        with pytest.raises(LiyanError) as denied:
            await retrieval.load_active(COURSE_ID)
        assert denied.value.code == ErrorCode.TOPIC4_NOT_FOUND


@pytest.mark.asyncio
async def test_c2_retrieval_persists_query_plan_evidence_and_idempotent_replay(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    database, _migrator, context = postgres_runtime
    object_store = FileSystemArtifactObjectStore(tmp_path / "artifacts")
    repository = PostgresKnowledgeRepository()
    artifact_repository = PostgresArtifactRepository(database)
    writer = KnowledgeArtifactWriter(artifact_repository, object_store)
    transactions = KnowledgeTransactionCoordinator(
        database,
        PostgresOutboxRepository(database),
        instance_id="topic4-c2-retrieval-integration",
        build_version="topic4-c2-test-v1",
    )
    indexes = HotReloadableRAGIndex()
    lifecycle = KnowledgeBaseLifecycleService(
        database,
        repository,
        PostgresTopic1Repository(),
        writer,
        transactions,
        indexes,
    )
    source_command = SourceImportCommand(
        course_id=COURSE_ID,
        title="Automatic Control Theory Retrieval Source",
        authors=("Integration Author",),
        publisher="Authoritative Press",
        authority_tier=SourceAuthorityTier.PRIMARY_STANDARD,
        source_type="STANDARD",
        canonical_citation="Integration Author. Retrieval Source. 2026.",
        license_expression="LicenseRef-Educational-Authorized",
        version="2026.2",
        content=(
            b'{"sections":[{"section_id":"stability","title":"Closed-loop stability",'
            b'"text":"Closed-loop stability follows from 1+G(s)H(s)=0 and pole location.",'
            b'"topic1_knowledge_point_ids":["KP_ATC_C2_STABILITY"]}]}'
        ),
        media_type="application/json",
        effective_from=NOW,
    )

    with tenant_scope(context):
        await _seed_topic1(database)
        imported = await lifecycle.import_source(
            source_command,
            idempotency_key="topic4-c2-retrieval-source-0000001",
        )
        await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=COURSE_ID,
                version="kb-2026.2",
                source_document_version_ids=(imported.source_version.source_document_version_id,),
            ),
            idempotency_key="topic4-c2-retrieval-build-0000001",
        )
        topic3_repository = PostgresTopic3Repository()
        topic2_service = Topic2Service(
            database,
            PostgresTopic2Repository(),
            PostgresTopic1Repository(),
            PostgresOutboxRepository(database),
            instance_id="topic4-c2-topic2-fixture",
        )
        topic2_runtime = Topic2Orchestrator(
            database,
            PostgresTopic1Repository(),
            topic2_service,
            SixDimensionProfileEngine(),
            EbbinghausMemoryEngine(),
            AdaptivePathPlanner(),
        )
        provider_registry = Topic3ProviderRegistry(
            ProviderPolicyRegistry.load(ROOT / "config" / "providers.toml"),
            {"spark_text": _FixtureSparkProvider()},
        )
        topic3_service = Topic3Service(
            database,
            topic3_repository,
            PostgresOutboxRepository(database),
            instance_id="topic4-c2-topic3-fixture",
        )
        topic3_runtime = Topic3Orchestrator(
            database,
            PostgresTopic1Repository(),
            topic2_runtime,
            topic3_service,
            ImmutableBlueprintPlanner(),
            Topic3AgentRegistry(provider_registry),
            Topic3StreamCoordinator(SSEBroker(InMemorySSEReplayLog(capacity_per_tenant=1000))),
        )
        generation = generation_command(
            resources=[ResourceType.LECTURER_DOC],
            target_kp_ids=[KP_ID],
        ).model_copy(
            update={
                "operation_id": uuid4(),
                "generation_session_id": uuid4(),
                "learner_ref": context.subject_ref,
                "course_id": COURSE_ID,
                "requested_at": datetime.now(UTC),
            }
        )
        now = generation.requested_at
        await topic2_runtime.initialize_learner(
            learner_ref=context.subject_ref,
            course_id=COURSE_ID,
            operation_id=uuid4(),
            requested_at=now,
            idempotency_key="topic4-c2-topic2-init-00000001",
        )
        await topic2_runtime.generate_path(
            learner_ref=context.subject_ref,
            course_id=COURSE_ID,
            operation_id=uuid4(),
            requested_at=now,
            target_goal="Master closed-loop stability.",
            target_kp_ids=[KP_ID],
            idempotency_key="topic4-c2-topic2-path-00000001",
        )
        await topic3_runtime.prepare(
            generation,
            idempotency_key="topic4-c2-topic3-prepare-00000001",
        )
        generated = await topic3_runtime.execute(generation.generation_session_id)
        assert generated.candidates, generated.model_dump(mode="json")
        candidate = generated.candidates[0]
        verifier = VerificationService(
            database,
            PostgresVerificationRepository(),
            topic3_repository,
            PostgresOutboxRepository(database),
            VerificationStateMachine(),
            _verifier_versions(),
            instance_id="topic4-c2-retrieval-verifier",
        )
        request = _verification_request(
            candidate,
            datetime.now(UTC),
            context.tenant_id,
            context.trace_id,
        )
        accepted = await verifier.accept_verification(request)
        claim = build_topic4_record(
            ClaimV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=datetime.now(UTC),
            immutable=True,
            schema_version="claim.v1",
            claim_id=uuid4(),
            verification_id=accepted.verification_id,
            candidate_id=candidate.candidate_id,
            candidate_version=1,
            candidate_sha256=candidate.candidate_sha256,
            block_id=candidate.blocks[0].block_id,
            claim_kind=ClaimKind.FORMULA,
            claim_subtype="stability_characteristic_equation",
            statement="Closed-loop stability follows from 1+G(s)H(s)=0.",
            normalized_statement="closed-loop stability follows from 1+G(s)H(s)=0.",
            json_pointer="/blocks/0/content/text",
            ordinal=0,
            source_span_start=0,
            source_span_end=64,
            claim_sha256=canonical_sha256("closed-loop stability follows from 1+G(s)H(s)=0."),
            extraction_method=ExtractionMethod.DETERMINISTIC,
            dependent_claim_ids=[],
        )
        async with database.transaction(context=current_session_context()) as session:
            audit_event_id = await transactions.append_audit(
                session,
                context,
                action="C2_RETRIEVAL_CLAIM_FIXTURE",
                target_ref=str(claim.claim_id),
                metadata={"verification_id": str(claim.verification_id)},
            )
            await PostgresVerificationRepository().append_claims(
                session,
                context.tenant_id,
                [claim],
                audit_event_id,
            )

        from liyans.domains.knowledge.retrieval_service import KnowledgeRetrievalService

        retrieval = KnowledgeRetrievalService(
            database,
            repository,
            PostgresTopic1Repository(),
            writer,
            transactions,
            HotReloadableRAGIndex(),
        )
        response = await retrieval.retrieve_claim(
            claim,
            course_id=COURSE_ID,
            target_kp_id=KP_ID,
            idempotency_key="topic4-c2-retrieval-run-00000001",
        )
        replay = await retrieval.retrieve_claim(
            claim,
            course_id=COURSE_ID,
            target_kp_id=KP_ID,
            idempotency_key="topic4-c2-retrieval-run-00000001",
        )
        assert response.record_sha256 == replay.record_sha256
        assert response.status.value in {"SUCCEEDED", "DEGRADED"}
        assert response.evidence_bundle is not None
        assert response.evidence_bundle.evidence_ref_ids
        async with database.transaction(context=current_session_context()) as session:
            stored_plan = await repository.latest_query_plan(
                session,
                context.tenant_id,
                claim.verification_id,
                claim.claim_id,
            )
            stored_bundle = await repository.latest_evidence_bundle(
                session,
                context.tenant_id,
                claim.verification_id,
                claim.claim_id,
            )
            stored_refs = await repository.list_evidence_refs(
                session,
                context.tenant_id,
                claim.claim_id,
            )
        assert stored_plan is not None
        assert stored_bundle is not None
        assert stored_refs

    other = replace(
        context,
        tenant_id=f"other-{context.tenant_id}",
        trace_id="d" * 32,
    )
    with tenant_scope(other):
        async with database.transaction(context=current_session_context()) as session:
            assert (
                await repository.latest_query_plan(
                    session,
                    other.tenant_id,
                    claim.verification_id,
                    claim.claim_id,
                )
                is None
            )
            assert (
                await repository.latest_evidence_bundle(
                    session,
                    other.tenant_id,
                    claim.verification_id,
                    claim.claim_id,
                )
                is None
            )
            assert (
                await repository.list_evidence_refs(session, other.tenant_id, claim.claim_id) == []
            )
            assert (
                await repository.get_retrieval_response(
                    session,
                    other.tenant_id,
                    response.retrieval_request_id,
                )
                is None
            )


@pytest.mark.integration
@pytest.mark.parametrize("artifact_kind", ("faiss", "bm25"))
@pytest.mark.asyncio
async def test_c2_corrupted_index_artifact_is_persistently_self_healed(
    postgres_runtime,
    tmp_path: Path,
    artifact_kind: str,
) -> None:
    database, _migrator, context = postgres_runtime
    with tenant_scope(context):
        (
            repository,
            writer,
            _transactions,
            _indexes,
            lifecycle,
            _retrieval,
        ) = _c2_services(
            database,
            tmp_path / "artifacts",
            instance_id=f"topic4-c2-recovery-{artifact_kind}",
        )
        await _seed_topic1(database)
        imported = await lifecycle.import_source(
            _c2_source_command(version="2026.3", title="Recovery Source"),
            idempotency_key="topic4-c2-recovery-source-0000000001",
        )
        built = await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=COURSE_ID,
                version="kb-recovery-2026.3",
                source_document_version_ids=(imported.source_version.source_document_version_id,),
            ),
            idempotency_key="topic4-c2-recovery-build-0000000001",
        )
        shard = built.ready_manifest.shards[0]
        reference = shard.faiss_artifact if artifact_kind == "faiss" else shard.bm25_artifact
        object_path = next(
            (tmp_path / "artifacts").rglob(Path(reference.object_key).name),
            None,
        )
        assert object_path is not None
        object_path.chmod(0o660)
        object_path.write_bytes(b"corrupted-index-artifact")

        (
            _fresh_repository,
            _fresh_writer,
            _fresh_transactions,
            _fresh_indexes,
            _fresh_lifecycle,
            fresh_retrieval,
        ) = _c2_services(
            database,
            tmp_path / "artifacts",
            instance_id=f"topic4-c2-recovery-fresh-{artifact_kind}",
        )
        (
            _concurrent_repository,
            _concurrent_writer,
            _concurrent_transactions,
            _concurrent_indexes,
            _concurrent_lifecycle,
            concurrent_retrieval,
        ) = _c2_services(
            database,
            tmp_path / "artifacts",
            instance_id=f"topic4-c2-recovery-concurrent-{artifact_kind}",
        )
        loaded, concurrent_loaded = await asyncio.gather(
            fresh_retrieval.load_active(COURSE_ID),
            concurrent_retrieval.load_active(COURSE_ID),
        )
        assert loaded.manifest.state == IndexBuildState.READY
        assert loaded.manifest.version_cas == 4
        assert loaded.index.entries
        assert concurrent_loaded.manifest.record_sha256 == loaded.manifest.record_sha256

        async with database.transaction(context=current_session_context()) as session:
            result = await session.execute(
                select(Topic4IndexBuildManifestModel)
                .where(
                    Topic4IndexBuildManifestModel.tenant_id == context.tenant_id,
                    Topic4IndexBuildManifestModel.index_build_manifest_id
                    == built.ready_manifest.index_build_manifest_id,
                )
                .order_by(Topic4IndexBuildManifestModel.manifest_version)
            )
            states = [(row.manifest_version, row.state) for row in result.scalars()]
        assert states[-2:] == [
            (3, IndexBuildState.CORRUPTED.value),
            (4, IndexBuildState.READY.value),
        ]
        repaired_reference = (
            loaded.manifest.shards[0].faiss_artifact
            if artifact_kind == "faiss"
            else loaded.manifest.shards[0].bm25_artifact
        )
        repaired_payload = await writer.read(context.tenant_id, repaired_reference)
        assert repaired_payload != b"corrupted-index-artifact"

        replayed_loaded = await fresh_retrieval.load_active(COURSE_ID)
        assert replayed_loaded.manifest.record_sha256 == loaded.manifest.record_sha256


@pytest.mark.integration
@pytest.mark.asyncio
async def test_c2_cached_active_knowledge_base_refreshes_after_activation_cas(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    database, _migrator, context = postgres_runtime
    with tenant_scope(context):
        _repository, _writer, _transactions, _indexes, lifecycle, retrieval = _c2_services(
            database,
            tmp_path / "artifacts",
            instance_id="topic4-c2-cache-refresh",
        )
        await _seed_topic1(database)
        imported = await lifecycle.import_source(
            _c2_source_command(version="2026.4", title="Cache Refresh Source"),
            idempotency_key="topic4-c2-cache-source-0000000001",
        )
        first = await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=COURSE_ID,
                version="kb-cache-2026.4",
                source_document_version_ids=(imported.source_version.source_document_version_id,),
            ),
            idempotency_key="topic4-c2-cache-build-0000000001",
        )
        cached = await retrieval.load_active(COURSE_ID)
        assert cached.knowledge_base.knowledge_base_version_id == (
            first.knowledge_base.knowledge_base_version_id
        )

        second = await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=COURSE_ID,
                version="kb-cache-2026.5",
                source_document_version_ids=(imported.source_version.source_document_version_id,),
                expected_activation_version=1,
            ),
            idempotency_key="topic4-c2-cache-build-0000000002",
        )
        refreshed = await retrieval.load_active(COURSE_ID)
        assert refreshed.activation_version == 2
        assert refreshed.activation_id == second.activation.activation_id
        assert refreshed.knowledge_base.knowledge_base_version_id == (
            second.knowledge_base.knowledge_base_version_id
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_c2_failed_activation_cas_leaves_no_database_artifacts_and_can_retry(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    database, _migrator, context = postgres_runtime
    with tenant_scope(context):
        repository, _writer, _transactions, _indexes, lifecycle, _retrieval = _c2_services(
            database,
            tmp_path / "artifacts",
            instance_id="topic4-c2-cas-rollback",
        )
        await _seed_topic1(database)
        imported = await lifecycle.import_source(
            _c2_source_command(version="2026.6", title="CAS Rollback Source"),
            idempotency_key="topic4-c2-cas-source-000000000001",
        )
        first = await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=COURSE_ID,
                version="kb-cas-2026.6",
                source_document_version_ids=(imported.source_version.source_document_version_id,),
            ),
            idempotency_key="topic4-c2-cas-build-000000000001",
        )
        failed_version = "kb-cas-2026.7"
        failed_command = KnowledgeBaseBuildCommand(
            course_id=COURSE_ID,
            version=failed_version,
            source_document_version_ids=(imported.source_version.source_document_version_id,),
            expected_activation_version=0,
        )
        retry_key = "topic4-c2-cas-build-000000000002"
        with pytest.raises(LiyanError) as error:
            await lifecycle.build_and_activate(failed_command, idempotency_key=retry_key)
        assert error.value.code == ErrorCode.TOPIC4_CONFLICT

        failed_kb_id = uuid5(
            NAMESPACE_URL,
            f"liyans://{context.tenant_id}/topic4/c2/{COURSE_ID}/{failed_version}",
        )
        failed_manifest_id = uuid5(failed_kb_id, "index-build-manifest")
        async with database.transaction(context=current_session_context()) as session:
            assert (
                await repository.get_knowledge_base_version(
                    session,
                    context.tenant_id,
                    failed_kb_id,
                )
                is None
            )
            assert await repository.list_chunks(session, context.tenant_id, failed_kb_id) == []
            assert (
                await repository.latest_manifest(
                    session,
                    context.tenant_id,
                    failed_manifest_id,
                )
                is None
            )
            activation = await repository.latest_activation(
                session,
                context.tenant_id,
                COURSE_ID,
            )
        assert activation is not None
        assert activation.activation_id == first.activation.activation_id

        retry = await lifecycle.build_and_activate(
            KnowledgeBaseBuildCommand(
                course_id=failed_command.course_id,
                version=failed_command.version,
                source_document_version_ids=failed_command.source_document_version_ids,
                expected_activation_version=1,
            ),
            idempotency_key=retry_key,
        )
        assert retry.activation.activation_version == 2
