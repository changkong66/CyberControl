from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path
from typing import Any

PROCESS_VERSION = "Gate-C-12-v2.0"
FORBIDDEN_NAMES = frozenset({"server.key", "postgres-password", "ca.key"})
FORBIDDEN_CONTENT = (b"-----BEGIN PRIVATE KEY-----", b"-----BEGIN RSA PRIVATE KEY-----")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)


def _files(
    evidence_directory: Path,
    forbidden_values: tuple[bytes, ...],
) -> list[tuple[str, bytes]]:
    evidence_directory = evidence_directory.resolve(strict=True)
    if not evidence_directory.is_dir() or evidence_directory.is_symlink():
        raise ValueError("evidence directory must be a real directory")
    files: list[tuple[str, bytes]] = []
    for path in sorted(evidence_directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"evidence cannot contain a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(evidence_directory).as_posix()
        if path.name in FORBIDDEN_NAMES:
            raise ValueError(f"evidence contains forbidden secret file {relative}")
        content = path.read_bytes()
        if any(marker in content for marker in (*FORBIDDEN_CONTENT, *forbidden_values)):
            raise ValueError(f"evidence contains forbidden secret content in {relative}")
        files.append((relative, content))
    if not files:
        raise ValueError("evidence directory is empty")
    return files


def create_package(
    evidence_directory: Path,
    package_path: Path,
    manifest_path: Path,
    *,
    run_id: str,
    process_version: str,
    forbidden_values: tuple[bytes, ...] = (),
) -> dict[str, Any]:
    if not run_id or run_id != run_id.strip():
        raise ValueError("evidence run ID is invalid")
    if re.fullmatch(r"Gate-C-12-v[12]\.0", process_version) is None:
        raise ValueError("evidence process version is invalid")
    if package_path.exists() or manifest_path.exists():
        raise FileExistsError("evidence package or manifest already exists")
    files = _files(evidence_directory, forbidden_values)
    manifest: dict[str, Any] = {
        "schema_version": "cybercontrol.gate-c-diagnostic-evidence-manifest.v1",
        "process_version": process_version,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "run_id": run_id,
        "files": [
            {"path": relative, "size_bytes": len(content), "sha256": _sha256(content)}
            for relative, content in files
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    _write_new(manifest_path, manifest_bytes)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        package_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for relative, content in [*files, ("evidence-manifest.json", manifest_bytes)]:
            info = zipfile.ZipInfo(relative, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    verify_package(package_path, manifest)
    manifest["package"] = {
        "path": package_path.name,
        "size_bytes": package_path.stat().st_size,
        "sha256": _sha256(package_path.read_bytes()),
    }
    return manifest


def verify_package(package_path: Path, manifest: dict[str, Any]) -> None:
    expected = {
        item["path"]: (int(item["size_bytes"]), str(item["sha256"])) for item in manifest["files"]
    }
    with zipfile.ZipFile(package_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != {*expected, "evidence-manifest.json"}:
            raise ValueError("evidence package members do not match the manifest")
        for name, (size, digest) in expected.items():
            content = archive.read(name)
            if len(content) != size or _sha256(content) != digest:
                raise ValueError(f"evidence package member failed verification: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an immutable diagnostic evidence package.")
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--process-version", required=True)
    parser.add_argument("--forbidden-value-file", type=Path, action="append", default=[])
    arguments = parser.parse_args()
    values = (path.read_bytes().strip() for path in arguments.forbidden_value_file)
    forbidden_values = tuple(value for value in values if value)
    result = create_package(
        arguments.evidence_directory,
        arguments.package,
        arguments.manifest,
        run_id=arguments.run_id,
        process_version=arguments.process_version,
        forbidden_values=forbidden_values,
    )
    print(json.dumps(result["package"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
