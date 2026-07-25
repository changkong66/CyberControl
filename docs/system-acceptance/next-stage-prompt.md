# CyberControl Phase 7 Gate C Fourth Remediation And Rerun - Next Task

You are the enterprise reliability engineer for CyberControl. Work only from
protected-main evidence. Do not reinterpret any failed Gate C threshold as
accepted and do not start Gate D.

## Fixed Baseline

- Workspace: `C:/Users/wch06/Documents/CyberControl`
- Before creating a branch, fetch `origin/main` and require its tip to be a
  descendant of `01595ae2634cb8114dfb9c591114048cba3864fd`, to contain the
  third-remediation failure evidence package metadata, and to have a successful
  8/8 protected-main Release Quality Gates run. Branch only from that exact
  current main tip.
- Evaluated third-remediation source:
  `01595ae2634cb8114dfb9c591114048cba3864fd`
- Evaluated source tree:
  `e319baaec6f1ba40e4d4069b6e0f78bf37b27bb0`
- Third-remediation protected-main CI:
  [Run 30171222537](https://github.com/changkong66/CyberControl/actions/runs/30171222537),
  8/8 successful
- Current state: `RELEASE_CANDIDATE`
- Formal state: `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Latest failed run:
  `D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260725T192105Z-01595ae2634c`
- Latest failure analysis:
  `docs/system-acceptance/evidence/phase7-gate-c-third-remediation-failure-analysis.md`
- Gate D-G: locked

## Evidence-Backed Failure Boundary

The 20, 200, 500 and 1,000 connection stages passed. The fresh-volume
2,000-connection stage held 2,000 active authenticated streams for 1,804
seconds, then failed these unchanged controls:

- Connection success: `4000 / 4040 = 0.9900990099`, required `>= 0.995`.
- Reconnect/durable replay success: `2000 / 2040 = 0.9803921569`, required
  `>= 0.999`.
- Committed event loss: `1,350`, required `0`.
- Commit-to-client p95/p99: `1830 / 3267 ms`, required `<= 1000 / <= 3000 ms`.
- Outbox p95/p99: `12149.778 / 14295.416 ms`, required `<= 2000 / <= 5000 ms`.
- Post-ramp API memory ratio: `1.388368`, required `<= 1.10`.

The evidence narrows, but does not by itself prove, the next root-cause work:

1. All 100 duplicate-replay clients were behind the final ordinal. Fifty
   `gate-c-alpha` clients finished at ordinal 982 and fifty `gate-c-beta`
   clients at ordinal 981, while both publishers reached ordinal 995. This
   exactly explains the 1,350 loss. Their duplicate suppression remained
   correct, so do not trade duplicate safety for tail completion.
2. The 40 failed stream attempts are in the reconnect population. Initial token
   acquisition had zero failures; use per-reason admission and replay timing to
   distinguish request admission, cursor verification, replay acquisition,
   notification synchronization and client disconnect outcomes.
3. The end of the fixed ten-minute recovery observation still had 17
   subscribers, 82 queued events, and 1,085 replay-cache events / 629,343
   bytes. API RSS moved from 279,445,504 to 387,973,120 bytes. Establish the
   retaining owner before changing cleanup or cache policy.
4. The third remediation eliminated all
   `aclose(): asynchronous generator is already running` errors, with final
   `closing_subscriptions=0` and `replay_tasks=0`. Preserve that result.
5. The post-failure PostgreSQL terminal snapshot reports 74/74 FORCE RLS tables,
   zero cross-tenant visibility, zero Outbox `DEAD`, zero pool acquisition
   timeouts, zero OOM/restarts and no HTTP 5xx. Preserve every one of these
   controls.

## Non-Negotiable Constraints

1. Do not modify migrations `0001-0010`, frozen contracts, RLS, identity
   authority, TenantContext, SERIALIZABLE semantics, Outbox atomicity, C12
   publication semantics, Gate C thresholds or Gate C workload.
2. Do not send `X-Tenant-ID`, `X-Subject-Ref`, role or scope identity headers.
3. Use real Keycloak-issued Tokens, real PostgreSQL and a fresh isolated Gate C
   volume for every formal rerun.
4. Do not hide the defect by increasing client timeouts, lowering load, reducing
   events, forcing GC, weakening ordered delivery, excluding coverage or
   changing metric aggregation.
5. Keep every failed package immutable. Every rerun needs a new run directory,
   evidence manifest, PostgreSQL volume and Compose project.
6. Gate D-G remain locked regardless of unit tests, local quality gates, CI or
   partial-stage success.

## Required PR-1: Fourth Scoped Remediation

Create `codex/phase7-gate-c-fourth-remediation` from the verified current main.
Before behavioral changes, add a compact ADR or design note that maps every
proposed change to a measured failed control and names the disproof metric.

### A. Duplicate-Replay Durable Tail Completion

- Trace the duplicate-replay population from signed `Last-Event-ID` validation,
  through `REPLAYING -> LIVE`, to the final publisher ordinal. Do not expose
  tenant identifiers, cursors or Tokens in logs or metrics.
- Record per-reason counters and bounded histograms for cursor validation,
  admission queueing, replay query/cache acquisition, replay merge completion,
  LIVE handoff, gap detection, reconnect cancellation and terminal tail catchup.
- Correct the replay/live handoff so a reconnect cannot report success before
  its ordered durable cursor has caught up to all events committed before the
  frozen workload's terminal observation boundary.
- Retain signed cursor tenant binding, ordered sequences, fail-closed gaps,
  per-tenant ordering and zero final duplicate rendering.
- Prove that the 100 duplicate-replay clients finish at the same final ordinal
  as their tenant publisher without adding a client-only grace period or hiding
  missing events.

### B. Admission And Cancellation Ownership

- Profile the 40 failed reconnect attempts separately from real Keycloak Token
  acquisition. Bound admission/replay concurrency only where evidence shows a
  queue or database fanout bottleneck.
- Preserve a single explicit idempotent close owner. Cancel and await request
  disconnect, heartbeat, replay and live-queue tasks before subscriber removal,
  ContextVar restoration and session/connection return.
- Ensure a subscriber cannot be counted closed while a retained replay cache,
  queue item or in-flight task still owns it.
- Add lifecycle gauges for live subscribers, closing owners, pending tasks,
  queued bytes/events, replay-cache tenants/events/bytes and admission wait
  reasons. Do not attach PII, cursor values or tenant IDs to labels.

### C. Outbox And Delivery Latency

- Measure `created -> claimed`, `claimed -> published` and
  `published -> client` independently under the frozen workload. Retain
  `FOR UPDATE SKIP LOCKED`, leases, retries, partition ordering and atomic
  publication.
- Identify whether the failing p95/p99 is claim polling/wakeup delay, partition
  head-of-line blocking, dispatcher scheduling, notification fanout or replay
  catchup. Use the evidence to select a fix; do not acknowledge publication
  early or skip a consumer confirmation.
- Verify publisher timeout/cancellation promptly releases or renews claims and
  cannot leave long-lived `CLAIMED` or `PENDING` work.

### D. Memory Recovery

- Capture tracemalloc snapshots, object counts, bounded task/subscriber/cache
  inventories and API RSS samples before ramp, at 2,000 streams, after forced
  disconnect and after the fixed recovery observation.
- Fix the actual retaining references for 17 residual subscribers, 82 queued
  events and replay cache state. `gc.collect()` and a lower cache limit without
  ownership proof are not acceptable remedies.
- Keep the asynchronous-generator close fix and add a regression that asserts
  no `aclose()` race warning under concurrent replay/live cancellation.

### E. Tests And Quality Gates

- Add unit, deterministic concurrency and real PostgreSQL tests for duplicate
  replay terminal tails, concurrent reconnect admission, ordered gap-free
  handoff, cursor tamper/cross-tenant rejection, cancellation/double-close,
  ContextVar restoration, pool return, queue/cache eviction, Outbox claim
  release, partition ordering and multi-tenant isolation.
- Include a regression where terminal events are committed during duplicate
  replay and prove every reconnecting subscriber reaches the terminal ordinal
  exactly once.
- Keep Python coverage `>= 90%`; target no lower than the current 92.14%
  evidence. No empty assertions, coverage exclusions or fabricated scale tests.
- Run full local quality gates: Python and real PostgreSQL integration,
  frontend, Playwright, Go, contract drift, SBOM/license, Trivy and Gitleaks.
- Push, create a PR, require push and pull-request Release Quality Gates 8/8,
  Squash Merge only after green, then require protected-main 8/8.

## Required PR-2: Fresh Gate C Rerun Evidence

Only after PR-1 merges and main is clean:

1. Build from new main without `-SkipBuild`.
2. Create a new explicitly named PostgreSQL volume and Compose project. Do not
   reuse any prior Gate C, release or development volume.
3. Run the unchanged 20, 200, 500, 1,000 and 2,000 authenticated connection
   stages plus the ten-minute recovery observation with two tenants and at
   least ten real Keycloak subjects per tenant.
4. Bind source commit/tree, image IDs, Compose and lock-file hashes, frozen
   threshold/workload hashes, monitor series, PostgreSQL terminal evidence and
   SHA256 manifest to the result. Redact all Tokens, credentials and PII.
5. If every frozen control passes, archive independent success evidence in a PR,
   mark `PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`, then stop. Gate D is
   only eligible for a separately authorized task after that evidence PR merges
   through 8/8 CI.
6. If any frozen control fails, archive the real failed evidence in an
   independent PR, retain `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, and stop.

Do not start Gate D soak, disaster recovery, Provider, production deployment or
new product features until an independent Gate C success-evidence PR has merged
through 8/8 CI.
