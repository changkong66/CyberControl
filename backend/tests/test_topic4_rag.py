from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import numpy as np
import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c2 import KnowledgeChunkV1, QueryPlanV1, SourceAuthorityTier
from topic3_support import graph_snapshot

from liyans.domains.knowledge.retrieval import (
    BM25Index,
    CorpusEntry,
    DeterministicTokenizer,
    FaissIndexShard,
    HashedLexicalVectorizer,
    HotReloadableRAGIndex,
    LocalHybridIndex,
    RetrievalIndexError,
    TopicGraphExpander,
)
from liyans.domains.verification.records import build_topic4_record

TENANT_ID = "tenant-a"
COURSE_ID = "CRS_ATC_001"
KB_VERSION_ID = UUID("2bf55055-8c02-4bff-9a34-6d08c5dad751")
PROFILE_ID = UUID("53d175f0-8f1c-4e9d-9160-4431030e06c2")
FORMULA_ID = UUID("b3d10fc4-3659-49e8-9718-1f6f978b2752")
NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)


def _chunk(
    ordinal: int,
    text: str,
    knowledge_point_id: str,
    *,
    formula_ids: list[UUID] | None = None,
    tenant_id: str = TENANT_ID,
    knowledge_base_version_id: UUID = KB_VERSION_ID,
) -> KnowledgeChunkV1:
    return build_topic4_record(
        KnowledgeChunkV1,
        trace_id="a" * 32,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="knowledge-chunk.v1",
        knowledge_chunk_id=uuid4(),
        knowledge_base_version_id=knowledge_base_version_id,
        source_document_version_id=uuid4(),
        document_ir_id=uuid4(),
        section_id=f"section-{ordinal}",
        chunk_ordinal=ordinal,
        normalized_text=text,
        content_sha256=canonical_sha256(text),
        token_count=max(1, len(text.split())),
        topic1_knowledge_point_ids=[knowledge_point_id],
        formula_signature_ids=formula_ids or [],
        lexical_terms=[],
        embedding_profile_id=PROFILE_ID,
        vector_ordinal=ordinal,
    )


def _entries(
    *, tenant_id: str = TENANT_ID, knowledge_base_version_id: UUID = KB_VERSION_ID
) -> tuple[CorpusEntry, ...]:
    chunks = (
        _chunk(
            0,
            "拉普拉斯变换将微分方程转换为复频域代数方程",
            "KP_ATC_A",
            tenant_id=tenant_id,
            knowledge_base_version_id=knowledge_base_version_id,
        ),
        _chunk(
            1,
            "传递函数 G(s) 等于零初始条件下输出与输入拉普拉斯变换之比",
            "KP_ATC_B",
            formula_ids=[FORMULA_ID],
            tenant_id=tenant_id,
            knowledge_base_version_id=knowledge_base_version_id,
        ),
        _chunk(
            2,
            "闭环稳定性可依据特征方程根的位置和 Routh Hurwitz 判据判断",
            "KP_ATC_C",
            tenant_id=tenant_id,
            knowledge_base_version_id=knowledge_base_version_id,
        ),
    )
    return tuple(
        CorpusEntry(
            chunk=chunk,
            source_document_id=uuid4(),
            citation=f"Automatic Control Theory, section {index}",
            authority_tier=(
                SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK
                if index != 2
                else SourceAuthorityTier.PRIMARY_STANDARD
            ),
        )
        for index, chunk in enumerate(chunks)
    )


def _plan(*, tenant_id: str = TENANT_ID, formula: bool = False) -> QueryPlanV1:
    return build_topic4_record(
        QueryPlanV1,
        trace_id="a" * 32,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="query-plan.v1",
        query_plan_id=uuid4(),
        verification_id=uuid4(),
        claim_id=uuid4(),
        knowledge_base_version_id=KB_VERSION_ID,
        lexical_queries=["闭环稳定性 Routh Hurwitz 特征方程"],
        graph_seed_knowledge_point_ids=["KP_ATC_C"],
        formula_signature_ids=[FORMULA_ID] if formula else [],
        top_k_bm25=3,
        top_k_vector=3,
        top_k_graph=3,
        top_k_formula=3,
        final_top_k=3,
        fusion_method="RRF_V1",
        tenant_filter_required=True,
        timeout_ms=200,
    )


