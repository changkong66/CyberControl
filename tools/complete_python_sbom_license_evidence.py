from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import tomllib
import urllib.request
import zipfile
from email.parser import Parser
from importlib import metadata
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "cybercontrol.python-license-evidence.v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value.strip().lower())


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _validate_entry(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("license evidence entries must be objects")
    required = (
        "name",
        "version",
        "purl",
        "spdx_expression",
        "declared_license",
        "license_file",
        "license_file_sha256",
        "artifact_url",
        "artifact_sha256",
        "artifact_size",
    )
    if any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in required[:-1]):
        raise ValueError("license evidence entry has a missing string field")
    artifact_size = raw.get("artifact_size")
    if not isinstance(artifact_size, int) or isinstance(artifact_size, bool) or artifact_size <= 0:
        raise ValueError("license evidence artifact_size must be a positive integer")
    for key in ("license_file_sha256", "artifact_sha256"):
        value = str(raw[key]).lower()
        if not SHA256.fullmatch(value):
            raise ValueError(f"{key} must be a lowercase SHA256 digest")
    url = str(raw["artifact_url"])
    if not url.startswith("https://files.pythonhosted.org/"):
        raise ValueError("license evidence artifact URL must use the PyPI file host")
    license_file = PurePosixPath(str(raw["license_file"]).replace("\\", "/"))
    if license_file.is_absolute() or ".." in license_file.parts:
        raise ValueError("license_file must not escape the distribution directory")
    return {
        **raw,
        "name": str(raw["name"]).strip(),
        "version": str(raw["version"]).strip(),
        "license_file_sha256": str(raw["license_file_sha256"]).lower(),
        "artifact_sha256": str(raw["artifact_sha256"]).lower(),
    }


def load_evidence(path: Path) -> tuple[dict[str, Any], ...]:
    document = _read_json(path)
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported Python license evidence schema")
    raw_components = document.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise ValueError("Python license evidence must contain components")
    entries = tuple(_validate_entry(value) for value in raw_components)
    keys = [(_normalized_name(str(item["name"])), str(item["version"])) for item in entries]
    if len(set(keys)) != len(keys):
        raise ValueError("Python license evidence component identities must be unique")
    return entries


