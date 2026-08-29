from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import gate_c_supply_chain as supply_chain  # noqa: E402


def _write_oci_archive(path: Path) -> tuple[str, str]:
    config = json.dumps({"architecture": "amd64", "os": "linux"}, sort_keys=True).encode()
    config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest_document = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": config_digest,
            "size": len(config),
        },
        "layers": [],
    }
    manifest = json.dumps(manifest_document, sort_keys=True).encode()
    manifest_digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
    index = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": manifest_digest,
                    "size": len(manifest),
                    "platform": {"architecture": "amd64", "os": "linux"},
                }
            ],
        },
        sort_keys=True,
    ).encode()
    members = {
        "oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
        "index.json": index,
        f"blobs/sha256/{manifest_digest.split(':', 1)[1]}": manifest,
        f"blobs/sha256/{config_digest.split(':', 1)[1]}": config,
    }
    with tarfile.open(path, mode="w:") as archive:
        for name, content in sorted(members.items()):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(content))
    return manifest_digest, config_digest


def _manifest(**overrides: object) -> dict[str, object]:
    archive = {
        "component": "python-base",
        "version": "sha256:" + "a" * 64,
        "source": "https://hub.docker.com/_/python",
        "path": "oci-layouts/python.tar",
        "sha256": "c" * 64,
        "size_bytes": 1,
        "spdx_license_id": "LicenseRef-CyberControl-Archive",
        "license_evidence_path": "licenses/evidence.json",
        "license_evidence_sha256": "b" * 64,
        "propagation_class": "RUNTIME_COPIED",
        "distribution_scope": "oci_layouts",
        "obligations": ["retain-license-evidence"],
        "disposition": "RUNTIME_LICENSE_REVIEWED",
    }
    value: dict[str, object] = {
        "schema_version": supply_chain.MANIFEST_SCHEMA,
        "process_version": supply_chain.PROCESS_VERSION,
        "required_directories": ["sources", "patches", "apk", "licenses"],
        "sources": [],
        "patches": [],
        "apk": [],
        "python_wheels": [],
        "pnpm_store": [],
        "oci_layouts": [archive],
        "licenses": [],
        "base_images": [
            {
                "role": "python",
                "local_reference": "cybercontrol/base-python:3.11@sha256:" + "a" * 64,
                "digest": "sha256:" + "a" * 64,
                "archive_path": "oci-layouts/python.tar",
                "archive_sha256": "c" * 64,
                "archive_size_bytes": 1,
                "oci_manifest_digest": "sha256:" + "d" * 64,
                "config_digest": "sha256:" + "e" * 64,
                "spdx_license_id": "PSF-2.0",
                "license_evidence_path": "licenses/evidence.json",
                "license_evidence_sha256": "b" * 64,
                "propagation_class": "RUNTIME_COPIED",
                "obligations": ["retain-license-evidence"],
                "disposition": "RUNTIME_LICENSE_REVIEWED",
            }
        ],
    }
    value.update(overrides)
    return value


def test_manifest_rejects_path_traversal() -> None:
    value = _manifest(sources=[{"path": "../escape", "sha256": "a" * 64}])
    with pytest.raises(ValueError, match="not normalized"):
        supply_chain.validate_manifest(value)


def test_manifest_rejects_unknown_propagation_class() -> None:
    value = _manifest(
        sources=[
            {
                "path": "sources/source.tar",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "spdx_license_id": "MIT",
                "license_evidence_path": "licenses/source.txt",
                "license_evidence_sha256": "b" * 64,
                "propagation_class": "RUNTIME_MAGIC",
            }
        ]
    )
    with pytest.raises(ValueError, match="propagation class"):
        supply_chain.validate_manifest(value)


def test_manifest_requires_license_evidence() -> None:
    value = _manifest(
        patches=[
            {
                "path": "patches/fix.patch",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "spdx_license_id": "MIT",
                "propagation_class": "BUILD_ONLY_TRANSIENT",
            }
        ]
    )
    with pytest.raises(ValueError, match="license evidence"):
        supply_chain.validate_manifest(value)


