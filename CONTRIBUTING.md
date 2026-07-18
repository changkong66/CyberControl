# Engineering Contribution Policy

## Protected branches

`main` is the release baseline. Direct feature development on `main` is
prohibited after the initial repository baseline. Repository hosting must require
pull requests, passing quality gates, resolved review threads, and linear history.
The current repository uses the documented `Solo` maintenance mode: approval
count, mandatory Code Owner review, and last-push approval are disabled because
the sole maintainer cannot approve their own pull request. All other protections,
including administrator enforcement, remain mandatory.

## Branch names

- `codex/<scope>` for Codex implementation work.
- `feature/<scope>` for product capabilities.
- `fix/<scope>` for defects.
- `security/<scope>` for confidential remediation.
- `release/<version>` for controlled release stabilization.

## Commit format

Use Conventional Commits:

```text
<type>(<scope>): <imperative summary>
```

Allowed types are `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`,
`ci`, `chore`, `security`, and `revert`. Every commit must be independently
buildable or explicitly marked as a mechanical/generated artifact update.
The complete subject must not exceed 100 characters. `WIP`, `fixup!`, and
`squash!` commits are rejected by the remote quality gate. Pull request titles
must follow the same format because protected `main` uses squash or rebase
history only.

## Versioning

- Public wire contracts use immutable semantic major versions such as `v1`.
- Python, TypeScript, Go, migrations, policies, prompts, and knowledge bases have
  independent versions.
- Release tags use `vMAJOR.MINOR.PATCH`.
- Database migrations are append-only after merge to `main`.

## Required checks

No pull request may merge without Python tests, Ruff, Go tests, TypeScript checks,
migration validation, dependency vulnerability checks, and SBOM generation.
The protected branch requires the aggregated **Release quality redline** status
defined in `.github/workflows/quality-gates.yml`. Windows contributors can reproduce
the release-equivalent suite with `tools/windows/run-quality-gates.ps1`; runs using
any skip switch are diagnostic only. The configured Python coverage threshold is
90%; higher acceptance observations do not silently change that hard threshold.

`.github/CODEOWNERS` remains the authoritative ownership map. In `Solo` mode it is
retained for responsibility and audit traceability but is not a mandatory approval
gate. Repositories that gain an independent reviewer must apply `Team` mode with
`tools/github/configure-repository-protection.ps1`; Team mode restores one approval,
mandatory Code Owner review, and last-push approval without changing other gates.
