from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from gate_c.config import Thresholds, Workload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize one Gate C load stage.")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _percentile(values: Counter[int], percentile: float) -> int | None:
    total = sum(values.values())
    if total == 0:
        return None
    rank = max(1, math.ceil(total * percentile))
    cumulative = 0
    for value in sorted(values):
        cumulative += values[value]
        if cumulative >= rank:
            return value
    return max(values)


def _active_timeline(paths: list[Path]) -> dict[str, Any]:
    series: list[list[tuple[int, int]]] = []
    for path in paths:
        samples: list[tuple[int, int]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                samples.append(
                    (
                        round(int(row["captured_at_unix_ns"]) / 1_000_000_000),
                        int(row["active_streams"]),
                    )
                )
        if samples:
            series.append(sorted(samples))
    if not series:
        return {"peak": 0, "samples": [], "first_second": None, "last_second": None}
    first = min(items[0][0] for items in series)
    last = max(items[-1][0] for items in series)
    indexes = [0 for _ in series]
    current = [0 for _ in series]
    samples: list[tuple[int, int]] = []
    for second in range(first, last + 1):
        for index, items in enumerate(series):
            while indexes[index] < len(items) and items[indexes[index]][0] <= second:
                current[index] = items[indexes[index]][1]
                indexes[index] += 1
        samples.append((second, sum(current)))
    return {
        "peak": max(value for _, value in samples),
        "samples": samples,
        "first_second": first,
        "last_second": last,
    }


def _longest_at_least(samples: list[tuple[int, int]], minimum: int) -> int:
    longest = 0
    current = 0
    previous: int | None = None
    for second, value in samples:
        if value >= minimum and (previous is None or second == previous + 1):
            current += 1
        elif value >= minimum:
            current = 1
        else:
            current = 0
        longest = max(longest, current)
        previous = second
    return longest


def _outbox_dead_peak(path: Path) -> int:
    maximum = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        database = row.get("database")
        if isinstance(database, dict):
            states = database.get("outbox_states")
            if isinstance(states, dict):
                maximum = max(maximum, int(states.get("DEAD", 0)))
    return maximum


def _distribution(workers: list[dict[str, Any]], field: str) -> Counter[int]:
    values: Counter[int] = Counter()
    for worker in workers:
        document = worker.get(field, {})
        if isinstance(document, dict):
            values.update(
                {int(key): int(value) for key, value in document.get("distribution_ms", {}).items()}
            )
    return values


def _metric_sum(row: dict[str, Any], prefix: str) -> float:
    metrics = row.get("platform_metrics")
    if not isinstance(metrics, dict):
        return 0.0
    return sum(float(value) for key, value in metrics.items() if str(key).startswith(prefix))


def _monitor_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"sample_count": 0, "complete_count": 0, "success_rate": 0.0}
    complete = 0
    for row in rows:
        containers = row.get("containers")
        has_api_fd = isinstance(containers, list) and any(
            item.get("service") == "api" and isinstance(item.get("open_file_descriptors"), int)
            for item in containers
            if isinstance(item, dict)
        )
        if (
            isinstance(row.get("database"), dict)
            and isinstance(row.get("platform_metrics"), dict)
            and isinstance(containers, list)
            and has_api_fd
        ):
            complete += 1
    return {
        "sample_count": len(rows),
        "complete_count": complete,
        "success_rate": complete / len(rows),
    }


