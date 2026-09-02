from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOAD_ROOT = ROOT / "tests" / "load"
if str(LOAD_ROOT) not in sys.path:
    sys.path.insert(0, str(LOAD_ROOT))

from gate_c.diagnostic_evidence_package import create_package  # noqa: E402
from gate_c.rss_l1_attribution import compare_measurements  # noqa: E402

PROCESS_VERSION = "Gate-C-12-v1.0"
SOURCE = {
    "source_sha": "a" * 40,
    "source_tree": "b" * 40,
    "product_source_sha": "c" * 40,
    "engineering_baseline_sha": "d" * 40,
    "process_version": PROCESS_VERSION,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _inventory(label: str, payload: int, slack: int) -> dict[str, object]:
    resident_gap = 10
    non_jemalloc = 20
    rss_anon = payload + slack + resident_gap + non_jemalloc
    return {
        "schema_version": "cybercontrol.bounded-memory-inventory.v1",
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "label": label,
        "source": SOURCE,
        "process_memory": {"rss_bytes": rss_anon + 30},
        "cgroup_memory": {"memory_current_bytes": rss_anon + 50},
        "memory_ledger": {
            "rss_anon_bytes": rss_anon,
            "physical_partition": {
                "allocator_payload_bytes": payload,
                "allocator_slack_bytes": slack,
                "allocator_resident_gap_bytes": resident_gap,
                "non_jemalloc_anon_bytes": non_jemalloc,
            },
        },
    }


def _measurement(tmp_path: Path, number: int) -> Path:
    directory = tmp_path / f"measurement-{number}"
    evidence = directory / "runs" / f"run-{number}" / "bounded-memory-inventory"
    _write_json(evidence / "baseline.json", _inventory("baseline", 100, 20))
    _write_json(evidence / "recovery.json", _inventory("recovery", 180, 25))
    package = directory / "evidence.zip"
    manifest = directory / "evidence-manifest.json"
    create_package(
        directory / "runs",
        package,
        manifest,
        run_id=f"run-{number}",
        process_version=PROCESS_VERSION,
    )
    cleanup = directory / "cleanup-receipt.json"
    _write_json(
        cleanup,
        {
            "process_version": PROCESS_VERSION,
            "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
            "zero_containers": True,
            "zero_networks": True,
            "zero_project_volumes": True,
            "postgres_volume_removed": True,
            "next_arm_admission_ready": True,
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
            "run_id": f"run-{number}",
            "arm": "Measurement",
            "source": {
                "source_commit": SOURCE["source_sha"],
                "source_tree": SOURCE["source_tree"],
                "product_source_sha": SOURCE["product_source_sha"],
                "engineering_baseline_sha": SOURCE["engineering_baseline_sha"],
            },
            "evidence_package": {"path": str(package), "sha256": _sha256(package)},
            "evidence_manifest": {"path": str(manifest), "sha256": _sha256(manifest)},
            "cleanup_receipt": {"path": str(cleanup), "sha256": _sha256(cleanup)},
        },
    )
    return reference


def test_l1_attribution_reconciles_and_reproduces_physical_category(tmp_path: Path) -> None:
    result = compare_measurements(
        _measurement(tmp_path, 1),
        _measurement(tmp_path, 2),
    )

    assert result["result"] == "CATEGORY_LOCALIZED"
    assert result["dominant_category"] == "allocator_payload_bytes"
    assert result["next_probe"] == "L2_SAMPLED_PROFILE"
    assert result["owner_admission"] == "NOT_EVALUATED"
    assert result["product_remediation_authorized"] is False