def _index(*, tenant_id: str = TENANT_ID) -> LocalHybridIndex:
    tokenizer = DeterministicTokenizer()
    return LocalHybridIndex(
        tenant_id=tenant_id,
        course_id=COURSE_ID,
        knowledge_base_version_id=KB_VERSION_ID,
        entries=_entries(tenant_id=tenant_id),
        tokenizer=tokenizer,
        vectorizer=HashedLexicalVectorizer(tokenizer),
        graph_expander=TopicGraphExpander(graph_snapshot()),
        shard_size=2,
    )


def test_hashed_vectorization_is_deterministic_and_l2_normalized() -> None:
    vectorizer = HashedLexicalVectorizer(DeterministicTokenizer())
    first = vectorizer.vectorize("闭环稳定性 G(s)=1/(s+1)")
    second = vectorizer.vectorize("闭环稳定性 G(s)=1/(s+1)")
    assert np.array_equal(first, second)
    assert first.shape == (2048,)
    assert np.linalg.norm(first) == pytest.approx(1.0, rel=1e-6)


def test_bm25_uses_inverted_postings_and_ranks_matching_document() -> None:
    tokenizer = DeterministicTokenizer()
    documents = (
        tokenizer.tokenize("transfer function model"),
        tokenizer.tokenize("closed loop stability routh hurwitz"),
        tokenizer.tokenize("frequency response bode plot"),
    )
    result = BM25Index(documents).search(tokenizer.tokenize("routh stability"), top_k=2)
    assert result[0][0] == 1
    assert result[0][1] > 0


def test_hybrid_retrieval_combines_text_graph_formula_and_authority() -> None:
    result = _index().search(_plan(formula=True))
    assert result.evidence
    assert result.evidence[0].entry.chunk.topic1_knowledge_point_ids == ["KP_ATC_C"]
    assert {item.entry.chunk.vector_ordinal for item in result.evidence} >= {1, 2}
    assert result.metrics.total_ms >= 0
    assert not result.degraded_reason_codes


def test_cross_tenant_query_and_cross_tenant_index_build_are_rejected() -> None:
    with pytest.raises(ValueError, match="cross-tenant"):
        LocalHybridIndex(
            tenant_id=TENANT_ID,
            course_id=COURSE_ID,
            knowledge_base_version_id=KB_VERSION_ID,
            entries=_entries(tenant_id="tenant-b"),
            tokenizer=DeterministicTokenizer(),
            vectorizer=HashedLexicalVectorizer(DeterministicTokenizer()),
            graph_expander=TopicGraphExpander(graph_snapshot()),
        )
    with pytest.raises(RetrievalIndexError, match="tenant"):
        _index().search(_plan(tenant_id="tenant-b"))


def test_faiss_corruption_rebuilds_without_external_access() -> None:
    vectors = np.vstack(
        [
            HashedLexicalVectorizer(DeterministicTokenizer()).vectorize("one"),
            HashedLexicalVectorizer(DeterministicTokenizer()).vectorize("two"),
        ]
    ).astype(np.float32)
    positions = np.asarray([0, 1], dtype=np.int64)
    shard = FaissIndexShard.build(vectors, positions)
    payload, digest = shard.serialize()
    restored, healed = FaissIndexShard.restore_or_rebuild(
        payload,
        digest,
        vectors=vectors,
        positions=positions,
    )
    assert not healed
    assert restored.index.ntotal == 2

    corrupted = bytes([payload[0] ^ 0xFF]) + payload[1:]
    rebuilt, healed = FaissIndexShard.restore_or_rebuild(
        corrupted,
        digest,
        vectors=vectors,
        positions=positions,
    )
    assert healed
    assert rebuilt.index.ntotal == 2


def test_hot_reload_atomically_switches_active_version() -> None:
    manager = HotReloadableRAGIndex()
    first = _index()
    assert manager.activate(first) is None
    assert manager.active_version(TENANT_ID, COURSE_ID) == KB_VERSION_ID
    assert manager.search(TENANT_ID, COURSE_ID, _plan()).evidence

    second_version = uuid4()
    tokenizer = DeterministicTokenizer()
    second = LocalHybridIndex(
        tenant_id=TENANT_ID,
        course_id=COURSE_ID,
        knowledge_base_version_id=second_version,
        entries=_entries(knowledge_base_version_id=second_version),
        tokenizer=tokenizer,
        vectorizer=HashedLexicalVectorizer(tokenizer),
        graph_expander=TopicGraphExpander(graph_snapshot()),
    )
    assert manager.activate(second) is first
    assert manager.active_version(TENANT_ID, COURSE_ID) == second_version
