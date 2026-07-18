from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote

SPDX_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")
DEPENDENCY_GROUPS = ("dependencies", "optionalDependencies", "devDependencies")
CURATED_LICENSE_PREFIXES = (
    ("@esbuild/", "MIT"),
    ("@rollup/rollup-", "MIT"),
    ("@tailwindcss/oxide-", "MIT"),
    ("lightningcss-", "MPL-2.0"),
)
CURATED_LICENSES = {
    "config-chain": "MIT",
    "fsevents": "MIT",
}


def package_version(node: dict[str, Any]) -> str:
    version = str(node.get("version", "unknown"))
    if not version.startswith(("file:", "link:")):
        return version
    package_path = node.get("path")
    if isinstance(package_path, str):
        manifest = Path(package_path) / "package.json"
        if manifest.is_file():
            document = json.loads(manifest.read_text(encoding="utf-8"))
            manifest_version = document.get("version")
            if isinstance(manifest_version, str) and manifest_version:
                return manifest_version
    return "0.0.0-local"


def package_purl(name: str, version: str) -> str:
    encoded_name = quote(name, safe="/")
    encoded_version = quote(version, safe=".-_~+")
    return f"pkg:npm/{encoded_name}@{encoded_version}"


def license_entries(value: Any) -> list[dict[str, dict[str, str]]]:
    if not isinstance(value, str) or not value.strip():
        return []
    license_value = value.strip()
    if SPDX_ID_PATTERN.fullmatch(license_value):
        return [{"license": {"id": license_value}}]
    return [{"license": {"name": license_value}}]


def curated_license(name: str) -> str | None:
    exact = CURATED_LICENSES.get(name)
    if exact is not None:
        return exact
    for prefix, license_id in CURATED_LICENSE_PREFIXES:
        if name.startswith(prefix):
            return license_id
    return None


def repository_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("url"), str):
        return value["url"]
    return None


def external_references(node: dict[str, Any]) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    homepage = node.get("homepage")
    if isinstance(homepage, str) and homepage:
        references.append({"type": "website", "url": homepage})
    repository = repository_url(node.get("repository"))
    if repository:
        references.append({"type": "vcs", "url": repository})
    resolved = node.get("resolved")
    if isinstance(resolved, str) and resolved.startswith(("https://", "http://")):
        references.append({"type": "distribution", "url": resolved})
    return references


def dependency_items(node: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any], str]]:
    for group in DEPENDENCY_GROUPS:
        dependencies = node.get(group)
        if not isinstance(dependencies, dict):
            continue
        for name, child in dependencies.items():
            if isinstance(name, str) and isinstance(child, dict):
                yield name, child, group


def build_bom(root: dict[str, Any]) -> dict[str, Any]:
    root_name = str(root.get("name", "unnamed-node-application"))
    root_version = str(root.get("version", "0.0.0"))
    root_ref = package_purl(root_name, root_version)
    components: dict[str, dict[str, Any]] = {}
    dependency_edges: dict[str, set[str]] = {root_ref: set()}

    def visit(parent_ref: str, name: str, node: dict[str, Any], group: str) -> None:
        version = package_version(node)
        bom_ref = package_purl(name, version)
        dependency_edges.setdefault(parent_ref, set()).add(bom_ref)
        dependency_edges.setdefault(bom_ref, set())
        component = components.get(bom_ref)
        required = group == "dependencies"
        if component is None:
            component = {
                "type": "library",
                "bom-ref": bom_ref,
                "name": name,
                "version": version,
                "purl": bom_ref,
                "scope": "required" if required else "optional",
                "properties": [
                    {
                        "name": "liyans:node-dependency-group",
                        "value": group,
                    }
                ],
            }
            license_value = node.get("license")
            license_source = "package-metadata"
            if not isinstance(license_value, str) or not license_value.strip():
                license_value = curated_license(name)
                license_source = "curated-platform-package-policy"
            licenses = license_entries(license_value)
            if licenses:
                component["licenses"] = licenses
                component["properties"].append(
                    {
                        "name": "liyans:license-source",
                        "value": license_source,
                    }
                )
            references = external_references(node)
            if references:
                component["externalReferences"] = references
            components[bom_ref] = component
        elif required:
            component["scope"] = "required"

        marker = (bom_ref, id(node))
        if marker in visited:
            return
        visited.add(marker)
        for child_name, child, child_group in dependency_items(node):
            visit(bom_ref, child_name, child, child_group)

    visited: set[tuple[str, int]] = set()
    for dependency_name, dependency, group in dependency_items(root):
        visit(root_ref, dependency_name, dependency, group)

    component_list = [components[key] for key in sorted(components)]
    dependencies = [
        {"ref": reference, "dependsOn": sorted(targets)}
        for reference, targets in sorted(dependency_edges.items())
    ]
    fingerprint = sha256(
        json.dumps(
            {"components": component_list, "dependencies": dependencies},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, fingerprint)}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": root_name,
                "version": root_version,
                "purl": root_ref,
            },
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "liyans-node-sbom-generator",
                        "version": "1.0.0",
                    }
                ]
            },
        },
        "components": component_list,
        "dependencies": dependencies,
    }


def validate_bom(document: dict[str, Any]) -> None:
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != "1.6":
        raise ValueError("generated document is not CycloneDX 1.6")
    root = document["metadata"]["component"]["bom-ref"]
    component_refs = [component["bom-ref"] for component in document["components"]]
    if len(component_refs) != len(set(component_refs)):
        raise ValueError("generated SBOM contains duplicate component references")
    known = {root, *component_refs}
    for dependency in document["dependencies"]:
        if dependency["ref"] not in known or not set(dependency["dependsOn"]) <= known:
            raise ValueError("generated SBOM contains an unknown dependency reference")


def pnpm_document(project: Path) -> dict[str, Any]:
    executable = shutil.which("pnpm")
    if executable is None:
        raise RuntimeError("pnpm is not available")
    command = [executable, "list", "--json", "--long", "--depth", "Infinity"]
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        command = ["cmd.exe", "/d", "/s", "/c", *command]
    result = subprocess.run(  # noqa: S603
        command,
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pnpm list failed: {result.stderr.strip()}")
    document = json.loads(result.stdout)
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise ValueError("pnpm list did not return one project document")
    return document[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a CycloneDX SBOM from pnpm JSON")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    arguments = parser.parse_args()

    project = arguments.project.resolve()
    if arguments.input is None:
        root = pnpm_document(project)
    else:
        loaded = json.loads(arguments.input.read_text(encoding="utf-8"))
        root = loaded[0] if isinstance(loaded, list) and len(loaded) == 1 else loaded
        if not isinstance(root, dict):
            raise ValueError("input must contain one pnpm project document")
    bom = build_bom(root)
    validate_bom(bom)
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bom, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Generated {len(bom['components'])} Node components at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
