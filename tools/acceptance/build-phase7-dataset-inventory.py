"""Materialize and inventory the Phase 7 acceptance datasets.

The three dataset classes intentionally have different acceptance purposes:
synthetic retrieval performance, local demonstration fixtures, and human-reviewed
academic facts.  This utility never upgrades one class into another.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_DATASET_ID = "phase7-c2-synthetic-retrieval-performance.v1"
GOLDEN_DATASET_ID = "phase7-academic-human-reviewed-facts.v1"
GOLDEN_FACTS_RELATIVE_PATH = Path("tests/golden/phase7-academic-golden-facts.v1.jsonl")
GOLDEN_REVIEW_RELATIVE_PATH = Path("tests/golden/phase7-academic-golden-review.v1.json")
DEMO_FIXTURE_RELATIVE_PATH = Path("data/topic1/automatic-control-principles.v1.json")
PERFORMANCE_GENERATOR_RELATIVE_PATH = Path("backend/benchmarks/topic4_c2_retrieval.py")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(encoded + b"\n")


def _performance_rows(count: int, knowledge_point_count: int) -> Iterable[dict[str, object]]:
    for ordinal in range(count):
        point_ordinal = ordinal % knowledge_point_count
        case_id = ordinal % 1_000
        text = (
            "closed loop stability routh hurwitz characteristic equation "
            f"control concept {point_ordinal:04d} benchmark case {case_id:04d} "
            f"authoritative evidence chunk {ordinal:06d}"
        )
        yield {
            "schema_version": "phase7.retrieval-performance-chunk.v1",
            "dataset_id": PERFORMANCE_DATASET_ID,
            "chunk_ordinal": ordinal,
            "knowledge_point_ordinal": point_ordinal,
            "case_id": case_id,
            "text": text,
            "content_sha256": _sha256_bytes(text.encode("utf-8")),
            "source_class": "SYNTHETIC_DETERMINISTIC",
            "license_expression": "LicenseRef-CyberControl-Internal-Benchmark",
        }


def _materialize_performance_corpus(
    path: Path,
    count: int,
    knowledge_point_count: int,
) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with path.open("wb") as handle:
        for row in _performance_rows(count, knowledge_point_count):
            encoded = _canonical_json(row) + b"\n"
            handle.write(encoded)
            digest.update(encoded)
    return {
        "artifact_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "content_sha256": digest.hexdigest(),
        "byte_size": path.stat().st_size,
        "record_count": count,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number} is not valid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        records.append(record)
    return records


def _human_golden_status() -> dict[str, object]:
    facts_path = ROOT / GOLDEN_FACTS_RELATIVE_PATH
    review_path = ROOT / GOLDEN_REVIEW_RELATIVE_PATH
    expected = {
        "facts_path": str(GOLDEN_FACTS_RELATIVE_PATH),
        "review_path": str(GOLDEN_REVIEW_RELATIVE_PATH),
        "required_fact_fields": [
            "fact_id",
            "claim",
            "expected_outcome",
            "citations",
            "license_expression",
        ],
        "required_review_fields": [
            "schema_version",
            "dataset_id",
            "facts_content_sha256",
            "reviewer_subject_ref",
            "reviewed_at_utc",
            "review_policy_version",
            "decision",
        ],
    }
    if not facts_path.exists() or not review_path.exists():
        return {
            "dataset_id": GOLDEN_DATASET_ID,
            "purpose": "ACADEMIC_ACCURACY_ONLY",
            "state": "MISSING_HUMAN_REVIEWED_GOLDEN_SET",
            "acceptance_eligible": False,
            "expected": expected,
        }

    facts = _read_jsonl(facts_path)
    fact_ids = [str(record.get("fact_id", "")) for record in facts]
    missing_fact_fields = sorted(
        {
            field
            for record in facts
            for field in expected["required_fact_fields"]
            if field not in record or record[field] in (None, "", [])
        }
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    missing_review_fields = [
        field
        for field in expected["required_review_fields"]
        if field not in review or review[field] in (None, "")
    ]
    facts_sha256 = _sha256_file(facts_path)
    accepted = (
        bool(facts)
        and len(fact_ids) == len(set(fact_ids))
        and not any(not fact_id for fact_id in fact_ids)
        and not missing_fact_fields
        and not missing_review_fields
        and review.get("schema_version") == "phase7.academic-golden-review.v1"
        and review.get("dataset_id") == GOLDEN_DATASET_ID
        and review.get("facts_content_sha256") == facts_sha256
        and review.get("decision") == "ACCEPTED"
    )
    return {
        "dataset_id": GOLDEN_DATASET_ID,
        "purpose": "ACADEMIC_ACCURACY_ONLY",
        "state": "HUMAN_REVIEWED_GOLDEN_SET_ACCEPTED" if accepted else "GOLDEN_SET_INVALID",
        "acceptance_eligible": accepted,
        "facts_path": str(GOLDEN_FACTS_RELATIVE_PATH),
        "review_path": str(GOLDEN_REVIEW_RELATIVE_PATH),
        "facts_content_sha256": facts_sha256,
        "fact_count": len(facts),
        "duplicate_fact_ids": len(fact_ids) - len(set(fact_ids)),
        "missing_fact_fields": missing_fact_fields,
        "missing_review_fields": missing_review_fields,
        "review_decision": review.get("decision"),
        "expected": expected,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize and inventory the strictly separated Phase 7 acceptance datasets."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Machine-readable dataset inventory JSON output.",
    )
    parser.add_argument(
        "--performance-corpus-output",
        type=Path,
        help="Optional JSONL output for the deterministic synthetic performance corpus.",
    )
    parser.add_argument("--performance-corpus-size", type=int, default=100_000)
    parser.add_argument("--knowledge-point-count", type=int, default=100)
    parser.add_argument(
        "--require-human-reviewed-golden",
        action="store_true",
        help=(
            "Return exit code 2 unless the academic golden facts and review "
            "attestation are accepted."
        ),
    )
    arguments = parser.parse_args()
    if arguments.performance_corpus_size < 1:
        parser.error("--performance-corpus-size must be positive")
    if not 1 <= arguments.knowledge_point_count <= arguments.performance_corpus_size:
        parser.error("--knowledge-point-count must be between one and corpus size")
    return arguments


def main() -> int:
    arguments = _arguments()
    performance_generator = ROOT / PERFORMANCE_GENERATOR_RELATIVE_PATH
    demo_fixture = ROOT / DEMO_FIXTURE_RELATIVE_PATH
    materialized: dict[str, object] | None = None
    if arguments.performance_corpus_output is not None:
        output_path = arguments.performance_corpus_output
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        materialized = _materialize_performance_corpus(
            output_path,
            arguments.performance_corpus_size,
            arguments.knowledge_point_count,
        )

    descriptor = {
        "schema_version": "phase7.dataset-registry.v1",
        "datasets": [
            {
                "dataset_id": PERFORMANCE_DATASET_ID,
                "purpose": "RETRIEVAL_LATENCY_AND_THROUGHPUT_ONLY",
                "source_class": "SYNTHETIC_DETERMINISTIC",
                "generator_path": str(PERFORMANCE_GENERATOR_RELATIVE_PATH),
                "generator_sha256": _sha256_file(performance_generator),
                "corpus_size": arguments.performance_corpus_size,
                "knowledge_point_count": arguments.knowledge_point_count,
                "license_expression": "LicenseRef-CyberControl-Internal-Benchmark",
                "accuracy_claim_permitted": False,
                "materialized_artifact": materialized,
            },
            {
                "dataset_id": "phase7-local-demo-fixtures.v1",
                "purpose": "LOCAL_DEMONSTRATION_ONLY",
                "source_class": "CURATED_LOCAL_FIXTURE",
                "source_path": str(DEMO_FIXTURE_RELATIVE_PATH),
                "source_sha256": _sha256_file(demo_fixture),
                "rights_status": "NOT_ASSERTED_FOR_REDISTRIBUTION",
                "accuracy_claim_permitted": False,
                "production_data_eligible": False,
            },
            _human_golden_status(),
        ],
    }
    descriptor["registry_descriptor_sha256"] = _sha256_bytes(_canonical_json(descriptor))
    descriptor["generated_at_utc"] = datetime.now(UTC).isoformat()
    descriptor["gate_b_state"] = (
        "DATASET_BOUNDARY_ACCEPTED"
        if descriptor["datasets"][2]["acceptance_eligible"]
        else "BLOCKED_HUMAN_REVIEWED_GOLDEN_SET_MISSING"
    )
    output_path = arguments.output
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    _write_json(output_path, descriptor)

    print(json.dumps(descriptor, ensure_ascii=False, indent=2, sort_keys=True))
    if (
        arguments.require_human_reviewed_golden
        and not descriptor["datasets"][2]["acceptance_eligible"]
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
