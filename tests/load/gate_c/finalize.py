from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gate_c.config import Thresholds

_JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize Gate C evidence.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _monitor_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))
    return round(ordered[index], 3)


def _longest_breach(
    rows: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> float:
    longest = 0.0
    started: int | None = None
    previous: int | None = None
    for row in rows:
        captured = int(row["captured_at_unix_ns"])
        if predicate(row):
            if started is None or (previous is not None and captured - previous > 15_000_000_000):
                started = captured
            longest = max(longest, (captured - started) / 1_000_000_000)
        else:
            started = None
        previous = captured
    return round(longest, 3)


def _metric_sum(row: dict[str, Any], prefix: str) -> float:
    values = row.get("platform_metrics")
    if not isinstance(values, dict):
        return 0.0
    return sum(float(value) for key, value in values.items() if str(key).startswith(prefix))


def _container_values(rows: list[dict[str, Any]], service: str, field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        containers = row.get("containers")
        if not isinstance(containers, list):
            continue
        for container in containers:
            if (
                isinstance(container, dict)
                and container.get("service") == service
                and isinstance(container.get(field), int | float)
            ):
                values.extend([float(container[field])])
    return values


def _manifest(run_dir: Path, excluded: set[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(value for value in run_dir.rglob("*") if value.is_file()):
        if path in excluded:
            continue
        content = path.read_bytes()
        if _JWT.search(content):
            raise RuntimeError(f"evidence contains a JWT-like value: {path}")
        records.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return records


def main() -> int:
    args = _parser().parse_args()
    thresholds = Thresholds.load(args.thresholds)
    if (args.run_dir / "secrets").exists():
        raise SystemExit("Gate C secrets must be removed before evidence finalization")
    stage_summaries = [
        _read(args.run_dir / "stages" / stage.name / "stage-summary.json")
        for stage in thresholds.stages
    ]
    final_stage = thresholds.stages[-1].name
    monitor = _monitor_rows(args.run_dir / "stages" / final_stage / "monitor.jsonl")
    database = _read(args.run_dir / "database-evidence.json")
    security = _read(args.run_dir / "stages" / thresholds.stages[0].name / "security-controls.json")
    host_cpu = [float(row["host_cpu_percent"]) for row in monitor]
    connections = [
        int(row["database"].get("application_connections", row["database"]["connections"]))
        for row in monitor
        if isinstance(row.get("database"), dict)
    ]
    memory_used = [
        int(row["host_memory"]["used"])
        for row in monitor
        if isinstance(row.get("host_memory"), dict)
    ]
    api_memory = _container_values(monitor, "api", "memory_usage_bytes")
    api_fds = _container_values(monitor, "api", "open_file_descriptors")
    api_fd_limits = _container_values(monitor, "api", "file_descriptor_limit")
    pool_checked_out = [_metric_sum(row, "liyans_database_pool_checked_out{") for row in monitor]
    pool_capacity = [_metric_sum(row, "liyans_database_pool_capacity{") for row in monitor]
    pool_timeouts = [
        _metric_sum(row, "liyans_database_pool_acquisition_timeouts_total{") for row in monitor
    ]
    complete_monitor_rows = sum(
        1
        for row in monitor
        if isinstance(row.get("database"), dict)
        and isinstance(row.get("platform_metrics"), dict)
        and any(
            isinstance(item, dict)
            and item.get("service") == "api"
            and isinstance(item.get("open_file_descriptors"), int)
            for item in row.get("containers", [])
            if isinstance(row.get("containers"), list)
        )
    )
    restart_or_oom = 0
    for row in monitor:
        for container in row.get("containers", []):
            if int(container.get("restart_count", 0)) > 0 or container.get("oom_killed") is True:
                restart_or_oom += 1
    connection_limit = int(
        int(thresholds.document["database_connection_budget"])
        * float(thresholds.document["maximum_database_connection_ratio"])
    )
    cpu_breach = _longest_breach(
        monitor,
        lambda row: (
            float(row["host_cpu_percent"]) > float(thresholds.document["maximum_host_cpu_percent"])
        ),
    )
    connection_breach = _longest_breach(
        monitor,
        lambda row: (
            isinstance(row.get("database"), dict)
            and int(row["database"].get("application_connections", row["database"]["connections"]))
            > connection_limit
        ),
    )
    recovery_values = api_memory if len(api_memory) >= 2 else memory_used
    recovery_ratio = (
        recovery_values[-1] / recovery_values[0]
        if len(recovery_values) >= 2 and recovery_values[0]
        else None
    )
    fd_recovery_ratio = api_fds[-1] / api_fds[0] if len(api_fds) >= 2 and api_fds[0] else None
    fd_utilization = (
        max(
            (
                value / limit
                for value, limit in zip(api_fds, api_fd_limits, strict=False)
                if limit > 0
            ),
            default=None,
        )
        if api_fds and api_fd_limits
        else None
    )
    metrics = {
        "stage_passes": {item["stage"]: bool(item["passed"]) for item in stage_summaries},
        "host_cpu_p95_percent": _percentile(host_cpu, 0.95),
        "host_cpu_max_percent": max(host_cpu) if host_cpu else None,
        "host_cpu_breach_seconds": cpu_breach,
        "database_connections_max": max(connections) if connections else None,
        "database_connection_breach_seconds": connection_breach,
        "post_ramp_memory_ratio": round(recovery_ratio, 6) if recovery_ratio is not None else None,
        "api_file_descriptors_max": max(api_fds) if api_fds else None,
        "api_file_descriptor_limit_min": min(api_fd_limits) if api_fd_limits else None,
        "api_file_descriptor_utilization_max": (
            round(fd_utilization, 6) if fd_utilization is not None else None
        ),
        "post_ramp_file_descriptor_ratio": (
            round(fd_recovery_ratio, 6) if fd_recovery_ratio is not None else None
        ),
        "database_pool_checked_out_max": max(pool_checked_out) if pool_checked_out else None,
        "database_pool_capacity_max": max(pool_capacity) if pool_capacity else None,
        "database_pool_acquisition_timeouts_max": max(pool_timeouts) if pool_timeouts else None,
        "complete_monitor_sample_rate": (complete_monitor_rows / len(monitor) if monitor else 0.0),
        "unplanned_restart_or_oom": restart_or_oom,
        "outbox_dead": int(database["outbox_states"].get("DEAD", 0)),
        "outbox_lag_p95_ms": float(database["outbox_lag"]["p95_ms"]),
        "outbox_lag_p99_ms": float(database["outbox_lag"]["p99_ms"]),
        "foreign_tenant_visible": int(database["rls_adversarial_read"]["foreign_tenant_visible"]),
        "invalid_cursor_acceptance": int(security["invalid_cursor_acceptance"]),
    }
    checks = {
        "all_stages": all(metrics["stage_passes"].values()),
        "security_controls": security.get("passed") is True,
        "invalid_cursor": metrics["invalid_cursor_acceptance"]
        <= int(thresholds.document["maximum_invalid_cursor_acceptance"]),
        "outbox_dead": metrics["outbox_dead"] <= int(thresholds.document["maximum_outbox_dead"]),
        "outbox_p95": metrics["outbox_lag_p95_ms"]
        <= float(thresholds.document["outbox_lag_p95_ms"]),
        "outbox_p99": metrics["outbox_lag_p99_ms"]
        <= float(thresholds.document["outbox_lag_p99_ms"]),
        "rls": metrics["foreign_tenant_visible"] == 0,
        "cpu_steady": metrics["host_cpu_p95_percent"] is not None
        and metrics["host_cpu_p95_percent"]
        <= float(thresholds.document["maximum_steady_host_cpu_percent"]),
        "cpu_breach": cpu_breach <= float(thresholds.document["maximum_host_cpu_breach_seconds"]),
        "database_connections": connection_breach
        <= float(thresholds.document["maximum_database_connection_breach_seconds"]),
        "database_pool_observed": metrics["database_pool_capacity_max"] is not None,
        "database_pool_utilization": (
            metrics["database_pool_checked_out_max"] is not None
            and metrics["database_pool_checked_out_max"]
            <= int(thresholds.document["database_connection_budget"])
            * float(thresholds.document["maximum_database_connection_ratio"])
        ),
        "database_pool_timeouts": (
            metrics["database_pool_acquisition_timeouts_max"] is not None
            and metrics["database_pool_acquisition_timeouts_max"]
            <= float(thresholds.document["maximum_database_pool_acquisition_timeouts"])
        ),
        "monitor_completeness": metrics["complete_monitor_sample_rate"]
        >= float(thresholds.document["minimum_monitor_sample_success_rate"]),
        "file_descriptors_observed": (
            metrics["api_file_descriptors_max"] is not None
            and metrics["api_file_descriptor_limit_min"] is not None
        ),
        "file_descriptors_not_exhausted": (
            metrics["api_file_descriptor_utilization_max"] is not None
            and metrics["api_file_descriptor_utilization_max"] < 1.0
        ),
        "memory_recovery": recovery_ratio is not None
        and recovery_ratio <= float(thresholds.document["maximum_post_ramp_memory_ratio"]),
        "restart_or_oom": restart_or_oom
        <= int(thresholds.document["maximum_unplanned_restart_or_oom"]),
    }
    document = {
        "schema_version": "cybercontrol.gate-c-summary.v1",
        "state": "ACCEPTED" if all(checks.values()) else "FAILED",
        "passed": all(checks.values()),
        "single_host_capacity_claim_permitted": False,
        "checks": checks,
        "metrics": metrics,
        "stage_summaries": stage_summaries,
    }
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = args.run_dir / "gate-c-report.md"
    report.write_text(
        "# Phase 7 Gate C Authenticated SSE Result\n\n"
        f"- State: `{document['state']}`\n"
        f"- Single-host production capacity claim permitted: `false`\n"
        f"- Final active connection target: `{thresholds.document['target_active_connections']}`\n"
        f"- Host CPU p95: `{metrics['host_cpu_p95_percent']}`\n"
        f"- Database connection maximum: `{metrics['database_connections_max']}`\n"
        f"- Database pool checked-out maximum: `{metrics['database_pool_checked_out_max']}`\n"
        f"- Database pool acquisition timeouts: "
        f"`{metrics['database_pool_acquisition_timeouts_max']}`\n"
        f"- API file descriptor maximum/utilization: `{metrics['api_file_descriptors_max']}` / "
        f"`{metrics['api_file_descriptor_utilization_max']}`\n"
        f"- Outbox lag p95/p99 ms: `{metrics['outbox_lag_p95_ms']}` / "
        f"`{metrics['outbox_lag_p99_ms']}`\n"
        f"- Cross-tenant visibility: `{metrics['foreign_tenant_visible']}`\n",
        encoding="utf-8",
    )
    manifest_path = args.run_dir / "gate-c-evidence-manifest.json"
    manifest = {
        "schema_version": "cybercontrol.gate-c-evidence-manifest.v1",
        "files": _manifest(args.run_dir, {manifest_path}),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"state": document["state"], "output": str(args.output)}))
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
