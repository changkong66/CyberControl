from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from gate_c.diagnostic_evidence_package import verify_package

PROCESS_VERSION = "Gate-C-12-v1.0"
PHYSICAL_COMPONENTS = (
    "allocator_payload_bytes",
    "allocator_slack_bytes",
    "allocator_resident_gap_bytes",
    "non_jemalloc_anon_bytes",
)
NEXT_PROBES = {
    "allocator_payload_bytes": "L2_SAMPLED_PROFILE",
    "allocator_slack_bytes": "ALLOCATOR_HIGH_WATER_REVIEW",
    "allocator_resident_gap_bytes": "ALLOCATOR_HIGH_WATER_REVIEW",
    "non_jemalloc_anon_bytes": "L0_MAPPING_REVIEW",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _artifact(reference: dict[str, Any], name: str) -> Path:
    record = reference.get(name)
    if not isinstance(record, dict):
        raise ValueError(f"measurement reference lacks {name}")
    raw_path = record.get("path")
    digest = record.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(digest, str):
        raise ValueError(f"measurement reference has an invalid {name} record")
    unresolved = Path(raw_path)
    if not unresolved.is_absolute():
        raise ValueError(f"measurement {name} path must be absolute")
    path = unresolved.resolve(strict=True)
    if not path.is_file() or _sha256(path) != digest:
        raise ValueError(f"measurement {name} failed its SHA256 binding")
    return path


def _archive_json(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"measurement package must contain exactly one {suffix}")
    value = json.loads(archive.read(matches[0]))
    if not isinstance(value, dict):
        raise ValueError(f"measurement package {suffix} is not a JSON object")
    return value


def _validate_inventory(inventory: dict[str, Any], label: str) -> None:
    ledger = inventory.get("memory_ledger")
    process = inventory.get("process_memory")
    cgroup = inventory.get("cgroup_memory")
    if (
        inventory.get("schema_version") != "cybercontrol.bounded-memory-inventory.v1"
        or inventory.get("process_version") != PROCESS_VERSION
        or inventory.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
        or inventory.get("label") != label
        or not isinstance(ledger, dict)
        or not isinstance(process, dict)
        or not isinstance(cgroup, dict)
    ):
        raise ValueError(f"{label} bounded inventory metadata is invalid")
    partition = ledger.get("physical_partition")
    rss_anon = ledger.get("rss_anon_bytes")
    if not isinstance(partition, dict) or not isinstance(rss_anon, int) or rss_anon <= 0:
        raise ValueError(f"{label} physical memory ledger is invalid")
    values = [partition.get(name) for name in PHYSICAL_COMPONENTS]
    if any(not isinstance(value, int) or value < 0 for value in values):
        raise ValueError(f"{label} physical memory partition is negative or incomplete")
    if sum(values) != rss_anon:
        raise ValueError(f"{label} physical memory partition does not reconcile")


def read_measurement(reference_path: Path) -> dict[str, Any]:
    reference_path = reference_path.resolve(strict=True)
    reference = _read_json(reference_path)
    if (
        reference.get("schema_version") != "cybercontrol.gate-c-diagnostic-package-reference.v1"
        or reference.get("process_version") != PROCESS_VERSION
        or reference.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
        or reference.get("formal_gate_attempt") is not False
        or reference.get("acceptance_claim") is not False
        or reference.get("arm") != "Measurement"
    ):
        raise ValueError("L1 measurement reference is not admissible")
    package_path = _artifact(reference, "evidence_package")
    manifest_path = _artifact(reference, "evidence_manifest")
    cleanup_path = _artifact(reference, "cleanup_receipt")
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema_version") != "cybercontrol.gate-c-diagnostic-evidence-manifest.v1"
        or manifest.get("process_version") != PROCESS_VERSION
        or manifest.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
        or manifest.get("formal_gate_attempt") is not False
        or manifest.get("acceptance_claim") is not False
        or manifest.get("run_id") != reference.get("run_id")
    ):
        raise ValueError("L1 measurement manifest binding is invalid")
    verify_package(package_path, manifest)
    cleanup = _read_json(cleanup_path)
    if (
        cleanup.get("process_version") != PROCESS_VERSION
        or cleanup.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
        or cleanup.get("zero_containers") is not True
        or cleanup.get("zero_networks") is not True
        or cleanup.get("zero_project_volumes") is not True
        or cleanup.get("postgres_volume_removed") is not True
        or cleanup.get("next_arm_admission_ready") is not True
    ):
        raise ValueError("L1 measurement cleanup is incomplete")
    with zipfile.ZipFile(package_path) as archive:
        baseline = _archive_json(archive, "/bounded-memory-inventory/baseline.json")
        recovery = _archive_json(archive, "/bounded-memory-inventory/recovery.json")
    _validate_inventory(baseline, "baseline")
    _validate_inventory(recovery, "recovery")
    if baseline.get("source") != recovery.get("source"):
        raise ValueError("L1 baseline and recovery source bindings differ")
    source = baseline["source"]
    reference_source = reference.get("source")
    if (
        not isinstance(reference_source, dict)
        or source.get("source_sha") != reference_source.get("source_commit")
        or source.get("source_tree") != reference_source.get("source_tree")
        or source.get("product_source_sha") != reference_source.get("product_source_sha")
        or source.get("engineering_baseline_sha")
        != reference_source.get("engineering_baseline_sha")
    ):
        raise ValueError("L1 inventory does not bind the Measurement package source")

    baseline_ledger = baseline["memory_ledger"]
    recovery_ledger = recovery["memory_ledger"]
    baseline_partition = baseline_ledger["physical_partition"]
    recovery_partition = recovery_ledger["physical_partition"]
    deltas = {
        name: int(recovery_partition[name]) - int(baseline_partition[name])
        for name in PHYSICAL_COMPONENTS
    }
    rss_anon_delta = int(recovery_ledger["rss_anon_bytes"]) - int(baseline_ledger["rss_anon_bytes"])
    if sum(deltas.values()) != rss_anon_delta:
        raise ValueError("L1 recovery delta does not reconcile to RssAnon")
    positive = {name: value for name, value in deltas.items() if value > 0}
    dominant = max(positive, key=positive.get) if positive else None
    dominant_ratio = (
        float(positive[dominant]) / rss_anon_delta
        if dominant is not None and rss_anon_delta > 0
        else 0.0
    )
    return {
        "reference_path": str(reference_path),
        "reference_sha256": _sha256(reference_path),
        "run_id": reference["run_id"],
        "source": source,
        "rss_anon_delta_bytes": rss_anon_delta,
        "api_rss_delta_bytes": int(recovery["process_memory"]["rss_bytes"])
        - int(baseline["process_memory"]["rss_bytes"]),
        "cgroup_current_delta_bytes": int(recovery["cgroup_memory"]["memory_current_bytes"])
        - int(baseline["cgroup_memory"]["memory_current_bytes"]),
        "physical_component_deltas_bytes": deltas,
        "physically_reconciled_bytes": rss_anon_delta,
        "physical_unknown_bytes": 0,
        "dominant_category": dominant,
        "dominant_category_ratio": dominant_ratio,
    }