def main() -> int:  # noqa: PLR0915 - one stage summary must be assembled atomically.
    args = _parser().parse_args()
    thresholds = Thresholds.load(args.thresholds)
    workload = Workload.load(args.workload)
    stage = thresholds.stage(args.stage)
    worker_paths = sorted(args.stage_dir.glob("worker-result-*.json"))
    if not worker_paths:
        raise SystemExit("Gate C stage has no worker results")
    workers = [_read(path) for path in worker_paths]
    publisher = _read(args.stage_dir / "publisher-result.json")
    runtime_controls = _read(args.stage_dir / "runtime-controls.json")
    counters: Counter[str] = Counter()
    delivery: Counter[int] = Counter()
    clients: list[dict[str, Any]] = []
    for worker in workers:
        counters.update({key: int(value) for key, value in worker["counters"].items()})
        delivery.update(
            {
                int(key): int(value)
                for key, value in worker["delivery_latency_upper_bound"]["distribution_ms"].items()
            }
        )
        clients.extend(worker["clients"].values())
    token_latency = _distribution(workers, "token_acquisition_latency")
    connection_latency = _distribution(workers, "connection_establishment_latency")
    expected_last = {
        tenant_id: int(value) for tenant_id, value in publisher["last_ordinal_by_tenant"].items()
    }
    tenant_counts = Counter(str(client["tenant_id"]) for client in clients)
    principal_counts = Counter(str(client["principal_fingerprint"]) for client in clients)
    slow_consumer_clients = sum(bool(client["slow_consumer"]) for client in clients)
    expected_principals = len(workload.tenant_ids) * workload.principals_per_tenant
    expected_slow_consumers = stage.users * workload.integer("slow_consumer_percent") // 100
    expected_duplicate_clients = stage.users * workload.integer("duplicate_replay_percent") // 100
    committed_loss = 0
    duplicate_rendered = 0
    for client in clients:
        duplicate_rendered += int(client["duplicate_rendered"])
        tenant_last = expected_last.get(str(client["tenant_id"]), -1)
        client_last = client.get("last_ordinal")
        committed_loss += int(client["missing_count"])
        if tenant_last >= 0:
            if client_last is None:
                committed_loss += tenant_last + 1
            else:
                committed_loss += max(0, tenant_last - int(client_last))
    attempts = counters["connection_attempts"]
    successes = counters["connection_successes"]
    reconnect_attempts = counters["reconnect_attempts"]
    timeline = _active_timeline(sorted(args.stage_dir.glob("active-streams-*.jsonl")))
    monitor_rows = [
        json.loads(line)
        for line in (args.stage_dir / "monitor.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    monitor_quality = _monitor_quality(monitor_rows)
    pool_checked_out_peak = max(
        (_metric_sum(row, "liyans_database_pool_checked_out{") for row in monitor_rows),
        default=0.0,
    )
    pool_timeout_peak = max(
        (
            _metric_sum(row, "liyans_database_pool_acquisition_timeouts_total{")
            for row in monitor_rows
        ),
        default=0.0,
    )
    pool_capacity_peak = max(
        (_metric_sum(row, "liyans_database_pool_capacity{") for row in monitor_rows),
        default=0.0,
    )
    minimum_active = math.ceil(
        stage.users * float(thresholds.document["minimum_connection_success_rate"])
    )
    sustained_seconds = _longest_at_least(timeline["samples"], minimum_active)
    metrics = {
        "users": stage.users,
        "client_records": len(clients),
        "connection_success_rate": successes / attempts if attempts else 0,
        "http_5xx_rate": counters["http_5xx"] / attempts if attempts else 0,
        "unexpected_disconnect_rate": (
            counters["unexpected_disconnects"] / successes if successes else 1
        ),
        "reconnect_replay_success_rate": (
            counters["reconnect_successes"] / reconnect_attempts if reconnect_attempts else 1
        ),
        "committed_event_loss": committed_loss,
        "duplicate_final_render": duplicate_rendered,
        "cross_tenant_leakage": counters["cross_tenant_leakage"],
        "delivery_latency_p95_ms": _percentile(delivery, 0.95),
        "delivery_latency_p99_ms": _percentile(delivery, 0.99),
        "token_acquisition_latency_p95_ms": _percentile(token_latency, 0.95),
        "token_acquisition_latency_p99_ms": _percentile(token_latency, 0.99),
        "connection_establishment_latency_p95_ms": _percentile(connection_latency, 0.95),
        "connection_establishment_latency_p99_ms": _percentile(connection_latency, 0.99),
        "active_stream_peak": timeline["peak"],
        "active_stream_sustained_seconds": sustained_seconds,
        "publisher_failures": int(publisher["counters"]["publish_failures"]),
        "workflow_failures": int(publisher["counters"]["workflow_failures"]),
        "token_acquisition_failures": counters["token_acquisition_failures"],
        "tenant_client_counts": dict(sorted(tenant_counts.items())),
        "unique_principals": len(principal_counts),
        "slow_consumer_clients": slow_consumer_clients,
        "duplicate_replay_clients": sum(
            bool(client.get("duplicate_replay_client")) for client in clients
        ),
        "duplicate_replay_attempts": counters["duplicate_replay_attempts"],
        "duplicate_replay_suppressions": counters["duplicate_replay_suppressions"],
        "planned_disconnects": counters["planned_disconnects"],
        "token_initial_acquisitions": counters["token_initial_acquisitions"],
        "token_refreshes": counters["token_refreshes"],
        "expired_token_probe_attempts": int(
            publisher["counters"].get("expired_token_probe_attempts", 0)
        ),
        "expired_token_probe_rejections": int(
            publisher["counters"].get("expired_token_probe_rejections", 0)
        ),
        "expired_token_probe_unexpected_acceptances": int(
            publisher["counters"].get("expired_token_probe_unexpected_acceptances", 0)
        ),
        "expired_token_probe_failures": int(
            publisher["counters"].get("expired_token_probe_failures", 0)
        ),
        "database_pool_checked_out_peak": round(pool_checked_out_peak, 3),
        "database_pool_capacity": round(pool_capacity_peak, 3),
        "database_pool_acquisition_timeout_peak": round(pool_timeout_peak, 3),
        "database_pool_acquisition_timeout_log_count": int(
            runtime_controls.get("database_pool_acquisition_timeout_count", 0)
        ),
        "monitor_quality": monitor_quality,
        "outbox_dead_peak": _outbox_dead_peak(args.stage_dir / "monitor.jsonl"),
    }
    tenant_distribution = (
        set(tenant_counts) == set(workload.tenant_ids)
        and max(tenant_counts.values(), default=0) - min(tenant_counts.values(), default=0) <= 1
    )
    principal_distribution = (
        len(principal_counts) == min(stage.users, expected_principals)
        and max(principal_counts.values(), default=0) - min(principal_counts.values(), default=0)
        <= 1
    )
    checks = {
        "client_count": len(clients) == stage.users,
        "tenant_distribution": tenant_distribution,
        "principal_distribution": principal_distribution,
        "slow_consumer_population": slow_consumer_clients == expected_slow_consumers,
        "duplicate_replay_population": metrics["duplicate_replay_clients"]
        == expected_duplicate_clients,
        "planned_disconnect_population": metrics["planned_disconnects"] >= stage.users,
        "duplicate_replay_attempts": metrics["duplicate_replay_attempts"]
        == expected_duplicate_clients,
        "duplicate_replay_suppression": metrics["duplicate_replay_suppressions"]
        == expected_duplicate_clients,
        "peak_active": timeline["peak"] >= stage.users,
        "sustain": sustained_seconds >= stage.sustain_seconds,
        "connection_success": metrics["connection_success_rate"]
        >= float(thresholds.document["minimum_connection_success_rate"]),
        "http_5xx": metrics["http_5xx_rate"] <= float(thresholds.document["maximum_http_5xx_rate"]),
        "unexpected_disconnect": metrics["unexpected_disconnect_rate"]
        <= float(thresholds.document["maximum_unexpected_disconnect_rate"]),
        "reconnect": metrics["reconnect_replay_success_rate"]
        >= float(thresholds.document["minimum_reconnect_replay_success_rate"]),
        "event_loss": committed_loss <= int(thresholds.document["maximum_committed_event_loss"]),
        "duplicate_render": duplicate_rendered
        <= int(thresholds.document["maximum_duplicate_final_render"]),
        "tenant_isolation": counters["cross_tenant_leakage"]
        <= int(thresholds.document["maximum_cross_tenant_leakage"]),
        "delivery_p95": metrics["delivery_latency_p95_ms"] is not None
        and metrics["delivery_latency_p95_ms"]
        <= int(thresholds.document["delivery_latency_p95_ms"]),
        "delivery_p99": metrics["delivery_latency_p99_ms"] is not None
        and metrics["delivery_latency_p99_ms"]
        <= int(thresholds.document["delivery_latency_p99_ms"]),
        "publisher": metrics["publisher_failures"] == 0,
        "workflow": int(publisher["counters"]["workflow_successes"]) > 0
        and metrics["workflow_failures"] == 0,
        "token_acquisition": metrics["token_acquisition_failures"] == 0,
        "token_latency_observed": metrics["token_acquisition_latency_p95_ms"] is not None,
        "connection_latency_observed": (
            metrics["connection_establishment_latency_p95_ms"] is not None
        ),
        "monitor_quality": monitor_quality["success_rate"]
        >= float(thresholds.document["minimum_monitor_sample_success_rate"]),
        "database_pool_capacity_observed": metrics["database_pool_capacity"] > 0,
        "database_pool_utilization": (
            metrics["database_pool_checked_out_peak"]
            <= float(thresholds.document["database_connection_budget"])
            * float(thresholds.document["maximum_database_connection_ratio"])
        ),
        "database_pool_timeout_metric": metrics["database_pool_acquisition_timeout_peak"]
        <= float(thresholds.document["maximum_database_pool_acquisition_timeouts"]),
        "database_pool_timeout_log": metrics["database_pool_acquisition_timeout_log_count"]
        <= int(thresholds.document["maximum_database_pool_acquisition_timeouts"]),
        "expired_token_probe": (
            stage.name != thresholds.stages[-1].name
            or (
                metrics["expired_token_probe_attempts"] >= 1
                and metrics["expired_token_probe_rejections"]
                == metrics["expired_token_probe_attempts"]
                and metrics["expired_token_probe_unexpected_acceptances"] == 0
                and metrics["expired_token_probe_failures"] == 0
            )
        ),
        "token_refresh": (
            stage.name != thresholds.stages[-1].name or metrics["token_refreshes"] > 0
        ),
        "outbox_dead": metrics["outbox_dead_peak"]
        <= int(thresholds.document["maximum_outbox_dead"]),
    }
    document = {
        "schema_version": "cybercontrol.gate-c-stage-summary.v1",
        "stage": args.stage,
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "worker_files": [path.name for path in worker_paths],
    }
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"stage": args.stage, "passed": document["passed"]}, sort_keys=True))
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
