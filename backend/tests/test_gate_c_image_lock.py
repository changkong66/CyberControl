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


def _lock_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    source = {
        "commit": "a" * 40,
        "tree": "b" * 40,
        "product_source_sha": gate_c_image_lock.PRODUCT_SOURCE_SHA,
        "engineering_baseline_sha": "a" * 40,
        "source_date_epoch": 1,
    }
    inputs = {
        "offline_supply_chain": {
            "manifest": {"path": "manifest.json", "sha256": "1" * 64},
            "base_images": {"path": "base-images.json", "sha256": "2" * 64},
        }
    }
    inputs_path = tmp_path / "build-inputs.json"
    _write_json(inputs_path, inputs)
    (tmp_path / "infra").mkdir()
    (tmp_path / "tests/load").mkdir(parents=True)
    compose_path = tmp_path / "infra/docker-compose.yml"
    threshold_path = tmp_path / "tests/load/gate-c-thresholds.v1.json"
    workload_path = tmp_path / "tests/load/gate-c-workload.v1.json"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    threshold_path.write_text("{}\n", encoding="utf-8")
    workload_path.write_text("{}\n", encoding="utf-8")
    target_builds = {
        target.name: {
            "reference": f"{target.name}:test",
            "image_id": "sha256:" + chr(99 + index) * 64,
        }
        for index, target in enumerate(gate_c_image_lock.TARGETS)
    }
    diagnostic_build = {
        "reference": "diagnostic:test",
        "image_id": "sha256:" + "e" * 64,
    }
    receipt_path = tmp_path / "build-receipt.json"
    _write_json(
        receipt_path,
        {
            "schema_version": gate_c_image_lock.BUILD_RECEIPT_SCHEMA,
            "process_version": gate_c_image_lock.PROCESS_VERSION,
            "source": source,
            "inputs": {
                "path": inputs_path.name,
                "sha256": _digest(inputs_path),
                "document": inputs,
            },
            "offline_supply_chain": {
                "manifest": inputs["offline_supply_chain"]["manifest"],
                "base_images": inputs["offline_supply_chain"]["base_images"],
                "network_policy": "BUILDKIT_CONTAINER_NONE_AND_RUN_NETWORK_NONE",
            },
            "environment": {
                "builders": [
                    {
                        "name": "a",
                        "driver": "docker-container",
                        "container_network_mode": "none",
                        "buildkit_image_digest": "sha256:" + "a" * 64,
                    },
                    {
                        "name": "b",
                        "driver": "docker-container",
                        "container_network_mode": "none",
                        "buildkit_image_digest": "sha256:" + "a" * 64,
                    },
                ]
            },
            "independent_builds": {"a": target_builds, "b": target_builds},
            "diagnostic_independent_builds": {
                "rss-calibration": {"a": diagnostic_build, "b": diagnostic_build}
            },
            "reproducible": True,
        },
    )
    receipt_digest = _digest(receipt_path)
    service = {
        "reference": "backend:locked",
        "image_id": "sha256:" + "c" * 64,
        "content_digest": "sha256:" + "c" * 64,
        "source_sha": source["commit"],
        "source_tree": source["tree"],
        "product_source_sha": source["product_source_sha"],
        "engineering_baseline_sha": source["engineering_baseline_sha"],
        "process_version": gate_c_image_lock.PROCESS_VERSION,
        "build_receipt_sha256": receipt_digest,
        "image_role": "FORMAL_SERVICE:api",
    }
    lock = {
        "schema_version": gate_c_image_lock.IMAGE_LOCK_SCHEMA,
        "process_version": gate_c_image_lock.PROCESS_VERSION,
        "source": source,
        "track": "FORMAL_NORMAL",
        "build_receipt": {"path": receipt_path.name, "sha256": receipt_digest},
        "compose_inputs": {"infra/docker-compose.yml": _digest(compose_path)},
        "threshold_sha256": _digest(threshold_path),
        "workload_sha256": _digest(workload_path),
        "services": {"api": service},
        "diagnostic_images": {},
    }
    lock_path = tmp_path / "image-lock.json"
    _write_json(lock_path, lock)
    return tmp_path, lock_path, lock


