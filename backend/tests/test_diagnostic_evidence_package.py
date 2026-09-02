from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOAD_ROOT = ROOT / "tests" / "load"
if str(LOAD_ROOT) not in sys.path:
    sys.path.insert(0, str(LOAD_ROOT))

from gate_c.diagnostic_evidence_package import create_package  # noqa: E402


def test_package_is_deterministic_complete_and_non_formal(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "result.json").write_text('{"passed":true}\n', encoding="ascii")
    (evidence / "logs").mkdir()
    (evidence / "logs" / "compose.log").write_text("clean\n", encoding="ascii")

    first = create_package(
        evidence,
        tmp_path / "first.zip",
        tmp_path / "first-manifest.json",
        run_id="run-a",
        process_version="Gate-C-12-v2.0",
    )
    second = create_package(
        evidence,
        tmp_path / "second.zip",
        tmp_path / "second-manifest.json",
        run_id="run-a",
        process_version="Gate-C-12-v2.0",
    )

    assert first["package"]["sha256"] == second["package"]["sha256"]
    assert first["process_version"] == "Gate-C-12-v2.0"
    assert first["formal_gate_attempt"] is False
    assert first["acceptance_claim"] is False
    assert {item["path"] for item in first["files"]} == {
        "logs/compose.log",
        "result.json",
    }
    with zipfile.ZipFile(tmp_path / "first.zip") as archive:
        embedded = json.loads(archive.read("evidence-manifest.json"))
    assert embedded["run_id"] == "run-a"


def test_package_requires_an_explicit_supported_process_version(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "result.json").write_text("{}\n", encoding="ascii")

    with pytest.raises(ValueError, match="process version"):
        create_package(
            evidence,
            tmp_path / "invalid.zip",
            tmp_path / "invalid-manifest.json",
            run_id="run-invalid-version",
            process_version="Gate-C-12-v3.0",
        )


@pytest.mark.parametrize(
    ("name", "content"),
    (
        ("server.key", b"not-even-a-key"),
        ("log.txt", b"-----BEGIN PRIVATE KEY-----\nsecret"),
        ("log.txt", b"database-password"),
    ),
)
def test_package_rejects_secrets_and_leaves_no_artifact(
    tmp_path: Path, name: str, content: bytes
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / name).write_bytes(content)
    package = tmp_path / "must-not-exist.zip"
    manifest = tmp_path / "must-not-exist.json"

    with pytest.raises(ValueError, match="forbidden"):
        create_package(
            evidence,
            package,
            manifest,
            run_id="run-secret",
            process_version="Gate-C-12-v2.0",
            forbidden_values=(b"database-password",),
        )
    assert not package.exists()
    assert not manifest.exists()


def test_package_rejects_preexisting_outputs_and_symlinks(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "result.json").write_text("{}", encoding="ascii")
    package = tmp_path / "existing.zip"
    package.write_bytes(b"preserve")

    with pytest.raises(FileExistsError, match="already exists"):
        create_package(
            evidence,
            package,
            tmp_path / "manifest.json",
            run_id="run-existing",
            process_version="Gate-C-12-v2.0",
        )
    assert package.read_bytes() == b"preserve"
