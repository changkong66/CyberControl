from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

PROCESS_VERSION = "Gate-C-12-v1.0"
ARMS = ("A", "Measurement", "APrime")
ZERO_TOLERANCE_CHECKS = (
    "http_5xx",
    "event_loss",
    "duplicate_render",
    "tenant_isolation",
    "publisher",
    "workflow",
    "token_acquisition",
    "database_pool_timeout_metric",
    "database_pool_timeout_log",
    "outbox_dead",
)
TERMINAL_SSE_FIELDS = (
    "subscribers",
    "subscribers_live",
    "subscribers_replaying",
    "subscribers_draining",
    "closing_subscriptions",
    "queued_events",
    "queued_bytes",
    "replay_buffer_events",
    "replay_buffer_bytes",
    "replay_cache_tenants",
    "replay_cache_events",
    "replay_cache_bytes",
    "replay_tasks",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} contains no valid monitor rows")
    return rows


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("L1 calibration metric has no samples")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _api_container(row: dict[str, Any]) -> dict[str, Any]:
    containers = row.get("containers")
    if not isinstance(containers, list):
        raise ValueError("L1 monitor row has no container inventory")
    matches = [item for item in containers if item.get("service") == "api"]
    if len(matches) != 1:
        raise ValueError("L1 monitor row does not contain exactly one API container")
    return matches[0]


def _heartbeat_ms(row: dict[str, Any]) -> float:
    metrics = row.get("platform_metrics")
    if not isinstance(metrics, dict):
        raise ValueError("L1 monitor row has no platform metrics")
    value = metrics.get("liyans_event_loop_heartbeat_lag_seconds")
    if not isinstance(value, int | float) or value < 0:
        raise ValueError("L1 event-loop heartbeat sample is missing or invalid")
    return 1000 * float(value)


def _rss_bytes(row: dict[str, Any]) -> int:
    memory = _api_container(row).get("process_memory")
    if not isinstance(memory, dict) or not isinstance(memory.get("rss_bytes"), int):
        raise ValueError("L1 API process RSS sample is missing")
    return int(memory["rss_bytes"])


def _terminal_owners_are_zero(recovery: dict[str, Any]) -> bool:
    overlays = recovery.get("ownership_overlays_not_additive")
    if not isinstance(overlays, dict):
        return False
    sse = overlays.get("sse")
    platform = overlays.get("platform")
    if not isinstance(sse, dict) or not isinstance(platform, dict):
        return False
    if any(int(sse.get(name, -1)) != 0 for name in TERMINAL_SSE_FIELDS):
        return False
    pools = platform.get("database_pools")
    if not isinstance(pools, dict):
        return False
    return all(
        isinstance(pool, dict) and int(pool.get("checked_out", -1)) == 0 for pool in pools.values()
    )


def _validate_zero_tolerance_controls(
    arm: str,
    checks: dict[str, Any],
    security: dict[str, Any],
    runtime: dict[str, Any],
) -> None:
    if any(checks.get(name) is not True for name in ZERO_TOLERANCE_CHECKS):
        raise ValueError(f"L1 {arm} failed a zero-tolerance control")
    if (
        security.get("passed") is not True
        or int(security.get("invalid_cursor_acceptance", -1)) != 0
    ):
        raise ValueError(f"L1 {arm} failed its signed cursor or authorization controls")
    if runtime.get("passed") is not True or int(runtime.get("bad_address_count", -1)) != 0:
        raise ValueError(f"L1 {arm} failed its runtime zero-tolerance controls")


