from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import gate_c_image_lock  # noqa: E402


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lock_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    receipt_path = tmp_path / "build-receipt.json"
    _write_json(
        receipt_path,
        {
            "schema_version": gate_c_image_lock.BUILD_RECEIPT_SCHEMA,
            "reproducible": True,
        },
    )
    lock = {
        "schema_version": gate_c_image_lock.IMAGE_LOCK_SCHEMA,
        "process_version": gate_c_image_lock.PROCESS_VERSION,
        "source": {"commit": "a" * 40, "tree": "b" * 40},
        "build_receipt": {"path": receipt_path.name, "sha256": _digest(receipt_path)},
        "compose_inputs": {"infra/docker-compose.yml": "compose"},
        "threshold_sha256": "threshold",
        "workload_sha256": "workload",
        "services": {"api": {"reference": "backend:locked", "image_id": "sha256:" + "c" * 64}},
    }
    lock_path = tmp_path / "image-lock.json"
    _write_json(lock_path, lock)
    return lock_path, lock


def test_image_lock_rejects_tampered_build_receipt(tmp_path: Path) -> None:
    lock_path, _ = _lock_fixture(tmp_path)
    (tmp_path / "build-receipt.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="receipt digest"):
        gate_c_image_lock._validated_lock(ROOT, lock_path)


def test_image_lock_rejects_a_different_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path, _ = _lock_fixture(tmp_path)
    monkeypatch.setattr(
        gate_c_image_lock,
        "_sha256",
        lambda path: {
            "build-receipt.json": json.loads(lock_path.read_text())["build_receipt"]["sha256"],
            "docker-compose.yml": "compose",
            "gate-c-thresholds.v1.json": "threshold",
            "gate-c-workload.v1.json": "workload",
        }[path.name],
    )
    monkeypatch.setattr(
        gate_c_image_lock,
        "_run",
        lambda arguments, **_kwargs: "d" * 40 if arguments[-1] == "HEAD" else "b" * 40,
    )

    with pytest.raises(ValueError, match="current source"):
        gate_c_image_lock._validated_lock(ROOT, lock_path)


def test_image_lock_rejects_service_content_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path, lock = _lock_fixture(tmp_path)
    monkeypatch.setattr(gate_c_image_lock, "_validated_lock", lambda *_args: lock)
    monkeypatch.setattr(gate_c_image_lock, "_image_id", lambda *_args: "sha256:" + "d" * 64)

    args = argparse.Namespace(root=ROOT, image_lock=lock_path)
    with pytest.raises(ValueError, match="service api"):
        gate_c_image_lock.verify(args)
