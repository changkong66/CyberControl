from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import validate_gate_c_metadata as metadata  # noqa: E402

PROCESS_VERSION = metadata.PROCESS_VERSION
validate_document = metadata.validate_document


def test_json_evidence_requires_current_process_version(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    valid = json.dumps({"process_version": PROCESS_VERSION, "result": "PASS"})

    assert validate_document(path, valid)["validated"] is True

    with pytest.raises(ValueError, match="process_version"):
        validate_document(path, json.dumps({"result": "PASS"}))


def test_markdown_evidence_requires_current_process_version() -> None:
    path = Path("docs/diagnostics/example-report.md")

    assert validate_document(path, f"Process Version: `{PROCESS_VERSION}`\n")["validated"] is True

    with pytest.raises(ValueError, match="Process Version"):
        validate_document(path, "# Evidence\n")


def test_yaml_evidence_requires_structured_process_version() -> None:
    path = Path("docs/evidence/example-manifest.yaml")

    assert validate_document(path, f'process_version: "{PROCESS_VERSION}"\n')["validated"] is True
    with pytest.raises(ValueError, match="process_version"):
        validate_document(path, "result: PASS\n")


def test_governed_evidence_delete_or_rename_is_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        metadata,
        "_run_git",
        lambda *_args: (
            "D\tdocs/evidence/formal-receipt.json\n"
            "R100\tdocs/diagnostics/owner-report.md\tdocs/diagnostics/moved.md\n"
            "D\tREADME.md\n"
        ),
    )

    mutations = metadata.immutable_path_mutations(tmp_path, "base", "head")

    assert mutations == [
        {"status": "D", "path": "docs/evidence/formal-receipt.json"},
        {"status": "R100", "path": "docs/diagnostics/owner-report.md"},
    ]
