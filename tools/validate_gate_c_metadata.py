"""Validate process metadata on newly changed Gate C evidence documents."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

PROCESS_VERSION = "Gate-C-12-v1.0"
REPORT_SCHEMA = "cybercontrol.gate-c-process-metadata-validation.v1"
_PROCESS_VERSION_LINE = re.compile(
    rf"(?im)^\s*process version\s*:\s*`?{re.escape(PROCESS_VERSION)}`?\s*$"
)
_YAML_PROCESS_VERSION_LINE = re.compile(
    rf"(?im)^\s*process_version\s*:\s*['\"]?{re.escape(PROCESS_VERSION)}['\"]?\s*$"
)
_GOVERNED_PREFIXES = (
    "docs/adr/",
    "docs/diagnostics/",
    "docs/evidence/",
    "docs/system-acceptance/",
    "artifacts/",
)
_EVIDENCE_NAME_PARTS = ("evidence", "receipt", "manifest", "report", "snapshot")


def _run_git(root: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - arguments are fixed Git queries.
        ("git", *arguments),  # noqa: S607 - executable is fixed to Git.
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    output = _run_git(root, "diff", "--name-only", "--diff-filter=AMRT", base, head)
    return sorted({line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()})


def immutable_path_mutations(root: Path, base: str, head: str) -> list[dict[str, str]]:
    output = _run_git(root, "diff", "--name-status", "--diff-filter=DR", base, head)
    mutations: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = line.strip().split("\t")
        if not fields:
            continue
        status = fields[0]
        source = fields[1].replace("\\", "/") if len(fields) > 1 else ""
        if source and is_governed_path(source):
            mutations.append({"status": status, "path": source})
    return mutations


def is_governed_path(path: str) -> bool:
    normalized = path.lower()
    if normalized.startswith(_GOVERNED_PREFIXES):
        return Path(normalized).suffix in {".json", ".md", ".yaml", ".yml"}
    name = Path(normalized).name
    return Path(normalized).suffix in {".json", ".md"} and any(
        part in name for part in _EVIDENCE_NAME_PARTS
    )


def validate_document(path: Path, content: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            document = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise ValueError(f"{path} must contain a JSON object")
        if document.get("process_version") != PROCESS_VERSION:
            raise ValueError(
                f"{path} must declare process_version {PROCESS_VERSION}; "
                f"found {document.get('process_version')!r}"
            )
        return {"path": path.as_posix(), "format": "json", "validated": True}
    if suffix in {".yaml", ".yml"}:
        if not _YAML_PROCESS_VERSION_LINE.search(content):
            raise ValueError(f"{path} must declare process_version: {PROCESS_VERSION}")
        return {"path": path.as_posix(), "format": suffix.removeprefix("."), "validated": True}
    if not _PROCESS_VERSION_LINE.search(content):
        raise ValueError(f"{path} must contain a Process Version: {PROCESS_VERSION} declaration")
    return {"path": path.as_posix(), "format": suffix.removeprefix("."), "validated": True}


def validate_changed_documents(root: Path, base: str, head: str) -> dict[str, Any]:
    paths = changed_paths(root, base, head)
    immutable_mutations = immutable_path_mutations(root, base, head)
    governed = [Path(path) for path in paths if is_governed_path(path)]
    documents: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    failures.extend(
        {
            "path": mutation["path"],
            "error": "governed evidence and status paths cannot be deleted or renamed",
        }
        for mutation in immutable_mutations
    )
    for path in governed:
        try:
            documents.append(validate_document(path, path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            failures.append({"path": path.as_posix(), "error": str(exc)})
    return {
        "schema_version": REPORT_SCHEMA,
        "process_version": PROCESS_VERSION,
        "base": base,
        "head": head,
        "changed_paths": paths,
        "governed_documents": documents,
        "immutable_path_mutations": immutable_mutations,
        "failures": failures,
        "passed": not failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    report = validate_changed_documents(root, arguments.base, arguments.head)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