def read_arm(run_directory: Path, arm: str) -> dict[str, Any]:
    run_directory = run_directory.resolve(strict=True)
    metadata = _read_json(run_directory / "execution-metadata.json")
    summary = _read_json(run_directory / "stages" / "ramp-200" / "stage-summary.json")
    security = _read_json(run_directory / "stages" / "ramp-200" / "security-controls.json")
    runtime = _read_json(run_directory / "stages" / "ramp-200" / "runtime-controls.json")
    baseline_rows = _read_json_lines(run_directory / "diagnostic-baseline" / "monitor.jsonl")
    stage_rows = _read_json_lines(run_directory / "stages" / "ramp-200" / "monitor.jsonl")
    if (
        metadata.get("process_version") != PROCESS_VERSION
        or metadata.get("mode") != "DiagnosticStages"
        or metadata.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
        or metadata.get("formal_gate_attempt") is not False
        or metadata.get("acceptance_claim") is not False
        or metadata.get("bounded_memory_inventory_arm") != arm
        or metadata.get("diagnostic_stage_names") != ["ramp-200"]
        or metadata.get("diagnostic_idle_seconds") != 300
        or metadata.get("diagnostic_recovery_seconds") != 600
    ):
        raise ValueError(f"L1 {arm} execution metadata is invalid")
    if summary.get("schema_version") != "cybercontrol.gate-c-stage-summary.v1":
        raise ValueError(f"L1 {arm} stage summary is invalid")
    checks = summary.get("checks")
    metrics = summary.get("metrics")
    if not isinstance(checks, dict) or not isinstance(metrics, dict):
        raise ValueError(f"L1 {arm} stage controls are missing")
    _validate_zero_tolerance_controls(arm, checks, security, runtime)
    quality = metrics.get("monitor_quality")
    if not isinstance(quality, dict) or float(quality.get("success_rate", 0)) < 0.95:
        raise ValueError(f"L1 {arm} monitor completeness is below 0.95")

    for row in stage_rows:
        api = _api_container(row)
        if api.get("oom_killed") is not False or int(api.get("restart_count", -1)) != 0:
            raise ValueError(f"L1 {arm} observed API OOM or restart")
    terminal_owners_zero = True
    if arm == "Measurement":
        recovery = _read_json(run_directory / "bounded-memory-inventory" / "recovery.json")
        terminal_owners_zero = _terminal_owners_are_zero(recovery)
        if not terminal_owners_zero:
            raise ValueError("L1 Measurement retained a zero-tolerance terminal owner")

    baseline_tail = baseline_rows[-12:]
    recovery_tail = stage_rows[-12:]
    if len(baseline_tail) < 10 or len(recovery_tail) < 10:
        raise ValueError(f"L1 {arm} lacks a complete baseline or recovery window")
    cpu = [float(_api_container(row)["cpu_percent_one_core_units"]) for row in stage_rows]
    heartbeat = [_heartbeat_ms(row) for row in stage_rows]
    return {
        "arm": arm,
        "run_id": metadata["run_id"],
        "source": {
            name: metadata[name]
            for name in (
                "source_commit",
                "source_tree",
                "product_source_sha",
                "engineering_baseline_sha",
                "image_lock_sha256",
                "build_receipt_sha256",
            )
        },
        "monitor_completeness": float(quality["success_rate"]),
        "connection_p95_ms": float(metrics["connection_establishment_latency_p95_ms"]),
        "delivery_p95_ms": float(metrics["delivery_latency_p95_ms"]),
        "api_cpu_p95": _percentile(cpu, 0.95),
        "event_loop_lag_p95_ms": _percentile(heartbeat, 0.95),
        "baseline_rss_bytes": round(median(_rss_bytes(row) for row in baseline_tail)),
        "recovery_rss_bytes": round(median(_rss_bytes(row) for row in recovery_tail)),
        "terminal_owners_zero": terminal_owners_zero,
        "passed": True,
    }


def compare_l1_arms(
    a: dict[str, Any],
    measurement: dict[str, Any],
    a_prime: dict[str, Any],
) -> dict[str, Any]:
    arms = (a, measurement, a_prime)
    if tuple(arm.get("arm") for arm in arms) != ARMS:
        raise ValueError("L1 comparison requires ordered A, Measurement and APrime arms")
    if len({str(arm.get("run_id")) for arm in arms}) != 3:
        raise ValueError("L1 comparison requires three distinct run IDs")
    if a["source"] != measurement["source"] or a["source"] != a_prime["source"]:
        raise ValueError("L1 arms do not bind the same source and image lock")

    results: dict[str, Any] = {}
    passed = True
    epsilons = {
        "connection_p95_ms": 1.0,
        "delivery_p95_ms": 1.0,
        "api_cpu_p95": 0.01,
        "event_loop_lag_p95_ms": 1.0,
    }
    for name, epsilon in epsilons.items():
        value_a = float(a[name])
        value_m = float(measurement[name])
        value_a_prime = float(a_prime[name])
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

    def rss_delta(arm: dict[str, Any]) -> int:
        return int(arm["recovery_rss_bytes"]) - int(arm["baseline_rss_bytes"])

    rss_a, rss_m, rss_a_prime = (rss_delta(arm) for arm in arms)
    rss_control = median((rss_a, rss_a_prime))
    rss_interference = abs(rss_m - rss_control)
    rss_limit = max(8 * 1024 * 1024, 0.10 * abs(rss_control))
    rss_passed = rss_interference <= rss_limit
    passed = passed and rss_passed
    return {
        "schema_version": "cybercontrol.gate-c-rss-l1-calibration-comparison.v1",
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "source": a["source"],
        "run_ids": {arm["arm"]: arm["run_id"] for arm in arms},
        "metrics": results,
        "rss": {
            "a_delta_bytes": rss_a,
            "measurement_delta_bytes": rss_m,
            "a_prime_delta_bytes": rss_a_prime,
            "control_median_delta_bytes": rss_control,
            "interference_bytes": rss_interference,
            "limit_bytes": rss_limit,
            "passed": rss_passed,
        },
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize or compare ADR-0032 L1 arms.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--run-directory", type=Path, required=True)
    summarize.add_argument("--arm", choices=ARMS, required=True)
    summarize.add_argument("--output", type=Path, required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--a", type=Path, required=True)
    compare.add_argument("--measurement", type=Path, required=True)
    compare.add_argument("--a-prime", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "summarize":
        result = read_arm(arguments.run_directory, arguments.arm)
        result = {
            "schema_version": "cybercontrol.gate-c-rss-l1-calibration-arm.v1",
            "process_version": PROCESS_VERSION,
            "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
            "formal_gate_attempt": False,
            "acceptance_claim": False,
            **result,
        }
        passed = True
    else:
        result = compare_l1_arms(
            _read_json(arguments.a),
            _read_json(arguments.measurement),
            _read_json(arguments.a_prime),
        )
        passed = bool(result["passed"])
    with arguments.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
