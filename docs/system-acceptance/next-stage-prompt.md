# CyberControl Phase 7 Gate C Remediation And Rerun - Next Task

You are the enterprise reliability engineer for CyberControl. Work only from
protected-main evidence. Do not reinterpret the failed Gate C run as accepted and
do not start Gate D.

## Fixed Baseline

- Workspace: C:/Users/wch06/Documents/CyberControl
- Current main: 865735015f6600f88d79b34ddbe7ba06e635f72e
- Current remediation branch: codex/phase7-gate-c-sse-remediation
- Local implementation commit: 0389961
- Local test commit: 2fcfb57
- Local quality result: 630 collected, 628 passed, 2 skipped, 91.74% coverage
- Current state: RELEASE_CANDIDATE
- Formal state: PHASE7_GATE_C_FAILED_GATE_D_LOCKED
- Gate C failed run: D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260724T120822Z-63d62f071176
- Evidence summary: docs/system-acceptance/evidence/phase7-gate-c-summary.json
- Failure analysis: docs/system-acceptance/evidence/phase7-gate-c-failure-analysis.md
- Frozen thresholds: tests/load/gate-c-thresholds.v1.json
- Gate D-G: locked

## Non-Negotiable Constraints

1. Do not modify migrations 0001-0010, frozen contracts, RLS, identity
   authority, C12 publication semantics or tenant isolation.
2. Do not lower or reinterpret Gate C thresholds.
3. Do not send X-Tenant-ID, X-Subject-Ref, role or scope identity headers.
4. Use real Keycloak Tokens, real PostgreSQL and fresh isolated Gate C volumes.
5. Keep failed evidence immutable; create new evidence for every rerun.

## Required PR-1: Close Scoped Remediation

The scoped remediation is implemented and locally verified. Review the existing
commits, push `codex/phase7-gate-c-sse-remediation`, create the protected PR and
require both push and pull-request Release Quality Gates to pass 8/8. Squash Merge
only after all checks pass, then require the resulting protected main to pass 8/8.

The completed implementation covers:

- SSE async-generator cancellation and ContextVar reset from different context.
- SQLAlchemy cancellation during SSE connection termination.
- Non-checked-in connection cleanup warnings.
- Reconnect/Last-Event-ID recovery shortfall.
- Duplicate replay suppression shortfall.
- Committed event loss under 2,000 streams.
- Publisher timeout and Outbox lag p95/p99 threshold failures.
- Post-ramp memory recovery ratio failure.

Targeted unit and real PostgreSQL tests cover cancellation, disconnect cleanup,
replay idempotence, duplicate suppression, publisher timeout handling and
pool/session cleanup. Do not reinterpret local success as Gate C acceptance.

## Required PR-2: Fresh Gate C Rerun Evidence

After remediation merges to main, create a fresh isolated PostgreSQL volume and
rerun the frozen Gate C stages: 20, 200, 500, 1,000 and 2,000 streams plus
10-minute recovery. Archive accepted or failed evidence in a new PR. If any
threshold fails, keep Gate D locked and stop.

## Stop Rule

Do not start Gate D soak until a protected-main Gate C rerun passes every frozen
threshold and the accepted evidence PR merges through 8/8 CI.
