from __future__ import annotations

import argparse
import hashlib
import json
import os
import tracemalloc
from pathlib import Path
from typing import Any
from uuid import uuid4


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(document: object) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _verified_artifact(root: Path, record: object) -> Path:
    if not isinstance(record, dict):
        raise ValueError("checkpoint manifest contains an invalid file record")
    relative = record.get("path")
    if not isinstance(relative, str) or Path(relative).name != relative:
        raise ValueError("checkpoint manifest contains an unsafe path")
    artifact = root / relative
    if not artifact.is_file():
        raise ValueError(f"checkpoint artifact is missing: {relative}")
    if artifact.stat().st_size != record.get("size_bytes"):
        raise ValueError(f"checkpoint artifact size differs: {relative}")
    if _sha256(artifact) != record.get("sha256"):
        raise ValueError(f"checkpoint artifact digest differs: {relative}")
    return artifact


def _load_manifest(path: Path, expected_label: str) -> tuple[dict[str, Any], dict[str, Path]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("schema_version") != "cybercontrol.memory-checkpoint-manifest.v1"
        or document.get("label") != expected_label
    ):
        raise ValueError(f"{expected_label} checkpoint manifest is invalid")
    files: dict[str, Path] = {}
    for record in document.get("files", []):
        artifact = _verified_artifact(path.parent, record)
        files[artifact.suffix] = artifact
        if artifact.name.endswith(".tracemalloc"):
            files[".tracemalloc"] = artifact
        elif artifact.name.endswith(".proc-maps.txt"):
            files[".proc-maps.txt"] = artifact
        elif artifact.name.endswith(".json"):
            files[".json"] = artifact
    for required in (".tracemalloc", ".proc-maps.txt", ".json"):
        if required not in files:
            raise ValueError(f"checkpoint manifest lacks {required}")
    metadata = json.loads(files[".json"].read_text(encoding="utf-8"))
    if metadata.get("label") != expected_label:
        raise ValueError("checkpoint metadata label differs from its manifest")
    return document, files


def _numeric_delta(baseline: object, recovery: object) -> object:
    if (
        isinstance(baseline, int | float)
        and not isinstance(baseline, bool)
        and isinstance(recovery, int | float)
        and not isinstance(recovery, bool)
    ):
        return recovery - baseline
    if isinstance(baseline, dict) and isinstance(recovery, dict):
        return {
            key: _numeric_delta(baseline[key], recovery[key])
            for key in sorted(set(baseline).intersection(recovery))
        }
    return None


def compare_checkpoints(
    *,
    baseline_manifest_path: Path,
    recovery_manifest_path: Path,
    output_directory: Path,
) -> dict[str, Any]:
    baseline_manifest, baseline_files = _load_manifest(baseline_manifest_path, "baseline")
    recovery_manifest, recovery_files = _load_manifest(recovery_manifest_path, "recovery")
    if baseline_manifest.get("source") != recovery_manifest.get("source"):
        raise ValueError("checkpoint source bindings differ")
    baseline_metadata = json.loads(baseline_files[".json"].read_text(encoding="utf-8"))
    recovery_metadata = json.loads(recovery_files[".json"].read_text(encoding="utf-8"))
    baseline_snapshot = tracemalloc.Snapshot.load(str(baseline_files[".tracemalloc"]))
    recovery_snapshot = tracemalloc.Snapshot.load(str(recovery_files[".tracemalloc"]))
    differences = recovery_snapshot.compare_to(baseline_snapshot, "traceback")
    records: list[dict[str, Any]] = []
    for difference in differences:
        if difference.size_diff == 0 and difference.count_diff == 0:
            continue
        frames = [
            {"filename": frame.filename, "lineno": frame.lineno} for frame in difference.traceback
        ]
        records.append(
            {
                "size_diff_bytes": difference.size_diff,
                "count_diff": difference.count_diff,
                "recovery_size_bytes": difference.size,
                "recovery_count": difference.count,
                "innermost_frame": frames[-1] if frames else None,
                "traceback": frames,
            }
        )
    records.sort(
        key=lambda item: (
            -abs(int(item["size_diff_bytes"])),
            -abs(int(item["count_diff"])),
            json.dumps(item["traceback"], sort_keys=True),
        )
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    traceback_path = output_directory / "tracemalloc-diff.jsonl"
    _atomic_write(
        traceback_path,
        b"".join((json.dumps(record, sort_keys=True) + "\n").encode("utf-8") for record in records),
    )
    summary = {
        "schema_version": "cybercontrol.memory-checkpoint-comparison.v1",
        "process_version": "Gate-C-11-v1.0",
        "source": baseline_manifest["source"],
        "traceback_group_count": len(records),
        "tracemalloc_size_diff_bytes": sum(int(item["size_diff_bytes"]) for item in records),
        "tracemalloc_count_diff": sum(int(item["count_diff"]) for item in records),
        "pre_capture_memory_delta": _numeric_delta(
            baseline_metadata.get("pre_capture_memory", {}),
            recovery_metadata.get("pre_capture_memory", {}),
        ),
        "allocator_delta": _numeric_delta(
            baseline_metadata.get("allocator", {}),
            recovery_metadata.get("allocator", {}),
        ),
        "inventory_delta": _numeric_delta(
            baseline_metadata.get("inventories", {}),
            recovery_metadata.get("inventories", {}),
        ),
        "task_delta": _numeric_delta(
            baseline_metadata.get("tasks", {}),
            recovery_metadata.get("tasks", {}),
        ),
        "artifacts": {"complete_traceback_diff": traceback_path.name},
    }
    summary_path = output_directory / "comparison.json"
    _atomic_write(summary_path, _json_bytes(summary))
    output_manifest = {
        "schema_version": "cybercontrol.memory-checkpoint-comparison-manifest.v1",
        "process_version": "Gate-C-11-v1.0",
        "source": baseline_manifest["source"],
        "files": [
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in (summary_path, traceback_path)
        ],
    }
    _atomic_write(output_directory / "sha256-manifest.json", _json_bytes(output_manifest))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--recovery-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    compare_checkpoints(
        baseline_manifest_path=arguments.baseline_manifest,
        recovery_manifest_path=arguments.recovery_manifest,
        output_directory=arguments.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
