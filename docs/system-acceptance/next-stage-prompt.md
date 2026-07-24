# CyberControl Phase 7 Gate C Remediation And Rerun - Next Task

You are the enterprise reliability engineer for CyberControl. Work only from
protected-main evidence. Do not reinterpret the failed Gate C run as accepted and
do not start Gate D.

## Fixed Baseline

- Workspace: C:/Users/wch06/Documents/CyberControl
- Current main: 63d62f071176185da33c195dbdf682186b3e8c9e
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

## Required PR-1: Scoped Remediation

Create codex/phase7-gate-c-sse-remediation from latest main.

Investigate and fix:

- SSE async-generator cancellation and ContextVar reset from different context.
- SQLAlchemy cancellation during SSE connection termination.
- Non-checked-in connection cleanup warnings.
- Reconnect/Last-Event-ID recovery shortfall.
- Duplicate replay suppression shortfall.
- Committed event loss under 2,000 streams.
- Publisher timeout and Outbox lag p95/p99 threshold failures.
- Post-ramp memory recovery ratio failure.

Add targeted tests for cancellation, disconnect cleanup, replay idempotence,
duplicate suppression, publisher timeout handling and pool/session cleanup. Run
the full local quality gates and push PR only after tests pass. Squash Merge only
after 8/8 CI.

## Required PR-2: Fresh Gate C Rerun Evidence

After remediation merges to main, create a fresh isolated PostgreSQL volume and
rerun the frozen Gate C stages: 20, 200, 500, 1,000 and 2,000 streams plus
10-minute recovery. Archive accepted or failed evidence in a new PR. If any
threshold fails, keep Gate D locked and stop.

## Stop Rule

Do not start Gate D soak until a protected-main Gate C rerun passes every frozen
threshold and the accepted evidence PR merges through 8/8 CI.
