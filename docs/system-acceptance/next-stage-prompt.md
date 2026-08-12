# CyberControl Phase 7 Gate C Eighth Remediation And Rerun

Work only from real protected-main, GitHub Actions, Docker, PostgreSQL,
Keycloak Token and immutable load evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, tests, CI,
Tokens, metrics, images, volumes, packages or acceptance decisions. Gate D,
Gate E, Gate F and Gate G remain locked.

## Fixed Evaluated Baseline

- Evaluated protected main: `fa5b4bd92e4b56704f70b63416906a10c54e0ee1`
- Evaluated tree: `a9f020fd5cceb7a094439ad4c4089b63d3b473a7`
- Seventh remediation PR: [#64](https://github.com/changkong66/CyberControl/pull/64)
- Seventh remediation head: `f891ddd1c4b757f38e214a3019c82c0a777130cd`
- Seventh remediation merge: `fa5b4bd92e4b56704f70b63416906a10c54e0ee1`
- Push CI: [Run 31592761559](https://github.com/changkong66/CyberControl/actions/runs/31592761559), 8/8
- Pull-request CI: [Run 31592947063](https://github.com/changkong66/CyberControl/actions/runs/31592947063), 8/8
- Protected-main CI: [Run 31593377181](https://github.com/changkong66/CyberControl/actions/runs/31593377181), 8/8
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Failed run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260812T120720Z-fa5b4bd92e4b`
- Immutable package SHA256:
  `a01a16fdfc4f50f14b0a74a234a9e5f332ab20a29451c49096b6f7901236f2fd`
- Immutable Release:
  `phase7-gate-c-seventh-remediation-failed-20260812-fa5b4bd`
- Original PostgreSQL volume:
  `cybercontrol_gate_c_seventh_fa5b4bd_20260812`
- Forensic PostgreSQL volume:
  `cybercontrol_gate_c_seventh_fa5b4bd_20260812_forensics`

## Mandatory Phase 0: Close The Seventh Failure Archive

The current evidence branch is
`codex/phase7-gate-c-seventh-rerun-failure-evidence`. Before creating any
remediation branch:

1. Perform read-only checks of branch, HEAD, tree, status, diff, `origin/main`,
   protected-main CI, Docker state and every historical Gate C volume.
2. Preserve all existing evidence, Releases, images and volumes. Do not reset,
   checkout, prune, delete, overwrite or amend historical snapshots.
3. Validate and commit only the seventh-run summary, report, failure analysis,
   database evidence, environment evidence, package metadata, manifest and the
   four current-state documents.
4. Verify every JSON file, repository-manifest hash/size, source/tree binding,
   threshold/workload hash, immutable Release and asset size/digest, and the
   credential/JWT/PII redaction scan.
5. Keep `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. Do not reinterpret five
   stage-local passes as Gate C acceptance.
6. Push the docs/evidence-only branch, create a ready PR, require push and
   pull-request Release Quality Gates 8/8, Squash Merge, then require
   protected-main 8/8.
7. Only after that merge and post-merge main CI are verified may the eighth
   remediation branch be created.

## Proven Seventh-Run Boundary

- All five stages passed: 20/181s, 200/304s, 500/305s, 1,000/604s and
  2,000/1,803s.
- The fixed ten-minute recovery observation completed.
- Connection and reconnect/replay success: `1.0 / 1.0`.
- Delivery p95/p99 at 2,000 streams: `781/990ms`.
- Event loss, duplicate final rendering, tenant leakage and invalid-cursor
  acceptance: all `0`.
- HTTP 5xx, unexpected disconnect, pool timeout, Outbox `DEAD`, OOM and
  unplanned restart: all `0`.
- Final subscribers, close owners, queued events/bytes, replay buffers, replay
  caches and replay tasks: all `0`.
- API FDs first/last/peak: `29/30/2039` against a limit of `1,048,576`.
- Outbox `PUBLISHED=221`, terminal `PENDING/CLAIMED/DEAD=0`.
- Migration head `20260720_0010`, FORCE RLS `74/74`, append-only triggers `57`
  and foreign-tenant visibility `0`.
- No `aclose()` race, traceback, error, pool timeout, OOM or restart log.
- Failed Outbox p95: `2225.796ms`, required `<=2000ms`; Outbox p99
  `3026.102ms` passed its `<=5000ms` limit.
- Failed post-ramp RSS ratio: `1.492792`, required `<=1.10`; API RSS
  first/last/peak was `276404634/412614656/448371098` bytes.

Do not weaken any passed control while remediating the two failures.

## Required PR-1: Eighth Scoped Remediation

After Phase 0 closes, fetch `origin/main` and require its exact current tip to
contain the seventh failure archive with a successful 8/8 protected-main run.
Create exactly:

`codex/phase7-gate-c-eighth-remediation`

from that tip. Before behavior changes, add an ADR mapping each modification to
one measured failed control, a proposed causal mechanism and a quantitative
disproof metric.

### A. Outbox p95 Tail Isolation

- Correlate every sampled event using internal non-PII identifiers from
  transaction commit through claimable, claim start/end, partition scheduling,
  dispatch, server-derived service-principal authorization, durable acceptance,
  published marking, notification bridge, SSE enqueue and client receipt.
- Reconstruct the exact p50/p90/p95/p99 segment contributions and inspect the
  events around the p95 boundary. The existing evidence has 221 lifecycle
  observations, 203 claimed within one second and 211 published within 2.5
  seconds; do not infer a single cause from aggregate timestamps.
- Determine whether the remaining 225.796ms p95 breach is caused by wake/poll
  jitter, claim scheduling, transaction/session acquisition, partition
  head-of-line blocking, authorization/durable acceptance, published marking or
  event-loop scheduling.
- Keep `FOR UPDATE SKIP LOCKED`, claim tokens, leases, retries, partition order,
  idempotent durable acceptance, published cursor and atomic Outbox semantics.
- A valid finalized event must end `PUBLISHED`; invalid and cross-tenant events
  must remain fail-closed. Cancellation and timeout must release or renew claims
  without long-lived `CLAIMED/PENDING` rows.
- Do not acknowledge publication early, skip durable acceptance, weaken order,
  broaden service roles or add client-supplied identity headers.

Disproof metric: under the unchanged formal workload, created-to-published p95
must be `<=2000ms` and p99 `<=5000ms`, with `DEAD=0`, no long-lived
`CLAIMED/PENDING`, unchanged partition order and zero tenant leakage.

### B. RSS Retention Ownership

- Capture synchronized RSS, USS/PSS, `/proc` memory maps, tracemalloc current
  and peak allocations, allocator statistics, GC generation counts, object
  counts and bounded inventories before ramp, at 2,000 streams, after forced
  disconnect and throughout the unchanged ten-minute recovery.
- Compare snapshots by allocation traceback and object type. Verify ownership
  in metric label/state storage, HTTP and database pools, task exceptions and
  frames, SSE serialization buffers, queue payloads, replay structures and
  client/request lifecycle objects.
- Distinguish reachable Python objects from native allocator arena
  fragmentation and legitimate bounded pool high-water state. If allocator
  behavior is the proven owner, any production configuration change must apply
  from process start, be justified in the ADR and pass complete regression; a
  recovery-only trim is not acceptable.
- Preserve the single idempotent close owner. Cancel and await disconnect,
  heartbeat, replay and live-queue tasks before subscriber, ContextVar, session
  and connection cleanup.
- Prove connection-pool return, transaction rollback, ContextVar restoration,
  queue/replay eviction and metric-label cardinality bounds on success,
  cancellation, token expiry, timeout and coordinated shutdown.
- Do not use `gc.collect()`, process restart, recovery-only `malloc_trim`, lower
  cache limits without ownership evidence, changed RSS baseline, changed
  aggregation or a client grace period as the fix.

Disproof metric: the unchanged recovery observation must finish with API RSS
`<=1.10` of the frozen pre-ramp baseline, terminal lifecycle gauges at zero,
FDs near baseline and no OOM/restart.

### C. Tests And Quality Gates

Add focused unit, deterministic concurrency and real PostgreSQL tests for:

- Outbox wakeup and poll jitter at the p95 boundary;
- claim-batch, lease renewal/release, retry exhaustion and partition ordering;
- valid finalized, invalid, duplicate and cross-tenant dispatch;
- publisher cancellation/timeout and terminal `PENDING/CLAIMED/DEAD` state;
- notification bridge readiness and ordered SSE enqueue;
- allocation ownership and bounded metric-label cardinality;
- slow-consumer, replay, cancellation, double-close and coordinated shutdown;
- ContextVar restoration, session/pool return, task/frame release and FD cleanup;
- signed cursor tamper/cross-tenant rejection and concurrent tenant isolation.

The regression for each proven defect must fail without the fix and pass with
it. Performance tests must use real measured operations and must not claim a
fabricated 2,000-client scale. Keep Python coverage `>=90%`, targeting no lower
than the current 91.68% evidence. No exclusions, empty assertions or forced GC.

Run the complete local quality suite: Python and real PostgreSQL integration,
frontend unit/build/coverage, Playwright, Go fmt/vet/race/test/build, frozen
contract drift, SBOM/license, dependency audit, Trivy and Gitleaks. Push and
pull-request CI must each pass 8/8. Squash Merge only after green, then require
the new protected-main run to pass 8/8.

## Required PR-2: Fresh Gate C Mainline Replay

Only after PR-1 merges and protected main is clean:

1. Build every image from the new main without `-SkipBuild`.
2. Create a unique Compose project, run directory and fresh PostgreSQL volume.
   Never reuse development, release or historical Gate C volumes.
3. Use real Keycloak-issued Tokens, two tenants and at least ten real subjects
   per tenant. Do not fabricate JWTs or send tenant/subject/role/scope headers.
4. Execute the frozen workload unchanged: 20 smoke, 200 for five minutes, 500
   for five minutes, 1,000 for ten minutes, 2,000 for thirty minutes and the
   fixed ten-minute recovery observation.
5. Do not change thresholds, workload, events, connections, timeouts, grace
   periods, baseline selection or aggregation.
6. Bind source/tree, image IDs, Compose and lock hashes, threshold/workload
   hashes, Keycloak issuance, admission/replay/handoff, Outbox segment and
   client metrics, CPU/RSS/USS/PSS/FD/restarts, PostgreSQL sessions/pool/RLS/
   Outbox terminal state, redacted logs and a SHA256 manifest to the result.
7. Publish a new immutable external package. Preserve every previous failed
   package and PostgreSQL volume.

If every frozen control passes, create an independent success-evidence PR,
mark `PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`, require push and
pull-request 8/8, Squash Merge and protected-main 8/8, then stop.

If any frozen control fails, stop the workload, publish a new immutable failure
package, create an independent failure-evidence PR, retain
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, complete the same CI/merge closure and
stop.

## Permanent Constraints And Stop Rule

- Do not modify migrations `0001-0010`, frozen contracts, RLS, TenantContext,
  identity authority, SERIALIZABLE transactions, Outbox atomicity, C12,
  thresholds or workload.
- Do not lower load, events or thresholds; increase timeouts; add grace periods;
  change metric aggregation; fabricate JWTs; force GC; or add workers solely to
  hide a single-process defect.
- Preserve zero loss, zero final duplicates, zero cross-tenant leakage, zero
  invalid-cursor acceptance, zero Outbox `DEAD`, ordered durable replay, signed
  tenant-bound cursors and zero async-generator close races.
- Keep failed evidence immutable and use a new run directory, Compose project,
  PostgreSQL volume and evidence package for every formal rerun.
- Do not start Gate D soak, disaster recovery, Provider acceptance, production
  deployment, accessibility/privacy closure or new product work during this
  task.

After the independent Gate C evidence PR merges and protected-main CI is
verified, stop and report exact PRs, commits, CI URLs, package hashes, complete
metrics, residual risks and whether Gate D is eligible. Gate D requires a
separate explicit authorization even after eligibility.
