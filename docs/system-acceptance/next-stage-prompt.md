# CyberControl Phase 7 Gate C Sixth Remediation And Rerun - Next Task

Work only from real protected-main evidence in:
`C:/Users/wch06/Documents/CyberControl`.

Do not fabricate source synchronization, tests, CI, Keycloak Tokens, load
metrics, Docker state, PostgreSQL state, commits, packages or acceptance
decisions. Gate D, Gate E, Gate F and Gate G remain locked.

## Fixed Baseline

- Protected main: `ab44180176e26665692929c6b306c1f184c747ae`
- Main tree: `f985181e9d6f208799b7ab129f1d2d393944d68d`
- Fifth failure archive PR: #59
- Fifth archive head: `1499548ee54fba4a07d87df320697f389221a2fe`
- Fifth archive merge: `ab44180176e26665692929c6b306c1f184c747ae`
- Fifth archive push CI: Run 31531236238, 8/8
- Fifth archive PR CI: Run 31531270251, 8/8
- Post-merge protected-main CI: Run 31531732396, 8/8
- Fifth remediation PR: #58
- Fifth remediation head: `739b46bee615d39231156a2bf7b3d8b66f3eb85d`
- Fifth remediation merge: `76cd099a034a395a89b26496c0d40e0673aaa97d`
- Fifth remediation push CI: Run 31264197240, 8/8
- Fifth remediation PR CI: Run 31264254111, 8/8
- Protected-main CI: Run 31264518015, 8/8
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Threshold file: `tests/load/gate-c-thresholds.v1.json`
- Threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Workload file: `tests/load/gate-c-workload.v1.json`
- Workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Fifth run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260808T154326Z-76cd099a034a`
- Fifth package SHA256:
  `566a65a5ac01d1eb6ec0f06a1bc85529bebcf7f53dc37c382d74dcbfa707630e`

## Mandatory Phase 0: Verify The Closed Fifth Failure Archive

The fifth failure archive is already merged. Before creating the sixth
remediation branch, re-verify the protected-main SHA, archive PR metadata and
all evidence bindings. Do not recreate or amend PR #59.

Before creating any remediation branch:

1. Perform read-only checks of branch, HEAD, tree, status, diff, origin/main,
   protected-main CI and all existing Gate C volumes.
2. Preserve all existing uncommitted evidence files. Do not reset, checkout,
   prune, delete or overwrite historical snapshots, volumes or releases.
3. Validate and commit only the fifth failure package metadata, reports and
   current-state documentation:
   - `acceptance-status.json`
   - `acceptance-report.md`
   - `project-stage-audit.md`
   - `next-stage-prompt.md`
   - `docs/system-acceptance/evidence/phase7-gate-c-fifth-remediation-*`
4. Keep the formal state
   `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. The run passed 20, 200 and 500,
   failed at 1,000, and did not execute 2,000 or recovery.
5. Verify JSON syntax, every file hash, source/tree binding, threshold/workload
   hashes, package URL, package size and JWT/credential scan.
6. Confirm PR #59 is Squash Merged and its push, pull-request and protected-main
   Release Quality Gates are all 8/8.
7. Only after these checks pass may the sixth-remediation branch be created.

## Evidence Boundary That Must Remain True

Fifth rerun observations:

- 20, 200 and 500 streams passed.
- 1,000 streams sustained for 603 seconds, then stopped.
- 2,000 streams and ten-minute recovery were not executed.
- Connection success: 1.0.
- Reconnect/replay success: 1.0.
- Committed event loss: 0.
- Duplicate final render: 0.
- Cross-tenant leakage: 0.
- Outbox DEAD: 0.
- Commit-to-client p95/p99: 1532/4985 ms, required <=1000/3000 ms.
- Outbox lag p95/p99: 5830.700/8434.789 ms, required <=2000/5000 ms.
- API CPU p95/max: 127.604/131.840 one-core units.
- Peak API file descriptors: 1038.
- Fail-fast closing owners: 826; no recovery conclusion is permitted.
- PostgreSQL: migration head 20260720_0010, FORCE RLS 74/74,
  append-only triggers 57, Outbox PUBLISHED 103, DEAD 0, cross-tenant rows 0.

Do not reinterpret any partial pass as Gate C acceptance.

## Required PR-1: Sixth Scoped Remediation

After the archive is merged and main is verified, create exactly:
`codex/phase7-gate-c-sixth-remediation`.