def test_image_lock_rejects_tampered_build_receipt(tmp_path: Path) -> None:
    _, lock_path, _ = _lock_fixture(tmp_path)
    (tmp_path / "build-receipt.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="receipt digest"):
        gate_c_image_lock._validated_lock(ROOT, lock_path)


def test_supply_chain_accepts_manifest_license_evidence_enrichment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {
        "schema_version": gate_c_image_lock.OFFLINE_MANIFEST_SCHEMA,
        "process_version": gate_c_image_lock.PROCESS_VERSION,
        "base_images": [
            {
                "role": "python-base",
                "digest": "sha256:" + "a" * 64,
                "oci_manifest_digest": "sha256:" + "b" * 64,
                "archive_sha256": "c" * 64,
                "license_evidence_path": "licenses/policy.json",
                "license_evidence_sha256": "d" * 64,
            }
        ],
    }
    specification = {
        "schema_version": gate_c_image_lock.BASE_IMAGE_SPEC_SCHEMA,
        "process_version": gate_c_image_lock.PROCESS_VERSION,
        "base_images": [
            {
                "role": "python-base",
                "digest": "sha256:" + "a" * 64,
                "oci_manifest_digest": "sha256:" + "b" * 64,
                "archive_sha256": "c" * 64,
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    specification_path = tmp_path / "base-images.json"
    _write_json(manifest_path, manifest)
    _write_json(specification_path, specification)
    inputs = {
        "offline_supply_chain": {
            "manifest": {"path": "manifest.json", "sha256": _digest(manifest_path)},
            "base_images": {
                "path": "base-images.json",
                "sha256": _digest(specification_path),
            },
        }
    }
    monkeypatch.setattr(gate_c_image_lock, "BASE_IMAGE_ROLES", {"python": "python-base"})

    _, roles = gate_c_image_lock._supply_chain(tmp_path, inputs)

    assert roles["python-base"]["digest"] == "sha256:" + "a" * 64


def test_image_lock_rejects_tampered_offline_manifest_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock_path, lock = _lock_fixture(tmp_path)
    receipt_path = root / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["offline_supply_chain"]["manifest"]["sha256"] = "f" * 64
    _write_json(receipt_path, receipt)
    lock["build_receipt"]["sha256"] = _digest(receipt_path)
    lock["services"]["api"]["build_receipt_sha256"] = lock["build_receipt"]["sha256"]
    _write_json(lock_path, lock)
    inputs = json.loads((root / "build-inputs.json").read_text())
    monkeypatch.setattr(gate_c_image_lock, "_validate_inputs", lambda *_args: inputs)
    monkeypatch.setattr(gate_c_image_lock, "_supply_chain", lambda *_args: ({}, {}))
    monkeypatch.setattr(
        gate_c_image_lock,
        "_run",
        lambda arguments, **_kwargs: (
            lock["source"]["commit"] if arguments[-1] == "HEAD" else lock["source"]["tree"]
        ),
    )

    with pytest.raises(ValueError, match="offline manifest binding"):
        gate_c_image_lock._validated_lock(root, lock_path)


def test_image_lock_rejects_non_isolated_builder_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock_path, lock = _lock_fixture(tmp_path)
    receipt_path = root / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["environment"]["builders"][0]["container_network_mode"] = "bridge"
    _write_json(receipt_path, receipt)
    lock["build_receipt"]["sha256"] = _digest(receipt_path)
    lock["services"]["api"]["build_receipt_sha256"] = lock["build_receipt"]["sha256"]
    _write_json(lock_path, lock)
    inputs = json.loads((root / "build-inputs.json").read_text())
    monkeypatch.setattr(gate_c_image_lock, "_validate_inputs", lambda *_args: inputs)
    monkeypatch.setattr(gate_c_image_lock, "_supply_chain", lambda *_args: ({}, {}))
    monkeypatch.setattr(
        gate_c_image_lock,
        "_run",
        lambda arguments, **_kwargs: (
            lock["source"]["commit"] if arguments[-1] == "HEAD" else lock["source"]["tree"]
        ),
    )

    with pytest.raises(ValueError, match="builder isolation"):
        gate_c_image_lock._validated_lock(root, lock_path)


def test_image_lock_rejects_tampered_service_source_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock_path, lock = _lock_fixture(tmp_path)
    lock["services"]["api"]["source_tree"] = "f" * 40
    _write_json(lock_path, lock)
    inputs = json.loads((root / "build-inputs.json").read_text())
    monkeypatch.setattr(gate_c_image_lock, "_validate_inputs", lambda *_args: inputs)
    monkeypatch.setattr(gate_c_image_lock, "_supply_chain", lambda *_args: ({}, {}))
    monkeypatch.setattr(
        gate_c_image_lock,
        "_run",
        lambda arguments, **_kwargs: (
            lock["source"]["commit"] if arguments[-1] == "HEAD" else lock["source"]["tree"]
        ),
    )

    with pytest.raises(ValueError, match="source or receipt binding"):
        gate_c_image_lock._validated_lock(root, lock_path)


def test_formal_lock_rejects_diagnostic_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock_path, lock = _lock_fixture(tmp_path)
    lock["diagnostic_images"] = {"rss-calibration": {}}
    _write_json(lock_path, lock)
    inputs = json.loads((root / "build-inputs.json").read_text())
    monkeypatch.setattr(gate_c_image_lock, "_validate_inputs", lambda *_args: inputs)
    monkeypatch.setattr(gate_c_image_lock, "_supply_chain", lambda *_args: ({}, {}))
    monkeypatch.setattr(
        gate_c_image_lock,
        "_run",
        lambda arguments, **_kwargs: (
            lock["source"]["commit"] if arguments[-1] == "HEAD" else lock["source"]["tree"]
        ),
    )

    with pytest.raises(ValueError, match="formal normal lock contains diagnostic"):
        gate_c_image_lock._validated_lock(root, lock_path)


def test_image_lock_rejects_a_different_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock_path, _ = _lock_fixture(tmp_path)
    inputs = json.loads((root / "build-inputs.json").read_text())
    monkeypatch.setattr(gate_c_image_lock, "_validate_inputs", lambda *_args: inputs)
    monkeypatch.setattr(gate_c_image_lock, "_supply_chain", lambda *_args: ({}, {}))
    monkeypatch.setattr(
        gate_c_image_lock,
        "_run",
        lambda arguments, **_kwargs: "d" * 40 if arguments[-1] == "HEAD" else "b" * 40,
    )

    with pytest.raises(ValueError, match="current source"):
        gate_c_image_lock._validated_lock(root, lock_path)


def test_image_lock_rejects_service_content_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock_path, lock = _lock_fixture(tmp_path)
    monkeypatch.setattr(gate_c_image_lock, "_validated_lock", lambda *_args: lock)
    monkeypatch.setattr(gate_c_image_lock, "_image_id", lambda *_args: "sha256:" + "d" * 64)

    args = argparse.Namespace(root=root, image_lock=lock_path)
    with pytest.raises(ValueError, match="service api"):
        gate_c_image_lock.verify(args)


def test_diagnostic_image_cannot_impersonate_a_formal_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock_path, lock = _lock_fixture(tmp_path)
    formal_id = lock["services"]["api"]["image_id"]
    lock["diagnostic_images"] = {
        "rss-calibration": {
            "image_role": "NON_ACCEPTANCE_DIAGNOSTIC:rss-calibration",
            "reference": "diagnostic:locked",
            "image_id": formal_id,
        }
    }
    monkeypatch.setattr(gate_c_image_lock, "_validated_lock", lambda *_args: lock)
    monkeypatch.setattr(gate_c_image_lock, "_image_id", lambda *_args: formal_id)

    args = argparse.Namespace(root=root, image_lock=lock_path)
    with pytest.raises(ValueError, match="impersonates"):
        gate_c_image_lock.verify(args)


@pytest.mark.parametrize("dockerfile", ["infra/backend.Dockerfile", "tests/load/Dockerfile"])
def test_python_images_remove_nondeterministic_uv_workspace_metadata(dockerfile: str) -> None:
    source = (ROOT / dockerfile).read_text(encoding="utf-8")

    assert "-path '*/site-packages/*.dist-info/uv_cache.json'" in source
    assert "'/\\/uv_cache\\.json,/d'" in source


def test_backend_image_removes_wall_clock_apk_log() -> None:
    source = (ROOT / "infra/backend.Dockerfile").read_text(encoding="utf-8")

    assert "rm -f /var/log/apk.log" in source


def test_diagnostic_image_removes_wall_clock_apk_log() -> None:
    source = (ROOT / "tests/load/jemalloc-profile.Dockerfile").read_text(encoding="utf-8")

    assert "rm -f /var/log/apk.log" in source


def test_diagnostic_build_consumes_each_independent_backend_as_an_oci_context() -> None:
    dockerfile = (ROOT / "tests" / "load" / "jemalloc-profile.Dockerfile").read_text(
        encoding="utf-8"
    )
    tool = (ROOT / "tools" / "gate_c_image_lock.py").read_text(encoding="utf-8")

    assert "FROM backend_image AS runtime" in dockerfile
    assert "BACKEND_IMAGE" not in dockerfile
    assert "type=oci," in tool
    assert "tar=false" in tool
    assert "backend_image={_oci_context_reference(root, backend_context)}" in tool
    assert "return f\"oci-layout://./{relative}@{matches[0]['digest']}\"" in tool
    assert "backend_contexts[arm]" in tool
    assert "shutil.rmtree(offline_context_root)" in tool


def test_ci_builds_all_images_from_offline_named_contexts_without_network() -> None:
    workflow = (ROOT / ".github" / "workflows" / "quality-gates.yml").read_text(encoding="utf-8")

    assert "python3 tools/gate_c_supply_chain.py verify" in workflow
    assert workflow.count("--network none") == 5
    assert '--build-context "python_base=$PYTHON_BASE_CONTEXT"' in workflow
    assert '--build-context "node_base=$NODE_BASE_CONTEXT"' in workflow
    assert '--build-context "nginx_base=$NGINX_BASE_CONTEXT"' in workflow
    assert (
        '--build-context "backend_image=oci-layout://./artifacts/container/backend-oci@'
        '$backend_manifest"'
    ) in workflow
    assert '--build-context "backend_image=docker-image://$BACKEND_IMAGE_REF"' not in workflow
    assert '--build-arg "BACKEND_IMAGE=$BACKEND_IMAGE_REF"' not in workflow


def test_windows_quality_gate_builds_the_backend_without_network() -> None:
    tool = (ROOT / "tools/windows/run-quality-gates.ps1").read_text(encoding="utf-8")

    assert '"tools/gate_c_supply_chain.py", "verify"' in tool
    assert '"--network", "none"' in tool
    assert '"--build-context", "python_base=$pythonBase"' in tool
    assert '"--build-arg", "PYTHON_IMAGE=python_base"' in tool
