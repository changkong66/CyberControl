from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import threading
import unicodedata
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

import faiss
import numpy as np
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic4_c2 import (
    KnowledgeChunkV1,
    QueryPlanV1,
    SourceAuthorityTier,
)

ASCII_TOKEN = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")
CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
FORMULA_TOKEN = re.compile(r"[a-zA-Z]+|\d+(?:\.\d+)?|[+\-*/^=(){}\[\]]")


class RetrievalIndexError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    chunk: KnowledgeChunkV1
    source_document_id: UUID
    citation: str
    authority_tier: SourceAuthorityTier

    def __post_init__(self) -> None:
        if not self.citation or len(self.citation) > 4096:
            raise ValueError("citation must contain between one and 4096 characters")


@dataclass(frozen=True, slots=True)
class RankedEvidence:
    entry: CorpusEntry
    fused_score: float
    bm25_score: float | None
    vector_score: float | None
    graph_score: float | None
    formula_score: float | None


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    bm25_ms: int
    vector_ms: int
    graph_ms: int
    formula_ms: int
    fusion_ms: int
    total_ms: int


@dataclass(frozen=True, slots=True)
class HybridSearchResult:
    evidence: tuple[RankedEvidence, ...]
    metrics: RetrievalMetrics
    degraded_reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SerializedHybridShard:
    ordinal: int
    first_position: int
    vector_count: int
    faiss_payload: bytes
    faiss_sha256: str
    bm25_payload: bytes
    bm25_sha256: str


@dataclass(frozen=True, slots=True)
class HybridShardPayload:
    ordinal: int
    first_position: int
    vector_count: int
    faiss_payload: bytes | None
    faiss_sha256: str
    bm25_payload: bytes | None
    bm25_sha256: str


@dataclass(frozen=True, slots=True)
class IndexRestoreReport:
    rebuilt_faiss_shards: tuple[int, ...]
    rebuilt_bm25_shards: tuple[int, ...]
    degraded_reason_codes: tuple[str, ...]

    @property
    def recovery_required(self) -> bool:
        return bool(self.rebuilt_faiss_shards or self.rebuilt_bm25_shards)


class DeterministicTokenizer:
    def tokenize(self, value: str) -> tuple[str, ...]:
        normalized = unicodedata.normalize("NFKC", value).lower()
        tokens = list(ASCII_TOKEN.findall(normalized))
        cjk = CJK_CHAR.findall(normalized)
        tokens.extend(cjk)
        tokens.extend(f"{left}{right}" for left, right in zip(cjk, cjk[1:], strict=False))
        tokens.extend(f"formula:{token.lower()}" for token in FORMULA_TOKEN.findall(normalized))
        return tuple(token for token in tokens if token)


