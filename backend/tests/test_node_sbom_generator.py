from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest


def load_node_sbom_generator() -> ModuleType:
    module_path = Path(__file__).resolve().parents[2] / "tools" / "generate_node_sbom.py"
    specification = importlib.util.spec_from_file_location(
        "liyans_node_sbom_generator", module_path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load Node SBOM generator from {module_path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


NODE_SBOM_GENERATOR = load_node_sbom_generator()


def sample_dependency_tree() -> dict[str, object]:
    return {
        "name": "liyans-frontend",
        "version": "0.1.0",
        "dependencies": {
            "vue": {
                "version": "3.5.21",
                "license": "MIT",
                "dependencies": {
                    "@vue/shared": {
                        "version": "3.5.21",
                        "license": "MIT",
                    }
                },
            }
        },
        "devDependencies": {
            "typescript": {
                "version": "5.9.2",
                "license": "Apache-2.0",
            }
        },
    }


def test_node_sbom_is_deterministic_and_preserves_dependency_edges() -> None:
    first = NODE_SBOM_GENERATOR.build_bom(sample_dependency_tree())
    second = NODE_SBOM_GENERATOR.build_bom(sample_dependency_tree())

    NODE_SBOM_GENERATOR.validate_bom(first)
    assert first == second
    assert first["specVersion"] == "1.6"
    assert len(first["components"]) == 3
    root_ref = first["metadata"]["component"]["bom-ref"]
    dependency_index = {item["ref"]: item["dependsOn"] for item in first["dependencies"]}
    assert dependency_index[root_ref] == [
        "pkg:npm/typescript@5.9.2",
        "pkg:npm/vue@3.5.21",
    ]
    assert dependency_index["pkg:npm/vue@3.5.21"] == ["pkg:npm/%40vue/shared@3.5.21"]


def test_node_sbom_validator_rejects_unknown_dependency_reference() -> None:
    bom = NODE_SBOM_GENERATOR.build_bom(sample_dependency_tree())
    invalid = deepcopy(bom)
    invalid["dependencies"][0]["dependsOn"].append("pkg:npm/unknown@1.0.0")

    with pytest.raises(ValueError, match="unknown dependency reference"):
        NODE_SBOM_GENERATOR.validate_bom(invalid)
