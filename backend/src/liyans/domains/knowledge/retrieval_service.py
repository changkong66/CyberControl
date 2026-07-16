from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import (
    EvidenceBundleV1,
    EvidenceRefV1,
    IndexBuildManifestV1,
    IndexBuildState,
    IndexShardManifestV1,
    KnowledgeBaseVersionV1,
    QueryPlanV1,
    RetrievalRequestV1,
    RetrievalResponseV1,
    RetrievalStatus,
    RetrievalTimingV1,
    SourceAuthorityTier,
)

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import TenantContext, current_tenant
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.session import DatabaseSessionManager

from .artifact_writer import KnowledgeArtifactWriter
from .entities import SourceVersionBundle
from .ingestion import FormulaSignatureExtractor
from .postgres_repository import PostgresKnowledgeRepository
from .retrieval import (
    CorpusEntry,
    DeterministicTokenizer,
    HashedLexicalVectorizer,
    HotReloadableRAGIndex,
    HybridShardPayload,
    IndexRestoreReport,
    LocalHybridIndex,
    RetrievalIndexError,
    TopicGraphExpander,
)
from .transactions import KnowledgeTransactionCoordinator

NEGATION_MARKERS = frozenset(
    {"不", "非", "无", "不能", "不可", "错误", "不稳定", "not", "no", "without", "unstable"}
)
WORD_PATTERN = re.compile(r"[a-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]")


@dataclass(frozen=True, slots=True)
class LoadedKnowledgeBase:
    course_id: str
    activation_id: UUID
    activation_version: int
    knowledge_base: KnowledgeBaseVersionV1
    manifest: IndexBuildManifestV1
    graph: Topic1GraphSnapshotV1
    source_bundles: tuple[SourceVersionBundle, ...]
    index: LocalHybridIndex


class ClaimQueryPlanner:
    def __init__(self) -> None:
        self._tokenizer = DeterministicTokenizer()
        self._formula_extractor = FormulaSignatureExtractor()

    def build(
        self,
        claim: ClaimV1,
        *,
        course_id: str,
        target_kp_id: str | None,
        knowledge_base: KnowledgeBaseVersionV1,
        graph: Topic1GraphSnapshotV1,
        signatures,
        created_at: datetime,
    ) -> QueryPlanV1:
        statement = claim.normalized_statement.strip()
        lexical_queries = [statement]
        formula_text = " ".join(
            self._formula_extractor.canonicalize(candidate)
            for candidate in self._formula_extractor._candidates(statement)
        ).strip()
        if formula_text and formula_text not in lexical_queries:
            lexical_queries.append(formula_text)
        words = self._tokenizer.tokenize(statement)
        if len(words) > 12:
            compact = " ".join(words[:48])
            if compact not in lexical_queries:
                lexical_queries.append(compact)
        seeds = self._graph_seeds(statement, target_kp_id, graph)
        formula_ids = self._formula_extractor.match_ids(statement, tuple(signatures))
        query_plan_id = uuid5(
            claim.claim_id,
            f"topic4-c2-query-plan:{knowledge_base.knowledge_base_version_id}:v1",
        )
        return build_topic4_record(
            QueryPlanV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="query-plan.v1",
            query_plan_id=query_plan_id,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            knowledge_base_version_id=knowledge_base.knowledge_base_version_id,
            lexical_queries=list(dict.fromkeys(lexical_queries))[:32],
            graph_seed_knowledge_point_ids=seeds,
            formula_signature_ids=list(formula_ids),
            top_k_bm25=64,
            top_k_vector=64,
            top_k_graph=32,
            top_k_formula=32,
            final_top_k=16,
            fusion_method="RRF_V1",
            tenant_filter_required=True,
            timeout_ms=200,
        )

    @staticmethod
    def _graph_seeds(
        statement: str,
        target_kp_id: str | None,
        graph: Topic1GraphSnapshotV1,
    ) -> list[str]:
        normalized = statement.casefold()
        candidates: list[tuple[int, str]] = []
        for point in graph.content.knowledge_points:
            names = [point.kp_id, point.title, *getattr(point, "aliases", [])]
            if any(len(name) >= 2 and name.casefold() in normalized for name in names):
                candidates.append((0 if point.kp_id == target_kp_id else 1, point.kp_id))
        if target_kp_id is not None and any(
            point.kp_id == target_kp_id for point in graph.content.knowledge_points
        ):
            candidates.append((0, target_kp_id))
        return [identifier for _, identifier in sorted(set(candidates), key=lambda item: item)]


