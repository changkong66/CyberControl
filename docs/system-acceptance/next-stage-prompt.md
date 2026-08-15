# CyberControl Phase 7 Gate C Eleventh Remediation And Rerun

Work only from real protected-main, GitHub Actions, Docker, PostgreSQL,
Keycloak Token and immutable load evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, tests, CI,
Tokens, metrics, images, volumes, packages or acceptance decisions. Gate D,
Gate E, Gate F and Gate G remain locked.

## Verified Tenth-Run Baseline

- Current protected main after the tenth failure archive:
  `e6b461cd0b919dfe01e87ed040d04771a746d6c2`
- Current protected-main tree:
  `50adc4192cd235155233a5ba5d216e808d5349ec`
- Current protected-main CI:
  [31883708144](https://github.com/changkong66/CyberControl/actions/runs/31883708144),
  8/8
- Evaluated protected main:
  `64792b0420f436d18beea2a301bd4017bc7e7a82`
- Evaluated tree:
  `61da331c23a5d5b6988aff70d0db5455732886cc`
- Tenth remediation PR:
  [#75](https://github.com/changkong66/CyberControl/pull/75)
- Push, pull-request and protected-main CI:
  [31865357058](https://github.com/changkong66/CyberControl/actions/runs/31865357058),
  [31865358914](https://github.com/changkong66/CyberControl/actions/runs/31865358914)
  and
  [31865636339](https://github.com/changkong66/CyberControl/actions/runs/31865636339),
  each 8/8
- Formal state:
  `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Frozen threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Failed run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260815T050434Z-64792b0420f4`
- Compose project:
  `cybercontrol-gate-c-tenth-main-64792b-20260815050434`
- Preserved PostgreSQL volume:
  `cybercontrol_gate_c_tenth_main_64792b_20260815050434`
- Immutable package SHA256:
  `036b3c8e09a8ff039b7b30a0d45cf9d67d6939f29690a39b35b9c52e8756e91c`
- Immutable Release:
  [371033270](https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-tenth-remediation-failed-20260815-64792b0-evidence-v1)
- Tenth failure-evidence PR:
  [#76](https://github.com/changkong66/CyberControl/pull/76)
- Tenth archive head/merge:
  `40471a50f58c758a5acf129f259126ca2ece0288` /
  `e6b461cd0b919dfe01e87ed040d04771a746d6c2`
- Tenth archive push/PR/main CI:
  [31883430063](https://github.com/changkong66/CyberControl/actions/runs/31883430063),
  [31883432630](https://github.com/changkong66/CyberControl/actions/runs/31883432630)
  and
  [31883708144](https://github.com/changkong66/CyberControl/actions/runs/31883708144),
  each 8/8

## Mandatory Protected-Main Preflight

Before creating a remediation branch:

1. Fetch `origin/main` and require its exact tip to contain archive merge
   `e6b461cd0b919dfe01e87ed040d04771a746d6c2` with successful protected-main
   Run `31883708144` at 8/8. If a later main exists, require it to be a clean
   descendant with its own successful 8/8 protected-main run.
2. Require a clean worktree and re-verify the frozen threshold/workload hashes.
3. Preserve the run directory, immutable Release, package, images and
   PostgreSQL volume. Do not reset, amend, prune, delete or overwrite history.
4. Keep `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. No smoke-local pass may be
   reinterpreted as Gate C acceptance.

After preflight, create exactly:

`codex/phase7-gate-c-eleventh-remediation`

from the exact current protected main.

## Proven Tenth-Run Boundary

- Real Keycloak provisioning produced two tenants and twenty principals.
- The unchanged `smoke-20` stage completed with twenty active authenticated
  streams and 121 sustained seconds.
- Delivery p95 was `439ms` and passed the `<=1000ms` control.
- Delivery p99 was `6850ms` and failed the `<=3000ms` control.
- The merged histogram had 3,380 observations, 70 above 1,000ms and 40 above
  3,000ms. The tail included observations at 6,850ms, 8,979ms, 9,276ms and
  approximately 9,609-9,613ms.
- Monitor completeness was `31/39=0.7948717949`, below `>=0.95`. Seven
  samples timed out reading `/metrics`; the final sample had one Docker
  inspection failure.
- Connection and reconnect/replay success were `1.0/1.0`.
- Committed loss, final duplicate rendering, cross-tenant leakage, HTTP 5xx,
  pool acquisition timeout and Outbox `DEAD` were zero.
- Tampered and cross-tenant cursors returned 400; unauthenticated and invalid
  Tokens returned 401.
- PostgreSQL ended at migration `20260720_0010`, FORCE RLS `74/74`, 57
  append-only triggers, foreign-tenant visibility 0 and Outbox
  `PUBLISHED=25` with no terminal `PENDING/CLAIMED/DEAD`.
- The mandatory stop rule left 200, 500, 1,000, 2,000 and recovery unexecuted.
  No post-ramp RSS, terminal subscriber or full-run Outbox conclusion is valid.

## Required PR-1: Eleventh Scoped Remediation

Before behavior changes, add an ADR that maps each modification to a measured
failed control, a causal hypothesis and a quantitative disproof metric.

### A. Delivery-Tail Correlation

- Correlate every non-PII probe from producer start and transaction commit
  through claimable, claim, dispatch, authorization, durable acceptance,
  `PUBLISHED`, notification bridge, SSE enqueue, socket write and client
  receipt.
- Reconstruct p50/p90/p95/p99 for each segment and identify the exact 40
  observations above 3,000ms. Determine whether they align with initial burst,
  reconnect/replay, workflow dispatch, metrics diagnostics, event-loop stalls,
  database acquisition, notification coalescing or socket backpressure.
- Measure event-loop runnable delay, tenant-lock wait, fan-out serialization,
  queue write, socket drain and slow-consumer effects without adding a client
  grace period or changing aggregation.
- Preserve signed tenant-bound Last-Event-ID, strict ordered durable replay,
  duplicate suppression, fail-closed cursor validation and the single
  idempotent close owner.

Disproof: under the unchanged smoke and full formal workload, delivery p95 must
be `<=1000ms` and p99 `<=3000ms`, with zero loss, final duplicate rendering,
tenant leakage and invalid-cursor acceptance.

### B. Metrics Readiness And Diagnostic Cost

- Trace all seven periodic `/metrics` ReadTimeout rows using request start/end,
  event-loop lag, response serialization time, metric-family size, label
  cardinality, tracemalloc snapshot ownership and allocator/object inventory
  timing.
- Determine whether optional memory/lifecycle diagnostics block or inflate the
  metrics scrape path. If so, preserve equivalent evidence while moving
  expensive collection off the request critical path or serving a bounded
  immutable snapshot. Do not disable required evidence or hide failed samples.
- Keep metric labels free of tenant IDs, subjects, cursors, Tokens and PII.
  Prove cardinality bounds and thread/task ownership across success,
  cancellation, timeout and coordinated shutdown.
- Keep the monitor interval, timeout, completeness aggregation and workload
  unchanged.

Disproof: monitor complete sample rate must be `>=0.95` in every executed
stage, with no periodic metrics timeout pattern and no missing API FD,
PostgreSQL or platform metric evidence.

### C. Outbox, Lifecycle And Memory Preservation

- Preserve `FOR UPDATE SKIP LOCKED`, claim tokens, leases, retries, partition
  order, idempotent durable acceptance, published cursor and atomic Outbox
  semantics.
- Valid finalized events must end `PUBLISHED`; invalid and cross-tenant events
  must fail closed. Cancellation and timeout must release or renew claims
  without long-lived open rows.
- Preserve ContextVar restoration, transaction rollback, session/pool return,
  FD cleanup, queue/replay eviction and zero async-generator close races.
- The partial smoke Outbox p95/p99 sample was
  `6714.479/9373.942ms`; use segment evidence to diagnose it, but do not
  represent it as a completed 2,000-stream aggregate.
- Re-evaluate RSS only in a new complete run with the unchanged fixed recovery
  observation. Do not use forced GC, restart, recovery-only trimming, changed
  baseline or changed aggregation.

### D. Tests And Quality Gates

Add deterministic unit, concurrency and real PostgreSQL regressions for:

- delivery-tail segment correlation and p99 boundary behavior;
- event-loop runnable delay and metrics scrape readiness;
- bounded diagnostic snapshots and metric label cardinality;
- notification bridge readiness and ordered SSE enqueue;
- slow consumers, replay, cancellation, double-close and coordinated shutdown;
- ContextVar restoration, session/pool return, task/frame and FD cleanup;
- Outbox wakeup, claim release/renewal, timeout, retry and partition ordering;
- valid finalized, invalid, duplicate and cross-tenant dispatch;
- signed cursor tamper/cross-tenant rejection and concurrent tenant isolation.

Every defect regression must fail without the fix and pass with it. Performance
tests must use real measured operations and must not claim fabricated
2,000-client scale. Keep Python coverage `>=90%`; do not use exclusions, empty
assertions or forced GC.

Run the complete local suite: Python and real PostgreSQL integration, frontend
unit/build/coverage, Playwright, Go fmt/vet/race/test/build, frozen contract
drift, SBOM/license, dependency audit, Trivy and Gitleaks. Push and
pull-request CI must each pass 8/8. Squash Merge only after green, then require
the new protected-main run to pass 8/8.

## Required PR-2: Fresh Gate C Mainline Replay

Only after PR-1 merges and protected main is clean:

1. Build every image from the new main without `-SkipBuild`.
2. Create a unique Compose project, run directory and fresh PostgreSQL volume.
   Never reuse development, release or historical Gate C volumes.
3. Use real Keycloak-issued Tokens, two tenants and at least ten real subjects
   per tenant. Never fabricate JWTs or send tenant, subject, role or scope
   identity headers.
4. Execute unchanged: 20 smoke, 200 for five minutes, 500 for five minutes,
   1,000 for ten minutes, 2,000 for thirty minutes and the fixed ten-minute
   recovery observation.
5. Do not change thresholds, workload, connections, events, timeouts, grace
   periods, diagnostics aggregation or baseline selection.
6. Bind source/tree, image IDs, Compose and lock hashes, threshold/workload
   hashes, Keycloak issuance, admission/replay/handoff, Outbox segments,
   delivery histogram, monitor completeness, CPU/RSS/USS/PSS/FD/restarts,
   PostgreSQL sessions/pool/RLS/Outbox terminal state, redacted logs and a
   SHA256 manifest.
7. Publish a new immutable external package and preserve every prior package,
   Release, image and PostgreSQL volume.

If every frozen control passes, create an independent success-evidence PR,
mark `PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`, require push,
pull-request and protected-main 8/8, then stop.

If any control fails, stop at the first failed stage, publish a new immutable
failure package, create an independent failure-evidence PR, retain
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, complete the same CI/merge closure and
stop.

## Permanent Constraints And Stop Rule

- Do not modify migrations 0001-0010, frozen contracts, RLS, TenantContext,
  identity authority, SERIALIZABLE transactions, Outbox atomicity, C12,
  thresholds or workload.
- Do not lower load, events or thresholds; increase timeouts; add grace periods;
  change metric aggregation; fabricate JWTs; force GC; or add workers solely to
  hide a single-process defect.
- Preserve zero loss, zero final duplicates, zero tenant leakage, zero
  invalid-cursor acceptance, zero Outbox DEAD, ordered durable replay, signed
  tenant-bound cursors and zero async-generator close races.
- Keep failed evidence immutable and use a new run directory, Compose project,
  PostgreSQL volume and package for every formal rerun.
- Do not start Gate D soak, disaster recovery, Provider acceptance, production
  deployment, accessibility/privacy closure or new product work.

After the independent Gate C evidence PR merges and protected-main CI is
verified, stop and report exact PRs, commits, CI URLs, package hashes, metrics,
residual risks and whether Gate D is eligible. Gate D requires separate
explicit authorization even after eligibility.