def test_remote_add_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "infra").mkdir()
    (tmp_path / "tests/load").mkdir(parents=True)
    for path in (
        "infra/backend.Dockerfile",
        "infra/frontend.Dockerfile",
        "infra/mock-provider.Dockerfile",
        "tests/load/Dockerfile",
        "tests/load/jemalloc-profile.Dockerfile",
    ):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / "infra/backend.Dockerfile").write_text(
        "FROM scratch\nADD https://example.invalid/input /input\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="remote Dockerfile ADD"):
        supply_chain.validate_dockerfiles(tmp_path)


def test_manifest_schema_is_stable() -> None:
    assert json.loads(json.dumps(_manifest()))["process_version"] == "Gate-C-12-v1.0"


def test_spdx_expression_accepts_parentheses_and_rejects_malformed_values() -> None:
    assert supply_chain._is_spdx_expression("(Apache-2.0 OR MIT) AND BSD-3-Clause")
    assert not supply_chain._is_spdx_expression("Apache-2.0 OR")
    assert not supply_chain._is_spdx_expression("(Apache-2.0 OR MIT")


def test_generated_manifest_is_deterministic_and_validates_assets(tmp_path: Path) -> None:
    for relative in (
        "infra/backend.Dockerfile",
        "infra/frontend.Dockerfile",
        "infra/mock-provider.Dockerfile",
        "tests/load/Dockerfile",
        "tests/load/jemalloc-profile.Dockerfile",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("FROM scratch\n", encoding="utf-8")
    base = tmp_path / "third_party/gate-c-build"
    directories = (
        "sources",
        "patches",
        "apk",
        "python-wheelhouse",
        "pnpm-store",
        "oci-layouts",
        "licenses",
    )
    for relative in directories:
        (base / relative).mkdir(parents=True, exist_ok=True)
    archive = base / "oci-layouts/python-base.tar"
    manifest_digest, config_digest = _write_oci_archive(archive)
    archive_hash = supply_chain.sha256(archive)
    base_spec = {
        "schema_version": supply_chain.BASE_IMAGE_SPEC_SCHEMA,
        "process_version": supply_chain.PROCESS_VERSION,
        "base_images": [
            {
                "role": "python-base",
                "local_reference": "local/python:3.11@sha256:" + "a" * 64,
                "digest": "sha256:" + "a" * 64,
                "archive_path": "third_party/gate-c-build/oci-layouts/python-base.tar",
                "archive_sha256": archive_hash,
                "archive_size_bytes": archive.stat().st_size,
                "oci_manifest_digest": manifest_digest,
                "config_digest": config_digest,
                "spdx_license_id": "PSF-2.0",
                "license_evidence": "Python image notice",
                "propagation_class": "RUNTIME_COPIED",
                "obligations": ["retain-license-evidence"],
                "disposition": "RUNTIME_LICENSE_REVIEWED",
                "source": "https://hub.docker.com/_/python",
            }
        ],
    }
    spec_path = base / "base-images.json"
    spec_path.write_text(json.dumps(base_spec), encoding="utf-8")
    arguments = SimpleNamespace(
        root=tmp_path,
        base_images=Path("third_party/gate-c-build/base-images.json"),
    )

    supply_chain.generate(arguments)
    first = {
        relative: supply_chain.sha256(tmp_path / relative)
        for relative in (
            "third_party/gate-c-build/manifest.json",
            "third_party/gate-c-build/licenses/license-policy.json",
            "third_party/gate-c-build/licenses/asset-license-catalog.json",
        )
    }
    manifest = supply_chain._read_json(tmp_path / "third_party/gate-c-build/manifest.json")
    assert len(supply_chain.validate_manifest(manifest)) == 4
    supply_chain.validate_assets(tmp_path, manifest)
    supply_chain.generate(arguments)
    second = {relative: supply_chain.sha256(tmp_path / relative) for relative in first}
    assert first == second


def test_asset_tampering_is_rejected(tmp_path: Path) -> None:
    value = _manifest(
        sources=[
            {
                "path": "sources/source.tar",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "spdx_license_id": "MIT",
                "license_evidence_path": "licenses/evidence.json",
                "license_evidence_sha256": "b" * 64,
                "propagation_class": "BUILD_ONLY_TRANSIENT",
                "obligations": ["retain-license-evidence"],
                "disposition": "BUILD_ONLY_LICENSE_RETAINED",
                "component": "source",
                "version": "1.0",
                "source": "https://example.invalid/source",
                "distribution_scope": "sources",
            }
        ]
    )
    (tmp_path / "sources").mkdir()
    (tmp_path / "licenses").mkdir()
    (tmp_path / "sources/source.tar").write_bytes(b"x")
    (tmp_path / "licenses/evidence.json").write_bytes(b"evidence")
    with pytest.raises(ValueError, match="hash mismatch"):
        supply_chain.validate_assets(tmp_path, value)


def test_oci_internal_config_blob_tampering_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "image.tar"
    manifest_digest, config_digest = _write_oci_archive(archive)
    with tarfile.open(archive, mode="r:") as source:
        members = [
            (member, source.extractfile(member).read())
            for member in source.getmembers()
            if member.isfile() and source.extractfile(member) is not None
        ]
    config_name = f"blobs/sha256/{config_digest.split(':', 1)[1]}"
    with tarfile.open(archive, mode="w:") as destination:
        for member, content in members:
            if member.name == config_name:
                content = b'{"architecture":"tampered","os":"linux"}'
            member.size = len(content)
            destination.addfile(member, io.BytesIO(content))
    image = {
        "role": "python-base",
        "oci_manifest_digest": manifest_digest,
        "config_digest": config_digest,
    }

    with pytest.raises(ValueError, match="config blob digest"):
        supply_chain._validate_oci_archive(archive, image)
