from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c2 import (
    DocumentIRV1,
    DocumentSectionIRV1,
    EmbeddingProfileV1,
    IndexBuildManifestV1,
    IndexBuildState,
    IndexShardManifestV1,
    KnowledgeBaseVersionV1,
    KnowledgeChunkV1,
    SourceDocumentV1,
    SourceDocumentVersionV1,
    SourceLifecycle,
)

from liyans.core.hashing import canonical_json_bytes
from liyans.core.tenant import TenantContext, current_tenant
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.session import DatabaseSessionManager

from .artifact_writer import KnowledgeArtifactWriter
from .entities import (
    ImportedSourceResult,
    KnowledgeBaseActivation,
    KnowledgeBaseBuildResult,
    SourceVersionBundle,
    StagedArtifact,
)
from .ingestion import (
    BoundedKnowledgeChunker,
    DeterministicDocumentParser,
    FormulaSignatureExtractor,
    KnowledgePointMatcher,
    ParsedSection,
    SourceImportCommand,
)
from .postgres_repository import PostgresKnowledgeRepository
from .retrieval import (
    CorpusEntry,
    DeterministicTokenizer,
    HashedLexicalVectorizer,
    HotReloadableRAGIndex,
    LocalHybridIndex,
    RetrievalIndexError,
    SerializedHybridShard,
    TopicGraphExpander,
)
from .transactions import KnowledgeTransactionCoordinator


@dataclass(frozen=True, slots=True)
class KnowledgeRuntimeConfig:
    parser_version: str = "c2-parser-v1"
    tokenizer_version: str = "c2-tokenizer-v1"
    hash_seed_version: str = "liyans-topic4-hash-v1"
    retrieval_pipeline_version: str = "local-hybrid-rag-v1"
    toolchain_manifest_version: str = "faiss-1.14-bm25-v1"
    chunk_max_tokens: int = 384
    chunk_overlap_tokens: int = 48
    shard_size: int = 10_000

    def __post_init__(self) -> None:
        versions = (
            self.parser_version,
            self.tokenizer_version,
            self.hash_seed_version,
            self.retrieval_pipeline_version,
            self.toolchain_manifest_version,
        )
        if any(not value or len(value) > 128 for value in versions):
            raise ValueError("knowledge runtime versions must contain 1 to 128 characters")
        if not 1 <= self.shard_size <= 25_000:
            raise ValueError("knowledge index shard_size must be between 1 and 25000")


@dataclass(frozen=True, slots=True)
class KnowledgeBaseBuildCommand:
    course_id: str
    version: str
    source_document_version_ids: tuple[UUID, ...]
    graph_snapshot_id: UUID | None = None
    expected_activation_version: int | None = None

    def __post_init__(self) -> None:
        if not self.course_id.strip() or not self.version.strip():
            raise ValueError("knowledge-base course and version cannot be blank")
        if not self.source_document_version_ids:
            raise ValueError("knowledge-base build requires at least one source version")
        if len(self.source_document_version_ids) > 65_536:
            raise ValueError("knowledge-base build exceeds the source version limit")
        if len(set(self.source_document_version_ids)) != len(self.source_document_version_ids):
            raise ValueError("knowledge-base source versions must be unique")
        if self.expected_activation_version is not None and self.expected_activation_version < 0:
            raise ValueError("expected activation version cannot be negative")


