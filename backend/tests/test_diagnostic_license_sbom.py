from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_generator():
    module_path = (
        Path(__file__).resolve().parents[2] / "tools" / "generate_diagnostic_license_sbom.py"
    )
    specification = importlib.util.spec_from_file_location(
        "cybercontrol_diagnostic_license_sbom", module_path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load diagnostic license SBOM generator")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


GENERATOR = _load_generator()


def _provenance(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    provenance = tmp_path / "provenance"
    licenses = tmp_path / "licenses" / "jemalloc"
    provenance.mkdir(parents=True)
    licenses.mkdir(parents=True)
    (provenance / "input-sha256.txt").write_text(
        f"{GENERATOR.JEMALLOC_SOURCE_SHA256}  /build/jemalloc.tar.bz2\n",
        encoding="utf-8",
    )
    (provenance / "library-sha256.txt").write_text(
        "a" * 64 + "  /out/libjemalloc.so.2\n", encoding="utf-8"
    )
    (provenance / "library-notes.txt").write_text(
        "    Build ID: 0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )
    license_path = licenses / "COPYING"
    license_path.write_text("BSD-2-Clause fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        GENERATOR,
        "JEMALLOC_LICENSE_SHA256",
        hashlib.sha256(license_path.read_bytes()).hexdigest(),
    )
    return provenance, licenses.parent


def test_build_bom_is_bound_to_real_provenance_and_license(tmp_path: Path, monkeypatch) -> None:
    provenance, licenses = _provenance(tmp_path, monkeypatch)

    document = GENERATOR.build_bom(provenance, licenses)

    component = document["components"][0]
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.6"
    assert component["name"] == "jemalloc"
    assert component["version"] == "5.3.0"
    assert component["licenses"] == [{"license": {"id": "BSD-2-Clause"}}]
    assert component["hashes"][0]["content"] == "a" * 64


def test_build_bom_rejects_unbound_source(tmp_path: Path, monkeypatch) -> None:
    provenance, licenses = _provenance(tmp_path, monkeypatch)
    (provenance / "input-sha256.txt").write_text("b" * 64 + "  source\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not bound"):
        GENERATOR.build_bom(provenance, licenses)


def test_build_bom_rejects_unapproved_license(tmp_path: Path, monkeypatch) -> None:
    provenance, licenses = _provenance(tmp_path, monkeypatch)
    (licenses / "jemalloc" / "COPYING").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="COPYING SHA256"):
        GENERATOR.build_bom(provenance, licenses)


def test_cli_writes_parseable_document(tmp_path: Path, monkeypatch) -> None:
    provenance, licenses = _provenance(tmp_path, monkeypatch)
    output = tmp_path / "sbom.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_diagnostic_license_sbom.py",
            "--provenance",
            str(provenance),
            "--licenses",
            str(licenses),
            "--output",
            str(output),
        ],
    )

    assert GENERATOR.main() == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert document["serialNumber"].startswith("urn:uuid:")