def compare_measurements(first_reference: Path, second_reference: Path) -> dict[str, Any]:
    first = read_measurement(first_reference)
    second = read_measurement(second_reference)
    if first["run_id"] == second["run_id"]:
        raise ValueError("L1 attribution requires two distinct Measurement runs")
    if first["source"] != second["source"]:
        raise ValueError("L1 attribution runs do not bind the same source and image receipt")
    categories = {first["dominant_category"], second["dominant_category"]}
    category_reproduced = len(categories) == 1 and None not in categories
    dominant_category = first["dominant_category"] if category_reproduced else None
    minimum_ratio = min(
        float(first["dominant_category_ratio"]),
        float(second["dominant_category_ratio"]),
    )
    localized = category_reproduced and minimum_ratio >= 0.50
    return {
        "schema_version": "cybercontrol.gate-c-rss-l1-attribution.v1",
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "product_remediation_authorized": False,
        "source": first["source"],
        "independent_measurement_count": 2,
        "measurements": [first, second],
        "category_reproduced": category_reproduced,
        "dominant_category": dominant_category,
        "minimum_dominant_category_ratio": minimum_ratio,
        "result": "CATEGORY_LOCALIZED" if localized else "CATEGORY_UNRESOLVED",
        "next_probe": NEXT_PROBES.get(dominant_category) if localized else "REPEAT_L0_L1_REVIEW",
        "owner_admission": "NOT_EVALUATED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile two ADR-0032 L1 Measurement packages.")
    parser.add_argument("--first-reference", type=Path, required=True)
    parser.add_argument("--second-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = compare_measurements(arguments.first_reference, arguments.second_reference)
    with arguments.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