class KnowledgeBaseLifecycleService:
    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: PostgresKnowledgeRepository,
        topic1_repository: PostgresTopic1Repository,
        artifact_writer: KnowledgeArtifactWriter,
        transactions: KnowledgeTransactionCoordinator,
        indexes: HotReloadableRAGIndex,
        *,
        config: KnowledgeRuntimeConfig | None = None,
    ) -> None:
        self._database = database
        self._repository = repository
        self._topic1_repository = topic1_repository
        self._artifact_writer = artifact_writer
        self._transactions = transactions
        self._indexes = indexes
        self._config = config or KnowledgeRuntimeConfig()
        self._parser = DeterministicDocumentParser()
        self._formula_extractor = FormulaSignatureExtractor()
        self._tokenizer = DeterministicTokenizer()
        self._vectorizer = HashedLexicalVectorizer(self._tokenizer)
        self._chunker = BoundedKnowledgeChunker(
            self._tokenizer,
            max_tokens=self._config.chunk_max_tokens,
            overlap_tokens=self._config.chunk_overlap_tokens,
        )

    async def import_source(
        self,
        command: SourceImportCommand,
        *,
        idempotency_key: str,
    ) -> ImportedSourceResult:
        context = current_tenant()
        document_id = command.resolved_document_id(context.tenant_id)
        version_id = command.resolved_version_id(context.tenant_id)
        now = datetime.now(UTC)
        graph = await self._required_graph(context, command.course_id)
        parsed = self._parser.parse(command)
        matcher = KnowledgePointMatcher(graph)
        matched = {section.section_id: matcher.match(section) for section in parsed.sections}
        signatures = self._formula_extractor.extract(
            parsed.sections,
            source_document_version_id=version_id,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            created_at=now,
        )
        request_document = {
            "course_id": command.course_id,
            "source_document_id": str(document_id),
            "source_document_version_id": str(version_id),
            "version": command.version,
            "content_sha256": parsed.content_sha256,
            "graph_snapshot_id": str(graph.snapshot_id),
        }
        replay = await self._transactions.completed_result(
            operation="topic4.c2.source.import",
            idempotency_key=idempotency_key,
            request_document=request_document,
        )
        if replay is not None:
            return self._imported_source_from_document(replay)

        source_artifact = await self._artifact_writer.stage(
            artifact_id=uuid5(version_id, "artifact:source-content"),
            tenant_id=context.tenant_id,
            object_key=self._source_object_key(version_id, command.media_type),
            media_type=command.media_type,
            content_encoding="identity",
            content=command.content,
            created_by_subject=context.subject_ref,
            created_at=now,
            provenance={
                "topic": "topic4-c2",
                "purpose": "authoritative-source-content",
                "source_document_id": str(document_id),
                "source_document_version_id": str(version_id),
            },
        )
        sections_artifact = await self._artifact_writer.stage(
            artifact_id=uuid5(version_id, "artifact:normalized-sections"),
            tenant_id=context.tenant_id,
            object_key=f"topic4/c2/sources/{version_id.hex}/sections.json",
            media_type="application/json",
            content_encoding="identity",
            content=self._parser.sections_payload(parsed),
            created_by_subject=context.subject_ref,
            created_at=now,
            provenance={
                "topic": "topic4-c2",
                "purpose": "normalized-document-sections",
                "source_document_version_id": str(version_id),
                "graph_snapshot_id": str(graph.snapshot_id),
                "graph_snapshot_version": graph.graph_version,
            },
        )
        section_records = tuple(
            build_topic4_record(
                DocumentSectionIRV1,
                trace_id=context.trace_id,
                tenant_id=context.tenant_id,
                version_cas=1,
                created_at=now,
                immutable=True,
                schema_version="document-section-ir.v1",
                section_id=section.section_id,
                parent_section_id=section.parent_section_id,
                ordinal=section.ordinal,
                title=section.title,
                json_pointer=section.json_pointer,
                text_artifact=sections_artifact.reference,
                text_sha256=section.text_sha256,
                formula_signature_ids=list(
                    self._formula_extractor.match_ids(section.text, signatures)
                ),
                topic1_knowledge_point_ids=list(matched[section.section_id]),
            )
            for section in parsed.sections
        )
        document_ir_id = uuid5(version_id, "document-ir:v1")
        document_ir_payload = canonical_json_bytes(
            {
                "schema_version": "document-ir-payload.v1",
                "document_ir_id": str(document_ir_id),
                "source_document_version_id": str(version_id),
                "parser_version": self._config.parser_version,
                "sections": [record.model_dump(mode="json") for record in section_records],
            }
        )
        document_ir_artifact = await self._artifact_writer.stage(
            artifact_id=uuid5(version_id, "artifact:document-ir"),
            tenant_id=context.tenant_id,
            object_key=f"topic4/c2/sources/{version_id.hex}/document-ir.json",
            media_type="application/json",
            content_encoding="identity",
            content=document_ir_payload,
            created_by_subject=context.subject_ref,
            created_at=now,
            provenance={
                "topic": "topic4-c2",
                "purpose": "document-ir",
                "source_document_version_id": str(version_id),
            },
        )
        document_ir = build_topic4_record(
            DocumentIRV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="document-ir.v1",
            document_ir_id=document_ir_id,
            source_document_version_id=version_id,
            parser_version=self._config.parser_version,
            sections=list(section_records),
            document_ir_artifact=document_ir_artifact.reference,
            document_ir_sha256=document_ir_artifact.reference.sha256,
        )
        source = build_topic4_record(
            SourceDocumentV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="source.document.v1",
            source_document_id=document_id,
            title=command.title,
            authors=list(command.authors),
            publisher=command.publisher,
            authority_tier=command.authority_tier,
            source_type=command.source_type,
            canonical_citation=command.canonical_citation,
            license_expression=command.license_expression,
            course_id=command.course_id,
            locale="zh-CN",
            lifecycle=command.lifecycle,
        )
        source_version = build_topic4_record(
            SourceDocumentVersionV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="source.document.version.v1",
            source_document_version_id=version_id,
            source_document_id=document_id,
            version=command.version,
            content_artifact=source_artifact.reference,
            content_sha256=source_artifact.reference.sha256,
            parser_version=self._config.parser_version,
            published_on=command.published_on,
            effective_from=command.effective_from,
            effective_until=command.effective_until,
            lifecycle=command.lifecycle,
        )
        bundle = SourceVersionBundle(
            source_document=source,
            source_version=source_version,
            document_ir=document_ir,
            graph_snapshot_id=graph.snapshot_id,
            graph_snapshot_version=graph.graph_version,
        )
        staged = (source_artifact, sections_artifact, document_ir_artifact)

        async def callback(session, scoped: TenantContext) -> dict[str, object]:
            await self._transactions.lock(
                session,
                f"topic4-c2-source:{scoped.tenant_id}:{document_id}",
            )
            current_graph = await self._topic1_repository.get_snapshot(
                session,
                scoped.tenant_id,
                graph.snapshot_id,
            )
            if current_graph is None or current_graph.content_sha256 != graph.content_sha256:
                raise self._transactions.integrity(
                    "Topic 1 graph snapshot changed during source import."
                )
            existing = await self._repository.get_source_document_by_citation(
                session,
                scoped.tenant_id,
                command.course_id,
                canonical_sha256(command.canonical_citation),
            )
            if existing is not None and not self._same_source(existing, source):
                raise self._transactions.conflict(
                    "The canonical citation is already bound to different source metadata."
                )
            if (
                await self._repository.get_source_version_bundle(
                    session,
                    scoped.tenant_id,
                    version_id,
                )
                is not None
            ):
                raise self._transactions.conflict("The immutable source version already exists.")
            audit_event_id = await self._transactions.append_audit(
                session,
                scoped,
                action="KNOWLEDGE_SOURCE_IMPORTED",
                target_ref=str(version_id),
                metadata={
                    "course_id": command.course_id,
                    "source_document_id": str(document_id),
                    "source_document_version_id": str(version_id),
                    "content_sha256": source_version.content_sha256,
                    "section_count": len(document_ir.sections),
                    "formula_signature_count": len(signatures),
                    "graph_snapshot_id": str(graph.snapshot_id),
                    "graph_snapshot_version": graph.graph_version,
                },
            )
            await self._artifact_writer.register_verified(
                session,
                staged,
                tenant_id=scoped.tenant_id,
                verified_at=now,
            )
            if existing is None:
                await self._repository.append_source_document(
                    session,
                    scoped.tenant_id,
                    source,
                    audit_event_id,
                )
            await self._repository.append_source_version(
                session,
                scoped.tenant_id,
                bundle,
                audit_event_id,
            )
            await self._repository.append_formula_signatures(
                session,
                scoped.tenant_id,
                signatures,
                audit_event_id,
            )
            result = ImportedSourceResult(
                source_document=source,
                source_version=source_version,
                document_ir=document_ir,
                formula_signature_count=len(signatures),
            ).to_document()
            await self._transactions.append_outbox(
                session,
                scoped,
                partition_key=f"topic4-c2:{scoped.tenant_id}:{command.course_id}",
                event_type="topic4.knowledge.source_imported",
                payload=result,
            )
            return result

        result = await self._transactions.execute(
            operation="topic4.c2.source.import",
            idempotency_key=idempotency_key,
            request_document=request_document,
            callback=callback,
        )
        return self._imported_source_from_document(result)

    async def build_and_activate(
        self,
        command: KnowledgeBaseBuildCommand,
        *,
        idempotency_key: str,
    ) -> KnowledgeBaseBuildResult:
        context = current_tenant()
        now = datetime.now(UTC)
        graph, bundles, signatures, stored_profile = await self._load_build_inputs(
            context,
            command,
        )
        request_document = {
            "course_id": command.course_id,
            "version": command.version,
            "source_document_version_ids": [
                str(identifier) for identifier in command.source_document_version_ids
            ],
            "graph_snapshot_id": str(graph.snapshot_id),
            "graph_snapshot_sha256": graph.content_sha256,
            "expected_activation_version": command.expected_activation_version,
        }
        replay = await self._transactions.completed_result(
            operation="topic4.c2.knowledge_base.build_activate",
            idempotency_key=idempotency_key,
            request_document=request_document,
        )
        if replay is not None:
            return self._build_result_from_document(replay)
        profile = stored_profile or self._embedding_profile(context, now)
        knowledge_base_id = uuid5(
            NAMESPACE_URL,
            f"liyans://{context.tenant_id}/topic4/c2/{command.course_id}/{command.version}",
        )
        manifest_id = uuid5(knowledge_base_id, "index-build-manifest")
        chunks = await self._build_chunks(
            context,
            knowledge_base_id,
            profile.embedding_profile_id,
            bundles,
            signatures,
            now,
        )
        entries = self._corpus_entries(chunks, bundles)
        try:
            index, serialized_shards = await asyncio.to_thread(
                self._build_index,
                context.tenant_id,
                command.course_id,
                knowledge_base_id,
                entries,
                graph,
            )
        except RetrievalIndexError as exc:
            raise self._transactions.integrity(
                "The local Faiss index could not be built without degradation."
            ) from exc
        index_artifacts: list[tuple[StagedArtifact, StagedArtifact]] = []
        shard_manifests: list[IndexShardManifestV1] = []
        for shard in serialized_shards:
            faiss_artifact = await self._artifact_writer.stage(
                artifact_id=uuid5(
                    knowledge_base_id,
                    f"artifact:faiss-shard:{shard.ordinal}",
                ),
                tenant_id=context.tenant_id,
                object_key=(
                    f"topic4/c2/indexes/{knowledge_base_id.hex}/shard-{shard.ordinal:05d}.faiss"
                ),
                media_type="application/octet-stream",
                content_encoding="identity",
                content=shard.faiss_payload,
                created_by_subject=context.subject_ref,
                created_at=now,
                provenance=self._index_provenance(
                    knowledge_base_id,
                    manifest_id,
                    shard.ordinal,
                    "faiss",
                ),
            )
            bm25_artifact = await self._artifact_writer.stage(
                artifact_id=uuid5(
                    knowledge_base_id,
                    f"artifact:bm25-shard:{shard.ordinal}",
                ),
                tenant_id=context.tenant_id,
                object_key=(
                    f"topic4/c2/indexes/{knowledge_base_id.hex}/"
                    f"shard-{shard.ordinal:05d}.bm25.json.gz"
                ),
                media_type="application/json",
                content_encoding="gzip",
                content=shard.bm25_payload,
                created_by_subject=context.subject_ref,
                created_at=now,
                provenance=self._index_provenance(
                    knowledge_base_id,
                    manifest_id,
                    shard.ordinal,
                    "bm25",
                ),
            )
            index_artifacts.append((faiss_artifact, bm25_artifact))
            shard_manifests.append(
                build_topic4_record(
                    IndexShardManifestV1,
                    trace_id=context.trace_id,
                    tenant_id=context.tenant_id,
                    version_cas=1,
                    created_at=now,
                    immutable=True,
                    schema_version="index-shard-manifest.v1",
                    shard_id=uuid5(manifest_id, f"shard:{shard.ordinal}"),
                    ordinal=shard.ordinal,
                    first_vector_ordinal=chunks[shard.first_position].vector_ordinal,
                    vector_count=shard.vector_count,
                    faiss_artifact=faiss_artifact.reference,
                    faiss_sha256=shard.faiss_sha256,
                    bm25_artifact=bm25_artifact.reference,
                    bm25_sha256=shard.bm25_sha256,
                )
            )
        building_manifest = build_topic4_record(
            IndexBuildManifestV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="index-build-manifest.v1",
            index_build_manifest_id=manifest_id,
            knowledge_base_version_id=knowledge_base_id,
            embedding_profile_id=profile.embedding_profile_id,
            state=IndexBuildState.BUILDING,
            chunk_count=0,
            shard_count=0,
            shards=[],
            graph_snapshot_id=graph.snapshot_id,
            graph_snapshot_version=graph.graph_version,
            toolchain_manifest_version=self._config.toolchain_manifest_version,
            built_at=None,
            failure_code=None,
        )
        ready_manifest = build_topic4_record(
            IndexBuildManifestV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=2,
            created_at=now,
            immutable=True,
            schema_version="index-build-manifest.v1",
            index_build_manifest_id=manifest_id,
            knowledge_base_version_id=knowledge_base_id,
            embedding_profile_id=profile.embedding_profile_id,
            state=IndexBuildState.READY,
            chunk_count=len(chunks),
            shard_count=len(shard_manifests),
            shards=shard_manifests,
            graph_snapshot_id=graph.snapshot_id,
            graph_snapshot_version=graph.graph_version,
            toolchain_manifest_version=self._config.toolchain_manifest_version,
            built_at=now,
            failure_code=None,
        )
        knowledge_base = build_topic4_record(
            KnowledgeBaseVersionV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="knowledge-base.version.v1",
            knowledge_base_version_id=knowledge_base_id,
            version=command.version,
            lifecycle=SourceLifecycle.ACTIVE,
            source_document_version_ids=list(command.source_document_version_ids),
            graph_snapshot_id=graph.snapshot_id,
            graph_snapshot_version=graph.graph_version,
            index_build_manifest_id=manifest_id,
            embedding_profile_id=profile.embedding_profile_id,
            activated_at=now,
            retired_at=None,
        )
        flattened_artifacts = tuple(artifact for pair in index_artifacts for artifact in pair)

        async def callback(session, scoped: TenantContext) -> dict[str, object]:
            await self._transactions.lock(
                session,
                f"topic4-c2-kb:{scoped.tenant_id}:{command.course_id}",
            )
            await self._transactions.lock(session, f"topic4-c2-profile:{scoped.tenant_id}")
            if (
                await self._repository.get_knowledge_base_version_by_label(
                    session,
                    scoped.tenant_id,
                    command.course_id,
                    command.version,
                )
                is not None
            ):
                raise self._transactions.conflict(
                    "The immutable knowledge-base version already exists."
                )
            latest_activation = await self._repository.latest_activation(
                session,
                scoped.tenant_id,
                command.course_id,
            )
            current_version = (
                0 if latest_activation is None else latest_activation.activation_version
            )
            if (
                command.expected_activation_version is not None
                and command.expected_activation_version != current_version
            ):
                raise self._transactions.conflict(
                    "The knowledge-base activation CAS version is stale."
                )
            current_graph = await self._topic1_repository.get_snapshot(
                session,
                scoped.tenant_id,
                graph.snapshot_id,
            )
            if current_graph is None or current_graph.content_sha256 != graph.content_sha256:
                raise self._transactions.integrity(
                    "Topic 1 graph snapshot changed during knowledge-base build."
                )
            current_bundles = await self._repository.list_source_version_bundles(
                session,
                scoped.tenant_id,
                command.source_document_version_ids,
            )
            if len(current_bundles) != len(command.source_document_version_ids):
                raise self._transactions.integrity(
                    "A source version disappeared during knowledge-base build."
                )
            persisted_profile = await self._repository.get_embedding_profile(
                session,
                scoped.tenant_id,
                tokenizer_version=self._config.tokenizer_version,
                hash_seed_version=self._config.hash_seed_version,
            )
            audit_event_id = await self._transactions.append_audit(
                session,
                scoped,
                action="KNOWLEDGE_BASE_ACTIVATED",
                target_ref=str(knowledge_base_id),
                metadata={
                    "course_id": command.course_id,
                    "knowledge_base_version": command.version,
                    "knowledge_base_version_id": str(knowledge_base_id),
                    "manifest_id": str(manifest_id),
                    "chunk_count": len(chunks),
                    "shard_count": len(shard_manifests),
                    "graph_snapshot_id": str(graph.snapshot_id),
                    "graph_snapshot_version": graph.graph_version,
                    "replaces_activation_id": (
                        None if latest_activation is None else str(latest_activation.activation_id)
                    ),
                },
            )
            await self._artifact_writer.register_verified(
                session,
                flattened_artifacts,
                tenant_id=scoped.tenant_id,
                verified_at=now,
            )
            if persisted_profile is None:
                await self._repository.append_embedding_profile(
                    session,
                    scoped.tenant_id,
                    profile,
                    audit_event_id,
                )
            elif persisted_profile.embedding_profile_id != profile.embedding_profile_id:
                raise self._transactions.integrity(
                    "The embedding profile identity changed during the build."
                )
            await self._repository.append_knowledge_base_version(
                session,
                scoped.tenant_id,
                command.course_id,
                knowledge_base,
                audit_event_id,
            )
            await self._repository.append_chunks(
                session,
                scoped.tenant_id,
                chunks,
                audit_event_id,
            )
            await self._repository.append_manifest(
                session,
                scoped.tenant_id,
                building_manifest,
                audit_event_id,
            )
            await self._repository.append_manifest(
                session,
                scoped.tenant_id,
                ready_manifest,
                audit_event_id,
            )
            activation = self._activation(
                scoped,
                command.course_id,
                knowledge_base_id,
                latest_activation,
                now,
            )
            await self._repository.append_activation(
                session,
                scoped.tenant_id,
                activation,
                audit_event_id,
            )
            result = KnowledgeBaseBuildResult(
                knowledge_base=knowledge_base,
                embedding_profile=profile,
                ready_manifest=ready_manifest,
                activation=activation,
                chunk_count=len(chunks),
            ).to_document()
            await self._transactions.append_outbox(
                session,
                scoped,
                partition_key=f"topic4-c2:{scoped.tenant_id}:{command.course_id}",
                event_type="topic4.knowledge.base_activated",
                payload=result,
            )
            return result

        result = await self._transactions.execute(
            operation="topic4.c2.knowledge_base.build_activate",
            idempotency_key=idempotency_key,
            request_document=request_document,
            callback=callback,
        )
        self._indexes.activate(index)
        return self._build_result_from_document(result)

    def _build_index(
        self,
        tenant_id: str,
        course_id: str,
        knowledge_base_id: UUID,
        entries: tuple[CorpusEntry, ...],
        graph,
    ) -> tuple[LocalHybridIndex, tuple[SerializedHybridShard, ...]]:
        index = LocalHybridIndex(
            tenant_id=tenant_id,
            course_id=course_id,
            knowledge_base_version_id=knowledge_base_id,
            entries=entries,
            tokenizer=self._tokenizer,
            vectorizer=self._vectorizer,
            graph_expander=TopicGraphExpander(graph),
            shard_size=self._config.shard_size,
        )
        return index, index.serialized_shards()

    async def _required_graph(self, context: TenantContext, course_id: str):
        async with self._database.transaction(context=current_session_context()) as session:
            course = await self._topic1_repository.get_course(
                session,
                context.tenant_id,
                course_id,
            )
            graph = await self._topic1_repository.latest_snapshot(
                session,
                context.tenant_id,
                course_id,
            )
        if course is None or graph is None:
            raise self._transactions.not_found(
                "The Topic 1 course graph required by C2 was not found."
            )
        return graph

    async def _load_build_inputs(
        self,
        context: TenantContext,
        command: KnowledgeBaseBuildCommand,
    ):
        async with self._database.transaction(context=current_session_context()) as session:
            graph = (
                await self._topic1_repository.latest_snapshot(
                    session,
                    context.tenant_id,
                    command.course_id,
                )
                if command.graph_snapshot_id is None
                else await self._topic1_repository.get_snapshot(
                    session,
                    context.tenant_id,
                    command.graph_snapshot_id,
                )
            )
            bundles = await self._repository.list_source_version_bundles(
                session,
                context.tenant_id,
                command.source_document_version_ids,
            )
            signatures = await self._repository.list_formula_signatures(
                session,
                context.tenant_id,
                command.source_document_version_ids,
            )
            profile = await self._repository.get_embedding_profile(
                session,
                context.tenant_id,
                tokenizer_version=self._config.tokenizer_version,
                hash_seed_version=self._config.hash_seed_version,
            )
        if graph is None or graph.course_id != command.course_id:
            raise self._transactions.not_found(
                "The requested Topic 1 graph snapshot was not found for the course."
            )
        if len(bundles) != len(command.source_document_version_ids):
            raise self._transactions.not_found(
                "One or more authoritative source versions were not found."
            )
        if any(bundle.source_document.course_id != command.course_id for bundle in bundles):
            raise self._transactions.integrity("A source version belongs to a different course.")
        if any(bundle.source_version.lifecycle == SourceLifecycle.REVOKED for bundle in bundles):
            raise self._transactions.integrity(
                "A revoked source version cannot enter an active knowledge base."
            )
        return graph, bundles, tuple(signatures), profile

    async def _build_chunks(
        self,
        context: TenantContext,
        knowledge_base_id: UUID,
        embedding_profile_id: UUID,
        bundles: list[SourceVersionBundle],
        signatures,
        now: datetime,
    ) -> tuple[KnowledgeChunkV1, ...]:
        signatures_by_source: dict[UUID, tuple] = {}
        for bundle in bundles:
            signatures_by_source[bundle.source_version.source_document_version_id] = tuple(
                signature
                for signature in signatures
                if signature.source_document_version_id
                == bundle.source_version.source_document_version_id
            )
        chunks: list[KnowledgeChunkV1] = []
        vector_ordinal = 0
        for bundle in bundles:
            section_reference = bundle.document_ir.sections[0].text_artifact
            if any(
                section.text_artifact != section_reference
                for section in bundle.document_ir.sections
            ):
                raise self._transactions.integrity(
                    "Document IR sections reference inconsistent section artifacts."
                )
            section_payload = await self._artifact_writer.read(
                context.tenant_id,
                section_reference,
            )
            parsed_sections = DeterministicDocumentParser.read_sections_payload(section_payload)
            ir_by_id = {section.section_id: section for section in bundle.document_ir.sections}
            for section in parsed_sections:
                ir_section = ir_by_id.get(section.section_id)
                if ir_section is None or ir_section.text_sha256 != section.text_sha256:
                    raise self._transactions.integrity(
                        "Document IR section does not match its immutable text artifact."
                    )
                source_signatures = signatures_by_source[
                    bundle.source_version.source_document_version_id
                ]
                formula_ids = tuple(
                    identifier
                    for identifier in ir_section.formula_signature_ids
                    if any(
                        signature.formula_signature_id == identifier
                        for signature in source_signatures
                    )
                )
                drafts = self._chunker.chunk(
                    ParsedSection(
                        section_id=section.section_id,
                        parent_section_id=section.parent_section_id,
                        ordinal=section.ordinal,
                        title=section.title,
                        json_pointer=section.json_pointer,
                        text=section.text,
                        text_sha256=section.text_sha256,
                        explicit_knowledge_point_ids=tuple(ir_section.topic1_knowledge_point_ids),
                    ),
                    knowledge_point_ids=tuple(ir_section.topic1_knowledge_point_ids),
                    formula_signature_ids=formula_ids,
                )
                for draft in drafts:
                    chunk_id = uuid5(
                        knowledge_base_id,
                        (
                            f"chunk:{bundle.source_version.source_document_version_id}:"
                            f"{draft.section_id}:{draft.chunk_ordinal}:{draft.content_sha256}"
                        ),
                    )
                    chunks.append(
                        build_topic4_record(
                            KnowledgeChunkV1,
                            trace_id=context.trace_id,
                            tenant_id=context.tenant_id,
                            version_cas=1,
                            created_at=now,
                            immutable=True,
                            schema_version="knowledge-chunk.v1",
                            knowledge_chunk_id=chunk_id,
                            knowledge_base_version_id=knowledge_base_id,
                            source_document_version_id=(
                                bundle.source_version.source_document_version_id
                            ),
                            document_ir_id=bundle.document_ir.document_ir_id,
                            section_id=draft.section_id,
                            chunk_ordinal=draft.chunk_ordinal,
                            normalized_text=draft.normalized_text,
                            content_sha256=draft.content_sha256,
                            token_count=draft.token_count,
                            topic1_knowledge_point_ids=list(draft.topic1_knowledge_point_ids),
                            formula_signature_ids=list(draft.formula_signature_ids),
                            lexical_terms=list(draft.lexical_terms),
                            embedding_profile_id=embedding_profile_id,
                            vector_ordinal=vector_ordinal,
                        )
                    )
                    vector_ordinal += 1
        if not chunks:
            raise self._transactions.integrity(
                "Knowledge-base build produced no retrievable chunks."
            )
        return tuple(chunks)

    @staticmethod
    def _corpus_entries(
        chunks: tuple[KnowledgeChunkV1, ...],
        bundles: list[SourceVersionBundle],
    ) -> tuple[CorpusEntry, ...]:
        sources = {
            bundle.source_version.source_document_version_id: bundle.source_document
            for bundle in bundles
        }
        return tuple(
            CorpusEntry(
                chunk=chunk,
                source_document_id=sources[chunk.source_document_version_id].source_document_id,
                citation=sources[chunk.source_document_version_id].canonical_citation,
                authority_tier=sources[chunk.source_document_version_id].authority_tier,
            )
            for chunk in chunks
        )

    def _embedding_profile(
        self,
        context: TenantContext,
        now: datetime,
    ) -> EmbeddingProfileV1:
        identifier = uuid5(
            NAMESPACE_URL,
            (
                f"liyans://{context.tenant_id}/topic4/c2/embedding-profile/"
                f"{self._config.tokenizer_version}/{self._config.hash_seed_version}"
            ),
        )
        return build_topic4_record(
            EmbeddingProfileV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="embedding-profile.v1",
            embedding_profile_id=identifier,
            algorithm="HASHED_LEXICAL_2048",
            dimension=2048,
            tokenizer_version=self._config.tokenizer_version,
            hash_seed_version=self._config.hash_seed_version,
            normalization="L2",
            signed_hashing=True,
            network_access=False,
        )

    @staticmethod
    def _activation(
        context: TenantContext,
        course_id: str,
        knowledge_base_id: UUID,
        previous: KnowledgeBaseActivation | None,
        now: datetime,
    ) -> KnowledgeBaseActivation:
        version = 1 if previous is None else previous.activation_version + 1
        activation_id = uuid5(knowledge_base_id, f"activation:{version}")
        material = {
            "schema_version": "knowledge-base.activation.v1",
            "activation_id": str(activation_id),
            "tenant_id": context.tenant_id,
            "trace_id": context.trace_id,
            "course_id": course_id,
            "activation_version": version,
            "knowledge_base_version_id": str(knowledge_base_id),
            "replaces_activation_id": (None if previous is None else str(previous.activation_id)),
            "activated_at": now.isoformat(),
            "version_cas": version,
            "immutable": True,
            "created_at": now.isoformat(),
        }
        return KnowledgeBaseActivation(
            activation_record_id=uuid5(activation_id, "activation-record"),
            activation_id=activation_id,
            tenant_id=context.tenant_id,
            trace_id=context.trace_id,
            course_id=course_id,
            activation_version=version,
            knowledge_base_version_id=knowledge_base_id,
            replaces_activation_id=None if previous is None else previous.activation_id,
            activated_at=now,
            version_cas=version,
            record_sha256=canonical_sha256(material),
            immutable=True,
            created_at=now,
        )

    @staticmethod
    def _activation_from_document(raw) -> KnowledgeBaseActivation:
        if not isinstance(raw, dict):
            raise ValueError("activation result must be an object")
        return KnowledgeBaseActivation(
            activation_record_id=uuid5(UUID(str(raw["activation_id"])), "activation-record"),
            activation_id=UUID(str(raw["activation_id"])),
            tenant_id=str(raw["tenant_id"]),
            trace_id=str(raw["trace_id"]),
            course_id=str(raw["course_id"]),
            activation_version=int(raw["activation_version"]),
            knowledge_base_version_id=UUID(str(raw["knowledge_base_version_id"])),
            replaces_activation_id=(
                None
                if raw.get("replaces_activation_id") is None
                else UUID(str(raw["replaces_activation_id"]))
            ),
            activated_at=datetime.fromisoformat(str(raw["activated_at"])),
            version_cas=int(raw["version_cas"]),
            record_sha256=str(raw["record_sha256"]),
            immutable=bool(raw["immutable"]),
            created_at=datetime.fromisoformat(str(raw["created_at"])),
        )

    @staticmethod
    def _same_source(left: SourceDocumentV1, right: SourceDocumentV1) -> bool:
        excluded = {"record_sha256", "created_at", "trace_id"}
        return left.model_dump(mode="json", exclude=excluded) == right.model_dump(
            mode="json",
            exclude=excluded,
        )

    @staticmethod
    def _source_object_key(version_id: UUID, media_type: str) -> str:
        suffix = {
            "text/markdown": "md",
            "text/plain": "txt",
            "application/json": "json",
        }[media_type]
        return f"topic4/c2/sources/{version_id.hex}/source.{suffix}"

    @staticmethod
    def _index_provenance(
        knowledge_base_id: UUID,
        manifest_id: UUID,
        shard_ordinal: int,
        index_type: str,
    ) -> dict[str, object]:
        return {
            "topic": "topic4-c2",
            "purpose": "local-rag-index-shard",
            "knowledge_base_version_id": str(knowledge_base_id),
            "index_build_manifest_id": str(manifest_id),
            "shard_ordinal": shard_ordinal,
            "index_type": index_type,
            "network_access": False,
        }

    @staticmethod
    def _imported_source_from_document(raw: dict[str, object]) -> ImportedSourceResult:
        return ImportedSourceResult(
            source_document=SourceDocumentV1.model_validate(raw["source_document"]),
            source_version=SourceDocumentVersionV1.model_validate(raw["source_version"]),
            document_ir=DocumentIRV1.model_validate(raw["document_ir"]),
            formula_signature_count=int(raw["formula_signature_count"]),
        )

    @staticmethod
    def _build_result_from_document(raw: dict[str, object]) -> KnowledgeBaseBuildResult:
        return KnowledgeBaseBuildResult(
            knowledge_base=KnowledgeBaseVersionV1.model_validate(raw["knowledge_base"]),
            embedding_profile=EmbeddingProfileV1.model_validate(raw["embedding_profile"]),
            ready_manifest=IndexBuildManifestV1.model_validate(raw["ready_manifest"]),
            activation=KnowledgeBaseLifecycleService._activation_from_document(raw["activation"]),
            chunk_count=int(raw["chunk_count"]),
        )
