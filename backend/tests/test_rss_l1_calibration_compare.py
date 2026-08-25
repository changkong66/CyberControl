from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOAD_ROOT = ROOT / "tests" / "load"
if str(LOAD_ROOT) not in sys.path:
    sys.path.insert(0, str(LOAD_ROOT))

from gate_c.rss_l1_calibration_compare import (  # noqa: E402
    TERMINAL_SSE_FIELDS,
    ZERO_TOLERANCE_CHECKS,
    compare_l1_arms,
    read_arm,
)

SOURCE = {
    "source_commit": "a" * 40,
    "source_tree": "b" * 40,
    "product_source_sha": "c" * 40,
    "engineering_baseline_sha": "d" * 40,
    "image_lock_sha256": "e" * 64,
    "build_receipt_sha256": "f" * 64,
}


def _arm(name: str, multiplier: float = 1.0) -> dict[str, object]:
    return {
        "arm": name,
        "run_id": f"run-{name}",
        "source": SOURCE,
        "monitor_completeness": 1.0,
        "connection_p95_ms": 10 * multiplier,
        "delivery_p95_ms": 2 * multiplier,
        "api_cpu_p95": 20 * multiplier,
        "event_loop_lag_p95_ms": 1 * multiplier,
        "baseline_rss_bytes": 100 * 1024 * 1024,
        "recovery_rss_bytes": round((110 + multiplier - 1) * 1024 * 1024),
        "terminal_owners_zero": True,
    }


def test_l1_comparator_applies_fixed_interference_formulas() -> None:
    result = compare_l1_arms(_arm("A"), _arm("Measurement", 1.05), _arm("APrime"))

    assert result["passed"] is True
    assert result["metrics"]["api_cpu_p95"]["measurement_to_control_ratio"] == 1.05
    assert result["rss"]["limit_bytes"] == 8 * 1024 * 1024


def test_l1_comparator_rejects_control_drift_and_source_mismatch() -> None:
    result = compare_l1_arms(_arm("A"), _arm("Measurement"), _arm("APrime", 1.5))
    assert result["passed"] is False

    wrong = _arm("APrime")
    wrong["source"] = {**SOURCE, "source_commit": "0" * 40}
    with pytest.raises(ValueError, match="same source"):
        compare_l1_arms(_arm("A"), _arm("Measurement"), wrong)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _monitor_row(*, rss_bytes: int = 100 * 1024 * 1024) -> dict[str, object]:
    return {
        "containers": [
            {
                "service": "api",
                "cpu_percent_one_core_units": 20.0,
                "oom_killed": False,
                "restart_count": 0,
                "process_memory": {"rss_bytes": rss_bytes},
            }
        ],
        "platform_metrics": {"liyans_event_loop_heartbeat_lag_seconds": 0.001},
    }


def _write_arm_fixture(tmp_path: Path, arm: str) -> Path:
    run_directory = tmp_path / arm
    metadata = {
        "process_version": "Gate-C-12-v1.0",
        "mode": "DiagnosticStages",
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "bounded_memory_inventory_arm": arm,
        "diagnostic_stage_names": ["ramp-200"],
        "diagnostic_idle_seconds": 300,
        "diagnostic_recovery_seconds": 600,
        "run_id": f"run-{arm}",
        **SOURCE,
    }
    _write_json(run_directory / "execution-metadata.json", metadata)
    _write_json(
        run_directory / "stages" / "ramp-200" / "stage-summary.json",
        {
            "schema_version": "cybercontrol.gate-c-stage-summary.v1",
            "checks": {name: True for name in ZERO_TOLERANCE_CHECKS},
            "metrics": {
                "monitor_quality": {"success_rate": 1.0},
                "connection_establishment_latency_p95_ms": 10.0,
                "delivery_latency_p95_ms": 2.0,
            },
        },
    )
    _write_json(
        run_directory / "stages" / "ramp-200" / "security-controls.json",
        {"passed": True, "invalid_cursor_acceptance": 0},
    )
    _write_json(
        run_directory / "stages" / "ramp-200" / "runtime-controls.json",
        {"passed": True, "bad_address_count": 0},
    )
    baseline_rows = "\n".join(json.dumps(_monitor_row()) for _ in range(12)) + "\n"
    recovery_rows = (
        "\n".join(json.dumps(_monitor_row(rss_bytes=110 * 1024 * 1024)) for _ in range(12)) + "\n"
    )
    baseline_path = run_directory / "diagnostic-baseline" / "monitor.jsonl"
    stage_path = run_directory / "stages" / "ramp-200" / "monitor.jsonl"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(baseline_rows, encoding="utf-8")
    stage_path.write_text(recovery_rows, encoding="utf-8")
    if arm == "Measurement":
        _write_json(
            run_directory / "bounded-memory-inventory" / "recovery.json",
            {
                "ownership_overlays_not_additive": {
                    "sse": {name: 0 for name in TERMINAL_SSE_FIELDS},
                    "platform": {"database_pools": {"runtime": {"checked_out": 0}}},
                }
            },
        )
    return run_directory


def test_read_arm_validates_fixture_and_all_terminal_replay_owners(tmp_path: Path) -> None:
    run_directory = _write_arm_fixture(tmp_path, "Measurement")

    result = read_arm(run_directory, "Measurement")

    assert result["terminal_owners_zero"] is True
    recovery_path = run_directory / "bounded-memory-inventory" / "recovery.json"
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    recovery["ownership_overlays_not_additive"]["sse"]["replay_cache_bytes"] = 1
    recovery_path.write_text(json.dumps(recovery), encoding="utf-8")
    with pytest.raises(ValueError, match="terminal owner"):
        read_arm(run_directory, "Measurement")
