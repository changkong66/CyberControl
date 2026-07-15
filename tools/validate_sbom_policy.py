from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

INTERNAL_PACKAGE_PATTERNS = (
    re.compile(r"^liyans(?:-|$)"),
    re.compile(r"^@liyans/"),
)
PROHIBITED_LICENSE_PATTERNS = (
    re.compile(r"\bAGPL(?:-|\b)", re.IGNORECASE),
    re.compile(r"(?<!L)\bGPL(?:-|\b)", re.IGNORECASE),
    re.compile(r"\bSSPL(?:-|\b)", re.IGNORECASE),
    re.compile(r"\bBUSL(?:-|\b)", re.IGNORECASE),
    re.compile(r"Commons[ -]Clause", re.IGNORECASE),
    re.compile(r"Elastic[ -]License", re.IGNORECASE),
)
UNKNOWN_LICENSE_VALUES = frozenset({"NONE", "NOASSERTION", "UNKNOWN"})


@dataclass(frozen=True, slots=True)
class ComponentLicenseRecord:
    name: str
    version: str
    licenses: tuple[str, ...]
    internal: bool


def component_licenses(component: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for entry in component.get("licenses", []):
        if not isinstance(entry, dict):
            continue
        license_document = entry.get("license")
        if isinstance(license_document, dict):
            value = license_document.get("id") or license_document.get("name")
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        expression = entry.get("expression")
        if isinstance(expression, str) and expression.strip():
            values.append(expression.strip())
    return tuple(sorted(set(values)))


def is_internal_package(name: str) -> bool:
    return any(pattern.search(name) for pattern in INTERNAL_PACKAGE_PATTERNS)


def validate_document(document: dict[str, Any]) -> list[ComponentLicenseRecord]:
    if document.get("bomFormat") != "CycloneDX":
        raise ValueError("SBOM must use the CycloneDX format")
    components = document.get("components")
    if not isinstance(components, list):
        raise ValueError("SBOM components must be an array")
    records: list[ComponentLicenseRecord] = []
    violations: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("SBOM contains a non-object component")
        name = str(component.get("name", "")).strip()
        version = str(component.get("version", "unknown")).strip()
        if not name:
            raise ValueError("SBOM component name is required")
        internal = is_internal_package(name)
        licenses = component_licenses(component)
        if not licenses and not internal:
            violations.append(f"{name}@{version}: missing license evidence")
        for value in licenses:
            if value.upper() in UNKNOWN_LICENSE_VALUES and not internal:
                violations.append(f"{name}@{version}: unknown license evidence")
            if any(pattern.search(value) for pattern in PROHIBITED_LICENSE_PATTERNS):
                violations.append(f"{name}@{version}: prohibited license {value}")
        records.append(
            ComponentLicenseRecord(
                name=name,
                version=version,
                licenses=licenses,
                internal=internal,
            )
        )
    if violations:
        raise ValueError("; ".join(sorted(violations)))
    return sorted(records, key=lambda record: (record.name, record.version))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CycloneDX license policy")
    parser.add_argument("sbom", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    document = json.loads(arguments.sbom.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("SBOM root must be an object")
    records = validate_document(document)
    report = {
        "schema_version": "phase1.1.license-policy.v1",
        "source_sbom": arguments.sbom.name,
        "result": "passed",
        "component_count": len(records),
        "components": [asdict(record) for record in records],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Validated license evidence for {len(records)} components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