class EvidenceAssembler:
    def build(
        self,
        result,
        plan: QueryPlanV1,
        *,
        verification_id: UUID,
        claim_id: UUID,
        created_at: datetime,
    ) -> tuple[tuple[EvidenceRefV1, ...], EvidenceBundleV1]:
        refs: list[EvidenceRefV1] = []
        for ranked in result.evidence:
            excerpt = ranked.entry.chunk.normalized_text[:8192]
            excerpt_sha256 = canonical_sha256(excerpt)
            refs.append(
                build_topic4_record(
                    EvidenceRefV1,
                    trace_id=plan.trace_id,
                    tenant_id=plan.tenant_id,
                    version_cas=1,
                    created_at=created_at,
                    immutable=True,
                    schema_version="evidence.ref.v1",
                    evidence_ref_id=uuid5(
                        claim_id,
                        (
                            f"evidence:{plan.knowledge_base_version_id}:"
                            f"{ranked.entry.chunk.knowledge_chunk_id}:{excerpt_sha256}"
                        ),
                    ),
                    verification_id=verification_id,
                    claim_id=claim_id,
                    knowledge_base_version_id=plan.knowledge_base_version_id,
                    knowledge_chunk_id=ranked.entry.chunk.knowledge_chunk_id,
                    source_document_id=ranked.entry.source_document_id,
                    source_document_version_id=ranked.entry.chunk.source_document_version_id,
                    section_id=ranked.entry.chunk.section_id,
                    citation=ranked.entry.citation,
                    excerpt=excerpt,
                    excerpt_sha256=excerpt_sha256,
                    bm25_score=ranked.bm25_score,
                    vector_score=ranked.vector_score,
                    graph_score=ranked.graph_score,
                    formula_score=ranked.formula_score,
                    fused_score=ranked.fused_score,
                    source_authority_tier=ranked.entry.authority_tier,
                )
            )
        coverage = self._coverage(refs, plan)
        bundle = build_topic4_record(
            EvidenceBundleV1,
            trace_id=plan.trace_id,
            tenant_id=plan.tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="evidence.bundle.v1",
            evidence_bundle_id=uuid5(plan.query_plan_id, "evidence-bundle:v1"),
            verification_id=verification_id,
            claim_id=claim_id,
            query_plan_id=plan.query_plan_id,
            knowledge_base_version_id=plan.knowledge_base_version_id,
            evidence_ref_ids=[item.evidence_ref_id for item in refs],
            coverage_score=coverage,
            conflicting_evidence=self._has_conflict(refs),
            retrieval_timing=build_topic4_record(
                RetrievalTimingV1,
                trace_id=plan.trace_id,
                tenant_id=plan.tenant_id,
                version_cas=1,
                created_at=created_at,
                immutable=True,
                schema_version="retrieval-timing.v1",
                bm25_ms=result.metrics.bm25_ms,
                vector_ms=result.metrics.vector_ms,
                graph_ms=result.metrics.graph_ms,
                formula_ms=result.metrics.formula_ms,
                fusion_ms=result.metrics.fusion_ms,
                total_ms=result.metrics.total_ms,
            ),
            retrieval_pipeline_version="local-hybrid-rag-v1",
            degraded_reason_codes=list(result.degraded_reason_codes),
        )
        return tuple(refs), bundle

    @staticmethod
    def _coverage(refs: list[EvidenceRefV1], plan: QueryPlanV1) -> float:
        if not refs:
            return 0.0
        count_score = min(1.0, len(refs) / max(1, plan.final_top_k))
        rank_score = min(1.0, sum(item.fused_score for item in refs) * 60.0 / max(1, len(refs)))
        channel_score = sum(
            any(
                value is not None
                for value in (
                    item.bm25_score,
                    item.vector_score,
                    item.graph_score,
                    item.formula_score,
                )
            )
            for item in refs
        ) / len(refs)
        authority_score = sum(
            {
                SourceAuthorityTier.PRIMARY_STANDARD: 1.0,
                SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK: 0.9,
                SourceAuthorityTier.PEER_REVIEWED: 0.8,
                SourceAuthorityTier.OFFICIAL_DOCUMENTATION: 0.7,
                SourceAuthorityTier.CURATED_INTERNAL: 0.6,
            }[item.source_authority_tier]
            for item in refs
        ) / len(refs)
        return min(
            1.0,
            0.25 * count_score + 0.35 * rank_score + 0.2 * channel_score + 0.2 * authority_score,
        )

    @staticmethod
    def _has_conflict(refs: list[EvidenceRefV1]) -> bool:
        polarities: set[int] = set()
        for ref in refs:
            words = set(WORD_PATTERN.findall(ref.excerpt.casefold()))
            polarities.add(-1 if words & NEGATION_MARKERS else 1)
        return len(polarities) > 1


