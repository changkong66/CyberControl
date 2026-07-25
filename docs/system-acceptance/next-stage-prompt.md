# CyberControl Phase 7 Gate C Third Remediation And Rerun - Next Task

You are the enterprise reliability engineer for CyberControl. Work only from
protected-main evidence. Do not reinterpret any failed Gate C threshold as
accepted and do not start Gate D.

## Fixed Baseline

- Workspace: `C:/Users/wch06/Documents/CyberControl`
- Current protected main: `7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8`
- Current protected-main CI:
  [Run 30158839398](https://github.com/changkong66/CyberControl/actions/runs/30158839398),
  8/8 successful
- Current state: `RELEASE_CANDIDATE`
- Formal state: `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Latest failed run:
  `D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260725T134112Z-7ff03ce0c4af`
- Latest failure analysis:
  `docs/system-acceptance/evidence/phase7-gate-c-second-remediation-failure-analysis.md`
- Gate D-G: locked

## Evidence-Backed Problem Statement

The 20, 200, 500 and 1,000 connection stages passed. The fresh-volume
2,000-connection stage held 2,000 active authenticated streams for 1,805
seconds but failed these frozen controls:

- Connection success: `0.9840098401`, required `>= 0.995`
- Reconnect/durable replay success: `0.9685230024`, required `>= 0.999`
- Committed event loss: `1,700`, required `0`
- Outbox lag p95/p99: `10277.417/11538.743 ms`, required `<= 2000/5000 ms`
- Post-ramp API memory ratio: `1.480965`, required `<= 1.10`
- Coordinated shutdown log errors:
  `14 x aclose(): asynchronous generator is already running`

The run retained zero cross-tenant leakage, zero duplicate final renders, zero
HTTP 5xx, zero Outbox `DEAD`, zero pool-acquisition timeouts and zero OOM or
unplanned restarts. Do not weaken or remove those controls while remediating the
remaining failure.

## Non-Negotiable Constraints

1. Do not modify migrations `0001-0010`, frozen contracts, RLS, identity
   authority, TenantContext, SERIALIZABLE semantics, Outbox atomicity, C12
   publication semantics, Gate C thresholds or Gate C workload.
2. Do not send `X-Tenant-ID`, `X-Subject-Ref`, role or scope identity headers.
3. Use real Keycloak-issued Tokens, real PostgreSQL and a fresh isolated Gate C
   volume for every formal rerun.
4. Do not hide the defect by increasing client timeouts, lowering load, reducing
   events, forcing GC, excluding coverage or changing metric aggregation.
5. Keep all failed evidence immutable. Every rerun requires new evidence.
6. Gate D-G remain locked regardless of local test, CI or partial-stage success.

## Required PR-1: Third Scoped Remediation

Create `codex/phase7-gate-c-third-remediation` from the exact current main.
Before changing behavior, record a compact root-cause measurement plan in an ADR
or design note that maps each modification to the observed Gate C metric.

### A. Subscription Close Ownership And Cancellation

- Establish one explicit idempotent subscription-close owner.
- Ensure no code path invokes `aclose()` while another task is advancing the
  same async generator.
- Cancel and await live queue, replay, heartbeat and request-disconnect tasks
  before subscriber removal and ContextVar/session cleanup.
- Prove cleanup after replay yield, live wait, forced disconnect, token expiry,
  coordinated shutdown and double-close.
- Instrument subscriber count, pending close tasks, queue depth, replay cache
  bytes, and open session/connection ownership without exposing tenant data.

### B. Connection Admission, Replay And Durable Continuity

- Separate token-acquisition latency from SSE admission and replay latency.
- Diagnose the p95/p99 admission collapse at 2,000 connections; retain real
  Keycloak tokens and do not replace them with fabricated JWTs.
- Preserve the two-phase `REPLAYING -> LIVE` handoff, signed Last-Event-ID,
  ordered sequence merge, duplicate suppression and fail-closed tenant checks.
- Bound concurrent replay/database work using evidence-backed single-flight or
  batching only if it preserves per-tenant ordering, zero loss and zero final
  duplicate rendering.
- Add per-reason counters for admission rejection, replay completion, reconnect
  timeout, gap detection and subscriber cleanup.

### C. Outbox Latency And Memory Recovery

- Measure `created -> claimed`, `claimed -> published` and
  `published -> client` separately under the unchanged workload.
- Retain `FOR UPDATE SKIP LOCKED`, leases, retries, partition ordering and
  atomic publication semantics. Do not acknowledge publication early.
- Identify retained reference chains with tracemalloc/object counts and RSS
  samples. Fix ownership or allocation pressure; `gc.collect()` is not a fix.
- Preserve all tenant isolation and release semantics while improving throughput.

### D. Tests And Quality Gates

- Add unit and real PostgreSQL tests for concurrent close races, cancellation,
  ContextVar restoration, pool return, 2,000-scale admission coordination,
  replay gaps, duplicate/ordered delivery, timeout recovery, Outbox claim
  release and multi-tenant isolation.
- Python coverage must remain `>= 90%`; target not below the current 91.74%
  evidence. No empty assertions or coverage exclusions.
- Run full local quality gates: Python, real PostgreSQL integration, frontend,
  Playwright, Go, contract drift, SBOM/license, Trivy and Gitleaks.
- Push, create a PR, require push and pull-request Release Quality Gates 8/8,
  Squash Merge only after green, then require protected-main 8/8.

## Required PR-2: Fresh Gate C Rerun Evidence

Only after PR-1 merges and main is clean:

1. Build from new main without `-SkipBuild`.
2. Create a new explicitly named PostgreSQL volume and Compose project; do not
   reuse any prior Gate C, release or development volume.
3. Execute the unchanged 20, 200, 500, 1,000 and 2,000 authenticated connection
   stages plus the 10-minute recovery observation using two tenants and at least
   ten real Keycloak subjects per tenant.
4. Bind source commit/tree, image IDs, Compose hash, threshold/workload hashes,
   monitor data, PostgreSQL evidence and SHA256 package manifest to the result.
5. If every frozen control passes, archive accepted evidence in an independent
   PR and mark `PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`.
6. If any frozen control fails, archive real failed evidence, retain
   `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, and stop.

## Stop Rule

Do not start Gate D soak, disaster recovery, Provider, production deployment or
new product features until the independent Gate C success-evidence PR is merged
through 8/8 CI.
