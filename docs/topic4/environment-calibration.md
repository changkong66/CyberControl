# Topic4 Environment Calibration Report

## 1. Git Calibration

- Local branch: `codex/topic4-verifier-runtime`
- Remote tracking branch: `origin/codex/topic4-verifier-runtime`
- Calibrated implementation SHA:
  `8d143ba43ae78f3b66ab8d691d1513f03f8baa2d`
- Protected main base:
  `6922cd3e6cf6a014f7c5a7e0436596d97fcc71df`
- Frontend diff from protected base: none
- Worktree before acceptance documentation: clean

## 2. Local Quality Calibration

- Full PostgreSQL/JUnit: 429 total, 428 passed, 1 skipped, 0 failed.
- Coverage: 91.19% (`18,589 / 20,384` lines).
- Non-integration suite: 371 passed, 1 skipped.
- Alembic round trip and head check: passed at `20260716_0009`.
- Ruff check and format: passed.
- Go format, mod verify, vet, race, and build: passed.
- TypeScript/Vue typecheck and build: passed.
- Python and Node dependency audits: passed.
- CycloneDX SBOM and license policies: passed.
- Actionlint 1.7.12: passed.
- Gitleaks 8.30.1 history/worktree: 0/0 findings.
- Trivy 0.72.0 all severities: 0 findings.

## 3. Runtime Image Calibration

- Retrieval extra and Faiss import: passed.
- Runtime user: `10001:10001`.
- Build/test tools absent from runtime: pytest, pip, setuptools, and wheel.
- `/health/live`: passed.

## 4. Remote Calibration

Release Quality Gates Run `29634407475` verified the exact calibrated SHA and
completed 8/8 jobs successfully. No dependency lock or generated contract drift
was reported by the workflow.