class BM25Index:
    def __init__(
        self,
        documents: tuple[tuple[str, ...], ...],
        *,
        k1: float = 1.5,
        b: float = 0.75,
        max_document_frequency_ratio: float = 0.2,
        max_query_terms: int = 16,
    ) -> None:
        if not documents:
            raise ValueError("BM25 requires at least one document")
        if not math.isfinite(k1) or not math.isfinite(b) or k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("invalid BM25 parameters")
        if (
            not math.isfinite(max_document_frequency_ratio)
            or not 0 < max_document_frequency_ratio <= 1
        ):
            raise ValueError("invalid BM25 document-frequency ratio")
        if not 1 <= max_query_terms <= 128:
            raise ValueError("invalid BM25 query-term limit")
        self._k1 = k1
        self._b = b
        self._max_document_frequency_ratio = max_document_frequency_ratio
        self._max_query_terms = max_query_terms
        self._document_count = len(documents)
        self._document_lengths = np.asarray(
            [len(document) for document in documents], dtype=np.float32
        )
        self._average_length = float(max(1.0, self._document_lengths.mean()))
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for document_index, document in enumerate(documents):
            for token, frequency in Counter(document).items():
                postings[token].append((document_index, frequency))
        count = len(documents)
        self._postings = {token: tuple(items) for token, items in postings.items()}
        self._idf = {
            token: math.log(1.0 + (count - len(items) + 0.5) / (len(items) + 0.5))
            for token, items in self._postings.items()
        }

    def search(self, query_tokens: tuple[str, ...], *, top_k: int) -> list[tuple[int, float]]:
        if top_k < 1:
            return []
        scores: dict[int, float] = defaultdict(float)
        candidates = [
            (token, query_frequency, self._postings[token])
            for token, query_frequency in Counter(query_tokens).items()
            if token in self._postings
        ]
        candidates.sort(key=lambda item: (len(item[2]), item[0]))
        selective = [
            item
            for item in candidates
            if len(item[2]) / self._document_count <= self._max_document_frequency_ratio
        ]
        selected = (selective or candidates[:1])[: self._max_query_terms]
        for token, query_frequency, postings in selected:
            idf = self._idf.get(token)
            if idf is None:
                continue
            for document_index, frequency in postings:
                length = float(self._document_lengths[document_index])
                denominator = frequency + self._k1 * (
                    1.0 - self._b + self._b * length / self._average_length
                )
                score = idf * (frequency * (self._k1 + 1.0)) / denominator
                scores[document_index] += score * (1.0 + math.log(query_frequency))
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]

    def serialize(self) -> tuple[bytes, str]:
        document = {
            "schema_version": "topic4.bm25-shard.v1",
            "k1": self._k1,
            "b": self._b,
            "max_document_frequency_ratio": self._max_document_frequency_ratio,
            "max_query_terms": self._max_query_terms,
            "document_lengths": [int(value) for value in self._document_lengths],
            "postings": {
                token: [[document_index, frequency] for document_index, frequency in postings]
                for token, postings in sorted(self._postings.items())
            },
        }
        raw = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        payload = gzip.compress(raw, compresslevel=6, mtime=0)
        return payload, hashlib.sha256(payload).hexdigest()

    @classmethod
    def restore(cls, payload: bytes, expected_sha256: str) -> BM25Index:
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RetrievalIndexError("BM25 shard digest mismatch")
        try:
            document = json.loads(gzip.decompress(payload))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RetrievalIndexError("BM25 shard payload is invalid") from exc
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != "topic4.bm25-shard.v1"
        ):
            raise RetrievalIndexError("BM25 shard schema is unsupported")
        lengths = document.get("document_lengths")
        raw_postings = document.get("postings")
        if not isinstance(lengths, list) or not lengths or not isinstance(raw_postings, dict):
            raise RetrievalIndexError("BM25 shard structure is invalid")
        if any(not isinstance(value, int) or value < 0 for value in lengths):
            raise RetrievalIndexError("BM25 shard document lengths are invalid")
        postings: dict[str, tuple[tuple[int, int], ...]] = {}
        for token, raw_items in raw_postings.items():
            if not isinstance(token, str) or not isinstance(raw_items, list):
                raise RetrievalIndexError("BM25 shard postings are invalid")
            items: list[tuple[int, int]] = []
            for raw_item in raw_items:
                if (
                    not isinstance(raw_item, list)
                    or len(raw_item) != 2
                    or not all(isinstance(value, int) for value in raw_item)
                ):
                    raise RetrievalIndexError("BM25 shard posting entry is invalid")
                document_index, frequency = raw_item
                if not 0 <= document_index < len(lengths) or frequency < 1:
                    raise RetrievalIndexError("BM25 shard posting value is outside its range")
                if items and document_index <= items[-1][0]:
                    raise RetrievalIndexError("BM25 shard postings are not strictly ordered")
                items.append((document_index, frequency))
            postings[token] = tuple(items)
        instance = cls.__new__(cls)
        try:
            instance._k1 = float(document.get("k1", 1.5))
            instance._b = float(document.get("b", 0.75))
            instance._max_document_frequency_ratio = float(
                document.get("max_document_frequency_ratio", 0.2)
            )
            instance._max_query_terms = int(document.get("max_query_terms", 16))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RetrievalIndexError("BM25 shard parameters are invalid") from exc
        if (
            not math.isfinite(instance._k1)
            or not math.isfinite(instance._b)
            or not math.isfinite(instance._max_document_frequency_ratio)
            or instance._k1 <= 0
            or not 0 <= instance._b <= 1
            or not 0 < instance._max_document_frequency_ratio <= 1
            or not 1 <= instance._max_query_terms <= 128
        ):
            raise RetrievalIndexError("BM25 shard parameters are invalid")
        instance._document_lengths = np.asarray(lengths, dtype=np.float32)
        instance._average_length = float(max(1.0, instance._document_lengths.mean()))
        instance._postings = postings
        count = len(lengths)
        instance._document_count = count
        instance._idf = {
            token: math.log(1.0 + (count - len(items) + 0.5) / (len(items) + 0.5))
            for token, items in postings.items()
        }
        return instance


