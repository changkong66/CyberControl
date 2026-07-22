"""Materialize and inventory the Phase 7 acceptance datasets.

The three dataset classes intentionally have different acceptance purposes:
synthetic retrieval performance, local demonstration fixtures, and human-reviewed
academic facts.  This utility never upgrades one class into another.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_DATASET_ID = "phase7-c2-synthetic-retrieval-performance.v1"
GOLDEN_DATASET_ID = "phase7-academic-human-reviewed-facts.v1"
GOLDEN_FACTS_RELATIVE_PATH = Path("tests/golden/phase7-academic-golden-facts.v1.jsonl")
GOLDEN_REVIEW_RELATIVE_PATH = Path("tests/golden/phase7-academic-golden-review.v1.json")
GOLDEN_SOURCE_LEDGER_RELATIVE_PATH = Path(
    "docs/system-acceptance/evidence/phase7-academic-source-ledger.v1.json"
)
GOLDEN_REVIEW_POLICY_RELATIVE_PATH = Path("docs/system-acceptance/phase7-academic-review-policy.md")
DEMO_FIXTURE_RELATIVE_PATH = Path("data/topic1/automatic-control-principles.v1.json")
PERFORMANCE_GENERATOR_RELATIVE_PATH = Path("backend/benchmarks/topic4_c2_retrieval.py")

_GOLDEN_FACT_SCHEMA = "phase7.academic-golden-fact.v1"
_GOLDEN_REVIEW_SCHEMA = "phase7.academic-golden-review.v1"
_GOLDEN_LEDGER_SCHEMA = "phase7.academic-source-ledger.v1"
_GOLDEN_POLICY_VERSION = "phase7.academic-review-policy.v1"
_PENDING_REVIEW_DECISION = "PENDING_HUMAN_HASH_CONFIRMATION"
_ALLOWED_EXPECTED_OUTCOMES = frozenset({"SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"})
_ALLOWED_LICENSES = frozenset({"CC-BY-3.0", "CC-BY-4.0"})
_MINIMUM_GOLDEN_FACTS = 60
_MINIMUM_OUTCOME_FACTS = 20
_MINIMUM_GOLDEN_TOPICS = 16
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_REQUIRED_GOLDEN_FACT_FIELDS = (
    "schema_version",
    "dataset_id",
    "fact_id",
    "target_module",
    "topic",
    "difficulty",
    "language",
    "claim",
    "expected_outcome",
    "expected_outcome_rationale",
    "citations",
    "license_expression",
    "curation_method",
    "source_text_reproduced",
    "contains_personal_data",
)
_REQUIRED_GOLDEN_REVIEW_FIELDS = (
    "schema_version",
    "dataset_id",
    "facts_content_sha256",
    "source_ledger_content_sha256",
    "review_policy_content_sha256",
    "reviewer_subject_ref",
    "reviewer_qualification_statement",
    "conflict_of_interest",
    "conflict_disposition",
    "review_policy_version",
    "fact_count",
    "outcome_counts",
    "rights_review_decision",
    "decision",
)


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


def _git_revision(revision: str) -> str:
    if revision not in {"HEAD", "HEAD^{tree}"}:
        raise ValueError("unsupported Git revision for dataset evidence")
    git_path = shutil.which("git")
    if git_path is None:
        raise RuntimeError("Git is required to bind dataset evidence to source")
    completed = subprocess.run(  # noqa: S603 - absolute executable and revision allowlist.
        [git_path, "rev-parse", revision],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_status() -> list[str]:
    git_path = shutil.which("git")
    if git_path is None:
        raise RuntimeError("Git is required to verify a clean dataset source")
    completed = subprocess.run(  # noqa: S603 - resolved Git executable and fixed arguments.
        [git_path, "status", "--porcelain=v1"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


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


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == UTC.utcoffset(parsed)


def _golden_expected() -> dict[str, object]:
    return {
        "facts_path": GOLDEN_FACTS_RELATIVE_PATH.as_posix(),
        "review_path": GOLDEN_REVIEW_RELATIVE_PATH.as_posix(),
        "source_ledger_path": GOLDEN_SOURCE_LEDGER_RELATIVE_PATH.as_posix(),
        "review_policy_path": GOLDEN_REVIEW_POLICY_RELATIVE_PATH.as_posix(),
        "required_fact_fields": list(_REQUIRED_GOLDEN_FACT_FIELDS),
        "required_review_fields": list(_REQUIRED_GOLDEN_REVIEW_FIELDS),
        "minimum_fact_count": _MINIMUM_GOLDEN_FACTS,
        "minimum_per_outcome": _MINIMUM_OUTCOME_FACTS,
        "minimum_topic_count": _MINIMUM_GOLDEN_TOPICS,
        "allowed_expected_outcomes": sorted(_ALLOWED_EXPECTED_OUTCOMES),
        "allowed_licenses": sorted(_ALLOWED_LICENSES),
    }


def _append_error_if(errors: list[str], condition: bool, message: str) -> None:
    if condition:
        errors.append(message)


def _missing_fields(records: Iterable[dict[str, Any]], required: Iterable[str]) -> list[str]:
    return sorted(
        {
            field
            for record in records
            for field in required
            if field not in record or record[field] in (None, "", [])
        }
    )


def _source_errors(source: dict[str, Any], source_id: str) -> list[str]:
    errors: list[str] = []
    chapter_authors = source.get("chapter_authors")
    checks = (
        (not source.get("work_title"), f"source {source_id} has no work title"),
        (not source.get("chapter_title"), f"source {source_id} has no chapter title"),
        (
            not isinstance(chapter_authors, list) or not chapter_authors,
            f"source {source_id} has no chapter authors",
        ),
        (not source.get("publisher"), f"source {source_id} has no publisher"),
        (not source.get("doi"), f"source {source_id} has no DOI"),
        (
            not _is_https_url(source.get("doi_url")),
            f"source {source_id} doi_url must be HTTPS",
        ),
        (
            not _is_https_url(source.get("metadata_url")),
            f"source {source_id} metadata_url must be HTTPS",
        ),
        (
            not isinstance(source.get("source_byte_size"), int) or source["source_byte_size"] < 1,
            f"source {source_id} byte size is invalid",
        ),
        (
            not _is_utc_timestamp(source.get("remote_hash_verified_at_utc")),
            f"source {source_id} remote hash verification time is invalid",
        ),
        (
            source.get("attribution_required") is not True,
            f"source {source_id} must require attribution",
        ),
        (
            source.get("included_material") != "PARAPHRASED_CHAPTER_FACTS_ONLY",
            f"source {source_id} has an invalid included-material boundary",
        ),
        (
            source.get("images_included") is not False,
            f"source {source_id} must not include source images",
        ),
    )
    errors.extend(message for condition, message in checks if condition)
    _append_error_if(
        errors,
        source.get("status") != "INCLUDED",
        f"source {source_id} is not marked INCLUDED",
    )
    _append_error_if(
        errors,
        source.get("commercial_reuse_permitted") is not True,
        f"source {source_id} does not permit commercial reuse",
    )
    _append_error_if(
        errors,
        source.get("license_expression") not in _ALLOWED_LICENSES,
        f"source {source_id} has an ineligible license",
    )
    _append_error_if(
        errors,
        not _is_https_url(source.get("source_url")),
        f"source {source_id} source_url must be HTTPS",
    )
    _append_error_if(
        errors,
        not _is_https_url(source.get("license_url")),
        f"source {source_id} license_url must be HTTPS",
    )
    _append_error_if(
        errors,
        not _is_sha256(source.get("source_content_sha256")),
        f"source {source_id} content SHA256 is invalid",
    )
    _append_error_if(
        errors,
        not source.get("license_evidence_locator"),
        f"source {source_id} has no license evidence locator",
    )
    return errors


def _source_ledger_index(ledger: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    _append_error_if(
        errors,
        ledger.get("schema_version") != _GOLDEN_LEDGER_SCHEMA,
        "source ledger schema_version is invalid",
    )
    rights_boundary = ledger.get("rights_boundary")
    if not isinstance(rights_boundary, dict):
        errors.append("source ledger rights_boundary must be an object")
    else:
        prohibited_uses = (
            "compilation_text_reused",
            "chapter_figures_reused",
            "chapter_tables_reused",
            "verbatim_source_text_reused",
        )
        errors.extend(
            f"source ledger must set {field}=false"
            for field in prohibited_uses
            if rights_boundary.get(field) is not False
        )

    included_sources = ledger.get("included_sources")
    if not isinstance(included_sources, list) or not included_sources:
        errors.append("source ledger included_sources must be a non-empty array")
        return {}, errors

    source_index: dict[str, dict[str, Any]] = {}
    for source_number, source in enumerate(included_sources, start=1):
        if not isinstance(source, dict):
            errors.append(f"source ledger item {source_number} must be an object")
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"source ledger item {source_number} has no source_id")
            continue
        _append_error_if(
            errors,
            source_id in source_index,
            f"source ledger source_id {source_id} is duplicated",
        )
        source_index[source_id] = source
        errors.extend(_source_errors(source, source_id))
    return source_index, errors


def _citation_errors(
    citation: object,
    citation_prefix: str,
    fact_license: object,
    source_index: dict[str, dict[str, Any]],
) -> tuple[list[str], str | None]:
    if not isinstance(citation, dict):
        return [f"{citation_prefix} must be an object"], None
    source_id = citation.get("source_id")
    if not isinstance(source_id, str) or source_id not in source_index:
        return [f"{citation_prefix} references an unknown source"], None

    source = source_index[source_id]
    errors: list[str] = []
    _append_error_if(
        errors,
        source.get("license_expression") != fact_license,
        f"{citation_prefix} license does not match the fact",
    )
    _append_error_if(
        errors,
        not citation.get("locator"),
        f"{citation_prefix} has no source locator",
    )
    citation_url = citation.get("source_url")
    permitted_urls = {source.get("source_url"), source.get("doi_url")}
    _append_error_if(
        errors,
        not _is_https_url(citation_url) or citation_url not in permitted_urls,
        f"{citation_prefix} URL is not a ledger-approved HTTPS endpoint",
    )
    return errors, source_id


def _fact_record_analysis(
    record: dict[str, Any],
    record_number: int,
    source_index: dict[str, dict[str, Any]],
) -> tuple[list[str], str | None, str | None, str | None, set[str]]:
    prefix = f"fact record {record_number}"
    errors: list[str] = []
    checks = (
        (
            record.get("schema_version") != _GOLDEN_FACT_SCHEMA,
            f"{prefix} has an invalid schema_version",
        ),
        (
            record.get("dataset_id") != GOLDEN_DATASET_ID,
            f"{prefix} has an invalid dataset_id",
        ),
        (
            record.get("target_module") != "C3_ACADEMIC",
            f"{prefix} must target C3_ACADEMIC",
        ),
        (
            record.get("language") != "en-US",
            f"{prefix} must declare language en-US",
        ),
        (
            record.get("license_expression") not in _ALLOWED_LICENSES,
            f"{prefix} has an ineligible license_expression",
        ),
        (
            record.get("curation_method") != "ORIGINAL_PARAPHRASE_FROM_LICENSED_SOURCE",
            f"{prefix} has an invalid curation_method",
        ),
        (
            record.get("source_text_reproduced") is not False,
            f"{prefix} must not reproduce source text",
        ),
        (
            record.get("contains_personal_data") is not False,
            f"{prefix} must not contain personal data",
        ),
    )
    errors.extend(message for condition, message in checks if condition)

    outcome = record.get("expected_outcome")
    valid_outcome = (
        outcome if isinstance(outcome, str) and outcome in _ALLOWED_EXPECTED_OUTCOMES else None
    )
    _append_error_if(
        errors,
        valid_outcome is None,
        f"{prefix} has an invalid expected_outcome",
    )

    used_source_ids: set[str] = set()
    citations = record.get("citations")
    if not isinstance(citations, list) or not citations:
        errors.append(f"{prefix} must have at least one structured citation")
    else:
        for citation_number, citation in enumerate(citations, start=1):
            citation_errors, source_id = _citation_errors(
                citation,
                f"{prefix} citation {citation_number}",
                record.get("license_expression"),
                source_index,
            )
            errors.extend(citation_errors)
            if source_id is not None:
                used_source_ids.add(source_id)

    target_module = record.get("target_module")
    topic = record.get("topic")
    return (
        errors,
        valid_outcome,
        target_module if isinstance(target_module, str) else None,
        topic if isinstance(topic, str) and topic else None,
        used_source_ids,
    )


def _golden_fact_analysis(
    facts: list[dict[str, Any]],
    source_index: dict[str, dict[str, Any]],
) -> dict[str, object]:
    errors: list[str] = []
    fact_ids = [str(record.get("fact_id", "")) for record in facts]
    missing_fields = _missing_fields(facts, _REQUIRED_GOLDEN_FACT_FIELDS)
    _append_error_if(
        errors,
        bool(missing_fields),
        "facts are missing required fields: " + ", ".join(missing_fields),
    )
    _append_error_if(errors, not facts, "golden fact set is empty")
    _append_error_if(
        errors,
        any(not fact_id for fact_id in fact_ids),
        "fact_id values must be non-empty",
    )
    _append_error_if(
        errors,
        len(fact_ids) != len(set(fact_ids)),
        "fact_id values must be unique",
    )

    outcome_counts: Counter[str] = Counter()
    target_module_counts: Counter[str] = Counter()
    topics: set[str] = set()
    used_source_ids: set[str] = set()
    for record_number, record in enumerate(facts, start=1):
        record_errors, outcome, target_module, topic, source_ids = _fact_record_analysis(
            record,
            record_number,
            source_index,
        )
        errors.extend(record_errors)
        if outcome is not None:
            outcome_counts[outcome] += 1
        if target_module is not None:
            target_module_counts[target_module] += 1
        if topic is not None:
            topics.add(topic)
        used_source_ids.update(source_ids)

    _append_error_if(
        errors,
        len(facts) < _MINIMUM_GOLDEN_FACTS,
        f"golden set requires at least {_MINIMUM_GOLDEN_FACTS} facts",
    )
    errors.extend(
        f"{outcome} requires at least {_MINIMUM_OUTCOME_FACTS} facts"
        for outcome in sorted(_ALLOWED_EXPECTED_OUTCOMES)
        if outcome_counts[outcome] < _MINIMUM_OUTCOME_FACTS
    )
    _append_error_if(
        errors,
        len(topics) < _MINIMUM_GOLDEN_TOPICS,
        f"golden set requires at least {_MINIMUM_GOLDEN_TOPICS} distinct topics",
    )
    _append_error_if(
        errors,
        used_source_ids != set(source_index),
        "every included source must be cited by at least one fact",
    )
    return {
        "errors": errors,
        "fact_ids": fact_ids,
        "missing_fields": missing_fields,
        "outcome_counts": outcome_counts,
        "target_module_counts": target_module_counts,
        "topics": topics,
        "used_source_ids": used_source_ids,
    }


def _review_errors(
    review: dict[str, Any],
    *,
    facts_sha256: str,
    source_ledger_sha256: str,
    review_policy_sha256: str,
    fact_count: int,
    outcome_counts: Counter[str],
) -> tuple[list[str], object, list[str]]:
    errors: list[str] = []
    missing_fields = _missing_fields([review], _REQUIRED_GOLDEN_REVIEW_FIELDS)
    _append_error_if(
        errors,
        bool(missing_fields),
        "review is missing required fields: " + ", ".join(missing_fields),
    )
    checks = (
        (
            review.get("schema_version") != _GOLDEN_REVIEW_SCHEMA,
            "review schema_version is invalid",
        ),
        (
            review.get("dataset_id") != GOLDEN_DATASET_ID,
            "review dataset_id is invalid",
        ),
        (
            review.get("facts_content_sha256") != facts_sha256,
            "review facts_content_sha256 does not match the facts",
        ),
        (
            review.get("source_ledger_content_sha256") != source_ledger_sha256,
            "review source ledger SHA256 does not match",
        ),
        (
            review.get("review_policy_content_sha256") != review_policy_sha256,
            "review policy SHA256 does not match",
        ),
        (
            review.get("review_policy_version") != _GOLDEN_POLICY_VERSION,
            "review_policy_version is invalid",
        ),
        (
            review.get("fact_count") != fact_count,
            "review fact_count does not match the facts",
        ),
        (
            review.get("outcome_counts") != dict(sorted(outcome_counts.items())),
            "review outcome_counts do not match the facts",
        ),
        (
            review.get("conflict_of_interest") != "PROJECT_AND_DATASET_OWNER",
            "project ownership conflict must be explicitly disclosed",
        ),
        (
            not review.get("conflict_disposition"),
            "reviewer conflict disposition is required",
        ),
        (
            not review.get("reviewer_qualification_statement"),
            "reviewer qualification statement is required",
        ),
    )
    errors.extend(message for condition, message in checks if condition)

    reviewer_subject_ref = review.get("reviewer_subject_ref")
    _append_error_if(
        errors,
        not isinstance(reviewer_subject_ref, str) or not reviewer_subject_ref.startswith("github:"),
        "reviewer_subject_ref must use a minimal github: subject reference",
    )
    decision = review.get("decision")
    _append_error_if(
        errors,
        decision not in {_PENDING_REVIEW_DECISION, "ACCEPTED", "REJECTED"},
        "review decision is invalid",
    )
    if decision == "ACCEPTED":
        _append_error_if(
            errors,
            review.get("rights_review_decision") != "ACCEPTED",
            "accepted review requires accepted rights review",
        )
        _append_error_if(
            errors,
            not _is_utc_timestamp(review.get("reviewed_at_utc")),
            "accepted review requires a valid UTC review timestamp",
        )
    return errors, decision, missing_fields


def _golden_review_state(decision: object, errors: list[str]) -> tuple[str, bool]:
    if errors:
        return "GOLDEN_SET_INVALID", False
    states = {
        "ACCEPTED": ("HUMAN_REVIEWED_GOLDEN_SET_ACCEPTED", True),
        _PENDING_REVIEW_DECISION: (
            "GOLDEN_SET_PENDING_HUMAN_HASH_CONFIRMATION",
            False,
        ),
        "REJECTED": ("GOLDEN_SET_REJECTED", False),
    }
    return states.get(decision, ("GOLDEN_SET_INVALID", False))


def _human_golden_status() -> dict[str, object]:
    facts_path = ROOT / GOLDEN_FACTS_RELATIVE_PATH
    review_path = ROOT / GOLDEN_REVIEW_RELATIVE_PATH
    source_ledger_path = ROOT / GOLDEN_SOURCE_LEDGER_RELATIVE_PATH
    review_policy_path = ROOT / GOLDEN_REVIEW_POLICY_RELATIVE_PATH
    expected = _golden_expected()
    required_paths = (facts_path, review_path, source_ledger_path, review_policy_path)
    missing_paths = [
        path.relative_to(ROOT).as_posix() for path in required_paths if not path.exists()
    ]
    if missing_paths:
        return {
            "dataset_id": GOLDEN_DATASET_ID,
            "purpose": "ACADEMIC_ACCURACY_ONLY",
            "state": "MISSING_HUMAN_REVIEWED_GOLDEN_SET",
            "acceptance_eligible": False,
            "missing_paths": missing_paths,
            "expected": expected,
        }

    try:
        facts = _read_jsonl(facts_path)
        review = _read_json_object(review_path)
        ledger = _read_json_object(source_ledger_path)
    except ValueError as exc:
        return {
            "dataset_id": GOLDEN_DATASET_ID,
            "purpose": "ACADEMIC_ACCURACY_ONLY",
            "state": "GOLDEN_SET_INVALID",
            "acceptance_eligible": False,
            "validation_errors": [str(exc)],
            "expected": expected,
        }

    source_index, ledger_errors = _source_ledger_index(ledger)
    fact_analysis = _golden_fact_analysis(facts, source_index)
    outcome_counts = fact_analysis["outcome_counts"]
    if not isinstance(outcome_counts, Counter):
        raise TypeError("golden fact analysis returned invalid outcome counts")

    facts_sha256 = _sha256_file(facts_path)
    source_ledger_sha256 = _sha256_file(source_ledger_path)
    review_policy_sha256 = _sha256_file(review_policy_path)
    review_errors, decision, missing_review_fields = _review_errors(
        review,
        facts_sha256=facts_sha256,
        source_ledger_sha256=source_ledger_sha256,
        review_policy_sha256=review_policy_sha256,
        fact_count=len(facts),
        outcome_counts=outcome_counts,
    )
    validation_errors = ledger_errors + list(fact_analysis["errors"]) + review_errors
    state, accepted = _golden_review_state(decision, validation_errors)
    fact_ids = fact_analysis["fact_ids"]
    topics = fact_analysis["topics"]
    target_module_counts = fact_analysis["target_module_counts"]
    used_source_ids = fact_analysis["used_source_ids"]
    if not all(
        isinstance(value, expected_type)
        for value, expected_type in (
            (fact_ids, list),
            (topics, set),
            (target_module_counts, Counter),
            (used_source_ids, set),
        )
    ):
        raise TypeError("golden fact analysis returned invalid collection types")

    return {
        "dataset_id": GOLDEN_DATASET_ID,
        "purpose": "ACADEMIC_ACCURACY_ONLY",
        "state": state,
        "acceptance_eligible": accepted,
        "facts_path": GOLDEN_FACTS_RELATIVE_PATH.as_posix(),
        "review_path": GOLDEN_REVIEW_RELATIVE_PATH.as_posix(),
        "source_ledger_path": GOLDEN_SOURCE_LEDGER_RELATIVE_PATH.as_posix(),
        "review_policy_path": GOLDEN_REVIEW_POLICY_RELATIVE_PATH.as_posix(),
        "facts_content_sha256": facts_sha256,
        "source_ledger_content_sha256": source_ledger_sha256,
        "review_policy_content_sha256": review_policy_sha256,
        "fact_count": len(facts),
        "duplicate_fact_ids": len(fact_ids) - len(set(fact_ids)),
        "topic_count": len(topics),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "target_module_counts": dict(sorted(target_module_counts.items())),
        "used_source_ids": sorted(used_source_ids),
        "missing_fact_fields": fact_analysis["missing_fields"],
        "missing_review_fields": missing_review_fields,
        "review_decision": decision,
        "validation_errors": validation_errors,
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
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="Permit local tool development runs from a dirty tree; never use for formal evidence.",
    )
    arguments = parser.parse_args()
    if arguments.performance_corpus_size < 1:
        parser.error("--performance-corpus-size must be positive")
    if not 1 <= arguments.knowledge_point_count <= arguments.performance_corpus_size:
        parser.error("--knowledge-point-count must be between one and corpus size")
    return arguments


def main() -> int:
    arguments = _arguments()
    dirty_files = _git_status()
    if dirty_files and not arguments.allow_dirty_source:
        raise SystemExit(
            "Phase 7 dataset evidence requires a clean source tree; "
            "commit tooling before formal generation."
        )
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
        "source_commit": _git_revision("HEAD"),
        "source_tree": _git_revision("HEAD^{tree}"),
        "clean_source": not dirty_files,
        "dirty_files_at_start": dirty_files,
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
    golden_state = descriptor["datasets"][2]["state"]
    descriptor["gate_b_state"] = {
        "HUMAN_REVIEWED_GOLDEN_SET_ACCEPTED": "DATASET_BOUNDARY_ACCEPTED",
        "GOLDEN_SET_PENDING_HUMAN_HASH_CONFIRMATION": "BLOCKED_HUMAN_HASH_CONFIRMATION",
        "GOLDEN_SET_REJECTED": "BLOCKED_HUMAN_REVIEW_REJECTED",
        "GOLDEN_SET_INVALID": "BLOCKED_GOLDEN_SET_INVALID",
    }.get(golden_state, "BLOCKED_HUMAN_REVIEWED_GOLDEN_SET_MISSING")
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
