from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any

from gate_c.rss_calibration import (
    BRACKET_BURST_MAX_SECONDS,
    BRACKET_SAMPLE_COUNT,
    BRACKET_SAMPLE_MAX_SECONDS,
    BRACKET_SAMPLE_ORDER,
    PROCESS_VERSION,
)


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


def _validate_ledger(ledger: object, arm: str, window: str) -> None:
    if not isinstance(ledger, dict) or ledger.get("schema_version") != (
        "cybercontrol.domain-separated-memory-ledger.v1"
    ):
        raise ValueError(f"calibration {arm} {window} domain ledger is invalid")
    allocator = ledger.get("jemalloc_accounting")
    process = ledger.get("linux_process")
    cgroup = ledger.get("cgroup_physical")
    cross_domain = ledger.get("cross_domain_non_additive")
    if (
        not isinstance(allocator, dict)
        or not isinstance(process, dict)
        or not isinstance(cgroup, dict)
    ):
        raise ValueError(f"calibration {arm} {window} same-domain ledgers are missing")
    allocator_fields = (
        "allocated_bytes",
        "active_bytes",
        "resident_bytes",
        "mapped_bytes",
        "metadata_bytes",
        "retained_bytes",
        "arena_count",
        "allocator_slack_bytes",
        "allocator_resident_gap_bytes",
    )
    if any(type(allocator.get(name)) is not int for name in allocator_fields):
        raise ValueError(f"calibration {arm} {window} allocator ledger is incomplete")
    if any(int(allocator[name]) < 0 for name in allocator_fields):
        raise ValueError(f"calibration {arm} {window} allocator ledger is negative")
    allocated = int(allocator["allocated_bytes"])
    active = int(allocator["active_bytes"])
    resident = int(allocator["resident_bytes"])
    if (
        allocated + int(allocator["allocator_slack_bytes"]) != active
        or active + int(allocator["allocator_resident_gap_bytes"]) != resident
    ):
        raise ValueError(f"calibration {arm} {window} allocator ledger is inconsistent")

    process_fields = (
        "vmrss_bytes",
        "rss_anon_bytes",
        "rss_file_bytes",
        "rss_shmem_bytes",
        "pss_bytes",
        "uss_bytes",
        "swap_bytes",
        "fd_count",
        "map_count",
        "rss_reconciliation_signed_bytes",
        "rss_reconciliation_limit_bytes",
    )
    if any(type(process.get(name)) is not int for name in process_fields):
        raise ValueError(f"calibration {arm} {window} process ledger is incomplete")
    vmrss = int(process["vmrss_bytes"])
    rss_anon = int(process["rss_anon_bytes"])
    rss_file = int(process["rss_file_bytes"])
    rss_shmem = int(process["rss_shmem_bytes"])
    reconciliation = vmrss - rss_anon - rss_file - rss_shmem
    reconciliation_limit = max(1024 * 1024, round(vmrss * 0.02))
    if (
        min(
            vmrss,
            rss_anon,
            rss_file,
            rss_shmem,
            int(process["pss_bytes"]),
            int(process["uss_bytes"]),
            int(process["swap_bytes"]),
            int(process["fd_count"]),
            int(process["map_count"]),
        )
        < 0
        or int(process["rss_reconciliation_signed_bytes"]) != reconciliation
        or int(process["rss_reconciliation_limit_bytes"]) != reconciliation_limit
        or abs(reconciliation) > reconciliation_limit
    ):
        raise ValueError(f"calibration {arm} {window} process ledger is inconsistent")

    cgroup_fields = (
        "memory_current_bytes",
        "anon_bytes",
        "file_bytes",
        "kernel_bytes",
        "unclassified_signed_bytes",
    )
    if any(type(cgroup.get(name)) is not int for name in cgroup_fields):
        raise ValueError(f"calibration {arm} {window} cgroup ledger is incomplete")
    current = int(cgroup["memory_current_bytes"])
    anon = int(cgroup["anon_bytes"])
    file_bytes = int(cgroup["file_bytes"])
    kernel = int(cgroup["kernel_bytes"])
    if (
        min(current, anon, file_bytes, kernel) < 0
        or int(cgroup["unclassified_signed_bytes"]) != current - anon - file_bytes - kernel
        or not isinstance(cgroup.get("drilldowns_non_additive"), dict)
    ):
        raise ValueError(f"calibration {arm} {window} cgroup ledger is inconsistent")
    if (
        not isinstance(cross_domain, dict)
        or cross_domain.get("classification") != "NON_ADDITIVE_CROSS_DOMAIN"
        or type(cross_domain.get("jemalloc_resident_minus_rss_anon_signed_bytes")) is not int
        or int(cross_domain["jemalloc_resident_minus_rss_anon_signed_bytes"]) != resident - rss_anon
    ):
        raise ValueError(f"calibration {arm} {window} cross-domain lane is additive")


