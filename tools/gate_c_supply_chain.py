from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

PROCESS_VERSION = "Gate-C-12-v1.0"
MANIFEST_SCHEMA = "cybercontrol.gate-c-build-supply-chain.v1"
LICENSE_CATALOG_SCHEMA = "cybercontrol.gate-c-build-license-catalog.v1"
LICENSE_POLICY_SCHEMA = "cybercontrol.gate-c-build-license-policy.v1"
BASE_IMAGE_SPEC_SCHEMA = "cybercontrol.gate-c-build-base-images.v1"
PROPAGATION_CLASSES = frozenset(
    {
        "BUILD_ONLY_TRANSIENT",
        "RUNTIME_COPIED",
        "LINKED_OR_DERIVED",
        "DIAGNOSTIC_ONLY",
    }
)
SPDX_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REMOTE_ADD = re.compile(r"^\s*ADD\s+(?:--[^\s]+\s+)*https?://", re.IGNORECASE | re.MULTILINE)
REMOTE_FETCH = re.compile(
    r"(?:curl|wget|apk\s+add(?![^\n]*--no-network)|pip\s+install(?![^\n]*--no-index)|"
    r"uv\s+(?:sync|pip)(?![^\n]*--offline)|(?:pnpm|npm)\s+install(?![^\n]*--offline))",
    re.IGNORECASE,
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _is_spdx_expression(value: str) -> bool:
    """Validate the small SPDX expression grammar used by archived inputs."""
    tokens = value.replace("(", " ( ").replace(")", " ) ").split()
    if not tokens:
        return False
    expect_operand = True
    depth = 0
    for part in tokens:
        if expect_operand:
            if part == "(":
                depth += 1
            elif SPDX_ID.fullmatch(part):
                expect_operand = False
            else:
                return False
        elif part in {"AND", "OR", "WITH"}:
            expect_operand = True
        elif part == ")" and depth:
            depth -= 1
        else:
            return False
    return not expect_operand and depth == 0


LICENSE_ALIASES = {
    "Apache Software License": "Apache-2.0",
    "Apache Software License v2": "Apache-2.0",
    "BSD": "BSD-3-Clause",
    "BSD License": "BSD-3-Clause",
    "BSD 3-Clause License": "BSD-3-Clause",
    "MIT License": "MIT",
    "MPL 2.0": "MPL-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Python Software Foundation License": "PSF-2.0",
    "Zlib License": "Zlib",
}
LICENSE_OVERRIDES = {
    "libgcc-15.2.0-r5.apk": (
        "GPL-2.0-or-later WITH GCC-exception-3.1 AND LGPL-2.1-or-later WITH GCC-exception-3.1",
        "Alpine package runtime license files and GCC Runtime Library Exception",
    ),
    "libstdc++-15.2.0-r5.apk": (
        "GPL-2.0-or-later WITH GCC-exception-3.1 AND LGPL-2.1-or-later WITH GCC-exception-3.1",
        "Alpine package runtime license files and GCC Runtime Library Exception",
    ),
}


def _normalise_license(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return ""
    if cleaned in LICENSE_ALIASES:
        cleaned = LICENSE_ALIASES[cleaned]
    if _is_spdx_expression(cleaned):
        return cleaned
    # Keep an auditable custom SPDX identifier when upstream metadata is
    # descriptive but does not contain a portable SPDX expression.
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", cleaned).strip("-") or "Unspecified"
    return f"LicenseRef-CyberControl-{slug}"


def _safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("supply-chain file path is required")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"supply-chain file path is not normalized: {value}")
    return path.as_posix()


def _file_entries(document: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: C901, PLR0912
    entries: list[dict[str, Any]] = []
    fields = (
        "sources",
        "patches",
        "apk",
        "python_wheels",
        "pnpm_store",
        "oci_layouts",
        "licenses",
    )
    for field in fields:
        value = document.get(field, [])
        if not isinstance(value, list):
            raise ValueError(f"supply-chain {field} must be an array")
        for entry in value:
            if not isinstance(entry, dict):
                raise ValueError(f"supply-chain {field} entry must be an object")
            item = dict(entry)
            item["path"] = _safe_relative_path(item.get("path"))
            digest = item.get("sha256")
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise ValueError(f"supply-chain file {item['path']} has an invalid SHA256")
            size = item.get("size_bytes")
            if not isinstance(size, int) or size < 0:
                raise ValueError(f"supply-chain file {item['path']} has an invalid size")
            license_id = item.get("spdx_license_id")
            if not isinstance(license_id, str) or not _is_spdx_expression(license_id):
                raise ValueError(f"supply-chain file {item['path']} has invalid SPDX evidence")
            propagation = item.get("propagation_class")
            if propagation not in PROPAGATION_CLASSES:
                raise ValueError(f"supply-chain file {item['path']} has invalid propagation class")
            evidence_digest = item.get("license_evidence_sha256")
            if not isinstance(evidence_digest, str) or SHA256.fullmatch(evidence_digest) is None:
                raise ValueError(f"supply-chain file {item['path']} lacks license evidence hash")
            item["license_evidence_path"] = _safe_relative_path(item.get("license_evidence_path"))
            obligations = item.get("obligations")
            if (
                not isinstance(obligations, list)
                or not obligations
                or not all(isinstance(obligation, str) and obligation for obligation in obligations)
            ):
                raise ValueError(f"supply-chain file {item['path']} lacks license obligations")
            disposition = item.get("disposition")
            if not isinstance(disposition, str) or not disposition:
                raise ValueError(f"supply-chain file {item['path']} lacks license disposition")
            for name in ("component", "version", "source", "distribution_scope"):
                if not isinstance(item.get(name), str) or not item[name]:
                    raise ValueError(f"supply-chain file {item['path']} lacks {name}")
            item["manifest_section"] = field
            entries.append(item)
    paths = [item["path"] for item in entries]
    if len(paths) != len(set(paths)):
        raise ValueError("supply-chain manifest contains duplicate file paths")
    return entries


def _validate_base_images(document: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: C901, PLR0912
    value = document.get("base_images")
    if not isinstance(value, list) or not value:
        raise ValueError("supply-chain base_images must be a non-empty array")
    result: list[dict[str, Any]] = []
    roles: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("supply-chain base image entry must be an object")
        role = entry.get("role")
        local_reference = entry.get("local_reference")
        digest = entry.get("digest")
        archive = _safe_relative_path(entry.get("archive_path"))
        license_id = entry.get("spdx_license_id")
        evidence_digest = entry.get("license_evidence_sha256")
        if not isinstance(role, str) or not role or role in roles:
            raise ValueError("supply-chain base image role is missing or duplicated")
        if not isinstance(local_reference, str) or "@sha256:" not in local_reference:
            raise ValueError(f"base image {role} must use a local content reference")
        if not isinstance(digest, str) or not IMAGE_DIGEST.fullmatch(digest):
            raise ValueError(f"base image {role} has an invalid digest")
        if not isinstance(license_id, str) or not _is_spdx_expression(license_id):
            raise ValueError(f"base image {role} has invalid SPDX evidence")
        if not isinstance(evidence_digest, str) or not SHA256.fullmatch(evidence_digest):
            raise ValueError(f"base image {role} lacks license evidence hash")
        evidence_path = _safe_relative_path(entry.get("license_evidence_path"))
        archive_digest = entry.get("archive_sha256")
        archive_size = entry.get("archive_size_bytes")
        oci_manifest_digest = entry.get("oci_manifest_digest")
        config_digest = entry.get("config_digest")
        if not isinstance(archive_digest, str) or not SHA256.fullmatch(archive_digest):
            raise ValueError(f"base image {role} has an invalid archive SHA256")
        if not isinstance(archive_size, int) or archive_size < 0:
            raise ValueError(f"base image {role} has an invalid archive size")
        if not isinstance(oci_manifest_digest, str) or not IMAGE_DIGEST.fullmatch(
            oci_manifest_digest
        ):
            raise ValueError(f"base image {role} has an invalid OCI manifest digest")
        if not isinstance(config_digest, str) or not IMAGE_DIGEST.fullmatch(config_digest):
            raise ValueError(f"base image {role} has an invalid OCI config digest")
        propagation = entry.get("propagation_class")
        if propagation not in PROPAGATION_CLASSES:
            raise ValueError(f"base image {role} has an invalid propagation class")
        roles.add(role)
        result.append(
            {
                **entry,
                "archive_path": archive,
                "license_evidence_path": evidence_path,
            }
        )
    return result


def _validate_base_image_specs(value: Any) -> list[dict[str, Any]]:  # noqa: C901, PLR0912
    if not isinstance(value, list) or not value:
        raise ValueError("base image specification is empty")
    result: list[dict[str, Any]] = []
    roles: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("base image specification entry must be an object")
        role = entry.get("role")
        if not isinstance(role, str) or not role or role in roles:
            raise ValueError("base image specification role is missing or duplicated")
        if (
            not isinstance(entry.get("local_reference"), str)
            or "@sha256:" not in entry["local_reference"]
        ):
            raise ValueError(f"base image {role} has no local content reference")
        if not IMAGE_DIGEST.fullmatch(str(entry.get("digest"))):
            raise ValueError(f"base image {role} has an invalid content digest")
        archive = _safe_relative_path(entry.get("archive_path"))
        if not SHA256.fullmatch(str(entry.get("archive_sha256"))):
            raise ValueError(f"base image {role} has an invalid archive SHA256")
        if not isinstance(entry.get("archive_size_bytes"), int) or entry["archive_size_bytes"] < 0:
            raise ValueError(f"base image {role} has an invalid archive size")
        if not IMAGE_DIGEST.fullmatch(str(entry.get("oci_manifest_digest"))):
            raise ValueError(f"base image {role} has an invalid OCI manifest digest")
        if not IMAGE_DIGEST.fullmatch(str(entry.get("config_digest"))):
            raise ValueError(f"base image {role} has an invalid OCI config digest")
        if not _is_spdx_expression(str(entry.get("spdx_license_id"))):
            raise ValueError(f"base image {role} has invalid SPDX evidence")
        if not isinstance(entry.get("license_evidence"), str) or not entry["license_evidence"]:
            raise ValueError(f"base image {role} lacks license evidence description")
        propagation = entry.get("propagation_class")
        if propagation not in PROPAGATION_CLASSES:
            raise ValueError(f"base image {role} has an invalid propagation class")
        if not isinstance(entry.get("obligations"), list) or not entry["obligations"]:
            raise ValueError(f"base image {role} lacks license obligations")
        if not isinstance(entry.get("disposition"), str) or not entry["disposition"]:
            raise ValueError(f"base image {role} lacks license disposition")
        roles.add(role)
        result.append({**entry, "archive_path": archive})
    return result


def _read_tar_json(archive: tarfile.TarFile, name: str) -> dict[str, Any]:
    try:
        stream = archive.extractfile(name)
    except KeyError as exc:
        raise ValueError(f"OCI archive is missing {name}") from exc
    if stream is None:
        raise ValueError(f"OCI archive member {name} is not a regular file")
    value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"OCI archive member {name} must contain a JSON object")
    return value


def _validate_oci_archive(path: Path, image: dict[str, Any]) -> None:
    role = str(image["role"])
    with tarfile.open(path, mode="r:") as archive:
        index = _read_tar_json(archive, "index.json")
        manifests = index.get("manifests")
        if not isinstance(manifests, list):
            raise ValueError(f"base image {role} OCI index has no manifests")
        expected_manifest = str(image["oci_manifest_digest"])
        matches = [
            item
            for item in manifests
            if isinstance(item, dict)
            and item.get("digest") == expected_manifest
            and item.get("platform") == {"architecture": "amd64", "os": "linux"}
        ]
        if len(matches) != 1:
            raise ValueError(f"base image {role} OCI manifest binding is missing or ambiguous")
        manifest_blob = f"blobs/sha256/{expected_manifest.split(':', 1)[1]}"
        try:
            manifest_member = archive.getmember(manifest_blob)
        except KeyError as exc:
            raise ValueError(f"base image {role} OCI manifest blob is missing") from exc
        manifest_stream = archive.extractfile(manifest_member)
        if manifest_stream is None:
            raise ValueError(f"base image {role} OCI manifest blob is not a file")
        manifest_bytes = manifest_stream.read()
        if "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest:
            raise ValueError(f"base image {role} OCI manifest blob digest does not match")
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict):
            raise ValueError(f"base image {role} OCI manifest blob is invalid")
        config = manifest.get("config")
        if not isinstance(config, dict) or config.get("digest") != image["config_digest"]:
            raise ValueError(f"base image {role} OCI config binding does not match")
        config_blob = f"blobs/sha256/{str(image['config_digest']).split(':', 1)[1]}"
        try:
            config_member = archive.getmember(config_blob)
        except KeyError as exc:
            raise ValueError(f"base image {role} OCI config blob is missing") from exc
        if not config_member.isfile():
            raise ValueError(f"base image {role} OCI config blob is not a file")
        config_stream = archive.extractfile(config_member)
        if config_stream is None:
            raise ValueError(f"base image {role} OCI config blob cannot be read")
        config_bytes = config_stream.read()
        expected_config = str(image["config_digest"])
        if "sha256:" + hashlib.sha256(config_bytes).hexdigest() != expected_config:
            raise ValueError(f"base image {role} OCI config blob digest does not match")


def validate_manifest(document: dict[str, Any]) -> list[dict[str, Any]]:
    if document.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("supply-chain manifest has the wrong schema")
    if document.get("process_version") != PROCESS_VERSION:
        raise ValueError("supply-chain manifest has the wrong process version")
    required = document.get("required_directories")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(item, str) for item in required)
    ):
        raise ValueError("supply-chain required_directories is invalid")
    entries = _file_entries(document)
    base_images = _validate_base_images(document)
    by_path = {entry["path"]: entry for entry in entries}
    for image in base_images:
        archive = image["archive_path"]
        archived = by_path.get(archive)
        if archived is None or archived["manifest_section"] != "oci_layouts":
            raise ValueError(f"base image {image['role']} archive is not in oci_layouts")
        if (
            archived["sha256"] != image["archive_sha256"]
            or archived["size_bytes"] != image["archive_size_bytes"]
        ):
            raise ValueError(f"base image {image['role']} archive binding does not match manifest")
    return entries


