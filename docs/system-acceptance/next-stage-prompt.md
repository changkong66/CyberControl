# CyberControl Phase 7 Gate C Tenth Remediation And Rerun

Work only from real protected-main evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, tests, CI,
Keycloak Tokens, Docker state, PostgreSQL state, load metrics, packages or
acceptance decisions. Gate D, Gate E, Gate F and Gate G remain locked.

## Verified Baseline

- Evaluated protected-main source:
  `993ed9719dfb363238fe3c2f075f1d7e7e269b40`
- Evaluated tree:
  `8dcbe0c2c23b618c851acc9e4b5de4dd4f3681c5`
- Ninth remediation PR: [#72](https://github.com/changkong66/CyberControl/pull/72)
- Ninth remediation head: `81bc33208cc5368a97ca74b9f519144cad93f196`
- Ninth push/PR/protected-main CI: Runs
  [31818504209](https://github.com/changkong66/CyberControl/actions/runs/31818504209),
  [31818567543](https://github.com/changkong66/CyberControl/actions/runs/31818567543)
  and [31819184923](https://github.com/changkong66/CyberControl/actions/runs/31819184923),
  each 8/8
- Formal state:
  `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Ninth failed run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260814T163148Z-993ed9719dfb`
- Ninth immutable package SHA256:
  `d6b5454dad9c4b9471415211b5f212efc6f73c8f90358af2743f363f87362ea3`
- Ninth package Release:
  `phase7-gate-c-ninth-remediation-failed-20260814-993ed97-evidence-v1`
- Ninth PostgreSQL volume:
  `cybercontrol_gate_c_ninth_993ed97_20260815`

## Mandatory Phase 0: Close Ninth Failure Archive

Before any remediation branch is created:

1. Verify the evidence-only branch
   `codex/phase7-gate-c-ninth-rerun-failure-evidence`, its source/tree, clean
   status, `origin/main`, protected-main Run `31819184923` and all historical
   Gate C volumes.
2. Preserve every historical snapshot, Release, image, Compose project and
   PostgreSQL volume. Never reset, checkout, prune, delete, overwrite or amend
   historical evidence.
3. Validate only the ninth evidence package and the four current-state
   documents. Verify JSON syntax, source/tree bindings, all file hashes,
   package size, package SHA256, Release asset digest and redaction scan.
4. Create a docs/evidence-only PR. Require push CI 8/8, pull-request CI 8/8,
   Squash Merge and protected-main CI 8/8.
5. Keep the formal state failed and Gate D-G locked. Do not interpret the five
   stage-local passes as Gate C acceptance.
6. Only after the archive merge and protected-main 8/8 may the tenth-remediation
   branch be created.

## Ninth Failure Boundary

The complete 20, 200, 500, 1,000 and 2,000 authenticated stages and fixed
ten-minute recovery completed. Connection/reconnect success was `1.0/1.0`;
event loss, final duplicate rendering, cross-tenant leakage, HTTP 5xx, pool
timeouts, Outbox `DEAD`, OOM, restart and async-generator close races were zero.
Final subscriber, close owner, queue, replay cache and replay task gauges were
zero.

The only frozen aggregate failures were:

- Outbox p95 `3102.698ms`, required `<=2000ms`; p99 `3935.444ms` passed.
- Post-ramp API memory ratio `1.416064`, required `<=1.10`.

Do not regress the passed controls or reuse the eighth-run one-live-subscriber
finding without new evidence. The ninth run ended with zero lifecycle gauges;
the tenth task must establish the actual RSS retaining owner and the exact
Outbox p95 tail segments.

## Required PR-1: Tenth Scoped Remediation

After the archive is merged and protected main is verified, create exactly:
`codex/phase7-gate-c-tenth-remediation`.

Before behavioral changes, add an ADR mapping every modification to one of the
two measured failed controls and specifying a quantitative disproof metric.

### A. Outbox p95 Tail

- Correlate non-PII internal event IDs from transaction commit through
  claimable, claim start/end, partition scheduling, dispatch, server-derived
  service-principal authorization, durable acceptance, published marking,
  notification bridge, SSE enqueue and client receipt.
- Reconstruct p50/p90/p95/p99 for each segment and identify the events around
  the p95 boundary. Distinguish wake/poll jitter, claim scheduling, session
  acquisition, partition head-of-line blocking, authorization, durable
  acceptance, publication marking and event-loop delay.
- Preserve `FOR UPDATE SKIP LOCKED`, claim tokens, leases, retries, partition
  order, idempotent durable acceptance, published cursor and atomic Outbox
  semantics. Valid finalized events must be `PUBLISHED`; invalid and
  cross-tenant events must fail closed.
- Timeout/cancellation must release or renew claims without durable
  `CLAIMED/PENDING` residue. Do not acknowledge early, broaden roles or add
  client identity headers.

Disproof: unchanged workload created-to-published Outbox p95 `<=2000ms`, p99
`<=5000ms`, `DEAD=0`, no long-lived `CLAIMED/PENDING`, unchanged order and zero
tenant leakage.

### B. RSS Ownership And Lifecycle

- Capture synchronized API RSS, USS/PSS, `/proc` maps, tracemalloc current and
  peak allocations, allocator statistics, GC generation counts, object counts,
  bounded task/frame inventories and pool high-water state before ramp, at
  2,000 streams, after disconnect and throughout recovery.
- Prove whether retention is reachable Python state, task exceptions/frames,
  metric label/state cardinality, HTTP/database pools, serialization buffers,
  queue payloads, replay structures or native allocator fragmentation.
- Preserve the single idempotent close owner and await disconnect, heartbeat,
  replay and live-queue tasks before subscriber, ContextVar, session, pool and
  FD cleanup. Prove zero terminal lifecycle gauges on success, cancellation,
  timeout, token expiry and coordinated shutdown.
- Do not use `gc.collect()`, process restart, recovery-only `malloc_trim`, a
  changed baseline, a lower cache limit without ownership proof or aggregation
  changes as the fix.

Disproof: unchanged ten-minute recovery ends at API RSS `<=1.10` of the frozen
pre-ramp baseline, terminal gauges are zero, FDs return near baseline and there
are no OOMs or restarts.

### C. Tests And Quality

Add deterministic unit/concurrency and real PostgreSQL tests for Outbox p95
segment timing, wake/poll behavior, claim release, retry exhaustion,
partition ordering, valid/invalid/cross-tenant dispatch, notification bridge
readiness, slow consumers, cancellation/double-close, task/frame release,
ContextVar/session/pool return, FD cleanup, allocation ownership and signed
cursor tamper isolation. Each regression must fail without the fix and pass
with it. Use real measured operations; do not claim fabricated scale.

Keep Python coverage `>=90%` with no exclusions, empty assertions or forced GC.
Run the complete local Python/PostgreSQL, frontend, Playwright, Go,
contract-drift, SBOM/license, dependency, Trivy and Gitleaks gates. Push and
pull-request CI must be 8/8; Squash Merge only after green; then require
protected-main 8/8.

## Required PR-2: Fresh Gate C Mainline Replay

Only after PR-1 merges and protected main is clean:

1. Build every image from the new main without `-SkipBuild`.
2. Create a unique Compose project, run directory and fresh PostgreSQL volume.
   Never reuse development, release or historical Gate C volumes.
3. Use real Keycloak-issued Tokens, two tenants and at least ten real subjects
   per tenant. Do not fabricate JWTs or send tenant, subject, role or scope
   identity headers.
4. Execute unchanged: 20 smoke, 200 for five minutes, 500 for five minutes,
   1,000 for ten minutes, 2,000 for thirty minutes and the fixed ten-minute
   recovery observation.
5. Bind source/tree, image IDs, Compose and lock hashes, threshold/workload
   hashes, token/admission/replay/handoff, Outbox segments, client delivery,
   CPU/RSS/USS/PSS/FD/restarts, PostgreSQL sessions/pool/RLS/Outbox terminal
   state, redacted logs and a SHA256 manifest.
6. Publish a new immutable package. Preserve all prior packages and volumes.

If every frozen control passes, create an independent success-evidence PR,
mark `PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`, require push, PR and
protected-main 8/8, then stop. If any control fails, publish a new immutable
failure package, create an independent failure-evidence PR, retain
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, complete the same CI closure and stop.

## Permanent Stop Rule

Do not start Gate D soak, disaster recovery, Provider acceptance, production
deployment, accessibility/privacy closure or new product work. Gate D requires
a separate explicit authorization even after an independent Gate C success
evidence PR has merged through protected-main 8/8.