def _lock_entry(lock: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise ValueError("uv.lock does not contain package entries")
    name = _normalized_name(str(evidence["name"]))
    version = str(evidence["version"])
    matches = [
        item
        for item in packages
        if isinstance(item, dict)
        and _normalized_name(str(item.get("name", ""))) == name
        and str(item.get("version", "")) == version
    ]
    if len(matches) != 1:
        raise ValueError(f"uv.lock must contain exactly one entry for {evidence['name']}@{version}")
    return matches[0]


def verify_lock_binding(lock: dict[str, Any], evidence: dict[str, Any]) -> None:
    package = _lock_entry(lock, evidence)
    if package.get("source", {}).get("registry") != "https://pypi.org/simple":
        raise ValueError(f"{evidence['name']} must resolve from the PyPI registry")
    wheels = package.get("wheels")
    if not isinstance(wheels, list):
        raise ValueError(f"uv.lock has no wheel records for {evidence['name']}")
    matches = [
        wheel
        for wheel in wheels
        if isinstance(wheel, dict)
        and wheel.get("url") == evidence["artifact_url"]
        and str(wheel.get("hash", "")).lower() == f"sha256:{evidence['artifact_sha256']}"
        and int(wheel.get("size", -1)) == int(evidence["artifact_size"])
    ]
    if len(matches) != 1:
        raise ValueError(
            f"license evidence is not bound to an exact uv.lock wheel for {evidence['name']}"
        )


def download_artifact(url: str, *, attempts: int = 3) -> bytes:
    # The caller validates this URL against the fixed PyPI file-host policy.
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={"User-Agent": "CyberControl-SupplyChainVerifier/1.0"},
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                body = response.read(20 * 1024 * 1024 + 1)
            if len(body) > 20 * 1024 * 1024:
                raise ValueError("license evidence artifact exceeds the verifier size limit")
            return body
        except Exception as error:  # pragma: no cover - network failures are environment-specific.
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(
        f"unable to download license evidence artifact: {last_error}"
    ) from last_error


def _metadata_from_wheel(artifact: bytes, evidence: dict[str, Any]) -> tuple[str, bytes]:
    with zipfile.ZipFile(BytesIO(artifact)) as archive:
        metadata_paths = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError("license evidence wheel must contain exactly one METADATA file")
        metadata_path = metadata_paths[0]
        document = Parser().parsestr(archive.read(metadata_path).decode("utf-8"))
        if (
            document.get("Name") != evidence["name"]
            or document.get("Version") != evidence["version"]
        ):
            raise ValueError("wheel metadata identity does not match license evidence")
        if document.get("License") != evidence["declared_license"]:
            raise ValueError("wheel declared license does not match license evidence")
        declared_files = document.get_all("License-File") or []
        if Path(str(evidence["license_file"])).name not in {
            Path(str(value)).name for value in declared_files
        }:
            raise ValueError("wheel metadata does not declare the evidenced license file")
        license_path = str(evidence["license_file"]).replace("\\", "/")
        try:
            license_bytes = archive.read(license_path)
        except KeyError as error:
            raise ValueError("evidenced license file is absent from the wheel") from error
        if _sha256(license_bytes) != evidence["license_file_sha256"]:
            raise ValueError("wheel license file digest does not match license evidence")
        return metadata_path, license_bytes


def verify_installed_distribution(evidence: dict[str, Any]) -> None:
    distribution = metadata.distribution(evidence["name"])
    if (
        distribution.metadata.get("Name") != evidence["name"]
        or distribution.version != evidence["version"]
    ):
        raise ValueError("installed distribution identity does not match license evidence")
    if distribution.metadata.get("License") != evidence["declared_license"]:
        raise ValueError("installed distribution license does not match license evidence")
    declared_files = distribution.metadata.get_all("License-File") or []
    if Path(str(evidence["license_file"])).name not in {
        Path(str(value)).name for value in declared_files
    }:
        raise ValueError("installed distribution does not declare the evidenced license file")
    license_path = Path(distribution.locate_file(str(evidence["license_file"])))
    if not license_path.is_file():
        raise ValueError("installed distribution license file is absent")
    if _sha256(license_path.read_bytes()) != evidence["license_file_sha256"]:
        raise ValueError("installed distribution license file digest does not match evidence")


def _component(document: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    components = document.get("components")
    if not isinstance(components, list):
        raise ValueError("Python SBOM components must be an array")
    matches = [
        component
        for component in components
        if isinstance(component, dict)
        and _normalized_name(str(component.get("name", ""))) == _normalized_name(evidence["name"])
        and str(component.get("version", "")) == evidence["version"]
    ]
    if len(matches) != 1:
        raise ValueError(f"Python SBOM must contain exactly one component for {evidence['name']}")
    component = matches[0]
    if component.get("purl") != evidence["purl"]:
        raise ValueError("Python SBOM component purl does not match license evidence")
    return component


def enrich_document(
    document: dict[str, Any],
    evidence_entries: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    enriched = json.loads(json.dumps(document))
    for evidence in evidence_entries:
        component = _component(enriched, evidence)
        existing = component.get("licenses", [])
        if existing:
            existing_text = json.dumps(existing, sort_keys=True)
            if evidence["spdx_expression"] not in existing_text:
                raise ValueError("existing SBOM license conflicts with external license evidence")
        else:
            component["licenses"] = [{"license": {"id": evidence["spdx_expression"]}}]
        properties = component.setdefault("properties", [])
        if not isinstance(properties, list):
            raise ValueError("Python SBOM component properties must be an array")
        additions = {
            "cybercontrol:license-evidence-artifact-sha256": evidence["artifact_sha256"],
            "cybercontrol:license-evidence-license-file-sha256": evidence["license_file_sha256"],
            "cybercontrol:license-evidence-schema": SCHEMA_VERSION,
        }
        for name, value in additions.items():
            conflicting = [
                item
                for item in properties
                if isinstance(item, dict)
                and item.get("name") == name
                and item.get("value") != value
            ]
            if conflicting:
                raise ValueError(f"SBOM contains conflicting property {name}")
            if not any(
                isinstance(item, dict) and item.get("name") == name and item.get("value") == value
                for item in properties
            ):
                properties.append({"name": name, "value": value})
        properties.sort(key=lambda item: (str(item.get("name", "")), str(item.get("value", ""))))
    return enriched


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Complete and verify Python SBOM license evidence."
    )
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    sbom = _read_json(arguments.sbom)
    with arguments.lock.open("rb") as stream:
        lock = tomllib.load(stream)
    evidence_entries = load_evidence(arguments.evidence)
    for evidence in evidence_entries:
        verify_lock_binding(lock, evidence)
        artifact = download_artifact(str(evidence["artifact_url"]))
        if len(artifact) != int(evidence["artifact_size"]):
            raise ValueError(f"downloaded artifact size mismatch for {evidence['name']}")
        if _sha256(artifact) != evidence["artifact_sha256"]:
            raise ValueError(f"downloaded artifact digest mismatch for {evidence['name']}")
        _metadata_from_wheel(artifact, evidence)
        verify_installed_distribution(evidence)
    enriched = enrich_document(sbom, evidence_entries)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_name(arguments.output.name + ".tmp")
    temporary.write_text(
        json.dumps(enriched, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(arguments.output)
    print(f"Verified and completed license evidence for {len(evidence_entries)} components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