def _dockerfile_paths(root: Path) -> list[Path]:
    configured = (
        "infra/backend.Dockerfile",
        "infra/frontend.Dockerfile",
        "infra/mock-provider.Dockerfile",
        "tests/load/Dockerfile",
        "tests/load/jemalloc-profile.Dockerfile",
    )
    paths = [root / relative for relative in configured]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"required Dockerfiles are missing: {', '.join(missing)}")
    return paths


def validate_dockerfiles(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in _dockerfile_paths(root):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        if REMOTE_ADD.search(text):
            raise ValueError(f"{relative} contains a remote Dockerfile ADD")
        for match in REMOTE_FETCH.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            line_text = text.splitlines()[line - 1].strip()
            if "apk add" in match.group(0).lower() and "--no-network" in line_text:
                continue
            if "pip install" in match.group(0).lower() and "--no-index" in line_text:
                continue
            if "uv " in match.group(0).lower() and "--offline" in line_text:
                continue
            if "pnpm" in match.group(0).lower() and "--offline" in line_text:
                continue
            raise ValueError(f"{relative}:{line} contains an online build operation: {line_text}")
        findings.append({"path": relative, "status": "offline-build-policy-passed"})
    return findings


def _docker_image_id(reference: str) -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise ValueError("docker executable is not available")
    completed = subprocess.run(  # noqa: S603 - fixed docker subcommand and format.
        (docker, "image", "inspect", reference, "--format", "{{.Id}}"),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _asset_license(path: Path) -> tuple[str, str]:  # noqa: C901, PLR0911
    """Extract a declared license where the archive format exposes one."""
    if path.name in LICENSE_OVERRIDES:
        return LICENSE_OVERRIDES[path.name]
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            metadata = next(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )
            fields = archive.read(metadata).decode("utf-8", errors="replace").splitlines()
        values = [
            line.split(":", 1)[1].strip()
            for line in fields
            if line.startswith(("License-Expression:", "License:"))
        ]
        if not values:
            classifiers = [
                line.rsplit("::", 1)[-1].strip()
                for line in fields
                if line.startswith("Classifier: License :: OSI Approved ::")
            ]
            values.extend(classifiers[:1])
        return (
            _normalise_license(values[0]) if values else "LicenseRef-CyberControl-Python-Declared",
            "wheel METADATA",
        )
    if path.suffix == ".apk":
        with tarfile.open(path, mode="r:*") as archive:
            pkginfo = next(
                (
                    archive.extractfile(member)
                    for member in archive.getmembers()
                    if PurePosixPath(member.name).name == ".PKGINFO"
                ),
                None,
            )
            if pkginfo is not None:
                for line in pkginfo.read().decode("utf-8", errors="replace").splitlines():
                    if line.startswith("license = "):
                        return _normalise_license(line.split("=", 1)[1]), "Alpine .PKGINFO"
        return "LicenseRef-CyberControl-Alpine-Package-Metadata", "Alpine .PKGINFO"
    if path.name.endswith(".tar.bz2") and "jemalloc" in path.name:
        return "BSD-2-Clause", "jemalloc COPYING"
    if path.name.startswith("uv-"):
        return "MIT OR Apache-2.0", "uv release licensing"
    if path.name.startswith("corepack-pnpm-"):
        return "MIT", "pnpm package-manager licensing"
    if path.suffix == ".patch":
        return "MIT", "Alpine aports patch provenance"
    if path.suffix == ".json":
        return "LicenseRef-CyberControl-Build-Metadata", "repository build metadata"
    return "LicenseRef-CyberControl-Catalogued-Build-Input", "catalogued build input"


def _archive_fields(path: Path, member_name: str) -> dict[str, str]:
    with tarfile.open(path, mode="r:*") as archive:
        member = next(
            (item for item in archive.getmembers() if PurePosixPath(item.name).name == member_name),
            None,
        )
        stream = archive.extractfile(member) if member is not None else None
        lines = stream.read().decode("utf-8", errors="replace").splitlines() if stream else []
    result: dict[str, str] = {}
    for line in lines:
        if " = " in line:
            name, value = line.split(" = ", 1)
            result.setdefault(name.strip(), value.strip())
    return result


def _asset_identity(path: Path) -> dict[str, str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            metadata = next(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )
            fields = archive.read(metadata).decode("utf-8", errors="replace").splitlines()
        values: dict[str, str] = {}
        for line in fields:
            if ":" in line:
                name, value = line.split(":", 1)
                if name in {"Name", "Version", "Home-page", "Project-URL"}:
                    values.setdefault(name, value.strip())
        source = values.get("Home-page") or values.get("Project-URL", "")
        if "," in source:
            source = source.split(",", 1)[1].strip()
        return {
            "component": values.get("Name", path.stem),
            "version": values.get("Version", "unknown"),
            "source": source or "https://pypi.org/",
        }
    if path.suffix == ".apk":
        fields = _archive_fields(path, ".PKGINFO")
        return {
            "component": fields.get("pkgname", path.stem),
            "version": fields.get("pkgver", "unknown"),
            "source": fields.get("url", "https://pkgs.alpinelinux.org/"),
        }
    known = {
        "jemalloc-5.3.0.tar.bz2": (
            "jemalloc",
            "5.3.0",
            "https://github.com/jemalloc/jemalloc/releases/tag/5.3.0",
        ),
        "uv-0.11.28-x86_64-unknown-linux-musl.tar.gz": (
            "uv",
            "0.11.28",
            "https://github.com/astral-sh/uv/releases/tag/0.11.28",
        ),
        "corepack-pnpm-11.7.0.tgz": (
            "pnpm",
            "11.7.0",
            "https://www.npmjs.com/package/pnpm/v/11.7.0",
        ),
        "pnpm-store-v11-linux.tgz": (
            "cybercontrol-pnpm-offline-store",
            "11.7.0",
            "repository://frontend/pnpm-lock.yaml",
        ),
        "musl-exception-specification-errors.patch": (
            "alpine-jemalloc-musl-patch",
            "fa59839ba07b53b11d12e849222439c785125d6a",
            "https://gitlab.alpinelinux.org/alpine/aports/-/tree/fa59839ba07b53b11d12e849222439c785125d6a/main/jemalloc",
        ),
        "pkgconf.patch": (
            "alpine-jemalloc-pkgconf-patch",
            "fa59839ba07b53b11d12e849222439c785125d6a",
            "https://gitlab.alpinelinux.org/alpine/aports/-/tree/fa59839ba07b53b11d12e849222439c785125d6a/main/jemalloc",
        ),
        "zope_interface-8.5.tar.gz": (
            "zope-interface",
            "8.5",
            "https://pypi.org/project/zope-interface/8.5/",
        ),
    }
    if path.name in known:
        component, version, source = known[path.name]
        return {"component": component, "version": version, "source": source}
    if path.name.endswith("-requirements.txt"):
        return {
            "component": path.stem,
            "version": "uv-lock-export-v1",
            "source": "repository://uv.lock",
        }
    if path.suffix == ".json":
        return {
            "component": path.stem,
            "version": PROCESS_VERSION,
            "source": f"repository://{path.name}",
        }
    return {
        "component": path.stem,
        "version": "content-addressed",
        "source": "repository://third_party/gate-c-build",
    }


def _license_decision(license_id: str, propagation: str) -> tuple[list[str], str]:
    obligations = ["retain-license-evidence"]
    if propagation == "BUILD_ONLY_TRANSIENT":
        return [*obligations, "record-build-only-use"], "BUILD_ONLY_LICENSE_RETAINED"
    if propagation == "DIAGNOSTIC_ONLY":
        return (
            [*obligations, "diagnostic-sbom", "exclude-from-formal-image"],
            "DIAGNOSTIC_ONLY_EXCLUDED_FROM_FORMAL",
        )
    prohibited = ("AGPL", "SSPL", "BUSL", "Commons-Clause", "Elastic-License")
    if propagation in {"RUNTIME_COPIED", "LINKED_OR_DERIVED"} and any(
        family.lower() in license_id.lower() for family in prohibited
    ):
        raise ValueError(f"prohibited {propagation} license: {license_id}")
    if (
        propagation in {"RUNTIME_COPIED", "LINKED_OR_DERIVED"}
        and re.search(r"(?<!L)GPL-", license_id)
        and "GCC-exception" not in license_id
    ):
        raise ValueError(f"GPL {propagation} license lacks an approved runtime exception")
    if propagation == "LINKED_OR_DERIVED":
        return (
            [*obligations, "record-derivation", "retain-source-or-notice"],
            "DERIVATION_LICENSE_REVIEWED",
        )
    return (
        [*obligations, "runtime-license-policy-review", "retain-notice"],
        "RUNTIME_LICENSE_REVIEWED",
    )


def _propagation_class(section: str, path: Path) -> str:
    name = path.name
    if section == "python_wheels":
        return "RUNTIME_COPIED"
    if section == "oci_layouts":
        return "RUNTIME_COPIED"
    if section == "apk" and name in {
        "jemalloc-5.3.0-r6.apk",
        "libgcc-15.2.0-r5.apk",
        "libstdc++-15.2.0-r5.apk",
        "libcrypto3-3.5.8-r0.apk",
        "libssl3-3.5.8-r0.apk",
    }:
        return "RUNTIME_COPIED"
    if section == "apk" and name in {
        "binutils-2.45.1-r1.apk",
        "libunwind-1.8.3-r0.apk",
        "perl-5.42.2-r0.apk",
    }:
        return "DIAGNOSTIC_ONLY"
    if section in {"patches"} or (section == "sources" and "jemalloc" in name):
        return "LINKED_OR_DERIVED"
    return "BUILD_ONLY_TRANSIENT"


def _asset_files(root: Path, base_spec_path: Path | None = None) -> dict[str, list[Path]]:
    base = root / "third_party/gate-c-build"
    source_dir = base / "sources"
    return {
        "sources": sorted(
            [
                path
                for path in source_dir.glob("*")
                if path.is_file() and path.name != "asset-license-catalog.json"
            ]
            + list((base / "python-wheelhouse").glob("*-requirements.txt"))
            + list((base / "python-wheelhouse").glob("*.tar.gz"))
        ),
        "patches": sorted((base / "patches").glob("*.patch")),
        "apk": sorted((base / "apk").glob("*.apk")),
        "python_wheels": sorted((base / "python-wheelhouse").glob("*.whl")),
        "pnpm_store": sorted((base / "pnpm-store").glob("*.tgz")),
        "oci_layouts": sorted((base / "oci-layouts").glob("*.tar")),
        "licenses": sorted(
            path
            for path in (base / "licenses").glob("*")
            if path.is_file()
            and path.name not in {"asset-license-catalog.json", "license-policy.json"}
        )
        + ([base_spec_path] if base_spec_path is not None else []),
    }


def generate(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    base = root / "third_party/gate-c-build"
    catalog_path = base / "licenses/asset-license-catalog.json"
    policy_path = base / "licenses/license-policy.json"
    base_spec_path = (root / args.base_images).resolve()
    base_specs = _read_json(base_spec_path)
    if base_specs.get("schema_version") != BASE_IMAGE_SPEC_SCHEMA:
        raise ValueError("base image specification has the wrong schema")
    if base_specs.get("process_version") != PROCESS_VERSION:
        raise ValueError("base image specification has the wrong process version")
    base_images = _validate_base_image_specs(base_specs.get("base_images"))

    policy = {
        "schema_version": LICENSE_POLICY_SCHEMA,
        "process_version": PROCESS_VERSION,
        "license_propagation_rule": {
            "BUILD_ONLY_TRANSIENT": (
                "Build-only inputs retain notice and source obligations but do not "
                "propagate into the runtime product image."
            ),
            "RUNTIME_COPIED": (
                "Inputs copied into a runtime image are governed by the runtime license policy."
            ),
            "LINKED_OR_DERIVED": (
                "Linked, patched, or compiled outputs require a derivation and notice review."
            ),
            "DIAGNOSTIC_ONLY": (
                "Diagnostic-only inputs require a separate SBOM and are excluded from "
                "formal images."
            ),
        },
        "runtime_prohibited_families": [
            "AGPL",
            "GPL",
            "SSPL",
            "BUSL",
            "Commons-Clause",
            "Elastic-License",
        ],
        "metadata_normalization": LICENSE_ALIASES,
        "base_image_spec": str(base_spec_path.relative_to(root)).replace("\\", "/"),
    }
    _write_json(policy_path, policy)

    catalog: list[dict[str, Any]] = []
    files = _asset_files(root, base_spec_path)
    base_by_archive = {
        _safe_relative_path(image["archive_path"]): image
        for image in base_images
        if isinstance(image, dict)
    }
    for section, paths in files.items():
        for path in paths:
            relative = path.relative_to(root).as_posix()
            base_image = base_by_archive.get(relative)
            if base_image is not None:
                license_id = str(base_image["spdx_license_id"])
                evidence = str(base_image.get("license_evidence", "base image license notice"))
            else:
                license_id, evidence = _asset_license(path)
            catalog.append(
                {
                    **(
                        {
                            "component": str(base_image["role"]),
                            "version": str(base_image["digest"]),
                            "source": str(base_image["source"]),
                        }
                        if base_image is not None
                        else _asset_identity(path)
                    ),
                    "path": relative,
                    "sha256": sha256(path),
                    "size_bytes": path.stat().st_size,
                    "spdx_license_id": license_id,
                    "evidence": evidence,
                    "propagation_class": (
                        str(base_image["propagation_class"])
                        if base_image is not None
                        else _propagation_class(section, path)
                    ),
                    "distribution_scope": section,
                }
            )
    catalog.sort(key=lambda item: item["path"])
    catalog_document = {
        "schema_version": LICENSE_CATALOG_SCHEMA,
        "process_version": PROCESS_VERSION,
        "license_policy": {
            "path": policy_path.relative_to(root).as_posix(),
            "sha256": sha256(policy_path),
        },
        "components": catalog,
    }
    _write_json(catalog_path, catalog_document)
    evidence_hash = sha256(catalog_path)

    policy_hash = sha256(policy_path)

    def entry(path: Path, section: str) -> dict[str, Any]:
        relative = path.relative_to(root).as_posix()
        base_image = base_by_archive.get(relative)
        license_id = (
            str(base_image["spdx_license_id"])
            if base_image is not None
            else _asset_license(path)[0]
        )
        propagation = (
            str(base_image.get("propagation_class"))
            if base_image is not None
            else _propagation_class(section, path)
        )
        obligations, disposition = _license_decision(license_id, propagation)
        identity = (
            {
                "component": str(base_image["role"]),
                "version": str(base_image["digest"]),
                "source": str(base_image["source"]),
            }
            if base_image is not None
            else _asset_identity(path)
        )
        evidence_path = (
            policy_path.relative_to(root).as_posix()
            if path in {policy_path, catalog_path}
            else catalog_path.relative_to(root).as_posix()
        )
        evidence_digest = policy_hash if path in {policy_path, catalog_path} else evidence_hash
        return {
            **identity,
            "path": relative,
            "sha256": sha256(path),
            "size_bytes": path.stat().st_size,
            "spdx_license_id": license_id,
            "license_evidence_path": evidence_path,
            "license_evidence_sha256": evidence_digest,
            "propagation_class": propagation,
            "distribution_scope": section,
            "obligations": obligations,
            "disposition": disposition,
        }

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "process_version": PROCESS_VERSION,
        "required_directories": [
            "third_party/gate-c-build/sources",
            "third_party/gate-c-build/patches",
            "third_party/gate-c-build/apk",
            "third_party/gate-c-build/python-wheelhouse",
            "third_party/gate-c-build/pnpm-store",
            "third_party/gate-c-build/oci-layouts",
            "third_party/gate-c-build/licenses",
        ],
        "sources": [],
        "patches": [],
        "apk": [],
        "python_wheels": [],
        "pnpm_store": [],
        "oci_layouts": [],
        "licenses": [],
        "base_images": [dict(image) for image in base_images],
    }
    for section, paths in files.items():
        manifest[section] = [entry(path, section) for path in paths]
    # Generated license records are inputs too; their evidence points to the
    # catalog, whose policy binding points back to the non-circular policy file.
    manifest["licenses"].append(entry(policy_path, "licenses"))
    manifest["licenses"].append(entry(catalog_path, "licenses"))
    for image in manifest["base_images"]:
        image["license_evidence_path"] = policy_path.relative_to(root).as_posix()
        image["license_evidence_sha256"] = policy_hash
    _write_json(base / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "result": "generated",
                "asset_count": len(catalog),
                "manifest": str(base / "manifest.json"),
            },
            sort_keys=True,
        )
    )


def validate_assets(root: Path, document: dict[str, Any]) -> list[dict[str, Any]]:
    entries = _file_entries(document)
    results: list[dict[str, Any]] = []
    for entry in entries:
        path = (root / entry["path"]).resolve()
        if root not in path.parents:
            raise ValueError(f"supply-chain input escapes repository root: {entry['path']}")
        if not path.is_file():
            raise ValueError(f"supply-chain input is missing: {entry['path']}")
        observed_size = path.stat().st_size
        observed_digest = sha256(path)
        if observed_size != entry["size_bytes"] or observed_digest != entry["sha256"]:
            raise ValueError(f"supply-chain input hash mismatch: {entry['path']}")
        license_evidence = (root / _safe_relative_path(entry["license_evidence_path"])).resolve()
        if root not in license_evidence.parents:
            raise ValueError(f"license evidence escapes repository root: {entry['path']}")
        if (
            not license_evidence.is_file()
            or sha256(license_evidence) != entry["license_evidence_sha256"]
        ):
            raise ValueError(f"license evidence hash mismatch: {entry['path']}")
        results.append(
            {
                "path": entry["path"],
                "size_bytes": observed_size,
                "sha256": observed_digest,
                "propagation_class": entry["propagation_class"],
            }
        )
    for image in _validate_base_images(document):
        _validate_oci_archive((root / image["archive_path"]).resolve(), image)
    return results


def verify(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    manifest_path = (root / args.manifest).resolve()
    document = _read_json(manifest_path)
    entries = validate_manifest(document)
    required_dirs = [
        _safe_relative_path(item).rstrip("/") for item in document["required_directories"]
    ]
    missing_dirs = [item for item in required_dirs if not (root / item).is_dir()]
    if missing_dirs:
        raise ValueError(f"supply-chain directories are missing: {', '.join(missing_dirs)}")
    findings = validate_dockerfiles(root)
    asset_results = validate_assets(root, document)
    base_results: list[dict[str, Any]] = []
    if not args.skip_docker:
        for image in _validate_base_images(document):
            observed = _docker_image_id(str(image["local_reference"]))
            expected = str(image["digest"])
            if observed != expected:
                raise ValueError(
                    f"local base image {image['role']} has content {observed}, expected {expected}"
                )
            base_results.append(
                {"role": image["role"], "reference": image["local_reference"], "image_id": observed}
            )
    report = {
        "schema_version": "cybercontrol.gate-c-build-supply-chain-verification.v1",
        "process_version": PROCESS_VERSION,
        "manifest": {
            "path": str(manifest_path.relative_to(root)).replace("\\", "/"),
            "sha256": sha256(manifest_path),
        },
        "dockerfiles": findings,
        "asset_count": len(entries),
        "assets": asset_results,
        "base_images": base_results,
        "network_policy": "BUILD_NETWORK_NONE_OR_OFFLINE_LOCAL_MIRRORS",
        "result": "passed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": "passed", "asset_count": len(entries)}, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the offline Gate C build supply chain.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command")
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument(
        "--base-images",
        type=Path,
        default=Path("third_party/gate-c-build/base-images.json"),
    )
    generate_parser.set_defaults(handler=generate)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("third_party/gate-c-build/manifest.json"),
    )
    verify_parser.add_argument("--output", type=Path, required=True)
    verify_parser.add_argument("--skip-docker", action="store_true")
    verify_parser.set_defaults(handler=verify)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Gate C supply-chain error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
