from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOAD_ROOT = ROOT / "tests" / "load"
if str(LOAD_ROOT) not in sys.path:
    sys.path.insert(0, str(LOAD_ROOT))

from gate_c.diagnostic_evidence_package import create_package  # noqa: E402
from gate_c.rss_reproduction_compare import compare_reproductions  # noqa: E402

PROCESS_VERSION = "Gate-C-12-v1.0"
SOURCE = {
    "source_commit": "a" * 40,
    "source_tree": "b" * 40,
    "product_source_sha": "c" * 40,
    "engineering_baseline_sha": "d" * 40,
    "image_lock_sha256": "e" * 64,
    "build_receipt_sha256": "f" * 64,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _sequence(tmp_path: Path, number: int, *, kind: str = "l1") -> Path:
    directory = tmp_path / f"sequence-{number}"
    evidence = directory / "evidence"
    evidence.mkdir(parents=True)
    arms: dict[str, object] = {}
    run_ids: dict[str, str] = {}
    for arm in ("A", "Measurement", "APrime"):
        run_id = f"sequence-{number}-{arm}"
        run_ids[arm] = run_id
        cleanup = directory / "arms" / run_id / "cleanup-receipt.json"
        _write_json(
            cleanup,
            {
                "process_version": PROCESS_VERSION,
                "zero_containers": True,
                "zero_networks": True,
                "zero_project_volumes": True,
                "postgres_volume_removed": True,
                "next_arm_admission_ready": True,
            },
        )
        arms[arm] = {
            "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
            "eligible_for_continuation": True,
            "process_exit_code": 0,
            "cleanup_receipt_path": str(cleanup),
            "cleanup_receipt_sha256": _sha256(cleanup),
        }
    _write_json(
        evidence / "arm-package-index.json",
        {
            "process_version": PROCESS_VERSION,
            "sequence_id": f"sequence-{number}",
            "arms": arms,
        },
    )
    package = directory / "evidence.zip"
    manifest = directory / "evidence-manifest.json"
    create_package(evidence, package, manifest, run_id=f"sequence-{number}")
    summary = directory / "run-summary.json"
    schema = (
        "cybercontrol.gate-c-rss-l1-calibration-comparison.v1"
        if kind == "l1"
        else "cybercontrol.gate-c-rss-calibration-comparison.v1"
    )
    value = {
        "schema_version": schema,
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "source": SOURCE,
        "run_ids": run_ids,
        "passed": True,
    }
    if kind == "calibration":
        value["variable"] = "S"
    _write_json(summary, value)
    cleanup = directory / "cleanup-receipt.json"
    _write_json(
        cleanup,
        {
            "process_version": PROCESS_VERSION,
            "archived_intermediates_removed": True,
        },
    )
    reference = directory / "package-reference.json"
    _write_json(
        reference,
        {
            "schema_version": "cybercontrol.gate-c-diagnostic-package-reference.v1",
            "process_version": PROCESS_VERSION,
            "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
            "formal_gate_attempt": False,
            "acceptance_claim": False,
            "run_id": f"sequence-{number}",
            "evidence_package": {"path": str(package), "sha256": _sha256(package)},
            "evidence_manifest": {"path": str(manifest), "sha256": _sha256(manifest)},
            "cleanup_receipt": {"path": str(cleanup), "sha256": _sha256(cleanup)},
            "run_summary": {"path": str(summary), "sha256": _sha256(summary)},
        },
    )
    return reference


@pytest.mark.parametrize("kind", ["calibration", "l1"])
def test_reproduction_requires_two_verified_disjoint_sequences(tmp_path: Path, kind: str) -> None:
    first = _sequence(tmp_path, 1, kind=kind)
    second = _sequence(tmp_path, 2, kind=kind)

    result = compare_reproductions(kind=kind, first_reference=first, second_reference=second)

    assert result["passed"] is True
    assert result["independent_sequence_count"] == 2
    assert result["distinct_arm_run_count"] == 6


def test_reproduction_rejects_reused_sequence(tmp_path: Path) -> None:
    reference = _sequence(tmp_path, 1)

    with pytest.raises(ValueError, match="distinct sequence IDs"):
        compare_reproductions(kind="l1", first_reference=reference, second_reference=reference)