class KnowledgeRetrievalService:
    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: PostgresKnowledgeRepository,
        topic1_repository: PostgresTopic1Repository,
        artifact_writer: KnowledgeArtifactWriter,
        transactions: KnowledgeTransactionCoordinator,
        indexes: HotReloadableRAGIndex,
        *,
        shard_size: int = 10_000,
        retrieval_pipeline_version: str = "local-hybrid-rag-v1",
    ) -> None:
        self._database = database
        self._repository = repository
        self._topic1_repository = topic1_repository
        self._artifact_writer = artifact_writer
        self._transactions = transactions
        self._indexes = indexes
        self._shard_size = shard_size
        self._retrieval_pipeline_version = retrieval_pipeline_version
        self._tokenizer = DeterministicTokenizer()
        self._vectorizer = HashedLexicalVectorizer(self._tokenizer)
        self._planner = ClaimQueryPlanner()
        self._assembler = EvidenceAssembler()
        self._load_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._loaded: dict[tuple[str, str], LoadedKnowledgeBase] = {}

    async def retrieve_claim(
        self,
        claim: ClaimV1,
        *,
        course_id: str,
        target_kp_id: str | None = None,
        deadline_at: datetime | None = None,
        idempotency_key: str,
    ) -> RetrievalResponseV1:
        context = current_tenant()
        if claim.tenant_id != context.tenant_id:
            raise LiyanError(
                ErrorCode.TENANT_MISMATCH,
                "The retrieval claim does not belong to the trusted tenant context.",
                category=ErrorCategory.TENANT,
                status_code=403,
            )
        now = datetime.now(UTC)
        deadline = deadline_at or (now + timedelta(seconds=10))
        if deadline.tzinfo is None or deadline <= now:
            raise LiyanError(
                ErrorCode.TOPIC4_DEADLINE_EXPIRED,
                "The retrieval deadline has expired.",
                category=ErrorCategory.TIMEOUT,
                status_code=408,
            )
        loaded = await self.load_active(course_id)
        plan = self._planner.build(
            claim,
            course_id=course_id,
            target_kp_id=target_kp_id,
            knowledge_base=loaded.knowledge_base,
            graph=loaded.graph,
            signatures=await self._signatures_for_loaded(loaded),
            created_at=now,
        )
        request_id = uuid5(claim.claim_id, f"retrieval-request:{idempotency_key}")
        request = build_topic4_record(
            RetrievalRequestV1,
            trace_id=claim.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="retrieval.request.v1",
            retrieval_request_id=request_id,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            query_plan=plan,
            deadline_at=deadline,
        )
        response, refs, bundle = await self._execute_search(
            loaded,
            request,
            deadline,
        )

        async def callback(session, scoped: TenantContext) -> dict[str, object]:
            current_activation = await self._repository.latest_activation(
                session,
                scoped.tenant_id,
                course_id,
            )
            if (
                current_activation is None
                or current_activation.knowledge_base_version_id
                != loaded.knowledge_base.knowledge_base_version_id
            ):
                raise self._transactions.conflict(
                    "The active knowledge base changed during retrieval."
                )
            existing = await self._repository.get_retrieval_response(
                session,
                scoped.tenant_id,
                request_id,
            )
            if existing is not None:
                return existing.model_dump(mode="json")
            audit_event_id = await self._transactions.append_audit(
                session,
                scoped,
                action="KNOWLEDGE_RETRIEVAL_COMPLETED",
                target_ref=str(claim.claim_id),
                metadata={
                    "verification_id": str(claim.verification_id),
                    "claim_id": str(claim.claim_id),
                    "query_plan_id": str(plan.query_plan_id),
                    "retrieval_request_id": str(request_id),
                    "knowledge_base_version_id": str(
                        loaded.knowledge_base.knowledge_base_version_id
                    ),
                    "status": response.status.value,
                    "elapsed_ms": response.elapsed_ms,
                    "evidence_count": len(refs),
                    "degraded_reason_codes": list(response.degraded_reason_codes),
                },
            )
            await self._repository.append_retrieval_result(
                session,
                scoped.tenant_id,
                plan=plan,
                response=response,
                evidence_refs=refs,
                evidence_bundle=bundle,
                audit_event_id=audit_event_id,
            )
            result = response.model_dump(mode="json")
            await self._transactions.append_outbox(
                session,
                scoped,
                partition_key=f"topic4-c2:{scoped.tenant_id}:{course_id}",
                event_type="topic4.knowledge.retrieval_completed",
                payload=result,
            )
            return result

        result = await self._transactions.execute(
            operation="topic4.c2.knowledge.retrieve_claim",
            idempotency_key=idempotency_key,
            request_document={
                "verification_id": str(claim.verification_id),
                "claim_id": str(claim.claim_id),
                "course_id": course_id,
                "knowledge_base_version_id": str(loaded.knowledge_base.knowledge_base_version_id),
                "claim_sha256": claim.claim_sha256,
            },
            callback=callback,
        )
        return RetrievalResponseV1.model_validate(result)

    async def load_active(self, course_id: str) -> LoadedKnowledgeBase:
        context = current_tenant()
        key = (context.tenant_id, course_id)
        cached = self._loaded.get(key)
        if cached is not None and await self._cache_matches_activation(cached):
            return cached
        lock = self._load_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._loaded.get(key)
            if cached is not None and await self._cache_matches_activation(cached):
                return cached
            restored = await self._read_active_metadata(course_id)
            if restored is None:
                raise self._transactions.not_found(
                    "No active local knowledge base exists for the tenant and course."
                )
            loaded, report = restored
            self._indexes.activate(loaded.index)
            if report.recovery_required:
                repaired = await self._persist_recovery(loaded, report)
                if repaired is not None:
                    loaded = repaired
            self._loaded[key] = loaded
            return loaded

    async def reload_active(self, course_id: str) -> LoadedKnowledgeBase:
        context = current_tenant()
        self._loaded.pop((context.tenant_id, course_id), None)
        return await self.load_active(course_id)

    async def _read_active_metadata(
        self,
        course_id: str,
    ) -> tuple[LoadedKnowledgeBase, IndexRestoreReport] | None:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            activation = await self._repository.latest_activation(
                session,
                context.tenant_id,
                course_id,
            )
            if activation is None:
                return None
            knowledge_base = await self._repository.get_knowledge_base_version(
                session,
                context.tenant_id,
                activation.knowledge_base_version_id,
            )
            if knowledge_base is None:
                raise self._integrity("Active activation points to a missing knowledge base.")
            manifest = await self._repository.latest_manifest(
                session,
                context.tenant_id,
                knowledge_base.index_build_manifest_id,
            )
            graph = await self._topic1_repository.get_snapshot(
                session,
                context.tenant_id,
                knowledge_base.graph_snapshot_id,
            )
            chunks = await self._repository.list_chunks(
                session,
                context.tenant_id,
                knowledge_base.knowledge_base_version_id,
            )
            bundles = await self._repository.list_source_version_bundles(
                session,
                context.tenant_id,
                knowledge_base.source_document_version_ids,
            )
        if manifest is None or manifest.state != IndexBuildState.READY:
            raise self._integrity("Active knowledge base does not have a READY index manifest.")
        if graph is None:
            raise self._integrity("Active knowledge base graph snapshot is unavailable.")
        if len(chunks) == 0 or len(bundles) != len(knowledge_base.source_document_version_ids):
            raise self._integrity("Active knowledge base corpus is incomplete.")
        entries = self._entries(chunks, bundles)
        index, report = await self._restore_index_with_report(
            manifest,
            entries,
            graph,
            course_id,
        )
        return LoadedKnowledgeBase(
            course_id=course_id,
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            knowledge_base=knowledge_base,
            manifest=manifest,
            graph=graph,
            source_bundles=tuple(bundles),
            index=index,
        ), report

    async def _restore_index_with_report(
        self,
        manifest: IndexBuildManifestV1,
        entries: tuple[CorpusEntry, ...],
        graph: Topic1GraphSnapshotV1,
        course_id: str,
    ) -> tuple[LocalHybridIndex, IndexRestoreReport]:
        payloads: list[HybridShardPayload] = []
        for shard in manifest.shards:
            faiss_payload: bytes | None
            bm25_payload: bytes | None
            try:
                faiss_payload = await self._artifact_writer.read(
                    current_tenant().tenant_id,
                    shard.faiss_artifact,
                )
            except (LiyanError, OSError, ValueError):
                faiss_payload = None
            try:
                bm25_payload = await self._artifact_writer.read(
                    current_tenant().tenant_id,
                    shard.bm25_artifact,
                )
            except (LiyanError, OSError, ValueError):
                bm25_payload = None
            payloads.append(
                HybridShardPayload(
                    ordinal=shard.ordinal,
                    first_position=shard.first_vector_ordinal,
                    vector_count=shard.vector_count,
                    faiss_payload=faiss_payload,
                    faiss_sha256=shard.faiss_sha256,
                    bm25_payload=bm25_payload,
                    bm25_sha256=shard.bm25_sha256,
                )
            )
        # Manifest ordinals refer to vector ordinals, while the in-memory index restores positions.
        normalized_payloads = tuple(
            payload.__class__(
                ordinal=payload.ordinal,
                first_position=sum(item.vector_count for item in payloads[: payload.ordinal]),
                vector_count=payload.vector_count,
                faiss_payload=payload.faiss_payload,
                faiss_sha256=payload.faiss_sha256,
                bm25_payload=payload.bm25_payload,
                bm25_sha256=payload.bm25_sha256,
            )
            for payload in payloads
        )
        try:
            return LocalHybridIndex.restore(
                tenant_id=current_tenant().tenant_id,
                course_id=course_id,
                knowledge_base_version_id=manifest.knowledge_base_version_id,
                entries=entries,
                tokenizer=self._tokenizer,
                vectorizer=self._vectorizer,
                graph_expander=TopicGraphExpander(graph),
                payloads=normalized_payloads,
                shard_size=self._shard_size,
            )
        except RetrievalIndexError:
            rebuilt = LocalHybridIndex(
                tenant_id=current_tenant().tenant_id,
                course_id=course_id,
                knowledge_base_version_id=manifest.knowledge_base_version_id,
                entries=entries,
                tokenizer=self._tokenizer,
                vectorizer=self._vectorizer,
                graph_expander=TopicGraphExpander(graph),
                shard_size=self._shard_size,
            )
            all_shards = tuple(range(len(manifest.shards)))
            return rebuilt, IndexRestoreReport(
                rebuilt_faiss_shards=all_shards,
                rebuilt_bm25_shards=all_shards,
                degraded_reason_codes=(),
            )

    async def _execute_search(
        self,
        loaded: LoadedKnowledgeBase,
        request: RetrievalRequestV1,
        deadline: datetime,
    ) -> tuple[RetrievalResponseV1, tuple[EvidenceRefV1, ...], EvidenceBundleV1 | None]:
        started = datetime.now(UTC)
        timeout_seconds = max(0.001, (deadline - started).total_seconds())
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(loaded.index.search, request.query_plan),
                timeout=timeout_seconds,
            )
            refs, bundle = EvidenceAssembler().build(
                result,
                request.query_plan,
                verification_id=request.verification_id,
                claim_id=request.claim_id,
                created_at=started,
            )
            status = (
                RetrievalStatus.DEGRADED
                if result.degraded_reason_codes
                else RetrievalStatus.SUCCEEDED
            )
            codes = list(result.degraded_reason_codes)
            elapsed_ms = max(0, round((datetime.now(UTC) - started).total_seconds() * 1000))
        except (TimeoutError, RetrievalIndexError, RuntimeError, ValueError) as exc:
            refs = ()
            bundle = None
            status = RetrievalStatus.FAILED
            codes = ["RETRIEVAL_TIMEOUT" if isinstance(exc, TimeoutError) else "RETRIEVAL_FAILED"]
            elapsed_ms = max(0, round((datetime.now(UTC) - started).total_seconds() * 1000))
        response = build_topic4_record(
            RetrievalResponseV1,
            trace_id=request.trace_id,
            tenant_id=request.tenant_id,
            version_cas=1,
            created_at=started,
            immutable=True,
            schema_version="retrieval.response.v1",
            retrieval_response_id=uuid5(request.retrieval_request_id, "response:v1"),
            retrieval_request_id=request.retrieval_request_id,
            verification_id=request.verification_id,
            claim_id=request.claim_id,
            status=status,
            evidence_bundle=bundle,
            index_build_manifest_id=loaded.manifest.index_build_manifest_id,
            elapsed_ms=elapsed_ms,
            degraded_reason_codes=list(dict.fromkeys(codes)),
            completed_at=datetime.now(UTC),
        )
        return response, refs, bundle

    async def _signatures_for_loaded(self, loaded: LoadedKnowledgeBase):
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.list_formula_signatures(
                session,
                current_tenant().tenant_id,
                loaded.knowledge_base.source_document_version_ids,
            )

    async def _persist_recovery(
        self,
        loaded: LoadedKnowledgeBase,
        report: IndexRestoreReport,
    ) -> LoadedKnowledgeBase | None:
        try:
            shards = loaded.index.serialized_shards()
        except RetrievalIndexError:
            return None
        context = current_tenant()
        now = datetime.now(UTC)
        old = loaded.manifest
        corrupted_version = old.version_cas + 1
        ready_version = corrupted_version + 1
        recovery_manifest_id = old.index_build_manifest_id
        staged: list = []
        shard_manifests: list = []
        for shard in shards:
            faiss_artifact = await self._artifact_writer.stage(
                artifact_id=uuid5(
                    recovery_manifest_id,
                    f"recovery:{ready_version}:faiss:{shard.ordinal}",
                ),
                tenant_id=context.tenant_id,
                object_key=(
                    f"topic4/c2/indexes/{loaded.knowledge_base.knowledge_base_version_id.hex}/"
                    f"recovery-{ready_version:05d}-shard-{shard.ordinal:05d}.faiss"
                ),
                media_type="application/octet-stream",
                content_encoding="identity",
                content=shard.faiss_payload,
                created_by_subject=context.subject_ref,
                created_at=now,
                provenance={
                    "topic": "topic4-c2",
                    "purpose": "faiss-corruption-recovery",
                    "recovery_from_manifest_version": old.version_cas,
                    "index_build_manifest_id": str(recovery_manifest_id),
                },
            )
            bm25_artifact = await self._artifact_writer.stage(
                artifact_id=uuid5(
                    recovery_manifest_id,
                    f"recovery:{ready_version}:bm25:{shard.ordinal}",
                ),
                tenant_id=context.tenant_id,
                object_key=(
                    f"topic4/c2/indexes/{loaded.knowledge_base.knowledge_base_version_id.hex}/"
                    f"recovery-{ready_version:05d}-shard-{shard.ordinal:05d}.bm25.json.gz"
                ),
                media_type="application/json",
                content_encoding="gzip",
                content=shard.bm25_payload,
                created_by_subject=context.subject_ref,
                created_at=now,
                provenance={
                    "topic": "topic4-c2",
                    "purpose": "bm25-corruption-recovery",
                    "recovery_from_manifest_version": old.version_cas,
                    "index_build_manifest_id": str(recovery_manifest_id),
                },
            )
            staged.extend((faiss_artifact, bm25_artifact))
            shard_manifests.append(
                build_topic4_record(
                    IndexShardManifestV1,
                    trace_id=context.trace_id,
                    tenant_id=context.tenant_id,
                    version_cas=1,
                    created_at=now,
                    immutable=True,
                    schema_version="index-shard-manifest.v1",
                    shard_id=uuid5(
                        recovery_manifest_id, f"recovery-shard:{ready_version}:{shard.ordinal}"
                    ),
                    ordinal=shard.ordinal,
                    first_vector_ordinal=shard.first_position,
                    vector_count=shard.vector_count,
                    faiss_artifact=faiss_artifact.reference,
                    faiss_sha256=shard.faiss_sha256,
                    bm25_artifact=bm25_artifact.reference,
                    bm25_sha256=shard.bm25_sha256,
                )
            )
        # The old manifest always contains IndexShardManifestV1 entries; the fallback keeps
        # this routine defensive when a future migration produces an empty shard list.
        corrupted = build_topic4_record(
            IndexBuildManifestV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=corrupted_version,
            created_at=now,
            immutable=True,
            schema_version="index-build-manifest.v1",
            index_build_manifest_id=recovery_manifest_id,
            knowledge_base_version_id=loaded.knowledge_base.knowledge_base_version_id,
            embedding_profile_id=loaded.knowledge_base.embedding_profile_id,
            state=IndexBuildState.CORRUPTED,
            chunk_count=old.chunk_count,
            shard_count=old.shard_count,
            shards=old.shards,
            graph_snapshot_id=loaded.knowledge_base.graph_snapshot_id,
            graph_snapshot_version=loaded.knowledge_base.graph_snapshot_version,
            toolchain_manifest_version="faiss-1.14-bm25-v1",
            built_at=old.built_at,
            failure_code="INDEX_ARTIFACT_RECOVERED",
        )
        ready = build_topic4_record(
            IndexBuildManifestV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=ready_version,
            created_at=now,
            immutable=True,
            schema_version="index-build-manifest.v1",
            index_build_manifest_id=recovery_manifest_id,
            knowledge_base_version_id=loaded.knowledge_base.knowledge_base_version_id,
            embedding_profile_id=loaded.knowledge_base.embedding_profile_id,
            state=IndexBuildState.READY,
            chunk_count=old.chunk_count,
            shard_count=len(shard_manifests),
            shards=shard_manifests,
            graph_snapshot_id=loaded.knowledge_base.graph_snapshot_id,
            graph_snapshot_version=loaded.knowledge_base.graph_snapshot_version,
            toolchain_manifest_version="faiss-1.14-bm25-v1",
            built_at=now,
            failure_code=None,
        )

        async def callback(session, scoped: TenantContext) -> dict[str, object]:
            await self._transactions.lock(
                session,
                f"topic4-c2-recovery:{scoped.tenant_id}:{recovery_manifest_id}",
            )
            current = await self._repository.latest_manifest(
                session,
                scoped.tenant_id,
                recovery_manifest_id,
            )
            if current is None or current.record_sha256 != old.record_sha256:
                return {"recovered": False}
            audit_event_id = await self._transactions.append_audit(
                session,
                scoped,
                action="KNOWLEDGE_INDEX_SELF_HEALED",
                target_ref=str(recovery_manifest_id),
                metadata={
                    "knowledge_base_version_id": str(
                        loaded.knowledge_base.knowledge_base_version_id
                    ),
                    "previous_manifest_version": old.version_cas,
                    "new_manifest_version": ready_version,
                    "rebuilt_faiss_shards": list(report.rebuilt_faiss_shards),
                    "rebuilt_bm25_shards": list(report.rebuilt_bm25_shards),
                },
            )
            await self._artifact_writer.register_verified(
                session,
                tuple(staged),
                tenant_id=scoped.tenant_id,
                verified_at=now,
            )
            await self._repository.append_manifest(
                session,
                scoped.tenant_id,
                corrupted,
                audit_event_id,
            )
            await self._repository.append_manifest(
                session,
                scoped.tenant_id,
                ready,
                audit_event_id,
            )
            result = {"recovered": True, "ready_manifest": ready.model_dump(mode="json")}
            await self._transactions.append_outbox(
                session,
                scoped,
                partition_key=f"topic4-c2:{scoped.tenant_id}:{loaded.index.course_id}",
                event_type="topic4.knowledge.index_self_healed",
                payload=result,
            )
            return result

        try:
            result = await self._transactions.execute(
                operation="topic4.c2.knowledge.index_recovery",
                idempotency_key=(
                    f"topic4:c2:index-recovery:{recovery_manifest_id.hex}:{ready_version:08d}"
                ),
                request_document={
                    "manifest_id": str(recovery_manifest_id),
                    "expected_record_sha256": old.record_sha256,
                    "ready_version": ready_version,
                },
                callback=callback,
            )
        except LiyanError as exc:
            if exc.code != ErrorCode.TOPIC4_CONFLICT:
                raise
            persisted = await self._wait_for_recovery(
                recovery_manifest_id,
                minimum_version=ready_version,
            )
            if persisted is None:
                return None
            return self._with_manifest(loaded, persisted)
        if not result.get("recovered"):
            persisted = await self._latest_manifest(recovery_manifest_id)
            if (
                persisted is None
                or persisted.state != IndexBuildState.READY
                or persisted.version_cas < ready_version
            ):
                return None
            return self._with_manifest(loaded, persisted)
        try:
            persisted = IndexBuildManifestV1.model_validate(result["ready_manifest"])
        except (KeyError, TypeError, ValueError) as exc:
            raise self._integrity("Index recovery returned an invalid READY manifest.") from exc
        if (
            persisted.index_build_manifest_id != recovery_manifest_id
            or persisted.knowledge_base_version_id
            != loaded.knowledge_base.knowledge_base_version_id
            or persisted.state != IndexBuildState.READY
            or persisted.version_cas < ready_version
        ):
            raise self._integrity("Index recovery returned a mismatched READY manifest.")
        return self._with_manifest(loaded, persisted)

    async def _cache_matches_activation(self, loaded: LoadedKnowledgeBase) -> bool:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            activation = await self._repository.latest_activation(
                session,
                context.tenant_id,
                loaded.course_id,
            )
        return (
            activation is not None
            and activation.activation_id == loaded.activation_id
            and activation.activation_version == loaded.activation_version
            and activation.knowledge_base_version_id
            == loaded.knowledge_base.knowledge_base_version_id
        )

    async def _latest_manifest(
        self,
        index_build_manifest_id: UUID,
    ) -> IndexBuildManifestV1 | None:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.latest_manifest(
                session,
                context.tenant_id,
                index_build_manifest_id,
            )

    async def _wait_for_recovery(
        self,
        index_build_manifest_id: UUID,
        *,
        minimum_version: int,
    ) -> IndexBuildManifestV1 | None:
        for delay in (0.02, 0.04, 0.08, 0.16, 0.32):
            persisted = await self._latest_manifest(index_build_manifest_id)
            if (
                persisted is not None
                and persisted.state == IndexBuildState.READY
                and persisted.version_cas >= minimum_version
            ):
                return persisted
            await asyncio.sleep(delay)
        return None

    @staticmethod
    def _with_manifest(
        loaded: LoadedKnowledgeBase,
        manifest: IndexBuildManifestV1,
    ) -> LoadedKnowledgeBase:
        return LoadedKnowledgeBase(
            course_id=loaded.course_id,
            activation_id=loaded.activation_id,
            activation_version=loaded.activation_version,
            knowledge_base=loaded.knowledge_base,
            manifest=manifest,
            graph=loaded.graph,
            source_bundles=loaded.source_bundles,
            index=loaded.index,
        )

    @staticmethod
    def _entries(
        chunks: list,
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

    @staticmethod
    def _integrity(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_INTEGRITY_FAILED,
            message,
            category=ErrorCategory.DATABASE,
            status_code=503,
        )
