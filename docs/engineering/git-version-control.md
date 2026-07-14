# Git and Version-Control Baseline

## Architecture decision

The repository uses trunk-based development with short-lived branches and a
protected `main` branch. This keeps the competition integration branch deployable
while retaining review, rollback, bisect, and release provenance.

## Baseline rules

1. The initial commit captures the validated Topic 3 engineering baseline.
2. Phase 1.1 work proceeds on `codex/phase-1.1-foundation`.
3. Generated contracts are committed and regenerated only from the canonical
   Pydantic registry.
4. Secrets, local databases, caches, build output, audit logs, and artifacts are
   excluded by `.gitignore`.
5. Accepted ADRs are immutable; changed decisions require a superseding ADR.
6. Security-sensitive changes require explicit tenant, authorization, and audit review.

## Hosting protection requirements

- Require pull requests and at least one owner approval.
- Require all CI jobs and migration checks.
- Block force pushes and branch deletion on `main`.
- Require signed commits or verified platform signatures for release branches.
- Retain release artifacts, SBOMs, and provenance attestations with the tag.

## Rollback

Application rollback uses an immutable release tag and image digest. Database
rollback uses a reviewed Alembic downgrade only when it is data-safe; otherwise a
forward corrective migration is mandatory. Outbox and audit data are never erased
as part of an application rollback.

## Quantitative acceptance

- Zero untracked source files after the baseline commit.
- A valid `main` history exists and can be cloned and built.
- Every Phase 1.1 implementation commit is attributable and independently testable.
- Release tags resolve to an SBOM and quality-gate result.