class HashedLexicalVectorizer:
    def __init__(
        self,
        tokenizer: DeterministicTokenizer,
        *,
        dimension: int = 2048,
        seed: bytes = b"liyans-topic4-hash-v1",
    ) -> None:
        if dimension != 2048:
            raise ValueError("ADR-0005 fixes the vector dimension at 2048")
        self._tokenizer = tokenizer
        self.dimension = dimension
        self._seed = seed

    def vectorize(self, value: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token, frequency in Counter(self._tokenizer.tokenize(value)).items():
            digest = hashlib.blake2b(token.encode("utf-8"), key=self._seed, digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(frequency))
        norm = float(np.linalg.norm(vector))
        if norm:
            vector /= norm
        return vector

    def matrix(self, values: list[str]) -> np.ndarray:
        if not values:
            return np.empty((0, self.dimension), dtype=np.float32)
        return np.vstack([self.vectorize(value) for value in values]).astype(np.float32)


class TopicGraphExpander:
    def __init__(self, graph: Topic1GraphSnapshotV1) -> None:
        adjacency: dict[str, set[str]] = defaultdict(set)
        known = {point.kp_id for point in graph.content.knowledge_points}
        for edge in graph.content.prerequisites:
            if edge.prerequisite_kp_id not in known or edge.dependent_kp_id not in known:
                raise ValueError("Topic 1 graph contains an edge with an unknown endpoint")
            adjacency[edge.prerequisite_kp_id].add(edge.dependent_kp_id)
            adjacency[edge.dependent_kp_id].add(edge.prerequisite_kp_id)
        self._known = frozenset(known)
        self._adjacency = {key: frozenset(values) for key, values in adjacency.items()}

    def expand(self, seeds: tuple[str, ...], *, max_depth: int = 2) -> dict[str, float]:
        if not 0 <= max_depth <= 8:
            raise ValueError("graph expansion depth must be between zero and eight")
        queue: deque[tuple[str, int]] = deque()
        distances: dict[str, int] = {}
        for seed in seeds:
            if seed in self._known and seed not in distances:
                distances[seed] = 0
                queue.append((seed, 0))
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor in sorted(self._adjacency.get(current, frozenset())):
                if neighbor in distances:
                    continue
                distances[neighbor] = depth + 1
                queue.append((neighbor, depth + 1))
        return {
            knowledge_point_id: 1.0 / (distance + 1.0)
            for knowledge_point_id, distance in distances.items()
        }


class FaissIndexShard:
    def __init__(self, index: faiss.Index, positions: np.ndarray) -> None:
        if index.d != 2048:
            raise RetrievalIndexError("Faiss shard dimension does not match ADR-0005")
        if index.ntotal != len(positions):
            raise RetrievalIndexError("Faiss shard position count is inconsistent")
        if index.metric_type != faiss.METRIC_INNER_PRODUCT:
            raise RetrievalIndexError("Faiss shard must use inner-product similarity")
        self.index = index
        self.positions = positions.astype(np.int64, copy=False)

    @classmethod
    def build(cls, vectors: np.ndarray, positions: np.ndarray) -> FaissIndexShard:
        if vectors.ndim != 2 or vectors.shape[1] != 2048:
            raise ValueError("Faiss vectors must have shape (n, 2048)")
        if len(vectors) != len(positions):
            raise ValueError("Faiss vectors and positions must have the same length")
        if len(vectors) >= 2048:
            index = faiss.IndexHNSWSQ(
                2048,
                faiss.ScalarQuantizer.QT_8bit,
                16,
                faiss.METRIC_INNER_PRODUCT,
            )
            index.hnsw.efConstruction = 40
            index.hnsw.efSearch = 64
            index.train(np.ascontiguousarray(vectors, dtype=np.float32))
        else:
            index = faiss.IndexFlatIP(2048)
        if len(vectors):
            index.add(np.ascontiguousarray(vectors, dtype=np.float32))
        return cls(index, positions)

    def serialize(self) -> tuple[bytes, str]:
        payload = bytes(faiss.serialize_index(self.index))
        return payload, hashlib.sha256(payload).hexdigest()

    @classmethod
    def restore_or_rebuild(
        cls,
        payload: bytes,
        expected_sha256: str,
        *,
        vectors: np.ndarray,
        positions: np.ndarray,
    ) -> tuple[FaissIndexShard, bool]:
        try:
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected_sha256:
                raise RetrievalIndexError("Faiss shard digest mismatch")
            index = faiss.deserialize_index(np.frombuffer(payload, dtype=np.uint8))
            restored = cls(index, positions)
            return restored, False
        except (AssertionError, RuntimeError, ValueError, RetrievalIndexError):
            return cls.build(vectors, positions), True

    @classmethod
    def restore(
        cls,
        payload: bytes,
        expected_sha256: str,
        *,
        positions: np.ndarray,
    ) -> FaissIndexShard:
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RetrievalIndexError("Faiss shard digest mismatch")
        try:
            index = faiss.deserialize_index(np.frombuffer(payload, dtype=np.uint8))
        except (AssertionError, RuntimeError, ValueError) as exc:
            raise RetrievalIndexError("Faiss shard payload is invalid") from exc
        return cls(index, positions)

    def search(self, query: np.ndarray, *, top_k: int) -> list[tuple[int, float]]:
        if top_k < 1 or self.index.ntotal == 0:
            return []
        scores, indices = self.index.search(
            np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32),
            min(top_k, self.index.ntotal),
        )
        results: list[tuple[int, float]] = []
        for local_index, score in zip(indices[0], scores[0], strict=True):
            if local_index < 0:
                continue
            results.append((int(self.positions[local_index]), float(score)))
        return results