def _sample_identity(sample: object, index: int, arm: str, window: str) -> tuple[int, int]:
    if (
        not isinstance(sample, dict)
        or sample.get("index") != index
        or sample.get("order") != list(BRACKET_SAMPLE_ORDER)
        or not 0 <= float(sample.get("duration_seconds", -1)) <= BRACKET_SAMPLE_MAX_SECONDS
    ):
        raise ValueError(f"calibration {arm} {window} sample order is invalid")
    started = sample.get("started_monotonic_seconds")
    completed = sample.get("completed_monotonic_seconds")
    if (
        not isinstance(started, (int, float))
        or not isinstance(completed, (int, float))
        or float(completed) < float(started)
        or abs((float(completed) - float(started)) - float(sample["duration_seconds"])) > 0.000002
    ):
        raise ValueError(f"calibration {arm} {window} sample timing is invalid")
    process = sample.get("process_representative")
    cgroup = sample.get("cgroup_representative")
    process_before = sample.get("process_before")
    process_after = sample.get("process_after")
    cgroup_before = sample.get("cgroup_before")
    cgroup_after = sample.get("cgroup_after")
    if any(
        not isinstance(item, dict)
        for item in (process, cgroup, process_before, process_after, cgroup_before, cgroup_after)
    ):
        raise ValueError(f"calibration {arm} {window} bracket is incomplete")
    process_id = int(process["process_id"])
    cgroup_inode = int(cgroup["cgroup_inode"])
    if (
        int(process_before["process_id"]) != process_id
        or int(process_after["process_id"]) != process_id
        or int(cgroup_before["cgroup_inode"]) != cgroup_inode
        or int(cgroup_after["cgroup_inode"]) != cgroup_inode
    ):
        raise ValueError(f"calibration {arm} {window} bracket identity changed")
    return process_id, cgroup_inode


def _validate_distribution(sampling: dict[str, Any], name: str, arm: str, window: str) -> None:
    distribution = sampling.get(name)
    if not isinstance(distribution, dict) or int(distribution["spread"]) > int(
        distribution["spread_limit"]
    ):
        raise ValueError(f"calibration {arm} {window} {name} spread is invalid")


def _validate_measurement_sampling(sampling: dict[str, Any], arm: str, window: str) -> None:
    if (
        sampling.get("schema_version") != "cybercontrol.gate-c-bracketed-domain-sampling.v1"
        or sampling.get("mode") != "FIVE_SAMPLE_BRACKETED_DOMAIN"
        or sampling.get("sample_count") != BRACKET_SAMPLE_COUNT
        or sampling.get("required_sample_count") != BRACKET_SAMPLE_COUNT
        or float(sampling.get("spacing_seconds", -1)) != 0.05
        or float(sampling.get("sample_max_seconds", -1)) != BRACKET_SAMPLE_MAX_SECONDS
        or float(sampling.get("burst_max_seconds", -1)) != BRACKET_BURST_MAX_SECONDS
        or float(sampling.get("burst_duration_seconds", BRACKET_BURST_MAX_SECONDS + 1))
        > BRACKET_BURST_MAX_SECONDS
    ):
        raise ValueError(f"calibration {arm} {window} bounded sampling is invalid")
    samples = sampling.get("samples")
    if not isinstance(samples, list) or len(samples) != BRACKET_SAMPLE_COUNT:
        raise ValueError(f"calibration {arm} {window} sample count is invalid")
    identities = [
        _sample_identity(sample, index, arm, window)
        for index, sample in enumerate(samples, start=1)
    ]
    if (
        len({identity[0] for identity in identities}) != 1
        or len({identity[1] for identity in identities}) != 1
    ):
        raise ValueError(f"calibration {arm} {window} identity changed")
    for name in ("process_rss_anon", "cgroup_memory_current"):
        _validate_distribution(sampling, name, arm, window)


def _validate_sampling(document: dict[str, Any], arm: str) -> None:
    if document.get("variable") != "D":
        raise ValueError("ADR-0033 calibration accepts variable D only")
    windows = document.get("windows")
    if not isinstance(windows, dict):
        raise ValueError(f"calibration {arm} windows are missing")
    for window_name in ("baseline", "recovery"):
        window = windows.get(window_name)
        if not isinstance(window, dict):
            raise ValueError(f"calibration {arm} {window_name} window is missing")
        _validate_ledger(window.get("ledger"), arm, window_name)
        sampling = window.get("sampling")
        if not isinstance(sampling, dict):
            raise ValueError(f"calibration {arm} {window_name} sampling is missing")
        if arm == "Measurement":
            _validate_measurement_sampling(sampling, arm, window_name)
        elif sampling != {"mode": "MINIMAL_CONTROL", "sample_count": 1}:
            raise ValueError(f"calibration {arm} must retain minimal control sampling")


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
        zero_tolerance = document.get("zero_tolerance")
        if (
            not isinstance(zero_tolerance, dict)
            or not zero_tolerance
            or any(value is not True for value in zero_tolerance.values())
        ):
            raise ValueError(f"calibration {arm} arm zero-tolerance controls are invalid")
        if float(document["connections"]["sample_completeness"]) != 1.0:
            raise ValueError(f"calibration {arm} arm completeness is not exactly one")
        _validate_sampling(document, arm)
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
    parser = argparse.ArgumentParser(description="Compare one ADR-0033 A/D/A' sequence.")
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
