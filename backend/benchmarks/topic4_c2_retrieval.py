from __future__ import annotations

import argparse
import ctypes
import gc
import json
import math
import os
import statistics
import sys
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import (
    CourseStatus,
    KnowledgePointStatus,
    Topic1CourseV1,
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1KnowledgePointV1,
)
from liyans_contracts.topic4_c2 import KnowledgeChunkV1, QueryPlanV1, SourceAuthorityTier

from liyans.domains.knowledge.retrieval import (
    CorpusEntry,
    DeterministicTokenizer,
    HashedLexicalVectorizer,
    LocalHybridIndex,
    TopicGraphExpander,
)
from liyans.domains.verification.records import build_topic4_record

TENANT_ID = "benchmark-topic4-c2"
COURSE_ID = "CRS_TOPIC4_C2_BENCHMARK"
TRACE_ID = "b" * 32
NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
NAMESPACE = UUID("7f07ef9d-5cbf-44f2-bf88-ab2db5b20a37")
KB_VERSION_ID = uuid5(NAMESPACE, "knowledge-base")
PROFILE_ID = uuid5(NAMESPACE, "embedding-profile")
SOURCE_DOCUMENT_ID = uuid5(NAMESPACE, "source-document")
SOURCE_VERSION_ID = uuid5(NAMESPACE, "source-version")
DOCUMENT_IR_ID = uuid5(NAMESPACE, "document-ir")


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    corpus_size: int
    knowledge_point_count: int
    shard_size: int
    shard_count: int
    query_count: int
    warmup_count: int
    corpus_generation_seconds: float
    index_build_seconds: float
    index_serialize_seconds: float
    serialized_index_megabytes: float
    retrieval_p50_ms: float
    retrieval_p95_ms: float
    retrieval_p99_ms: float
    retrieval_max_ms: float
    bm25_p95_ms: float
    vector_p95_ms: float
    graph_p95_ms: float
    fusion_p95_ms: float
    python_heap_peak_megabytes: float | None
    process_peak_working_set_megabytes: float | None
    p95_limit_ms: float
    passed: bool


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the Topic 4 C2 local hybrid RAG index without network access."
    )
    parser.add_argument("--corpus-size", type=int, default=100_000)
    parser.add_argument("--knowledge-points", type=int, default=100)
    parser.add_argument("--shard-size", type=int, default=10_000)
    parser.add_argument("--query-count", type=int, default=200)
    parser.add_argument("--warmup-count", type=int, default=20)
    parser.add_argument("--p95-limit-ms", type=float, default=200.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trace-python-memory", action="store_true")
    arguments = parser.parse_args()
    if arguments.corpus_size < 1:
        parser.error("--corpus-size must be positive")
    if not 1 <= arguments.knowledge_points <= arguments.corpus_size:
        parser.error("--knowledge-points must be between one and --corpus-size")
    if not 1 <= arguments.shard_size <= 25_000:
        parser.error("--shard-size must be between one and 25000")
    if arguments.query_count < 1 or arguments.warmup_count < 0:
        parser.error("query counts must be non-negative and include at least one measured query")
    if arguments.p95_limit_ms <= 0:
        parser.error("--p95-limit-ms must be positive")
    return arguments


def _graph(knowledge_point_count: int) -> Topic1GraphSnapshotV1:
    course = Topic1CourseV1(
        course_id=COURSE_ID,
        revision=1,
        course_code="C2-BENCH",
        title="Topic 4 C2 Retrieval Benchmark",
        description="Deterministic local hybrid retrieval benchmark corpus.",
        credit_hours=64,
        status=CourseStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    points = [
        Topic1KnowledgePointV1(
            kp_id=_knowledge_point_id(ordinal),
            course_id=COURSE_ID,
            revision=1,
            title=f"Control benchmark concept {ordinal:04d}",
            summary=f"Authoritative benchmark summary for concept {ordinal:04d}.",
            learning_objectives=[f"Verify concept {ordinal:04d}."],
            category="CONTROL_THEORY",
            difficulty_level=1 + ordinal % 5,
            difficulty_score=round((1 + ordinal % 5) / 5, 6),
            topology_level=0,
            topology_weight=1.0,
            estimated_minutes=60,
            formula_signatures=[],
            tags=["benchmark", "automatic-control"],
            status=KnowledgePointStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
        for ordinal in range(knowledge_point_count)
    ]
    content = Topic1GraphContentV1(
        course=course,
        knowledge_points=points,
        prerequisites=[],
        misconceptions=[],
    )
    return Topic1GraphSnapshotV1(
        snapshot_id=uuid5(NAMESPACE, f"graph:{knowledge_point_count}"),
        course_id=COURSE_ID,
        graph_version=1,
        content=content,
        content_sha256=canonical_sha256(content.model_dump(mode="json")),
        node_count=len(points),
        edge_count=0,
        created_by_subject="system:topic4-c2-benchmark",
        frozen_at=NOW,
    )


def _corpus(corpus_size: int, knowledge_point_count: int) -> tuple[CorpusEntry, ...]:
    entries: list[CorpusEntry] = []
    for ordinal in range(corpus_size):
        point_ordinal = ordinal % knowledge_point_count
        knowledge_point_id = _knowledge_point_id(point_ordinal)
        case_id = ordinal % 1000
        text = (
            "closed loop stability routh hurwitz characteristic equation "
            f"control concept {point_ordinal:04d} benchmark case {case_id:04d} "
            f"authoritative evidence chunk {ordinal:06d}"
        )
        chunk = build_topic4_record(
            KnowledgeChunkV1,
            trace_id=TRACE_ID,
            tenant_id=TENANT_ID,
            version_cas=1,
            created_at=NOW,
            immutable=True,
            schema_version="knowledge-chunk.v1",
            knowledge_chunk_id=uuid5(NAMESPACE, f"chunk:{ordinal}"),
            knowledge_base_version_id=KB_VERSION_ID,
            source_document_version_id=SOURCE_VERSION_ID,
            document_ir_id=DOCUMENT_IR_ID,
            section_id=f"section-{point_ordinal:04d}",
            chunk_ordinal=ordinal,
            normalized_text=text,
            content_sha256=canonical_sha256(text),
            token_count=len(text.split()),
            topic1_knowledge_point_ids=[knowledge_point_id],
            formula_signature_ids=[],
            lexical_terms=[
                "closed",
                "loop",
                "stability",
                f"concept-{point_ordinal:04d}",
                f"case-{case_id:04d}",
            ],
            embedding_profile_id=PROFILE_ID,
            vector_ordinal=ordinal,
        )
        entries.append(
            CorpusEntry(
                chunk=chunk,
                source_document_id=SOURCE_DOCUMENT_ID,
                citation="Topic 4 C2 deterministic benchmark authority source.",
                authority_tier=SourceAuthorityTier.PRIMARY_STANDARD,
            )
        )
    return tuple(entries)


def _query_plan(ordinal: int, knowledge_point_count: int) -> QueryPlanV1:
    point_ordinal = ordinal % knowledge_point_count
    case_id = ordinal % 1000
    return build_topic4_record(
        QueryPlanV1,
        trace_id=TRACE_ID,
        tenant_id=TENANT_ID,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="query-plan.v1",
        query_plan_id=uuid5(NAMESPACE, f"query-plan:{ordinal}"),
        verification_id=uuid5(NAMESPACE, f"verification:{ordinal}"),
        claim_id=uuid5(NAMESPACE, f"claim:{ordinal}"),
        knowledge_base_version_id=KB_VERSION_ID,
        lexical_queries=[
            "closed loop stability routh hurwitz "
            f"control concept {point_ordinal:04d} benchmark case {case_id:04d}"
        ],
        graph_seed_knowledge_point_ids=[_knowledge_point_id(point_ordinal)],
        formula_signature_ids=[],
        top_k_bm25=64,
        top_k_vector=64,
        top_k_graph=32,
        top_k_formula=0,
        final_top_k=16,
        fusion_method="RRF_V1",
        tenant_filter_required=True,
        timeout_ms=200,
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _process_peak_working_set_megabytes() -> float | None:
    if os.name == "nt":

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        succeeded = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        if not succeeded:
            return None
        return counters.peak_working_set_size / (1024 * 1024)
    try:
        import resource

        maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError):
        return None
    divisor = 1024 if sys.platform != "darwin" else 1024 * 1024
    return maximum / divisor


def _knowledge_point_id(ordinal: int) -> str:
    return f"KP_C2_BENCH_{ordinal:04d}"


def run(arguments: argparse.Namespace) -> BenchmarkResult:
    if arguments.trace_python_memory:
        tracemalloc.start()
    generation_started = perf_counter()
    graph = _graph(arguments.knowledge_points)
    entries = _corpus(arguments.corpus_size, arguments.knowledge_points)
    corpus_generation_seconds = perf_counter() - generation_started

    tokenizer = DeterministicTokenizer()
    build_started = perf_counter()
    index = LocalHybridIndex(
        tenant_id=TENANT_ID,
        course_id=COURSE_ID,
        knowledge_base_version_id=KB_VERSION_ID,
        entries=entries,
        tokenizer=tokenizer,
        vectorizer=HashedLexicalVectorizer(tokenizer),
        graph_expander=TopicGraphExpander(graph),
        shard_size=arguments.shard_size,
    )
    index_build_seconds = perf_counter() - build_started

    serialize_started = perf_counter()
    serialized = index.serialized_shards()
    index_serialize_seconds = perf_counter() - serialize_started
    serialized_bytes = sum(
        len(shard.faiss_payload) + len(shard.bm25_payload) for shard in serialized
    )

    plans = [
        _query_plan(ordinal, arguments.knowledge_points)
        for ordinal in range(arguments.warmup_count + arguments.query_count)
    ]
    if arguments.trace_python_memory:
        _, python_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        python_peak = None
    for plan in plans[: arguments.warmup_count]:
        result = index.search(plan)
        if not result.evidence:
            raise RuntimeError("benchmark warmup query returned no evidence")

    samples: list[float] = []
    channel_samples: dict[str, list[float]] = {
        "bm25": [],
        "vector": [],
        "graph": [],
        "fusion": [],
    }
    for plan in plans[arguments.warmup_count :]:
        started = perf_counter()
        result = index.search(plan)
        elapsed_ms = (perf_counter() - started) * 1000
        if not result.evidence:
            raise RuntimeError("benchmark query returned no evidence")
        samples.append(elapsed_ms)
        channel_samples["bm25"].append(float(result.metrics.bm25_ms))
        channel_samples["vector"].append(float(result.metrics.vector_ms))
        channel_samples["graph"].append(float(result.metrics.graph_ms))
        channel_samples["fusion"].append(float(result.metrics.fusion_ms))
    result = BenchmarkResult(
        corpus_size=arguments.corpus_size,
        knowledge_point_count=arguments.knowledge_points,
        shard_size=arguments.shard_size,
        shard_count=len(serialized),
        query_count=arguments.query_count,
        warmup_count=arguments.warmup_count,
        corpus_generation_seconds=round(corpus_generation_seconds, 3),
        index_build_seconds=round(index_build_seconds, 3),
        index_serialize_seconds=round(index_serialize_seconds, 3),
        serialized_index_megabytes=round(serialized_bytes / (1024 * 1024), 3),
        retrieval_p50_ms=round(statistics.median(samples), 3),
        retrieval_p95_ms=round(_percentile(samples, 0.95), 3),
        retrieval_p99_ms=round(_percentile(samples, 0.99), 3),
        retrieval_max_ms=round(max(samples), 3),
        bm25_p95_ms=round(_percentile(channel_samples["bm25"], 0.95), 3),
        vector_p95_ms=round(_percentile(channel_samples["vector"], 0.95), 3),
        graph_p95_ms=round(_percentile(channel_samples["graph"], 0.95), 3),
        fusion_p95_ms=round(_percentile(channel_samples["fusion"], 0.95), 3),
        python_heap_peak_megabytes=(
            None if python_peak is None else round(python_peak / (1024 * 1024), 3)
        ),
        process_peak_working_set_megabytes=(
            None
            if (working_set := _process_peak_working_set_megabytes()) is None
            else round(working_set, 3)
        ),
        p95_limit_ms=arguments.p95_limit_ms,
        passed=_percentile(samples, 0.95) <= arguments.p95_limit_ms,
    )
    del plans, serialized, index, entries, graph
    gc.collect()
    return result


def main() -> int:
    arguments = _arguments()
    result = run(arguments)
    document = asdict(result)
    payload = json.dumps(document, indent=2, sort_keys=True)
    print(payload)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
