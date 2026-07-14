# Engineering Contribution Policy

## Protected branches

`main` is the release baseline. Direct feature development on `main` is
prohibited after the initial repository baseline. Repository hosting must require
pull requests, passing quality gates, resolved review threads, and linear history.

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

## Versioning

- Public wire contracts use immutable semantic major versions such as `v1`.
- Python, TypeScript, Go, migrations, policies, prompts, and knowledge bases have
  independent versions.
- Release tags use `vMAJOR.MINOR.PATCH`.
- Database migrations are append-only after merge to `main`.

## Required checks

No pull request may merge without Python tests, Ruff, Go tests, TypeScript checks,
migration validation, dependency vulnerability checks, and SBOM generation.
