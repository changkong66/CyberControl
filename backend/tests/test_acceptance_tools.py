from __future__ import annotations

import json
import runpy
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

TOOLS_ROOT = Path(__file__).resolve().parents[2] / "tools" / "topic4"
PHASE7_DATASET_TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "acceptance"
    / "build-phase7-dataset-inventory.py"
)
SYSTEM_ACCEPTANCE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "tools" / "windows" / "run-system-acceptance.ps1"
)
SSE_TOOL = cast(
    dict[str, Any],
    runpy.run_path(
        str(TOOLS_ROOT / "verify-authenticated-sse.py"),
        run_name="verify_authenticated_sse_test",
    ),
)
PHASE7_DATASET_TOOL = cast(
    dict[str, Any],
    runpy.run_path(
        str(PHASE7_DATASET_TOOL_PATH),
        run_name="phase7_dataset_inventory_test",
    ),
)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/internal/topic4/sse/stream",
        "http://127.0.0.1:8000/internal/topic4/sse/stream",
        "http://[::1]:8000/internal/topic4/sse/stream",
    ],
)
def test_sse_acceptance_endpoint_allows_only_loopback(url: str) -> None:
    assert SSE_TOOL["_endpoint"](url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/internal/topic4/sse/stream",
        "http://user:password@localhost:8000/internal/topic4/sse/stream",
        "file:///tmp/token-sink",
    ],
)
def test_sse_acceptance_endpoint_rejects_token_disclosure_targets(url: str) -> None:
    with pytest.raises(SystemExit):
        SSE_TOOL["_endpoint"](url)


def test_sse_acceptance_http_client_disables_proxies_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []
    expected_opener = object()

    def capture_handlers(*handlers: object) -> object:
        captured.extend(handlers)
        return expected_opener

    monkeypatch.setattr(urllib.request, "build_opener", capture_handlers)

    assert SSE_TOOL["_http_opener"]() is expected_opener
    proxy_handler = next(
        handler for handler in captured if isinstance(handler, urllib.request.ProxyHandler)
    )
    redirect_handler = next(
        handler for handler in captured if handler.__class__.__name__ == "_RejectRedirects"
    )
    assert proxy_handler.proxies == {}
    request = urllib.request.Request("http://127.0.0.1:8000/stream")
    with pytest.raises(urllib.error.HTTPError, match="redirects are forbidden"):
        redirect_handler.redirect_request(
            request,
            object(),
            302,
            "Found",
            {},
            "https://example.com/token-sink",
        )


def test_system_acceptance_covers_identity_mainline_release() -> None:
    script = SYSTEM_ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")
    required_evidence = (
        'if ($migrationHead -ne "20260720_0010")',
        "/api/auth/verification-challenges",
        "/api/auth/register/email",
        "Get-AccessToken `\n        -Username $registeredEmail",
        "learner_admin_http_status = $learnerAdminStatus",
        "identity_plaintext_contact_matches",
        "foreign_tenant_visible_identity_accounts",
    )
    for evidence in required_evidence:
        assert evidence in script
    assert 'registeredPassword = "Acceptance-$(([Guid]::NewGuid())' in script


def test_phase7_performance_dataset_is_deterministic_and_content_addressed(
    tmp_path: Path,
) -> None:
    materialize = PHASE7_DATASET_TOOL["_materialize_performance_corpus"]
    first = materialize(tmp_path / "first.jsonl", 12, 3)
    second = materialize(tmp_path / "second.jsonl", 12, 3)

    assert first["record_count"] == 12
    assert first["content_sha256"] == second["content_sha256"]
    assert (tmp_path / "first.jsonl").read_bytes() == (tmp_path / "second.jsonl").read_bytes()


def test_phase7_human_golden_set_is_accepted_after_hash_confirmation() -> None:
    golden_status = PHASE7_DATASET_TOOL["_human_golden_status"]()

    assert golden_status["state"] == "HUMAN_REVIEWED_GOLDEN_SET_ACCEPTED"
    assert golden_status["acceptance_eligible"] is True
    assert golden_status["validation_errors"] == []
    assert golden_status["fact_count"] == 72
    assert golden_status["topic_count"] == 24
    assert golden_status["outcome_counts"] == {
        "CONTRADICTED": 24,
        "INSUFFICIENT_EVIDENCE": 24,
        "SUPPORTED": 24,
    }


