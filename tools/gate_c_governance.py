"""Enforce append-only Gate C governance and produce audit receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROCESS_VERSION = "Gate-C-12-v2.0"
SEALED_DOCKER_MIGRATION_PROCESS_VERSION = "Gate-C-12-v1.0"
PRODUCT_SOURCE_SHA = "a57d0ce57427804ede3f3c620fda2a93b3a300ff"
FORMAL_STATE = "PHASE7_GATE_C_FAILED_GATE_D_LOCKED"
D1_READY_STATE = "GATE_C12_TRUSTED_FOUNDATION_VERIFIED_D1_READY"
STATUS_PATH = Path("docs/system-acceptance/acceptance-status.json")
BASELINE_TYPES = {"INFRA", "STATUS", "DIAGNOSTIC", "REMEDIATION", "EVIDENCE", "RELEASE"}
EXECUTION_CLASSIFICATIONS = {
    "NON_ACCEPTANCE_ENGINEERING",
    "NON_ACCEPTANCE_DIAGNOSTIC",
    "NON_ACCEPTANCE_REMEDIATION_VALIDATION",
    "PREFLIGHT_CHECK",
    "HARNESS_SMOKE",
    "FORMAL_GATE_C_ATTEMPT",
}
EXPECTED_JOBS = {
    "Python, contracts, and unit tests",
    "PostgreSQL 16 integration and coverage",
    "Go contract compiler gate",
    "Vue, TypeScript, pnpm audit, and Node SBOM",
    "Python audit and SBOM",
    "Container build, runtime, SBOM, and vulnerability scan",
    "Full Git history secret scan",
    "Release quality redline",
}
_PROCESS_VERSION_LINE = re.compile(r"(?im)^\s*process version\s*:\s*`?([^`\s]+)`?\s*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MIGRATION_SOURCE_DOCUMENTS = {
    "checkpoint_verification",
    "cleanup_receipt",
    "policy",
    "reference_inventory",
    "volume_copy_verification",
}


def _run(arguments: tuple[str, ...], *, cwd: Path) -> str:
    return subprocess.run(  # noqa: S603 - callers pass fixed executable and validated arguments.
        arguments,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _run_json(arguments: tuple[str, ...], *, cwd: Path) -> dict[str, Any]:
    value = json.loads(_run(arguments, cwd=cwd))
    if not isinstance(value, dict):
        raise ValueError(f"command did not return a JSON object: {' '.join(arguments)}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_json(root: Path, reference: str, path: Path = STATUS_PATH) -> dict[str, Any]:
    return json.loads(_run(("git", "show", f"{reference}:{path.as_posix()}"), cwd=root))


def _changed_paths(root: Path, base: str, head: str) -> list[str]:
    output = _run(
        ("git", "diff", "--name-only", "--diff-filter=AMRT", base, head),
        cwd=root,
    )
    return sorted({line.strip().replace("\\", "/") for line in output.splitlines() if line})


def _assert_append_only(*, name: str, before: list[Any], after: list[Any]) -> list[dict[str, Any]]:
    if len(after) < len(before) or after[: len(before)] != before:
        raise ValueError(f"{name} is not append-only")
    appended = after[len(before) :]
    if not all(isinstance(item, dict) for item in appended):
        raise ValueError(f"new {name} entries must be JSON objects")
    return appended


def _walk_objects(value: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if isinstance(value, dict):
        objects.append(value)
        for nested in value.values():
            objects.extend(_walk_objects(nested))
    elif isinstance(value, list):
        for nested in value:
            objects.extend(_walk_objects(nested))
    return objects


def _formal_metadata_candidates(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for relative in paths:
        path = root / relative
        if path.suffix.lower() != ".json" or not path.is_file():
            continue
        try:
            document = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        candidates.extend(
            value for value in _walk_objects(document) if value.get("formal_gate_attempt") is True
        )
    return candidates


def _validate_new_history(before_count: int, entries: list[dict[str, Any]]) -> None:
    for offset, entry in enumerate(entries, start=before_count + 1):
        if entry.get("sequence") != offset:
            raise ValueError("baseline_history sequences must remain contiguous")
        if entry.get("type") not in BASELINE_TYPES:
            raise ValueError("new baseline_history entries require a supported type")
        if not isinstance(entry.get("change_type"), str) or not entry["change_type"]:
            raise ValueError("new baseline_history entries require change_type")
        if entry.get("process_version") != PROCESS_VERSION:
            raise ValueError("new baseline_history entries require the current process_version")


def _validate_new_attempts(
    before_count: int,
    entries: list[dict[str, Any]],
    formal_metadata: list[dict[str, Any]],
) -> None:
    for offset, entry in enumerate(entries, start=before_count + 1):
        if entry.get("sequence") != offset:
            raise ValueError("gate_c_attempts sequences must remain contiguous")
        if entry.get("process_version") != PROCESS_VERSION:
            raise ValueError("new formal attempts require the current process_version")
        if str(entry.get("result", "")).upper() not in {
            "PASS",
            "PASSED",
            "FAIL",
            "FAILED",
        }:
            raise ValueError("new formal attempts require a terminal PASS/FAIL result")
        matching = [
            item
            for item in formal_metadata
            if item.get("mode") == "Full"
            and item.get("classification") == "FORMAL_GATE_C_ATTEMPT"
            and item.get("process_version") == PROCESS_VERSION
            and item.get("formal_gate_attempt") is True
            and item.get("run_id") == entry.get("run_id")
            and item.get("product_source_sha") == entry.get("product_source_sha")
        ]
        if len(matching) != 1:
            raise ValueError(
                "gate_c_attempts may advance only with one exactly bound Full "
                "execution metadata record"
            )


def _validate_state_transitions(
    before: dict[str, Any],
    after: dict[str, Any],
    new_history: list[dict[str, Any]],
    new_attempts: list[dict[str, Any]],
) -> None:
    before_product = before.get("baseline", {}).get("product_source_sha")
    after_product = after.get("baseline", {}).get("product_source_sha")
    if before_product != after_product:
        if not new_history or new_history[-1].get("type") != "REMEDIATION":
            raise ValueError("product_source_sha may advance only through REMEDIATION history")
        if new_history[-1].get("product_source_sha") != after_product:
            raise ValueError("remediation history does not bind the new product_source_sha")

    before_formal = before.get("formal_release_state")
    after_formal = after.get("formal_release_state")
    if before_formal != after_formal:
        if after_formal != "PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY" or not new_attempts:
            raise ValueError(
                "formal state may advance only after an appended formal Gate C attempt"
            )
        if str(new_attempts[-1].get("result", "")).upper() not in {"PASS", "PASSED"}:
            raise ValueError("formal acceptance state requires a passing final attempt")


def validate_history(root: Path, base: str, head: str) -> dict[str, Any]:
    before = _git_json(root, base)
    after = _git_json(root, head)
    changed = _changed_paths(root, base, head)
    before_history = before.get("baseline_history")
    after_history = after.get("baseline_history")
    before_attempts = before.get("gate_c_attempts")
    after_attempts = after.get("gate_c_attempts")
    if not all(
        isinstance(value, list)
        for value in (
            before_history,
            after_history,
            before_attempts,
            after_attempts,
        )
    ):
        raise ValueError("acceptance status history fields must be arrays")

    new_history = _assert_append_only(
        name="baseline_history", before=before_history, after=after_history
    )
    new_attempts = _assert_append_only(
        name="gate_c_attempts", before=before_attempts, after=after_attempts
    )
    _validate_new_history(len(before_history), new_history)
    formal_metadata = _formal_metadata_candidates(root, changed)
    _validate_new_attempts(len(before_attempts), new_attempts, formal_metadata)
    _validate_state_transitions(before, after, new_history, new_attempts)

    return {
        "schema_version": "cybercontrol.gate-c-history-validation.v1",
        "process_version": PROCESS_VERSION,
        "base": base,
        "head": head,
        "changed_paths": changed,
        "baseline_history_before": len(before_history),
        "baseline_history_appended": len(new_history),
        "gate_c_attempts_before": len(before_attempts),
        "gate_c_attempts_appended": len(new_attempts),
        "passed": True,
    }


def verify_worktree(root: Path, expected_ref: str) -> dict[str, Any]:
    root = root.resolve()
    head = _run(("git", "rev-parse", "HEAD"), cwd=root)
    tree = _run(("git", "rev-parse", "HEAD^{tree}"), cwd=root)
    expected = _run(("git", "rev-parse", expected_ref), cwd=root)
    expected_tree = _run(("git", "rev-parse", f"{expected_ref}^{{tree}}"), cwd=root)
    status = _run(("git", "status", "--porcelain=v1", "--untracked-files=all"), cwd=root)
    if status:
        raise ValueError("Gate C execution requires a clean isolated worktree")
    if head != expected or tree != expected_tree:
        raise ValueError(f"worktree is stale relative to {expected_ref}")
    return {
        "schema_version": "cybercontrol.gate-c-worktree-verification.v1",
        "process_version": PROCESS_VERSION,
        "worktree": str(root),
        "expected_ref": expected_ref,
        "commit": head,
        "tree": tree,
        "clean": True,
        "result": "PASS",
    }


def _baseline_type(change_type: str) -> str:
    normalized = change_type.upper()
    if "RELEASE" in normalized:
        return "RELEASE"
    if "EVIDENCE" in normalized or "ARCHIVE" in normalized:
        return "EVIDENCE"
    if "REMEDIATION" in normalized:
        return "REMEDIATION"
    if "DIAGNOSTIC" in normalized or "MEASUREMENT" in normalized:
        return "DIAGNOSTIC"
    if "STATUS" in normalized or "CLOSURE" in normalized:
        return "STATUS"
    return "INFRA"


def build_audit_index(status_path: Path, evidence_root: Path, output: Path) -> dict[str, Any]:
    status = _read_json(status_path)
    history = status.get("baseline_history")
    attempts = status.get("gate_c_attempts")
    if not isinstance(history, list) or not isinstance(attempts, list):
        raise ValueError("acceptance status has no append-only histories")
    mapped_history = []
    for entry in history:
        if not isinstance(entry, dict):
            raise ValueError("baseline_history contains a non-object entry")
        mapped = dict(entry)
        mapped["type"] = entry.get("type") or _baseline_type(str(entry.get("change_type", "")))
        if mapped["type"] not in BASELINE_TYPES:
            raise ValueError("baseline_history type mapping is invalid")
        mapped_history.append(mapped)

    artifacts: list[dict[str, Any]] = []
    for path in sorted(item for item in evidence_root.rglob("*") if item.is_file()):
        if path.resolve() == output.resolve():
            continue
        process_version = None
        if path.suffix.lower() == ".json":
            try:
                process_version = _read_json(path).get("process_version")
            except (OSError, json.JSONDecodeError, ValueError):
                process_version = None
        elif path.suffix.lower() == ".md":
            match = _PROCESS_VERSION_LINE.search(path.read_text(encoding="utf-8-sig"))
            process_version = match.group(1) if match else None
        artifacts.append(
            {
                "path": path.relative_to(evidence_root.parent).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
                "process_version": process_version,
            }
        )

    return {
        "schema_version": "cybercontrol.gate-c-audit-index.v1",
        "process_version": PROCESS_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_status": {
            "path": status_path.as_posix(),
            "sha256": _sha256(status_path),
        },
        "current": {
            "state": status.get("state"),
            "formal_release_state": status.get("formal_release_state"),
            "baseline": status.get("baseline"),
            "baseline_history_count": len(history),
            "gate_c_attempts_count": len(attempts),
        },
        "baseline_history": mapped_history,
        "gate_c_attempts": attempts,
        "evidence": artifacts,
        "result": "PASS",
    }


def build_execution_context(
    root: Path,
    status_path: Path,
    capacity_snapshot_path: Path,
    classification: str,
    formal_gate_attempt: bool,
    image_lock_paths: list[Path],
) -> dict[str, Any]:
    worktree = verify_worktree(root, "origin/main")
    status = _read_json(status_path)
    capacity = _read_json(capacity_snapshot_path)
    if classification not in EXECUTION_CLASSIFICATIONS:
        raise ValueError("execution context classification is not supported")
    if classification == "FORMAL_GATE_C_ATTEMPT" and not formal_gate_attempt:
        raise ValueError("formal classification requires formal_gate_attempt=true")
    if classification != "FORMAL_GATE_C_ATTEMPT" and formal_gate_attempt:
        raise ValueError("non-formal execution cannot set formal_gate_attempt=true")
    if capacity.get("process_version") != PROCESS_VERSION:
        raise ValueError("capacity snapshot has the wrong process version")
    if capacity.get("admission_ready") is not True:
        raise ValueError("all capacity roots must pass admission before execution")
    baseline = status.get("baseline", {})
    if baseline.get("product_source_sha") != PRODUCT_SOURCE_SHA:
        raise ValueError("execution context product_source_sha is not frozen")
    if status.get("formal_release_state") != FORMAL_STATE:
        raise ValueError("execution context formal state is not locked")
    if len(status.get("gate_c_attempts", [])) != 12:
        raise ValueError("execution context requires gate_c_attempts to remain 12")

    lock_bindings = []
    for path in image_lock_paths:
        lock = _read_json(path)
        source = lock.get("source", {})
        if (
            lock.get("process_version") != PROCESS_VERSION
            or source.get("commit") != worktree["commit"]
            or source.get("tree") != worktree["tree"]
            or source.get("product_source_sha") != PRODUCT_SOURCE_SHA
        ):
            raise ValueError(f"image lock is not bound to exact protected main: {path}")
        _run(
            (
                sys.executable,
                "tools/gate_c_image_lock.py",
                "--root",
                str(root),
                "verify",
                "--image-lock",
                str(path),
            ),
            cwd=root,
        )
        lock_bindings.append(
            {
                "path": str(path),
                "track": lock.get("track"),
                "sha256": _sha256(path),
                "build_receipt_sha256": lock.get("build_receipt", {}).get("sha256"),
            }
        )

    threshold_path = root / "tests/load/gate-c-thresholds.v1.json"
    workload_path = root / "tests/load/gate-c-workload.v1.json"
    return {
        "schema_version": "cybercontrol.gate-c-execution-context.v1",
        "process_version": PROCESS_VERSION,
        "classification": classification,
        "formal_gate_attempt": formal_gate_attempt,
        "acceptance_claim": False,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "commit": worktree["commit"],
            "tree": worktree["tree"],
            "product_source_sha": PRODUCT_SOURCE_SHA,
            "engineering_baseline_sha": worktree["commit"],
            "status_declared_engineering_baseline_sha": baseline.get("engineering_baseline_sha"),
            "clean_exact_origin_main": True,
        },
        "frozen_inputs": {
            "threshold_path": threshold_path.relative_to(root).as_posix(),
            "threshold_sha256": _sha256(threshold_path),
            "workload_path": workload_path.relative_to(root).as_posix(),
            "workload_sha256": _sha256(workload_path),
        },
        "formal_release_state": FORMAL_STATE,
        "gate_c_attempts": len(status.get("gate_c_attempts", [])),
        "capacity_snapshot": {
            "path": str(capacity_snapshot_path),
            "sha256": _sha256(capacity_snapshot_path),
            "state": capacity.get("state"),
            "admission_ready": True,
            "targets": capacity.get("targets"),
        },
        "image_locks": lock_bindings,
        "historical_intent_snapshots_authoritative": False,
    }


def _validated_run(
    root: Path, repository: str, run_id: int, event: str, head_sha: str
) -> dict[str, Any]:
    run = _run_json(
        (
            "gh",
            "run",
            "view",
            str(run_id),
            "--repo",
            repository,
            "--json",
            "databaseId,event,status,conclusion,headSha,jobs,url",
        ),
        cwd=root,
    )
    jobs = run.get("jobs")
    if (
        run.get("event") != event
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("headSha") != head_sha
        or not isinstance(jobs, list)
    ):
        raise ValueError(f"quality run {run_id} does not match its closure binding")
    observed = {job.get("name") for job in jobs if job.get("conclusion") == "success"}
    if observed != EXPECTED_JOBS:
        raise ValueError(f"quality run {run_id} does not contain the exact 8/8 job set")
    return {
        "run_id": run_id,
        "event": event,
        "head_sha": head_sha,
        "conclusion": "success",
        "jobs_successful": len(observed),
        "url": run.get("url"),
    }


def build_closure_receipt(
    root: Path,
    repository: str,
    pr_number: int,
    push_run: int,
    pull_request_run: int,
    protected_main_run: int,
) -> dict[str, Any]:
    pull_request = _run_json(("gh", "api", f"repos/{repository}/pulls/{pr_number}"), cwd=root)
    merge_sha = pull_request.get("merge_commit_sha")
    head_sha = pull_request.get("head", {}).get("sha")
    if pull_request.get("state") != "closed" or not pull_request.get("merged"):
        raise ValueError(f"PR #{pr_number} is not merged")
    if not isinstance(merge_sha, str) or not isinstance(head_sha, str):
        raise ValueError(f"PR #{pr_number} has incomplete source bindings")
    commit = _run_json(("gh", "api", f"repos/{repository}/git/commits/{merge_sha}"), cwd=root)
    tree = commit.get("tree", {}).get("sha")
    if not isinstance(tree, str):
        raise ValueError("merged commit tree is unavailable")
    return {
        "schema_version": "cybercontrol.gate-c-post-merge-closure-receipt.v1",
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_ENGINEERING_CLOSURE",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "repository": repository,
        "pull_request": pr_number,
        "head_sha": head_sha,
        "merge_sha": merge_sha,
        "merge_tree": tree,
        "product_source_sha": PRODUCT_SOURCE_SHA,
        "formal_release_state": FORMAL_STATE,
        "gate_c_attempts": 12,
        "quality_runs": {
            "push": _validated_run(root, repository, push_run, "push", head_sha),
            "pull_request": _validated_run(
                root, repository, pull_request_run, "pull_request", head_sha
            ),
            "protected_main": _validated_run(
                root, repository, protected_main_run, "push", merge_sha
            ),
        },
        "result": "CLOSED",
    }


def _validate_sealed_migration_report(migration: dict[str, Any]) -> None:
    environment = migration.get("environment")
    checks = environment.get("checks") if isinstance(environment, dict) else None
    observed = environment.get("observed") if isinstance(environment, dict) else None
    source_documents = migration.get("source_documents")
    source_bindings_valid = (
        isinstance(source_documents, dict)
        and set(source_documents) == _MIGRATION_SOURCE_DOCUMENTS
        and all(
            isinstance(binding, dict)
            and isinstance(binding.get("path"), str)
            and bool(binding["path"].strip())
            and _SHA256.fullmatch(str(binding.get("sha256"))) is not None
            for binding in source_documents.values()
        )
    )
    if (
        migration.get("schema_version") != "cybercontrol.docker-migration-validation.v1"
        or migration.get("process_version") != SEALED_DOCKER_MIGRATION_PROCESS_VERSION
        or migration.get("classification") != "NON_ACCEPTANCE_INFRASTRUCTURE_VERIFICATION"
        or migration.get("result") != "MIGRATION_VALIDATED"
        or migration.get("formal_volume_result") != "PASS"
        or migration.get("formal_state_changed") is not False
        or migration.get("gate_c_attempts_appended") is not False
        or not isinstance(environment, dict)
        or environment.get("passed") is not True
        or not isinstance(checks, dict)
        or not checks
        or any(value is not True for value in checks.values())
        or not isinstance(observed, dict)
        or observed.get("running_containers") != 0
        or migration.get("unexplained_differences") != {}
        or not source_bindings_valid
    ):
        raise ValueError("D1 readiness requires the sealed validated Docker migration report")


def _validate_d1_documents(
    status: dict[str, Any],
    status_path: Path,
    capacity: dict[str, Any],
    migration: dict[str, Any],
    audit_index: dict[str, Any],
) -> None:
    if status.get("formal_release_state") != FORMAL_STATE:
        raise ValueError("formal Gate C state changed before M3")
    if len(status.get("gate_c_attempts", [])) != 12:
        raise ValueError("D1 readiness requires gate_c_attempts to remain 12")
    if status.get("baseline", {}).get("product_source_sha") != PRODUCT_SOURCE_SHA:
        raise ValueError("D1 readiness product_source_sha is not frozen")
    target_names = {
        target.get("name") for target in capacity.get("targets", []) if isinstance(target, dict)
    }
    if (
        capacity.get("process_version") != PROCESS_VERSION
        or capacity.get("admission_ready") is not True
        or capacity.get("state") != "NORMAL"
        or target_names != {"results_root", "docker_data_root", "docker_internal_root"}
    ):
        raise ValueError("D1 readiness requires a normal three-root capacity snapshot")
    _validate_sealed_migration_report(migration)
    if (
        audit_index.get("process_version") != PROCESS_VERSION
        or audit_index.get("result") != "PASS"
        or audit_index.get("current", {}).get("gate_c_attempts_count") != 12
        or audit_index.get("source_status", {}).get("sha256") != _sha256(status_path)
    ):
        raise ValueError("D1 readiness requires the current passing audit index")


def _validate_d1_lock(
    root: Path,
    worktree: dict[str, Any],
    name: str,
    lock: dict[str, Any],
    track: str,
    lock_path: Path,
) -> None:
    if lock.get("process_version") != PROCESS_VERSION or lock.get("track") != track:
        raise ValueError(f"{name} image lock has an invalid process version or track")
    source = lock.get("source", {})
    if (
        source.get("commit") != worktree["commit"]
        or source.get("tree") != worktree["tree"]
        or source.get("product_source_sha") != PRODUCT_SOURCE_SHA
    ):
        raise ValueError(f"{name} image lock is not bound to exact protected main")
    _run(
        (
            sys.executable,
            "tools/gate_c_image_lock.py",
            "--root",
            str(root),
            "verify",
            "--image-lock",
            str(lock_path),
        ),
        cwd=root,
    )


def verify_d1_readiness(
    root: Path,
    status_path: Path,
    normal_lock_path: Path,
    diagnostic_lock_path: Path,
    closure_receipts: list[Path],
    capacity_snapshot_path: Path,
    migration_report_path: Path,
    audit_index_path: Path,
) -> dict[str, Any]:
    worktree = verify_worktree(root, "origin/main")
    status = _read_json(status_path)
    normal = _read_json(normal_lock_path)
    diagnostic = _read_json(diagnostic_lock_path)
    capacity = _read_json(capacity_snapshot_path)
    migration = _read_json(migration_report_path)
    audit_index = _read_json(audit_index_path)
    _validate_d1_documents(status, status_path, capacity, migration, audit_index)
    for name, lock, track, lock_path in (
        ("normal", normal, "FORMAL_NORMAL", normal_lock_path),
        (
            "diagnostic",
            diagnostic,
            "NON_ACCEPTANCE_DIAGNOSTIC",
            diagnostic_lock_path,
        ),
    ):
        _validate_d1_lock(root, worktree, name, lock, track, lock_path)
    receipt_entries = []
    for path in closure_receipts:
        receipt = _read_json(path)
        if (
            receipt.get("process_version") != PROCESS_VERSION
            or receipt.get("result") != "CLOSED"
            or receipt.get("formal_release_state") != FORMAL_STATE
            or receipt.get("gate_c_attempts") != 12
        ):
            raise ValueError(f"closure receipt is invalid: {path}")
        receipt_entries.append({"path": str(path), "sha256": _sha256(path)})
    if not receipt_entries:
        raise ValueError("D1 readiness requires at least one post-merge closure receipt")
    return {
        "schema_version": "cybercontrol.gate-c-d1-readiness.v1",
        "process_version": PROCESS_VERSION,
        "state": D1_READY_STATE,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": {"commit": worktree["commit"], "tree": worktree["tree"]},
        "product_source_sha": PRODUCT_SOURCE_SHA,
        "formal_release_state": FORMAL_STATE,
        "gate_c_attempts": 12,
        "normal_image_lock_sha256": _sha256(normal_lock_path),
        "diagnostic_image_lock_sha256": _sha256(diagnostic_lock_path),
        "closure_receipts": receipt_entries,
        "capacity_snapshot_sha256": _sha256(capacity_snapshot_path),
        "migration_report_sha256": _sha256(migration_report_path),
        "migration_report_process_version": SEALED_DOCKER_MIGRATION_PROCESS_VERSION,
        "audit_index_sha256": _sha256(audit_index_path),
        "authorization_scope": "D1_ONLY",
        "gate_d_through_g_locked": True,
        "result": "PASS",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)

    history = subparsers.add_parser("verify-history")
    history.add_argument("--base", required=True)
    history.add_argument("--head", required=True)
    history.add_argument("--output", type=Path)

    worktree = subparsers.add_parser("verify-worktree")
    worktree.add_argument("--expected-ref", default="origin/main")
    worktree.add_argument("--output", type=Path)

    audit = subparsers.add_parser("build-audit-index")
    audit.add_argument("--status", type=Path, default=STATUS_PATH)
    audit.add_argument(
        "--evidence-root", type=Path, default=Path("docs/system-acceptance/evidence")
    )
    audit.add_argument("--output", type=Path, required=True)

    context = subparsers.add_parser("execution-context")
    context.add_argument("--status", type=Path, default=STATUS_PATH)
    context.add_argument("--capacity-snapshot", type=Path, required=True)
    context.add_argument("--classification", required=True)
    context.add_argument("--formal-gate-attempt", action="store_true")
    context.add_argument("--image-lock", action="append", type=Path, default=[])
    context.add_argument("--output", type=Path, required=True)

    closure = subparsers.add_parser("closure-receipt")
    closure.add_argument("--repository", default="changkong66/CyberControl")
    closure.add_argument("--pr", type=int, required=True)
    closure.add_argument("--push-run", type=int, required=True)
    closure.add_argument("--pull-request-run", type=int, required=True)
    closure.add_argument("--protected-main-run", type=int, required=True)
    closure.add_argument("--output", type=Path, required=True)

    readiness = subparsers.add_parser("verify-d1-readiness")
    readiness.add_argument("--status", type=Path, default=STATUS_PATH)
    readiness.add_argument("--normal-image-lock", type=Path, required=True)
    readiness.add_argument("--diagnostic-image-lock", type=Path, required=True)
    readiness.add_argument("--closure-receipt", action="append", type=Path, required=True)
    readiness.add_argument("--capacity-snapshot", type=Path, required=True)
    readiness.add_argument("--migration-report", type=Path, required=True)
    readiness.add_argument("--audit-index", type=Path, required=True)
    readiness.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = args.root.resolve()
    try:
        if args.command == "verify-history":
            result = validate_history(root, args.base, args.head)
        elif args.command == "verify-worktree":
            result = verify_worktree(root, args.expected_ref)
        elif args.command == "build-audit-index":
            result = build_audit_index(
                (root / args.status).resolve(),
                (root / args.evidence_root).resolve(),
                (root / args.output).resolve(),
            )
        elif args.command == "execution-context":
            result = build_execution_context(
                root,
                (root / args.status).resolve(),
                args.capacity_snapshot.resolve(),
                args.classification,
                args.formal_gate_attempt,
                [path.resolve() for path in args.image_lock],
            )
        elif args.command == "closure-receipt":
            result = build_closure_receipt(
                root,
                args.repository,
                args.pr,
                args.push_run,
                args.pull_request_run,
                args.protected_main_run,
            )
        else:
            result = verify_d1_readiness(
                root,
                (root / args.status).resolve(),
                args.normal_image_lock.resolve(),
                args.diagnostic_image_lock.resolve(),
                [path.resolve() for path in args.closure_receipt],
                args.capacity_snapshot.resolve(),
                args.migration_report.resolve(),
                args.audit_index.resolve(),
            )
        output = getattr(args, "output", None)
        if output:
            destination = output if output.is_absolute() else root / output
            _write_json(destination, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"Gate C governance error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
