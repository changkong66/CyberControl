from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_gate_c_metadata import PROCESS_VERSION, validate_document  # noqa: E402


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
