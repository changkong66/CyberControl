from __future__ import annotations

import json
import runpy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
TOOL = runpy.run_path(str(ROOT / "tools/acceptance/run-phase7-c3-accuracy.py"))


def test_phase7_c3_fixture_matches_frozen_contract_literals() -> None:
    facts = cast(list[dict[str, Any]], TOOL["_read_facts"]())
    now = datetime.now(UTC)

    candidate, spans = TOOL["_candidate_and_spans"](facts, now)
    request = TOOL["_verification_request"](
        candidate,
        tenant_id="phase7-contract-test",
        trace_id="a" * 32,
        now=now,
    )

    assert candidate.provenance.provider_alias == "local"
    assert len(spans) == len(facts)
    assert request.context.locale == "zh-CN"
    assert request.context.subject_domain == "AUTOMATION"


def test_phase7_c3_evidence_inputs_do_not_leak_expected_labels() -> None:
    read_facts = TOOL["_read_facts"]
    read_json = TOOL["_read_json"]
    build_inputs = TOOL["_build_evidence_inputs"]
    facts = cast(list[dict[str, Any]], read_facts())
    ledger = cast(
        dict[str, Any],
        read_json(ROOT / "docs/system-acceptance/evidence/phase7-academic-source-ledger.v1.json"),
    )

    evidence_inputs, source_index = build_inputs(facts, ledger)

    assert len(evidence_inputs) == 24
    assert len(source_index) == 4
    supported_by_topic = {
        fact["topic"]: fact for fact in facts if fact["expected_outcome"] == "SUPPORTED"
    }
    for evidence in evidence_inputs:
        supported = supported_by_topic[evidence.topic]
        assert evidence.fact_id == supported["fact_id"]
        assert evidence.excerpt == supported["claim"]
        serialized = json.dumps(asdict(evidence), ensure_ascii=False)
        assert supported["expected_outcome_rationale"] not in serialized
        assert "expected_outcome" not in serialized


def test_phase7_c3_metrics_report_critical_unsafe_false_negatives() -> None:
    metrics = TOOL["_classification_metrics"](
        [
            {
                "fact_id": "supported",
                "expected_outcome": "SUPPORTED",
                "actual_outcome": "SUPPORTED",
            },
            {
                "fact_id": "unsafe",
                "expected_outcome": "CONTRADICTED",
                "actual_outcome": "SUPPORTED",
            },
            {
                "fact_id": "abstain",
                "expected_outcome": "INSUFFICIENT_EVIDENCE",
                "actual_outcome": "INSUFFICIENT_EVIDENCE",
            },
        ]
    )

    assert metrics["overall_accuracy"] == 0.666667
    assert metrics["critical_unsafe_false_negatives"] == 1
    assert metrics["critical_unsafe_false_negative_fact_ids"] == ["unsafe"]
    assert metrics["per_class"]["CONTRADICTED"] == {
        "tp": 0,
        "fp": 0,
        "tn": 2,
        "fn": 1,
        "precision": "NOT_MEASURABLE",
        "recall": 0.0,
    }


def test_phase7_c3_thresholds_cannot_hide_a_failed_class() -> None:
    records = []
    for outcome in ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"):
        records.extend(
            {
                "fact_id": f"{outcome}-{index}",
                "expected_outcome": outcome,
                "actual_outcome": outcome,
            }
            for index in range(10)
        )
    records[10]["actual_outcome"] = "SUPPORTED"
    records[11]["actual_outcome"] = "SUPPORTED"
    metrics = TOOL["_classification_metrics"](records)

    evaluation = TOOL["_evaluate_thresholds"](
        metrics,
        missing_results=0,
        nondeterministic_results=0,
    )

    assert evaluation["passed"] is False
    assert "critical_unsafe_false_negatives" in evaluation["failed_checks"]
    assert "CONTRADICTED.recall" in evaluation["failed_checks"]


def test_phase7_c3_thresholds_accept_balanced_exact_results() -> None:
    records = [
        {
            "fact_id": f"{outcome}-{index}",
            "expected_outcome": outcome,
            "actual_outcome": outcome,
        }
        for outcome in ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE")
        for index in range(10)
    ]
    metrics = TOOL["_classification_metrics"](records)

    evaluation = TOOL["_evaluate_thresholds"](
        metrics,
        missing_results=0,
        nondeterministic_results=0,
    )

    assert evaluation["passed"] is True
    assert evaluation["failed_checks"] == []