Before behavior changes, add an ADR/design note mapping every change to a
measured failed control and naming a disproof metric.

### A. SSE Fan-Out And Scheduling

- Measure fan-out lock wait, per-subscriber serialization time, queue writes,
  notification bridge delay, publisher dispatch delay and socket write delay.
- Diagnose the near single-core API saturation without simply adding workers,
  forcing GC or changing the workload.
- Preserve ordered global sequence delivery, signed tenant-bound
  `Last-Event-ID`, durable replay, duplicate suppression and fail-closed
  cursor validation.
- Preserve the single idempotent close owner and zero async-generator close
  races.
- Cancel and await disconnect, heartbeat, replay and live-queue tasks before
  subscriber/session/ContextVar cleanup.
- Keep terminal subscriber, queue and replay-cache gauges at zero after an
  actual recovery observation.

### B. Backpressure, File Descriptors And Memory

- Measure slow-consumer queue depth/bytes, pending tasks, socket writes,
  subscriber lifetime, file descriptors and RSS/object retention.
- Fix the evidenced owner or scheduling problem. A lower threshold, client grace
  period, forced GC or changed metric aggregation is prohibited.
- Prove connection-pool return, session rollback, ContextVar restoration and
  queue/cache eviction on success, cancellation, timeout and shutdown.
- Do not claim memory recovery until the unchanged ten-minute observation runs.

### C. Outbox And Notification Pipeline

- Measure created -> claimable -> claimed -> dispatch -> authorized acceptance
  -> SSE enqueue -> client separately.
- Preserve `FOR UPDATE SKIP LOCKED`, lease tokens, retries, partition ordering,
  idempotent consumer behavior, published cursor and atomic Outbox semantics.
- Keep valid finalized workflow events PUBLISHED and invalid or cross-tenant
  events fail-closed.
- Verify publisher timeout/cancellation releases or renews claims and never
  leaves long-lived CLAIMED/PENDING work.
- Keep all TenantContext and service-principal authorization server-derived;
  never add identity headers or broaden user roles.

### D. Tests And Quality Gates

Add unit, deterministic concurrency and real PostgreSQL integration tests for:

- fan-out lock contention and deterministic ordering;
- slow consumers and bounded backpressure;
- cancellation, double-close, shutdown and ContextVar restoration;
- file descriptor and subscriber cleanup;
- notification bridge readiness and publisher wakeup;
- valid finalized event, invalid event and cross-tenant event;
- claim release, retry exhaustion, partition ordering and duplicate dispatch;
- multi-tenant isolation and signed cursor tamper rejection.

Keep Python coverage >=90% and do not use exclusions, empty assertions or fake
scale tests. Run Python/PostgreSQL, frontend, Playwright, Go, contract drift,
SBOM/license, Trivy and Gitleaks gates. Push and PR CI must be 8/8; merge only
with Squash Merge; then require protected-main 8/8.

## Required PR-2: Fresh Gate C Mainline Replay

Only after PR-1 merges and protected main is clean:

1. Build all images from the new main without `-SkipBuild`.
2. Create a unique Compose project, run directory and fresh PostgreSQL volume.
   Never reuse development, release or historical Gate C volumes.
3. Use real Keycloak-issued Tokens, two tenants and at least ten real subjects
   per tenant. Do not fabricate JWTs.
4. Execute unchanged: 20 smoke, 200 for 5 minutes, 500 for 5 minutes,
   1,000 for 10 minutes, 2,000 for 30 minutes, and 10-minute recovery.
5. Do not change thresholds, connections, events, timeouts, grace periods,
   workload or aggregation.
6. Bind source/tree, image IDs, Compose and lock hashes, threshold/workload
   hashes, token/admission/replay metrics, client metrics, CPU/RSS/FD/restarts,
   PostgreSQL sessions/pool/RLS/Outbox terminal state and redacted logs.
7. Publish a new SHA256 manifest and immutable external package. Preserve all
   prior failed packages and volumes.

If every frozen control passes, create and merge an independent success-evidence
PR through push, pull-request and protected-main 8/8, then mark
`PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`.

If any control fails, stop, archive the real new failure evidence in a separate
PR, retain `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, and do not start Gate D.

## Stop Rule

After the independent Gate C evidence PR is merged and protected-main CI is
verified, stop. Do not start Gate D soak, disaster recovery, Provider
acceptance, production deployment, accessibility/privacy closure or new product
features.
