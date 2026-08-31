from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import gate_c_governance as governance  # noqa: E402


def test_history_is_strictly_append_only() -> None:
    before = [{"sequence": 1, "value": "kept"}]

    assert governance._assert_append_only(
        name="history", before=before, after=[*before, {"sequence": 2}]
    ) == [{"sequence": 2}]
    with pytest.raises(ValueError, match="append-only"):
        governance._assert_append_only(
            name="history",
            before=before,
            after=[{"sequence": 1, "value": "rewritten"}],
        )


def test_baseline_type_mapping_preserves_audit_categories() -> None:
    assert governance._baseline_type("DIAGNOSTIC_CAPABILITY") == "DIAGNOSTIC"
    assert governance._baseline_type("FAILED_EVIDENCE_ARCHIVE") == "EVIDENCE"
    assert governance._baseline_type("P2_REMEDIATION") == "REMEDIATION"
    assert governance._baseline_type("STATUS_CLOSURE") == "STATUS"
    assert governance._baseline_type("FOUNDATION_TOOLING") == "INFRA"
    assert governance._baseline_type("RELEASE_PUBLICATION") == "RELEASE"


def test_audit_index_adds_type_without_rewriting_source_history(tmp_path: Path) -> None:
    status_path = tmp_path / "acceptance-status.json"
    evidence_root = tmp_path / "evidence"
    output = tmp_path / "audit-index.json"
    evidence_root.mkdir()
    status = {
        "state": "RELEASE_CANDIDATE",
        "formal_release_state": governance.FORMAL_STATE,
        "baseline": {"product_source_sha": governance.PRODUCT_SOURCE_SHA},
        "baseline_history": [{"sequence": 1, "change_type": "STATUS_CLOSURE"}],
        "gate_c_attempts": [{"sequence": 1, "result": "FAILED"}],
    }
    status_path.write_text(json.dumps(status), encoding="utf-8")
    evidence = evidence_root / "receipt.json"
    evidence.write_text(
        json.dumps({"process_version": governance.PROCESS_VERSION}), encoding="utf-8"
    )

    index = governance.build_audit_index(status_path, evidence_root, output)

    assert index["baseline_history"][0]["type"] == "STATUS"
    assert "type" not in status["baseline_history"][0]
    assert index["evidence"][0]["sha256"] == governance._sha256(evidence)


def test_worktree_rejects_stale_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    values = iter(["a" * 40, "b" * 40, "c" * 40, "d" * 40, ""])
    monkeypatch.setattr(governance, "_run", lambda *_args, **_kwargs: next(values))

    with pytest.raises(ValueError, match="stale"):
        governance.verify_worktree(tmp_path, "origin/main")


def test_formal_attempt_requires_full_execution_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = {
        "baseline": {"product_source_sha": governance.PRODUCT_SOURCE_SHA},
        "formal_release_state": governance.FORMAL_STATE,
        "baseline_history": [],
        "gate_c_attempts": [],
    }
    after = {
        **before,
        "gate_c_attempts": [
            {"sequence": 1, "result": "FAILED", "process_version": governance.PROCESS_VERSION}
        ],
    }
    monkeypatch.setattr(
        governance,
        "_git_json",
        lambda _root, reference: before if reference == "base" else after,
    )
    monkeypatch.setattr(governance, "_changed_paths", lambda *_args: [])

    with pytest.raises(ValueError, match="exactly bound Full execution metadata"):
        governance.validate_history(tmp_path, "base", "head")


def test_formal_attempt_binds_exact_full_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = {
        "sequence": 1,
        "run_id": "gate-c-formal-13",
        "product_source_sha": governance.PRODUCT_SOURCE_SHA,
        "result": "FAILED",
        "process_version": governance.PROCESS_VERSION,
    }
    before = {
        "baseline": {"product_source_sha": governance.PRODUCT_SOURCE_SHA},
        "formal_release_state": governance.FORMAL_STATE,
        "baseline_history": [],
        "gate_c_attempts": [],
    }
    after = {**before, "gate_c_attempts": [attempt]}
    monkeypatch.setattr(
        governance,
        "_git_json",
        lambda _root, reference: before if reference == "base" else after,
    )
    monkeypatch.setattr(governance, "_changed_paths", lambda *_args: ["formal.json"])
    monkeypatch.setattr(
        governance,
        "_formal_metadata_candidates",
        lambda *_args: [
            {
                "mode": "Full",
                "classification": "FORMAL_GATE_C_ATTEMPT",
                "formal_gate_attempt": True,
                "process_version": governance.PROCESS_VERSION,
                "run_id": attempt["run_id"],
                "product_source_sha": governance.PRODUCT_SOURCE_SHA,
            }
        ],
    )

    report = governance.validate_history(tmp_path, "base", "head")

    assert report["gate_c_attempts_appended"] == 1


def test_execution_context_binds_capacity_and_frozen_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tests/load").mkdir(parents=True)
    (tmp_path / "tests/load/gate-c-thresholds.v1.json").write_text(
        '{"threshold": 1}\n', encoding="utf-8"
    )
    (tmp_path / "tests/load/gate-c-workload.v1.json").write_text(
        '{"workload": 1}\n', encoding="utf-8"
    )
    status_path = tmp_path / "status.json"
    status_path.write_text(
        json.dumps(
            {
                "baseline": {
                    "product_source_sha": governance.PRODUCT_SOURCE_SHA,
                    "engineering_baseline_sha": "a" * 40,
                },
                "formal_release_state": governance.FORMAL_STATE,
                "gate_c_attempts": [{}] * 12,
            }
        ),
        encoding="utf-8",
    )
    capacity_path = tmp_path / "capacity.json"
    capacity_path.write_text(
        json.dumps(
            {
                "process_version": governance.PROCESS_VERSION,
                "state": "NORMAL",
                "admission_ready": True,
                "targets": [{"name": "results_root"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        governance,
        "verify_worktree",
        lambda *_args: {"commit": "a" * 40, "tree": "b" * 40},
    )

    context = governance.build_execution_context(
        tmp_path,
        status_path,
        capacity_path,
        "NON_ACCEPTANCE_ENGINEERING",
        False,
        [],
    )

    assert context["source"]["product_source_sha"] == governance.PRODUCT_SOURCE_SHA
    assert context["capacity_snapshot"]["admission_ready"] is True
    assert context["gate_c_attempts"] == 12
    assert context["historical_intent_snapshots_authoritative"] is False


def test_repository_protection_declares_merge_queue() -> None:
    source = (ROOT / "tools/github/configure-repository-protection.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/quality-gates.yml").read_text(encoding="utf-8")

    assert 'type = "merge_queue"' in source
    assert '"merge_queue"' in source
    assert '$repositoryOwnerType -eq "Organization"' in source
    assert 'mode = "STRICT_PROTECTED_SQUASH_FALLBACK"' in source
    assert 'allowed_merge_methods = @("squash")' in source
    assert "allow_squash_merge = $true" in source
    assert "allow_merge_commit = $false" in source
    assert "allow_rebase_merge = $false" in source
    assert "merge_group:" in workflow


def test_governance_subprocess_decodes_utf8_output() -> None:
    assert (
        governance._run(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write('闭环'.encode('utf-8'))",
            ),
            cwd=ROOT,
        )
        == "闭环"
    )
