from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

ALLOWED_TYPES = (
    "feat",
    "fix",
    "refactor",
    "perf",
    "test",
    "docs",
    "build",
    "ci",
    "chore",
    "security",
    "revert",
)
SUBJECT_PATTERN = re.compile(
    rf"^(?P<type>{'|'.join(ALLOWED_TYPES)})"
    r"(?:\((?P<scope>[a-z0-9][a-z0-9._/-]*)\))?"
    r"(?P<breaking>!)?: (?P<summary>\S(?:.*\S)?)$"
)
ZERO_SHA_PATTERN = re.compile(r"^0{40}$")
MAX_SUBJECT_LENGTH = 100


@dataclass(frozen=True, slots=True)
class CommitSubject:
    commit: str
    subject: str


def validate_subject(subject: str) -> tuple[str, ...]:
    errors: list[str] = []
    if len(subject) > MAX_SUBJECT_LENGTH:
        errors.append(f"subject length {len(subject)} exceeds {MAX_SUBJECT_LENGTH} characters")
    if subject.startswith(("fixup! ", "squash! ")):
        errors.append("fixup and squash commits must be resolved before push")
    if subject.upper().startswith("WIP"):
        errors.append("WIP commits are prohibited")
    if SUBJECT_PATTERN.fullmatch(subject) is None:
        errors.append(
            "subject must match <type>(<optional-scope>)!: <summary> with an allowed type"
        )
    return tuple(errors)


def _run_git(arguments: list[str]) -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required for commit-message validation")
    result = subprocess.run(  # noqa: S603
        [git, *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git failure"
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


def _assert_revision(revision: str) -> None:
    _run_git(["rev-parse", "--verify", f"{revision}^{{commit}}"])


def commits_to_validate(base: str | None, head: str) -> tuple[CommitSubject, ...]:
    normalized_base = (base or "").strip()
    normalized_head = head.strip() or "HEAD"
    _assert_revision(normalized_head)

    if not normalized_base or ZERO_SHA_PATTERN.fullmatch(normalized_base):
        revision_arguments = ["rev-list", "--reverse", normalized_head]
    else:
        _assert_revision(normalized_base)
        _run_git(["merge-base", "--is-ancestor", normalized_base, normalized_head])
        revision_arguments = [
            "rev-list",
            "--reverse",
            f"{normalized_base}..{normalized_head}",
        ]

    commits = tuple(filter(None, _run_git(revision_arguments).splitlines()))
    if not commits:
        commits = (_run_git(["rev-parse", normalized_head]),)
    return tuple(
        CommitSubject(
            commit=commit,
            subject=_run_git(["show", "-s", "--format=%s", commit]),
        )
        for commit in commits
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce the repository Conventional Commit subject policy"
    )
    parser.add_argument(
        "--base",
        default=os.getenv("COMMIT_BASE", ""),
        help="exclusive base commit; an empty/all-zero value validates full history",
    )
    parser.add_argument(
        "--head",
        default=os.getenv("COMMIT_HEAD", "HEAD"),
        help="inclusive head commit",
    )
    arguments = parser.parse_args()

    failures: list[str] = []
    commits = commits_to_validate(arguments.base, arguments.head)
    for item in commits:
        errors = validate_subject(item.subject)
        if errors:
            failures.append(f"{item.commit[:12]} {item.subject!r}: {'; '.join(errors)}")
    if failures:
        raise ValueError("invalid commit subjects:\n" + "\n".join(failures))
    print(f"Validated {len(commits)} Conventional Commit subject(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
