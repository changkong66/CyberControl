from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from gate_c.diagnostic_evidence_package import verify_package

PROCESS_VERSION = "Gate-C-12-v1.0"
KINDS = {
    "calibration": "cybercontrol.gate-c-rss-calibration-comparison.v1",
    "l1": "cybercontrol.gate-c-rss-l1-calibration-comparison.v1",
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
        raise ValueError(f"sequence reference lacks {name}")
    raw_path = record.get("path")
    digest = record.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(digest, str):
        raise ValueError(f"sequence reference has an invalid {name} record")
    unresolved = Path(raw_path)
    if not unresolved.is_absolute():
        raise ValueError(f"sequence {name} path must be absolute")
    path = unresolved.resolve(strict=True)
    if not path.is_file() or _sha256(path) != digest:
        raise ValueError(f"sequence {name} failed its SHA256 binding")
    return path


def _read_sequence(reference_path: Path, kind: str) -> dict[str, Any]:
    reference_path = reference_path.resolve(strict=True)
    reference = _read_json(reference_path)
    if (
        reference.get("schema_version") != "cybercontrol.gate-c-diagnostic-package-reference.v1"
        or reference.get("process_version") != PROCESS_VERSION
        or reference.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
        or reference.get("formal_gate_attempt") is not False
        or reference.get("acceptance_claim") is not False
    ):
        raise ValueError("sequence reference is not an admissible non-acceptance diagnostic")

    package_path = _artifact(reference, "evidence_package")
    manifest_path = _artifact(reference, "evidence_manifest")
    cleanup_path = _artifact(reference, "cleanup_receipt")
    summary_path = _artifact(reference, "run_summary")
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema_version") != "cybercontrol.gate-c-diagnostic-evidence-manifest.v1"
        or manifest.get("process_version") != PROCESS_VERSION
        or manifest.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
        or manifest.get("formal_gate_attempt") is not False
        or manifest.get("acceptance_claim") is not False
        or manifest.get("run_id") != reference.get("run_id")
    ):
        raise ValueError("sequence evidence manifest binding is invalid")
    verify_package(package_path, manifest)
    cleanup = _read_json(cleanup_path)
    if (
        cleanup.get("process_version") != PROCESS_VERSION
        or cleanup.get("archived_intermediates_removed") is not True
    ):
        raise ValueError("sequence cleanup is incomplete")

    summary = _read_json(summary_path)
    if (
        summary.get("schema_version") != KINDS[kind]
        or summary.get("process_version") != PROCESS_VERSION
        or summary.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
        or summary.get("formal_gate_attempt") is not False
        or summary.get("acceptance_claim") is not False
        or summary.get("passed") is not True
    ):
        raise ValueError("sequence summary did not pass the interference gate")

    with zipfile.ZipFile(package_path) as archive:
        index_name = "arm-package-index.json"
        if index_name not in archive.namelist():
            raise ValueError("sequence package lacks its arm package index")
        arm_index = json.loads(archive.read(index_name))
    arms = arm_index.get("arms")
    if not isinstance(arms, dict) or set(arms) != {"A", "Measurement", "APrime"}:
        raise ValueError("sequence package has an incomplete arm index")
    for arm, record in arms.items():
        if (
            not isinstance(record, dict)
            or record.get("classification") != "NON_ACCEPTANCE_DIAGNOSTIC"
            or record.get("eligible_for_continuation") is not True
            or int(record.get("process_exit_code", -1)) != 0
        ):
            raise ValueError(f"sequence arm {arm} is not admissible")
        cleanup_key = "cleanup_receipt_path"
        cleanup_digest_key = "cleanup_receipt_sha256"
        raw_cleanup_path = record.get(cleanup_key)
        if not isinstance(raw_cleanup_path, str) or not Path(raw_cleanup_path).is_absolute():
            raise ValueError(f"sequence arm {arm} cleanup path must be absolute")
        arm_cleanup_path = Path(raw_cleanup_path).resolve(strict=True)
        if _sha256(arm_cleanup_path) != record.get(cleanup_digest_key):
            raise ValueError(f"sequence arm {arm} cleanup receipt failed verification")
        arm_cleanup = _read_json(arm_cleanup_path)
        if (
            arm_cleanup.get("process_version") != PROCESS_VERSION
            or arm_cleanup.get("zero_containers") is not True
            or arm_cleanup.get("zero_networks") is not True
            or arm_cleanup.get("zero_project_volumes") is not True
            or arm_cleanup.get("postgres_volume_removed") is not True
            or arm_cleanup.get("next_arm_admission_ready") is not True
        ):
            raise ValueError(f"sequence arm {arm} did not clean its isolated resources")

    return {
        "reference_path": str(reference_path),
        "reference_sha256": _sha256(reference_path),
        "run_id": reference["run_id"],
        "package_sha256": reference["evidence_package"]["sha256"],
        "summary_sha256": reference["run_summary"]["sha256"],
        "summary": summary,
        "arm_run_ids": summary["run_ids"],
    }


def compare_reproductions(
    *, kind: str, first_reference: Path, second_reference: Path
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError("reproduction kind is invalid")
    first = _read_sequence(first_reference, kind)
    second = _read_sequence(second_reference, kind)
    if first["run_id"] == second["run_id"]:
        raise ValueError("independent reproductions require distinct sequence IDs")
    if first["package_sha256"] == second["package_sha256"]:
        raise ValueError("independent reproductions require distinct evidence packages")
    first_arm_ids = set(first["arm_run_ids"].values())
    second_arm_ids = set(second["arm_run_ids"].values())
    if len(first_arm_ids) != 3 or len(second_arm_ids) != 3 or first_arm_ids & second_arm_ids:
        raise ValueError("independent reproductions require six distinct arm runs")
    if first["summary"].get("source") != second["summary"].get("source"):
        raise ValueError("reproductions do not bind the same source and image receipt")
    if kind == "calibration" and first["summary"].get("variable") != second["summary"].get(
        "variable"
    ):
        raise ValueError("calibration reproductions do not test the same variable")

    result: dict[str, Any] = {
        "schema_version": "cybercontrol.gate-c-rss-calibration-reproduction.v1",
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "kind": kind,
        "source": first["summary"]["source"],
        "independent_sequence_count": 2,
        "distinct_arm_run_count": 6,
        "sequences": [
            {name: value for name, value in sequence.items() if name != "summary"}
            for sequence in (first, second)
        ],
        "passed": True,
    }
    if kind == "calibration":
        result["variable"] = first["summary"]["variable"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify two independent ADR-0032 A/M/A' sequences."
    )
    parser.add_argument("--kind", choices=sorted(KINDS), required=True)
    parser.add_argument("--first-reference", type=Path, required=True)
    parser.add_argument("--second-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = compare_reproductions(
        kind=arguments.kind,
        first_reference=arguments.first_reference,
        second_reference=arguments.second_reference,
    )
    with arguments.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
