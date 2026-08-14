# CyberControl Phase 7 Gate C Ninth Remediation And Rerun

Work only from real protected-main, GitHub Actions, Docker, PostgreSQL,
Keycloak-issued Tokens and immutable load evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, tests, CI,
Tokens, metrics, images, volumes, packages or acceptance decisions. Gate D,
Gate E, Gate F and Gate G remain locked.

## Fixed Evaluated Baseline

- Current protected main: `0c35364d79cd89d149190c02557d2c352643300e`
- Current protected-main tree: `284df2edd208daf2379f5e1827bad18f92e303c8`
- Current protected-main CI:
  [Run 31798607779](https://github.com/changkong66/CyberControl/actions/runs/31798607779), 8/8
- Current product-code main: `c826b508ee5b094532a13bbe88d68e66948ed84c`
- Evaluated Gate C source: `4f0a7670782c5002a2da6e429c0428d8fef29153`
- Evaluated Gate C tree: `d79b15fce52b8a8b9afe4be361cfbcbba4c7ddc9`
- Seventh failure archive PR: [#65](https://github.com/changkong66/CyberControl/pull/65)
- Seventh archive merge: `4563ad4696c2cd8cd6aaec3108a287780d236293`
- Seventh archive protected-main CI:
  [Run 31610698379](https://github.com/changkong66/CyberControl/actions/runs/31610698379), 8/8
- Eighth remediation PR: [#66](https://github.com/changkong66/CyberControl/pull/66)
- Eighth remediation head: `e71654389dd2c3bf85a535faf956731cc82b289b`
- Eighth remediation merge: `4f0a7670782c5002a2da6e429c0428d8fef29153`
- Push CI: [Run 31629029809](https://github.com/changkong66/CyberControl/actions/runs/31629029809), 8/8
- Pull-request CI: [Run 31629100666](https://github.com/changkong66/CyberControl/actions/runs/31629100666), 8/8
- Protected-main CI: [Run 31629561293](https://github.com/changkong66/CyberControl/actions/runs/31629561293), 8/8
- Eighth failure-evidence PR: [#70](https://github.com/changkong66/CyberControl/pull/70)
- Eighth archive head: `c96f64f5230bf90ffebe4d9b125af4b6be138971`
- Eighth archive merge: `0c35364d79cd89d149190c02557d2c352643300e`
- Eighth archive push CI:
  [Run 31798234042](https://github.com/changkong66/CyberControl/actions/runs/31798234042), 8/8
- Eighth archive pull-request CI:
  [Run 31798238730](https://github.com/changkong66/CyberControl/actions/runs/31798238730), 8/8
- Eighth archive protected-main CI:
  [Run 31798607779](https://github.com/changkong66/CyberControl/actions/runs/31798607779), 8/8
- Superseded archive PR: [#67](https://github.com/changkong66/CyberControl/pull/67)
- Initial evidence push CI:
  [Run 31788710871](https://github.com/changkong66/CyberControl/actions/runs/31788710871),
  failed on `GHSA-2v37-7h3g-55p8` in `nanoid 3.3.17`
- Initial evidence pull-request CI:
  [Run 31788806194](https://github.com/changkong66/CyberControl/actions/runs/31788806194),
  failed on the same newly published advisory
- Independent supply-chain PR: [#68](https://github.com/changkong66/CyberControl/pull/68)
- Supply-chain head/merge:
  `91d5e74904bc5b17e6d55e05b556497649ec4fd1` /
  `c826b508ee5b094532a13bbe88d68e66948ed84c`
- Supply-chain push/pull-request CI:
  [Run 31790758140](https://github.com/changkong66/CyberControl/actions/runs/31790758140) /
  [Run 31790811040](https://github.com/changkong66/CyberControl/actions/runs/31790811040), both 8/8
- Superseded PR #67 retry CI:
  [Run 31797008505](https://github.com/changkong66/CyberControl/actions/runs/31797008505) /
  [Run 31797011334](https://github.com/changkong66/CyberControl/actions/runs/31797011334),
  both 6/8 because merge commit `939d4b7b98c4` failed Conventional Commit
  subject validation; preserve these runs as failed evidence
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Failed run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260812T190722Z-4f0a7670782c`
- Immutable package SHA256:
  `b22f81bbcd42fb5dab0c9bc64891fe8b49888663ab9c0f13260b1de313802ff1`
- Valid immutable Release:
  `phase7-gate-c-eighth-remediation-failed-20260812-4f0a767-evidence-v1`
- Original PostgreSQL volume:
  `cybercontrol_gate_c_eighth_4f0a767_20260813`
- Forensic PostgreSQL volume:
  `cybercontrol_gate_c_eighth_4f0a767_20260813_forensics`

## Proven Eighth-Run Boundary

- All five stages passed: 20/181s, 200/304s, 500/304s, 1,000/605s and
  2,000/1,804s.
- The fixed ten-minute recovery observation completed.
- Connection and reconnect/replay success: `1.0 / 1.0`.
- Delivery p95/p99 at 2,000 streams: `788/1042ms`.
- Event loss, duplicate final rendering, tenant leakage and invalid-cursor
  acceptance: all `0`.
- HTTP 5xx, unexpected disconnect, pool timeout, Outbox `DEAD`, OOM and
  unplanned restart: all `0`.
- Closing owners, queued events/bytes, replay buffers/caches and replay tasks:
  all `0`.
- API FDs first/last/peak: `29/29/2039` against a limit of `1,048,576`.
- Outbox `PUBLISHED=223`, terminal `PENDING/CLAIMED/DEAD=0`.
- Migration head `20260720_0010`, FORCE RLS `74/74`, append-only triggers `57`
  and foreign-tenant visibility `0`.
- No `aclose()` race, traceback, error, pool timeout, OOM or restart log.
- Failed Outbox p95: `2247.346ms`, required `<=2000ms`; Outbox p99
  `3438.55ms` passed its `<=5000ms` limit.
- Failed post-ramp RSS ratio: `1.393027`, required `<=1.10`; container RSS
  first/last/peak was `264660582/368679322/435054182` bytes.
- Process PSS was `300299264 -> 407353344`, USS was
  `297070592 -> 404389888`, anonymous RSS was
  `259416064 -> 363573248`, file RSS was unchanged at `48758784`, and map count
  changed from `615` to `619`.
- The final 30 recovery samples continuously reported `subscribers=1` and
  `subscribers_live=1`. This violates the required terminal lifecycle boundary
  and may relate to RSS retention, but the evidence does not yet prove causality.

Do not weaken any passed control while remediating these failures.

## Required PR-1: Ninth Scoped Remediation

Before creating a branch, fetch `origin/main` and require its exact tip to be
`0c35364d79cd89d149190c02557d2c352643300e`, tree
`284df2edd208daf2379f5e1827bad18f92e303c8`, with protected-main Run
31798607779 at 8/8. Require the worktree to be clean, verify the frozen hashes,
and preserve every historical Gate C package, Release, image and PostgreSQL
volume. Then create exactly:

`codex/phase7-gate-c-ninth-remediation`

Before behavior changes, add an ADR mapping every modification to one measured
failed control, a proposed causal mechanism and a quantitative disproof metric.

### A. Persistent Subscriber Close Ownership

- Trace the single residual subscriber from HTTP request admission through
  generator ownership, disconnect monitoring, heartbeat/live wait, response
  cancellation, task completion and subscriber removal.
- Determine whether the retained stream is the expired-token/invalid-cursor
  probe, a readiness request, a planned disconnect, a Locust connection or a
  server-side lifecycle task. Do not identify it by tenant, subject or cursor in
  logs or metric labels.
- Preserve one explicit idempotent close owner. No task may call `aclose()`
  while another task advances the same generator.
- Cancel and await disconnect, heartbeat, replay, live-queue and response-body
  tasks before subscriber removal, ContextVar restoration, session rollback and
  connection-pool return.
- Prove cleanup after replay yield, live wait, token expiry, invalid cursor,
  forced disconnect, timeout, client cancellation and coordinated shutdown.
- Keep all lifecycle metrics bounded and free of PII/cardinality expansion.

Disproof metric: after formal clients disconnect, subscriber and
live-subscriber gauges must reach zero and remain zero throughout the unchanged
ten-minute recovery, with close owners, queues, replay state, tasks and FDs at
their required terminal values and no async-generator close warning.

### B. Anonymous RSS/PSS/USS Retention

- Capture synchronized container RSS, process RSS/PSS/USS, anonymous/file RSS,
  memory maps, allocator stats, GC generations, tracemalloc snapshots, object
  counts, task/frame inventories, pool inventories and metric cardinality
  before ramp, at 2,000 streams, immediately after disconnect and throughout
  recovery.
- Compare snapshots by allocation traceback and type. Test the residual
  subscriber as one candidate owner, but also inspect ASGI response/request
  objects, task exceptions/frames, socket buffers, SSE serialized payloads,
  SQLAlchemy/HTTP pools, metric label state and allocator arena high-water.
- Distinguish reachable Python objects from native allocator fragmentation and
  legitimate bounded pool retention. Any allocator configuration change must
  apply from process start, be justified by measurements and pass the complete
  regression suite.
- Do not use `gc.collect()`, process restart, recovery-only `malloc_trim`, lower
  cache limits without ownership evidence, changed baseline/aggregation or a
  client grace period as the fix.

Disproof metric: the unchanged recovery observation must finish with API RSS
`<=1.10` of the frozen pre-ramp baseline, terminal lifecycle gauges at zero,
FDs near baseline and no OOM/restart.

### C. Outbox p95 Tail Correlation

- Correlate every sampled event using internal non-PII identifiers from
  transaction commit through claimable, claim start/end, partition scheduling,
  dispatch, server-derived service-principal authorization, durable acceptance,
  published marking, notification bridge, SSE enqueue and client receipt.
- Reconstruct p50/p90/p95/p99 segment contributions and inspect events around
  the actual p95 boundary. Do not infer a single cause from aggregate timestamps.
- Determine whether the remaining `247.346ms` breach is caused by wake/poll
  jitter, session acquisition, claim scheduling, partition head-of-line
  blocking, authorization/durable acceptance, published marking or event-loop
  scheduling.
- Keep `FOR UPDATE SKIP LOCKED`, claim tokens, leases, retries, partition order,
  idempotent durable acceptance, published cursor and atomic Outbox semantics.
- Valid finalized events must end `PUBLISHED`; invalid and cross-tenant events
  remain fail-closed. Cancellation and timeout must not leave long-lived
  `CLAIMED/PENDING` work.
- Do not acknowledge publication early, skip durable acceptance, broaden
  service roles or add client-supplied identity headers.

Disproof metric: under the unchanged workload, created-to-published p95 must be
`<=2000ms` and p99 `<=5000ms`, with `DEAD=0`, no long-lived
`CLAIMED/PENDING`, unchanged partition order and zero tenant leakage.

### D. Tests And Quality Gates

Add focused unit, deterministic concurrency and real PostgreSQL tests for:

- the exact residual-subscriber request/lifecycle path;
- replay/live cancellation, token expiry, invalid cursor and double close;
- coordinated shutdown, response-body completion and close-owner idempotency;
- ContextVar restoration, session rollback, pool return, task/frame and FD
  release;
- bounded queue/replay/metric-label state and slow-consumer backpressure;
- allocation ownership and anonymous-memory recovery without forced GC;
- Outbox wake/poll jitter, claim batch, lease release/renewal, retry exhaustion
  and partition ordering;
- valid finalized, invalid, duplicate and cross-tenant dispatch;
- publisher cancellation/timeout and terminal `PENDING/CLAIMED/DEAD` state;
- notification bridge readiness, ordered SSE enqueue and concurrent tenant
  isolation.

Each proven-defect regression must fail without its fix and pass with it.
Performance tests must use real measured operations and must not claim a
fabricated 2,000-client scale. Keep Python coverage `>=90%`; target no lower
than the current accepted code-quality evidence. No exclusions, empty
assertions, fabricated timing or forced GC.

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
   client metrics, CPU/RSS/USS/PSS/FD/restarts, terminal subscriber/task/queue/
   replay inventories, PostgreSQL sessions/pool/RLS/Outbox state, redacted logs
   and a SHA256 manifest to the result.
7. Publish a new immutable external package. Preserve every previous failed
   package, Release and PostgreSQL volume.

If every frozen control passes and the required terminal lifecycle boundary is
zero, create an independent success-evidence PR, mark
`PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`, require push and pull-request
8/8, Squash Merge and protected-main 8/8, then stop.

If any frozen control or required terminal lifecycle boundary fails, stop the
workload, publish a new immutable failure package, create an independent
failure-evidence PR, retain `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, complete the
same CI/merge closure and stop.

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