class LocalHybridIndex:
    def __init__(
        self,
        *,
        tenant_id: str,
        course_id: str,
        knowledge_base_version_id: UUID,
        entries: tuple[CorpusEntry, ...],
        tokenizer: DeterministicTokenizer,
        vectorizer: HashedLexicalVectorizer,
        graph_expander: TopicGraphExpander,
        shard_size: int = 25_000,
    ) -> None:
        ordered = self._validate_entries(
            tenant_id,
            knowledge_base_version_id,
            entries,
            shard_size,
        )
        self._initialize_common(
            tenant_id=tenant_id,
            course_id=course_id,
            knowledge_base_version_id=knowledge_base_version_id,
            entries=ordered,
            tokenizer=tokenizer,
            vectorizer=vectorizer,
            graph_expander=graph_expander,
            shard_size=shard_size,
        )
        bm25_shards: list[tuple[BM25Index, np.ndarray]] = []
        faiss_shards: list[FaissIndexShard | None] = []
        degraded: list[str] = []
        for start in range(0, len(ordered), shard_size):
            stop = min(start + shard_size, len(ordered))
            shard_entries = ordered[start:stop]
            positions = np.arange(start, stop, dtype=np.int64)
            bm25_shards.append(
                (
                    BM25Index(
                        tuple(
                            tokenizer.tokenize(entry.chunk.normalized_text)
                            for entry in shard_entries
                        )
                    ),
                    positions,
                )
            )
            try:
                vectors = vectorizer.matrix(
                    [entry.chunk.normalized_text for entry in shard_entries]
                )
                faiss_shards.append(FaissIndexShard.build(vectors, positions))
            except (AssertionError, MemoryError, RuntimeError, ValueError):
                faiss_shards.append(None)
                degraded.append(f"FAISS_BUILD_DEGRADED_SHARD_{len(faiss_shards) - 1}")
        self._bm25_shards = tuple(bm25_shards)
        self._faiss_shards = tuple(faiss_shards)
        self._base_degraded_reason_codes = tuple(degraded)

    @classmethod
    def restore(
        cls,
        *,
        tenant_id: str,
        course_id: str,
        knowledge_base_version_id: UUID,
        entries: tuple[CorpusEntry, ...],
        tokenizer: DeterministicTokenizer,
        vectorizer: HashedLexicalVectorizer,
        graph_expander: TopicGraphExpander,
        payloads: tuple[HybridShardPayload, ...],
        shard_size: int = 25_000,
    ) -> tuple[LocalHybridIndex, IndexRestoreReport]:
        ordered = cls._validate_entries(
            tenant_id,
            knowledge_base_version_id,
            entries,
            shard_size,
        )
        if not payloads:
            raise RetrievalIndexError("index restore requires at least one shard payload")
        instance = cls.__new__(cls)
        instance._initialize_common(
            tenant_id=tenant_id,
            course_id=course_id,
            knowledge_base_version_id=knowledge_base_version_id,
            entries=ordered,
            tokenizer=tokenizer,
            vectorizer=vectorizer,
            graph_expander=graph_expander,
            shard_size=shard_size,
        )
        bm25_shards: list[tuple[BM25Index, np.ndarray]] = []
        faiss_shards: list[FaissIndexShard | None] = []
        rebuilt_bm25: list[int] = []
        rebuilt_faiss: list[int] = []
        degraded: list[str] = []
        expected_start = 0
        for expected_ordinal, payload in enumerate(sorted(payloads, key=lambda item: item.ordinal)):
            if payload.ordinal != expected_ordinal or payload.first_position != expected_start:
                raise RetrievalIndexError("index shard manifest positions are not contiguous")
            stop = expected_start + payload.vector_count
            if payload.vector_count < 1 or stop > len(ordered):
                raise RetrievalIndexError("index shard manifest vector count is invalid")
            shard_entries = ordered[expected_start:stop]
            positions = np.arange(expected_start, stop, dtype=np.int64)
            documents = tuple(
                tokenizer.tokenize(entry.chunk.normalized_text) for entry in shard_entries
            )
            try:
                if payload.bm25_payload is None:
                    raise RetrievalIndexError("BM25 shard artifact is unavailable")
                bm25 = BM25Index.restore(payload.bm25_payload, payload.bm25_sha256)
                if len(bm25._document_lengths) != payload.vector_count:
                    raise RetrievalIndexError("BM25 shard document count is inconsistent")
            except RetrievalIndexError:
                bm25 = BM25Index(documents)
                rebuilt_bm25.append(payload.ordinal)
            bm25_shards.append((bm25, positions))

            try:
                if payload.faiss_payload is None:
                    raise RetrievalIndexError("Faiss shard artifact is unavailable")
                faiss_shard = FaissIndexShard.restore(
                    payload.faiss_payload,
                    payload.faiss_sha256,
                    positions=positions,
                )
            except RetrievalIndexError:
                try:
                    vectors = vectorizer.matrix(
                        [entry.chunk.normalized_text for entry in shard_entries]
                    )
                    faiss_shard = FaissIndexShard.build(vectors, positions)
                    rebuilt_faiss.append(payload.ordinal)
                except (AssertionError, MemoryError, RuntimeError, ValueError):
                    faiss_shard = None
                    degraded.append(f"FAISS_MEMORY_DEGRADED_SHARD_{payload.ordinal}")
            faiss_shards.append(faiss_shard)
            expected_start = stop
        if expected_start != len(ordered):
            raise RetrievalIndexError("index shard manifest does not cover the corpus")
        instance._bm25_shards = tuple(bm25_shards)
        instance._faiss_shards = tuple(faiss_shards)
        instance._base_degraded_reason_codes = tuple(degraded)
        return instance, IndexRestoreReport(
            rebuilt_faiss_shards=tuple(rebuilt_faiss),
            rebuilt_bm25_shards=tuple(rebuilt_bm25),
            degraded_reason_codes=tuple(degraded),
        )

    def search(self, plan: QueryPlanV1) -> HybridSearchResult:
        if plan.tenant_id != self.tenant_id:
            raise RetrievalIndexError("query plan tenant does not match the active index")
        if plan.knowledge_base_version_id != self.knowledge_base_version_id:
            raise RetrievalIndexError("query plan is bound to a different knowledge-base version")

        started = perf_counter()
        query_text = " ".join(plan.lexical_queries)
        query_tokens = self._tokenizer.tokenize(query_text)

        step = perf_counter()
        bm25 = _top_results(
            (
                (int(positions[local_position]), score)
                for index, positions in self._bm25_shards
                for local_position, score in index.search(
                    query_tokens,
                    top_k=plan.top_k_bm25,
                )
            ),
            plan.top_k_bm25,
        )
        bm25_ms = _elapsed_ms(step)

        degraded: list[str] = list(self._base_degraded_reason_codes)
        step = perf_counter()
        try:
            query_vector = self._vectorizer.vectorize(query_text)
            vector_results = _top_results(
                (
                    result
                    for shard in self._faiss_shards
                    if shard is not None
                    for result in shard.search(query_vector, top_k=plan.top_k_vector)
                ),
                plan.top_k_vector,
            )
            if not vector_results and any(shard is None for shard in self._faiss_shards):
                degraded.append("FAISS_UNAVAILABLE")
        except (AssertionError, RuntimeError, RetrievalIndexError, ValueError):
            vector_results = []
            degraded.append("FAISS_SEARCH_FAILED")
        vector_ms = _elapsed_ms(step)

        step = perf_counter()
        graph_results = self._graph_results(plan)
        graph_ms = _elapsed_ms(step)

        step = perf_counter()
        formula_results = self._formula_results(plan)
        formula_ms = _elapsed_ms(step)

        step = perf_counter()
        fused = self._fuse(bm25, vector_results, graph_results, formula_results, plan.final_top_k)
        fusion_ms = _elapsed_ms(step)
        total_ms = _elapsed_ms(started)
        return HybridSearchResult(
            evidence=tuple(fused),
            metrics=RetrievalMetrics(
                bm25_ms=bm25_ms,
                vector_ms=vector_ms,
                graph_ms=graph_ms,
                formula_ms=formula_ms,
                fusion_ms=fusion_ms,
                total_ms=total_ms,
            ),
            degraded_reason_codes=tuple(dict.fromkeys(degraded)),
        )

    def serialized_faiss_shards(self) -> tuple[tuple[bytes, str], ...]:
        if any(shard is None for shard in self._faiss_shards):
            raise RetrievalIndexError("degraded Faiss shards cannot be persisted as ready")
        return tuple(shard.serialize() for shard in self._faiss_shards if shard is not None)

    def serialized_shards(self) -> tuple[SerializedHybridShard, ...]:
        serialized: list[SerializedHybridShard] = []
        for ordinal, ((bm25, positions), faiss_shard) in enumerate(
            zip(self._bm25_shards, self._faiss_shards, strict=True)
        ):
            if faiss_shard is None:
                raise RetrievalIndexError("degraded Faiss shards cannot be persisted as ready")
            faiss_payload, faiss_digest = faiss_shard.serialize()
            bm25_payload, bm25_digest = bm25.serialize()
            serialized.append(
                SerializedHybridShard(
                    ordinal=ordinal,
                    first_position=int(positions[0]),
                    vector_count=len(positions),
                    faiss_payload=faiss_payload,
                    faiss_sha256=faiss_digest,
                    bm25_payload=bm25_payload,
                    bm25_sha256=bm25_digest,
                )
            )
        return tuple(serialized)

    @staticmethod
    def _validate_entries(
        tenant_id: str,
        knowledge_base_version_id: UUID,
        entries: tuple[CorpusEntry, ...],
        shard_size: int,
    ) -> tuple[CorpusEntry, ...]:
        if not entries:
            raise ValueError("hybrid index requires at least one corpus entry")
        if not 1 <= shard_size <= 1_000_000:
            raise ValueError("invalid Faiss shard size")
        if any(entry.chunk.tenant_id != tenant_id for entry in entries):
            raise ValueError("cross-tenant chunk detected during index build")
        if any(
            entry.chunk.knowledge_base_version_id != knowledge_base_version_id for entry in entries
        ):
            raise ValueError("chunk belongs to a different knowledge-base version")
        ordered = tuple(
            sorted(
                entries,
                key=lambda entry: (entry.chunk.vector_ordinal, str(entry.chunk.knowledge_chunk_id)),
            )
        )
        ordinals = [entry.chunk.vector_ordinal for entry in ordered]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("knowledge chunk vector ordinals must be unique")
        if ordinals != list(range(len(ordered))):
            raise ValueError("knowledge chunk vector ordinals must be contiguous from zero")
        return ordered

    def _initialize_common(
        self,
        *,
        tenant_id: str,
        course_id: str,
        knowledge_base_version_id: UUID,
        entries: tuple[CorpusEntry, ...],
        tokenizer: DeterministicTokenizer,
        vectorizer: HashedLexicalVectorizer,
        graph_expander: TopicGraphExpander,
        shard_size: int,
    ) -> None:
        self.tenant_id = tenant_id
        self.course_id = course_id
        self.knowledge_base_version_id = knowledge_base_version_id
        self.entries = entries
        self.shard_size = shard_size
        self._tokenizer = tokenizer
        self._vectorizer = vectorizer
        self._graph_expander = graph_expander
        graph_postings: dict[str, set[int]] = defaultdict(set)
        formula_postings: dict[UUID, set[int]] = defaultdict(set)
        for position, entry in enumerate(entries):
            for knowledge_point_id in entry.chunk.topic1_knowledge_point_ids:
                graph_postings[knowledge_point_id].add(position)
            for formula_signature_id in entry.chunk.formula_signature_ids:
                formula_postings[formula_signature_id].add(position)
        self._graph_postings = {key: frozenset(value) for key, value in graph_postings.items()}
        self._formula_postings = {key: frozenset(value) for key, value in formula_postings.items()}

    def _graph_results(self, plan: QueryPlanV1) -> list[tuple[int, float]]:
        if not plan.graph_seed_knowledge_point_ids or plan.top_k_graph == 0:
            return []
        expanded = self._graph_expander.expand(tuple(plan.graph_seed_knowledge_point_ids))
        scores: dict[int, float] = defaultdict(float)
        for knowledge_point_id, graph_score in expanded.items():
            for position in self._graph_postings.get(knowledge_point_id, frozenset()):
                scores[position] = max(scores[position], graph_score)
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[: plan.top_k_graph]

    def _formula_results(self, plan: QueryPlanV1) -> list[tuple[int, float]]:
        if not plan.formula_signature_ids or plan.top_k_formula == 0:
            return []
        scores: dict[int, float] = defaultdict(float)
        query_ids = set(plan.formula_signature_ids)
        for formula_signature_id in query_ids:
            for position in self._formula_postings.get(formula_signature_id, frozenset()):
                chunk_ids = set(self.entries[position].chunk.formula_signature_ids)
                union = len(query_ids | chunk_ids)
                scores[position] = len(query_ids & chunk_ids) / union if union else 0.0
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[: plan.top_k_formula]

    def _fuse(
        self,
        bm25: list[tuple[int, float]],
        vector: list[tuple[int, float]],
        graph: list[tuple[int, float]],
        formula: list[tuple[int, float]],
        final_top_k: int,
    ) -> list[RankedEvidence]:
        rankings = (bm25, vector, graph, formula)
        raw = [{position: score for position, score in ranking} for ranking in rankings]
        fused_scores: dict[int, float] = defaultdict(float)
        for ranking in rankings:
            for rank, (position, _) in enumerate(ranking, start=1):
                fused_scores[position] += 1.0 / (60.0 + rank)
        positions = sorted(
            fused_scores,
            key=lambda position: (
                -fused_scores[position],
                -self._authority_weight(self.entries[position].authority_tier),
                str(self.entries[position].chunk.knowledge_chunk_id),
            ),
        )[:final_top_k]
        return [
            RankedEvidence(
                entry=self.entries[position],
                fused_score=fused_scores[position],
                bm25_score=raw[0].get(position),
                vector_score=raw[1].get(position),
                graph_score=raw[2].get(position),
                formula_score=raw[3].get(position),
            )
            for position in positions
        ]

    @staticmethod
    def _authority_weight(authority: SourceAuthorityTier) -> int:
        return {
            SourceAuthorityTier.PRIMARY_STANDARD: 5,
            SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK: 4,
            SourceAuthorityTier.PEER_REVIEWED: 3,
            SourceAuthorityTier.OFFICIAL_DOCUMENTATION: 2,
            SourceAuthorityTier.CURATED_INTERNAL: 1,
        }[authority]


class HotReloadableRAGIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: dict[tuple[str, str], LocalHybridIndex] = {}

    def activate(self, index: LocalHybridIndex) -> LocalHybridIndex | None:
        key = (index.tenant_id, index.course_id)
        with self._lock:
            previous = self._active.get(key)
            self._active[key] = index
            return previous

    def active_version(self, tenant_id: str, course_id: str) -> UUID | None:
        with self._lock:
            index = self._active.get((tenant_id, course_id))
            return None if index is None else index.knowledge_base_version_id

    def search(self, tenant_id: str, course_id: str, plan: QueryPlanV1) -> HybridSearchResult:
        with self._lock:
            index = self._active.get((tenant_id, course_id))
        if index is None:
            raise RetrievalIndexError("no active local RAG index for tenant and course")
        return index.search(plan)


def _top_results(results: Iterable[tuple[int, float]], top_k: int) -> list[tuple[int, float]]:
    best: dict[int, float] = {}
    for position, score in results:
        best[position] = max(best.get(position, -math.inf), score)
    return sorted(best.items(), key=lambda item: (-item[1], item[0]))[:top_k]


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
