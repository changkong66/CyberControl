# Gate C 12 Trusted Foundation Governance

Process Version: `Gate-C-12-v1.0`

This document defines the executable governance added for the twelfth Gate C
foundation. It supplements the existing repository and quality-gate policies;
it does not relabel or rewrite historical evidence.

## Source And Worktree Binding

Every image, diagnostic, preflight and formal run records the exact source
commit, source tree, frozen `product_source_sha`, engineering baseline,
threshold SHA-256, workload SHA-256 and this process version. Image creation
requires a clean isolated worktree. A candidate branch image is always marked
as non-acceptance validation and cannot satisfy a protected-main or formal
image lock.

`product_source_sha` remains
`a57d0ce57427804ede3f3c620fda2a93b3a300ff`. Documentation, evidence and
infrastructure changes may advance `engineering_baseline_sha`, but do not
advance the product source baseline.

## Required CI Contexts

The protected `main` branch requires both of these exact job contexts:

- `Container build, runtime, SBOM, and vulnerability scan`
- `Release quality redline`

The workflow runs for pull requests, pushes to `main` and `codex/**`, and
GitHub merge queues through the `merge_group` event. The release redline keeps
its `always()` aggregation and rejects every failed, cancelled or skipped
prerequisite. The container job is required independently so a green aggregate
cannot hide a missing container security result.

## Infrastructure Abort Classification

`INFRA_ABORTED` is valid only when a run has an immutable failure record and
the failure is independently attributable to Docker/WSL, storage, image
digest, network, or another execution dependency. A product assertion failure,
probe design failure, zero-tolerance failure, or inconclusive owner is not an
infrastructure abort.

An infrastructure retry:

1. references the interrupted run ID and the same failure cause;
2. reruns only the interrupted level or stage with a fresh project, network and
   PostgreSQL volume;
3. is numbered `1` or `2` and does not reset diagnostic design or attribution
   counters;
4. never appends `gate_c_attempts` unless a Full run completes a formal product
   PASS/FAIL decision.

After two retries of the same proven cause, the next abort is archived as an
infrastructure report and execution stops for operator remediation. No retry
may be used to bypass a failed product or semantic control.

## Capacity And Cleanup

The 15/8/5 GiB policy remains active even when storage is migrated. Every
snapshot covers the results root, the host Docker data root and
`/mnt/docker-desktop-disk`; all three roots must pass admission. A warning on
any root blocks stage escalation. A hard stop gracefully stops every running
container owned by the current Compose project and never deletes a volume.
After each diagnostic or validation round, the evidence package and hashes are
verified first; only then are that round's containers, networks, PostgreSQL
volume and intermediate logs removed. Historical formal volumes, core images
and immutable evidence are never pruned or deleted.

## Evidence And State

New evidence JSON has a top-level `process_version`; Markdown reports declare
`Process Version: Gate-C-12-v1.0`. The CI metadata gate validates only files
changed by the current revision, so legacy records remain append-only and are
not backfilled. Every run emits both `execution-metadata.json` (the existing
runner contract) and `execution-context.json` (the stable audit alias) with
identical content.

`baseline_history` entries use the existing `change_type` field and may add
the normalized `type` values `INFRA`, `STATUS`, `DIAGNOSTIC`, `REMEDIATION`,
`EVIDENCE` and `RELEASE` only when a new append is made. `gate_c_attempts` is
formal-Full-only and remains append-only. State transitions require the exact
main SHA/tree, protected-main CI, image lock, build receipt and post-merge
closure receipt.

## Executable Governance

All commands run from a clean isolated worktree. Paths outside the repository
are supplied explicitly and become SHA-256-bound inputs in the generated JSON.

```powershell
uv run --frozen python tools/gate_c_governance.py verify-worktree `
  --expected-ref origin/main --output artifacts/gate-c/worktree.json

uv run --frozen python tools/gate_c_governance.py execution-context `
  --capacity-snapshot D:\path\capacity-snapshot.json `
  --classification NON_ACCEPTANCE_ENGINEERING `
  --image-lock D:\path\normal-image-lock.json `
  --image-lock D:\path\diagnostic-image-lock.json `
  --output artifacts/gate-c/execution-context.json

uv run --frozen python tools/gate_c_governance.py build-audit-index `
  --evidence-root docs/system-acceptance/evidence `
  --output artifacts/gate-c/gate-c-audit-index.json
```

`verify-history` runs in CI and rejects reordered or rewritten history, an
unsupported new baseline type, and any new attempt that is not bound by run ID
and product source to exactly one changed Full execution metadata record.
`verify-d1-readiness` is the final target-one gate: it verifies exact main,
normal and diagnostic locks, Docker migration, three-root capacity, the audit
index and post-merge receipts. Its output authorizes D1 only.
