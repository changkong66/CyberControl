from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_policy() -> ModuleType:
    module_path = Path(__file__).resolve().parents[2] / "tools" / "validate_sbom_policy.py"
    specification = importlib.util.spec_from_file_location("liyans_sbom_policy", module_path)
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load SBOM policy validator")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


POLICY = _load_policy()


def test_license_policy_accepts_permissive_and_internal_components() -> None:
    records = POLICY.validate_document(
        {
            "bomFormat": "CycloneDX",
            "components": [
                {
                    "name": "external-library",
                    "version": "1.0.0",
                    "licenses": [{"license": {"id": "MIT"}}],
                },
                {"name": "liyans-backend", "version": "0.1.0"},
            ],
        }
    )

    assert len(records) == 2


@pytest.mark.parametrize(
    "component",
    [
        {"name": "unknown", "version": "1.0.0"},
        {
            "name": "copyleft",
            "version": "1.0.0",
            "licenses": [{"license": {"id": "AGPL-3.0-only"}}],
        },
    ],
)
def test_license_policy_rejects_missing_or_prohibited_evidence(component) -> None:
    with pytest.raises(ValueError):
        POLICY.validate_document(
            {
                "bomFormat": "CycloneDX",
                "components": [component],
            }
        )