def _copy_phase7_golden_set(tmp_path: Path) -> Path:
    root = Path(__file__).resolve().parents[2]
    relative_paths = (
        Path("tests/golden/phase7-academic-golden-facts.v1.jsonl"),
        Path("tests/golden/phase7-academic-golden-review.v1.json"),
        Path("docs/system-acceptance/evidence/phase7-academic-source-ledger.v1.json"),
        Path("docs/system-acceptance/phase7-academic-review-policy.md"),
    )
    for relative_path in relative_paths:
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative_path, target)
    return tmp_path


def _golden_status_at(monkeypatch: pytest.MonkeyPatch, root: Path) -> dict[str, object]:
    golden_status = PHASE7_DATASET_TOOL["_human_golden_status"]
    monkeypatch.setitem(golden_status.__globals__, "ROOT", root)
    return cast(dict[str, object], golden_status())


def _write_review(root: Path, update: dict[str, object]) -> None:
    review_path = root / "tests/golden/phase7-academic-golden-review.v1.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review.update(update)
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_phase7_human_golden_acceptance_requires_exact_bound_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _copy_phase7_golden_set(tmp_path)
    _write_review(
        root,
        {
            "decision": "ACCEPTED",
            "rights_review_decision": "ACCEPTED",
            "reviewed_at_utc": "2026-07-21T18:45:00Z",
        },
    )

    status = _golden_status_at(monkeypatch, root)

    assert status["state"] == "HUMAN_REVIEWED_GOLDEN_SET_ACCEPTED"
    assert status["acceptance_eligible"] is True
    assert status["validation_errors"] == []


def test_phase7_human_golden_rejects_changed_fact_after_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _copy_phase7_golden_set(tmp_path)
    facts_path = root / "tests/golden/phase7-academic-golden-facts.v1.jsonl"
    facts_path.write_text(
        facts_path.read_text(encoding="utf-8").replace(
            "selects a controller structure",
            "selects an altered controller structure",
            1,
        ),
        encoding="utf-8",
    )

    status = _golden_status_at(monkeypatch, root)

    assert status["state"] == "GOLDEN_SET_INVALID"
    assert "review facts_content_sha256 does not match the facts" in status["validation_errors"]


def test_phase7_human_golden_rejects_noncommercial_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _copy_phase7_golden_set(tmp_path)
    ledger_path = root / "docs/system-acceptance/evidence/phase7-academic-source-ledger.v1.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["included_sources"][0]["commercial_reuse_permitted"] = False
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    status = _golden_status_at(monkeypatch, root)

    assert status["state"] == "GOLDEN_SET_INVALID"
    assert "source SRC-PID-2012-C1 does not permit commercial reuse" in status["validation_errors"]


def test_phase7_human_golden_rejects_unbalanced_classes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _copy_phase7_golden_set(tmp_path)
    facts_path = root / "tests/golden/phase7-academic-golden-facts.v1.jsonl"
    supported = [
        line
        for line in facts_path.read_text(encoding="utf-8").splitlines()
        if line and json.loads(line)["expected_outcome"] == "SUPPORTED"
    ]
    facts_path.write_text("\n".join(supported) + "\n", encoding="utf-8")

    status = _golden_status_at(monkeypatch, root)

    errors = status["validation_errors"]
    assert status["state"] == "GOLDEN_SET_INVALID"
    assert "CONTRADICTED requires at least 20 facts" in errors
    assert "INSUFFICIENT_EVIDENCE requires at least 20 facts" in errors


def test_phase7_human_golden_rejects_accepted_review_without_utc_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _copy_phase7_golden_set(tmp_path)
    _write_review(
        root,
        {
            "decision": "ACCEPTED",
            "rights_review_decision": "ACCEPTED",
            "reviewed_at_utc": None,
        },
    )

    status = _golden_status_at(monkeypatch, root)

    assert status["state"] == "GOLDEN_SET_INVALID"
    assert "accepted review requires a valid UTC review timestamp" in status["validation_errors"]


def test_phase7_dataset_inventory_binds_git_commit_and_tree() -> None:
    git_revision = PHASE7_DATASET_TOOL["_git_revision"]

    for revision in (git_revision("HEAD"), git_revision("HEAD^{tree}")):
        assert len(revision) == 40
        assert set(revision) <= set("0123456789abcdef")


def test_phase7_dataset_inventory_rejects_dirty_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main = PHASE7_DATASET_TOOL["main"]
    monkeypatch.setitem(main.__globals__, "_git_status", lambda: [" M source.py"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build-phase7-dataset-inventory.py",
            "--output",
            str(tmp_path / "inventory.json"),
        ],
    )

    with pytest.raises(SystemExit, match="requires a clean source tree"):
        main()
