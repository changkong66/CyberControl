from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[2] / "tools" / "complete_python_sbom_license_evidence.py"
    )
    specification = importlib.util.spec_from_file_location(
        "python_sbom_license_evidence", module_path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load Python SBOM license evidence verifier")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


EVIDENCE = _load_module()


def _entry() -> dict[str, object]:
    return {
        "name": "sseclient-py",
        "version": "1.9.0",
        "purl": "pkg:pypi/sseclient-py@1.9.0",
        "spdx_expression": "Apache-2.0",
        "declared_license": "Apache Software License v2",
        "license_file": "sseclient_py-1.9.0.dist-info/licenses/LICENSE",
        "license_file_sha256": "a" * 64,
        "artifact_url": "https://files.pythonhosted.org/packages/example.whl",
        "artifact_sha256": "b" * 64,
        "artifact_size": 123,
    }


def test_enrichment_adds_spdx_license_and_auditable_properties() -> None:
    entry = _entry()
    result = EVIDENCE.enrich_document(
        {
            "bomFormat": "CycloneDX",
            "components": [
                {
                    "name": "sseclient-py",
                    "version": "1.9.0",
                    "purl": "pkg:pypi/sseclient-py@1.9.0",
                }
            ],
        },
        (entry,),
    )

    component = result["components"][0]
    assert component["licenses"] == [{"license": {"id": "Apache-2.0"}}]
    assert {property_["name"] for property_ in component["properties"]} == {
        "cybercontrol:license-evidence-artifact-sha256",
        "cybercontrol:license-evidence-license-file-sha256",
        "cybercontrol:license-evidence-schema",
    }


def test_enrichment_rejects_conflicting_existing_license() -> None:
    entry = _entry()
    with pytest.raises(ValueError, match="conflicts"):
        EVIDENCE.enrich_document(
            {
                "bomFormat": "CycloneDX",
                "components": [
                    {
                        "name": "sseclient-py",
                        "version": "1.9.0",
                        "purl": "pkg:pypi/sseclient-py@1.9.0",
                        "licenses": [{"license": {"id": "GPL-3.0-only"}}],
                    }
                ],
            },
            (entry,),
        )


def test_wheel_metadata_and_license_digest_are_verified() -> None:
    license_bytes = b"Apache License\n"
    entry = _entry()
    entry["license_file_sha256"] = EVIDENCE._sha256(license_bytes)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "sseclient_py-1.9.0.dist-info/METADATA",
            "Name: sseclient-py\n"
            "Version: 1.9.0\n"
            "License: Apache Software License v2\n"
            "License-File: LICENSE\n",
        )
        archive.writestr(entry["license_file"], license_bytes)

    EVIDENCE._metadata_from_wheel(stream.getvalue(), entry)


def test_load_evidence_rejects_non_pypi_artifact() -> None:
    entry = _entry()
    entry["artifact_url"] = "https://example.invalid/package.whl"
    with pytest.raises(ValueError, match="PyPI file host"):
        EVIDENCE._validate_entry(entry)
