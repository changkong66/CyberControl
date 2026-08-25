from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any

from gate_c.rss_calibration import PROCESS_VERSION


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _metric(document: dict[str, Any], name: str) -> float:
    if name == "connection_p95_ms":
        return float(document["connections"]["connection_latency_ms"]["p95"])
    if name == "delivery_p95_ms":
        return float(document["connections"]["delivery_latency_ms"]["p95"])
    if name == "api_cpu_p95":
        return float(document["runtime"]["cpu_one_core_units_p95"])
    if name == "event_loop_lag_p95_ms":
        return float(document["runtime"]["event_loop_lag_p95_ms"])
    raise ValueError(f"unsupported interference metric {name}")


def compare_arms(
    control_a: dict[str, Any],
    measurement: dict[str, Any],
    control_a_prime: dict[str, Any],
) -> dict[str, Any]:
    documents = (control_a, measurement, control_a_prime)
    for document, arm in zip(documents, ("A", "Measurement", "APrime"), strict=True):
        if (
            document.get("schema_version") != "cybercontrol.gate-c-rss-calibration-arm.v1"
            or document.get("process_version") != PROCESS_VERSION
            or document.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
            or document.get("formal_gate_attempt") is not False
            or document.get("acceptance_claim") is not False
            or document.get("arm") != arm
        ):
            raise ValueError(f"calibration {arm} arm metadata is invalid")
        if document.get("passed") is not True:
            raise ValueError(f"calibration {arm} arm did not pass zero-tolerance controls")
        if float(document["connections"]["sample_completeness"]) != 1.0:
            raise ValueError(f"calibration {arm} arm completeness is not exactly one")
    for field in ("variable", "source", "config", "database"):
        if control_a[field] != measurement[field] or control_a[field] != control_a_prime[field]:
            raise ValueError(f"calibration arms do not share the same {field}")
    run_ids = {str(document.get("run_id")) for document in documents}
    if len(run_ids) != 3:
        raise ValueError("calibration arms require distinct run IDs")

    results: dict[str, object] = {}
    passed = True
    epsilons = {
        "connection_p95_ms": 1.0,
        "delivery_p95_ms": 1.0,
        "api_cpu_p95": 0.01,
        "event_loop_lag_p95_ms": 1.0,
    }
    for name, epsilon in epsilons.items():
        value_a = _metric(control_a, name)
        value_m = _metric(measurement, name)
        value_a_prime = _metric(control_a_prime, name)
        control_median = median((value_a, value_a_prime))
        drift = abs(value_a - value_a_prime) / max(abs(control_median), epsilon)
        ratio = value_m / max(control_median, epsilon)
        metric_passed = drift <= 0.10 and ratio <= 1.10
        if name == "event_loop_lag_p95_ms" and control_median == 0:
            metric_passed = metric_passed and value_m <= 1.0
        passed = passed and metric_passed
        results[name] = {
            "a": value_a,
            "measurement": value_m,
            "a_prime": value_a_prime,
            "control_median": control_median,
            "control_drift_ratio": drift,
            "measurement_to_control_ratio": ratio,
            "passed": metric_passed,
        }

    def rss_delta(document: dict[str, Any]) -> int:
        baseline = int(document["windows"]["baseline"]["process"]["rss_bytes"])
        recovery = int(document["windows"]["recovery"]["process"]["rss_bytes"])
        return recovery - baseline

    rss_a = rss_delta(control_a)
    rss_m = rss_delta(measurement)
    rss_a_prime = rss_delta(control_a_prime)
    rss_control_median = median((rss_a, rss_a_prime))
    rss_interference = abs(rss_m - rss_control_median)
    rss_limit = max(8 * 1024 * 1024, 0.10 * abs(rss_control_median))
    rss_passed = rss_interference <= rss_limit
    passed = passed and rss_passed
    return {
        "schema_version": "cybercontrol.gate-c-rss-calibration-comparison.v1",
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "variable": control_a["variable"],
        "source": control_a["source"],
        "run_ids": {
            "A": control_a["run_id"],
            "Measurement": measurement["run_id"],
            "APrime": control_a_prime["run_id"],
        },
        "metrics": results,
        "rss": {
            "a_delta_bytes": rss_a,
            "measurement_delta_bytes": rss_m,
            "a_prime_delta_bytes": rss_a_prime,
            "control_median_delta_bytes": rss_control_median,
            "interference_bytes": rss_interference,
            "limit_bytes": rss_limit,
            "passed": rss_passed,
        },
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare one ADR-0032 A/M/A' sequence.")
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--a-prime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = compare_arms(
        _read(arguments.a),
        _read(arguments.measurement),
        _read(arguments.a_prime),
    )
    with arguments.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
