from __future__ import annotations

import hashlib
import json
import sys
import tracemalloc
from pathlib import Path

LOAD_ROOT = Path(__file__).resolve().parents[2] / "tests" / "load"
if str(LOAD_ROOT) not in sys.path:
    sys.path.insert(0, str(LOAD_ROOT))

from gate_c.memory_checkpoint_compare import compare_checkpoints  # noqa: E402

SOURCE = {
    "source_sha": "a" * 40,
    "source_tree": "b" * 40,
    "product_source_sha": "c" * 40,
    "engineering_baseline_sha": "d" * 40,
    "process_version": "Gate-C-12-v1.0",
}


def _checkpoint(directory: Path, label: str, snapshot: tracemalloc.Snapshot) -> Path:
    snapshot_path = directory / f"{label}.tracemalloc"
    snapshot.dump(str(snapshot_path))
    maps_path = directory / f"{label}.proc-maps.txt"
    maps_path.write_text("1000-2000 rw-p 00000000 00:00 0\n", encoding="utf-8")
    metadata_path = directory / f"{label}.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": "cybercontrol.memory-checkpoint.v1",
                "label": label,
                "pre_capture_memory": {"vmrss_bytes": 100 if label == "baseline" else 200},
                "allocator": {"summary": {"allocated": 10 if label == "baseline" else 30}},
                "inventories": {"sse": {"subscribers": 0}},
                "tasks": {"total": 1},
            }
        ),
        encoding="utf-8",
    )
    artifacts = (metadata_path, maps_path, snapshot_path)
    manifest_path = directory / f"{label}.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "cybercontrol.memory-checkpoint-manifest.v1",
                "label": label,
                "source": SOURCE,
                "files": [
                    {
                        "path": path.name,
                        "size_bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in artifacts
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_offline_comparator_retains_complete_tracebacks_and_verifies_hashes(
    tmp_path: Path,
) -> None:
    if not tracemalloc.is_tracing():
        tracemalloc.start(8)
    baseline = _checkpoint(tmp_path, "baseline", tracemalloc.take_snapshot())
    retained = [bytearray(2048) for _ in range(64)]
    recovery = _checkpoint(tmp_path, "recovery", tracemalloc.take_snapshot())
    output = tmp_path / "comparison"

    summary = compare_checkpoints(
        baseline_manifest_path=baseline,
        recovery_manifest_path=recovery,
        output_directory=output,
    )

    assert retained
    assert summary["traceback_group_count"] > 0
    assert summary["pre_capture_memory_delta"]["vmrss_bytes"] == 100
    assert summary["allocator_delta"]["summary"]["allocated"] == 20
    records = [
        json.loads(line)
        for line in (output / "tracemalloc-diff.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        any(
            frame["filename"].endswith("test_memory_checkpoint_compare.py")
            for frame in row["traceback"]
        )
        for row in records
    )
    manifest = json.loads((output / "sha256-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 2

    baseline_document = json.loads(baseline.read_text(encoding="utf-8"))
    baseline_document["files"][0]["sha256"] = "0" * 64
    baseline.write_text(json.dumps(baseline_document), encoding="utf-8")
    try:
        compare_checkpoints(
            baseline_manifest_path=baseline,
            recovery_manifest_path=recovery,
            output_directory=tmp_path / "rejected",
        )
    except ValueError as exc:
        assert "digest differs" in str(exc)
    else:
        raise AssertionError("tampered checkpoint manifest was accepted")
