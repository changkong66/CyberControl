# CyberControl Phase 7 Gate C Seventh Remediation And Rerun - Next Task

Work only from real protected-main evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, CI,
PostgreSQL, Keycloak Tokens, Docker state, load metrics, evidence packages or
acceptance decisions. Gate D, Gate E, Gate F and Gate G remain locked.

## Fixed Evidence Baseline

- Evaluated protected main: `a6979d760701271d579776b082dabe247ac6138b`
- Evaluated tree: `52ba6cd9f1c532cedbfe27fbcaf8b206c5d02c3f`
- Sixth remediation PR: [#61](https://github.com/changkong66/CyberControl/pull/61)
- Sixth remediation published head: `c95901bc36c1fa8c9a991bdbd593f18fe6007215`
- Sixth remediation merge: `a6979d760701271d579776b082dabe247ac6138b`
- Push CI: [Run 31537797593](https://github.com/changkong66/CyberControl/actions/runs/31537797593), 8/8
- Pull-request CI: [Run 31538456518](https://github.com/changkong66/CyberControl/actions/runs/31538456518), 8/8
- Protected-main CI: [Run 31538917814](https://github.com/changkong66/CyberControl/actions/runs/31538917814), 8/8
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Failed run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260811T214704Z-a6979d760701`
- Immutable package SHA256:
  `bb406ab73e7bc4532266f3274605402e28c356b58586ea20eee6648a54b5a18a`
- Immutable Release:
  `phase7-gate-c-sixth-remediation-failed-20260811-a6979d7`

## Mandatory Phase 0: Close The Sixth Failure Archive

The evidence-only branch is
`codex/phase7-gate-c-sixth-rerun-failure-evidence`, PR
[#62](https://github.com/changkong66/CyberControl/pull/62). Before creating a
remediation branch:

1. Verify branch, HEAD, tree, status, diff, `origin/main`, protected-main CI,
   all historical Gate C volumes and the two new sixth-run volumes.
2. Preserve every historical snapshot, Release, image and volume. Do not reset,
   checkout, prune, delete or overwrite them.
3. Validate only the sixth-remediation summary, report, failure analysis,
   database evidence, environment evidence, package metadata, manifest and
   current-state documentation.
4. Verify all JSON, repository file hashes, source/tree binding, threshold and
   workload hashes, immutable Release state, asset size/digest and redaction
   scan.
5. Require push CI 8/8, pull-request CI 8/8, Squash Merge and protected-main CI
   8/8. Do not create the seventh-remediation branch before this closure.

## Proven Sixth-Run Boundary

- 20, 200 and 500 authenticated streams passed.
- 1,000 streams sustained for 603 seconds and failed frozen controls.
- 2,000 streams and ten-minute recovery were not executed.
- Connection success: `1.0`.
- Reconnect/replay success: `1.0`.
- Committed event loss: `0`.
- Duplicate final render: `0`.
- Cross-tenant leakage: `0`.
- HTTP 5xx: `0`.
- Outbox `PUBLISHED/DEAD`: `105/0`.
- Commit-to-client p95/p99: `1805/7190 ms`, required `<=1000/3000 ms`.
- Outbox p95/p99: `10102.261/11812.566 ms`, required `<=2000/5000 ms`.
- Connection-establishment p95/p99: `21888/25735 ms`.
- API CPU p95/max: `128.502/145.910` one-core units.
- Host CPU p95/max: `39.720/50.100%`.
- Peak API RSS/file descriptors: `314677658 bytes / 1038`.
- Final subscribers, closing owners, queues, replay cache and replay tasks:
  `0/0/0/0/0`.
- `aclose()` race, pool timeout, OOM and unplanned restart: `0`.
- PostgreSQL migration head `20260720_0010`, FORCE RLS `74/74`, append-only
  triggers `57`, foreign-tenant visible rows `0`.

Do not reinterpret any partial pass as Gate C acceptance.

## Required PR-1: Seventh Scoped Remediation

After archive closure and a fresh `origin/main` 8/8 verification, create
exactly `codex/phase7-gate-c-seventh-remediation` from that main.

Before behavior changes, add an ADR mapping each proposed change to a measured
failed control and a quantitative disproof metric.

### A. Outbox Critical Path

- Reconstruct each valid `topic3.workflow.finalized` and Gate C probe path from
  transaction commit through `claimable`, `claimed`, dispatch start,
  server-derived service-principal authorization, durable acceptance,
  `PUBLISHED`, notification enqueue and client receipt.
- Use exact timestamps and bounded histograms to separate claim polling/wakeup,
  claim-batch SQL, partition scheduling, authorization, durable acceptance,
  published marking and notification delay.
- Explain why created-to-published p95/p99 regressed from
  `5830.700/8434.789` to `10102.261/11812.566 ms` despite zero `DEAD`, zero
  pool timeout and terminal `PUBLISHED=105`.
- Preserve `FOR UPDATE SKIP LOCKED`, lease tokens, retries, partition ordering,
  idempotent consumption, published cursors and atomic Outbox semantics.
- Never acknowledge publication before durable acceptance, broaden roles,
  fabricate user claims or add identity request headers.

### B. Event Loop, Fan-Out And Socket Delivery

- Profile event-loop runnable delay, notification coalescing work, per-event
  serialization, metrics aggregation, tenant-lock wait/hold, queue writes,
  slow-consumer handling and socket drain.
- Prove whether one-core API saturation is caused by fan-out, metrics,
  admission/replay work, publisher scheduling or socket writes before changing
  ownership or concurrency.
- Preserve global ordered sequence delivery, signed tenant-bound
  `Last-Event-ID`, durable replay, duplicate suppression and fail-closed cursor
  validation.
- Preserve the single idempotent close owner and zero asynchronous-generator
  close races.

### C. Admission And Resource Ownership

- Separate Keycloak Token issuance, HTTP authentication, admission queue,
  replay acquisition, subscriber registration, `REPLAYING -> LIVE` handoff and
  first-event readiness.
- Explain the `21888/25735 ms` admission p95/p99 with per-reason counters and
  bounded histograms. Do not widen timeouts or add a client-only grace period.
- Measure subscriber lifetime, queue bytes/events, pending tasks, socket file
  descriptors, database sessions and ContextVar ownership on success,
  cancellation, timeout and shutdown.
- Keep final subscriber, close-owner, queue and replay gauges at zero; do not
  claim memory recovery until the unchanged ten-minute observation executes.

### D. Tests And Quality Gates

Add deterministic unit, concurrency and real PostgreSQL tests for:

- Outbox wakeup, claim windows, lease renewal/release, timeout and retry;
- partition ordering, duplicate dispatch and valid finalized publication;
- invalid/cross-tenant event fail-closed behavior;
- notification coalescing without delayed durable synchronization;
- fan-out ordering, slow consumers, bounded backpressure and cancellation;
- admission/replay/LIVE handoff timing and signed cursor tamper rejection;
- session/pool return, ContextVar restoration, file-descriptor and task cleanup;
- multi-tenant isolation under concurrent Outbox and SSE activity.

The original regression must fail without the fix and pass with it. Keep Python
coverage `>=90%` without exclusions or empty assertions. Run Python and real
PostgreSQL integration, frontend, Playwright, Go, contract drift, SBOM/license,
Trivy and Gitleaks gates. Push and pull-request CI must pass 8/8; Squash Merge
only after green; then require protected-main 8/8.

## Required PR-2: Fresh Gate C Replay

Only after PR-1 merges and protected main is clean:

1. Build all images from the new main without `-SkipBuild`.
2. Create a unique Compose project, evidence directory and fresh PostgreSQL
   volume. Never reuse development, release or historical Gate C volumes.
3. Use real Keycloak-issued Tokens, two tenants and at least ten real subjects
   per tenant. Never fabricate JWTs.
4. Execute unchanged: 20 smoke, 200 for five minutes, 500 for five minutes,
   1,000 for ten minutes, 2,000 for thirty minutes, and ten-minute recovery.
5. Do not change thresholds, workload, events, connections, timeouts, grace
   periods or aggregation.
6. Bind source/tree, image IDs, Compose and lock hashes, frozen hashes,
   Token/admission/replay metrics, client metrics, CPU/RSS/FD/restarts,
   PostgreSQL sessions/pool/RLS/Outbox evidence and redacted logs.
7. Publish a new SHA256 manifest and immutable external package. Preserve all
   prior failed packages and volumes.

If every frozen control passes, merge an independent success-evidence PR
through push, pull-request and protected-main 8/8, then mark
`PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`.

If any control fails, stop, archive a new immutable failure package and
evidence PR, retain `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, and do not start Gate
D.

## Stop Rule

After the independent Gate C evidence PR is merged and protected-main CI is
verified, stop. Do not start Gate D soak, disaster recovery, Provider
acceptance, production deployment, accessibility/privacy closure or new
product features.
