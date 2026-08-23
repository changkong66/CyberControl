# CyberControl Phase 7 Gate C P2 RSS Single-Variable Remediation And Rerun

Process Version: `Gate-C-11-v1.0`

Record this process version in every new diagnostic, preflight and formal-run
metadata record. Do not relabel historical runs.

Work only from real protected-main, GitHub Actions, Docker, PostgreSQL,
Keycloak-issued Tokens and immutable evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, tests, CI,
Tokens, images, volumes, metrics, packages or acceptance decisions. Gate D-G
remain locked.

## Evaluated M2 Baseline

- Evaluated protected main/product source/engineering baseline:
  `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Source tree: `f721fca017c247aee93765d5f11fcbc37e12fcfc`
- Eleventh remediation PR:
  [#81](https://github.com/changkong66/CyberControl/pull/81)
- Remediation head: `af10947bf05b40a5759f40973770f3aaef561f89`
- Push/PR/main CI:
  [32644827393](https://github.com/changkong66/CyberControl/actions/runs/32644827393) /
  [32644829425](https://github.com/changkong66/CyberControl/actions/runs/32644829425) /
  [32645162420](https://github.com/changkong66/CyberControl/actions/runs/32645162420), each 8/8
- Formal run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260823T144052Z-5fcb917b6388`
- Preserved PostgreSQL volume:
  `cybercontrol_gate_c_eleventh_5fcb917_20260823`
- Immutable package SHA256:
  `205517caae21e184d079219454e9e66903083839b9af87c6cc1d45b2bc604ab8`
- Immutable Release:
  [375257600](https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-eleventh-remediation-failed-20260823-5fcb917-evidence-v1)
- Threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Formal state:
  `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`

The run reached M2, not M3. All 20/200/500/1000/2000 stages and the fixed
ten-minute recovery completed. Delivery p95/p99 at 2,000 was `758/1077ms`,
monitor completeness was `491/495`, and Outbox p95/p99 was
`1879.698/2898.555ms`. Loss, final duplicates, tenant leakage, invalid cursor
acceptance, HTTP 5xx, pool timeout, Outbox `DEAD`, OOM and restart were zero.
Terminal subscriber, close, queue, replay/cache/task and pool gauges were zero.

The only failed frozen control was API cgroup recovery memory ratio `1.417200`
against `<=1.10`. Cgroup memory first/final/peak was
262,144,000/371,510,477/436,941,619 bytes. Process RSS was
307,265,536/416,342,016/481,173,504 bytes; USS was
295,247,872/405,143,552/468,893,696 bytes; PSS was
298,700,800/409,633,792/472,241,152 bytes. Mapping count was 2,259 first,
4,237 final and 4,684 peak. These observations prove retention, not ownership.

## Phase 0: Close This Failure Archive

Before any P2 branch or behavior change:

1. Require the independent eleventh failure-evidence PR to pass push and
   pull-request Release Quality Gates 8/8, Squash Merge and protected-main 8/8.
2. Fetch `origin/main` and record the exact evidence merge SHA/tree and CI URL.
   Preserve `product_source_sha=5fcb917b...`; the evidence merge changes only
   `engineering_baseline_sha`.
3. Verify the immutable Release asset size/digest and local package hash again.
4. Preserve the formal run, volume, images, Release and all historical evidence.
   Do not reset, stash, prune, delete, overwrite or reuse them.
5. Use a new isolated worktree from exact current `origin/main`. Do not use the
   dirty primary workspace as a build context.
6. Revalidate hard environment controls, image provenance, Compose/lock and
   frozen hashes. Hard differences block execution; reference differences are
   documented.

Only after that closure may a separately authorized branch be created:

`codex/phase7-gate-c-eleventh-p2-rss-remediation`

## P2 Scope And ADR

P2 may change only the concrete owner of the proven RSS retention. Before a
behavior change, add an ADR with:

- product and engineering baseline SHA/tree and process version;
- the formal run ID, package SHA/URI and exact evidence paths;
- one measurable ownership hypothesis;
- A/B/A' reproduction method and quantitative disproof metric;
- affected modules/interfaces and semantic-redline impact assessment;
- positive and negative/boundary regression coverage;
- stop conditions and the P2 root-cause round count.

One PR may contain one root cause and the minimum corresponding change. No
unrelated refactoring, formatting, Outbox optimization, P0 rework or feature
change is permitted.

## Ownership Measurement Before Fix

Measure synchronized snapshots at system idle, the frozen first 2,000-stage
sample, the 2,000-stage final minute, forced client disconnect, and throughout
the unchanged ten-minute recovery. Correlate:

- cgroup RSS, process RSS/USS/PSS, anonymous/file RSS and `/proc` maps;
- Python traced current/peak allocations and bounded object-type deltas;
- GC generation counters without calling `gc.collect()`;
- live tasks, completed task exceptions and retained coroutine/frame chains;
- metric family, label and sample cardinality;
- HTTP/DB pools, sessions, transactions and checked-out connections;
- SSE serialization buffers, queues, replay buffers/caches and subscribers;
- client/request/response lifecycle objects and socket buffers;
- allocator arena/mmap statistics available without recovery-only mutation.

Trace suspected objects from creation through cancellation/close/shutdown to
the concrete retaining reference. Distinguish reachable Python memory, native
allocator high-water state, mappings, legitimate bounded pools and abnormal
references. A correlation or object count alone is not a root-cause proof.

Do not use forced GC, process restart, recovery-only `malloc_trim`, a changed
RSS baseline, lower cache limits without ownership evidence, increased timeout
or grace period, reduced load/events, extra workers or changed aggregation.

## Layered Causal Validation

1. Reproduce a deterministic lifecycle defect in unit or real-PostgreSQL
   integration tests whenever possible. Prove A fails, B passes and an
   independent clean A' fails; do not use `git revert` on B as A'.
2. For native allocator or concurrency behavior unavailable at test level, run
   the smallest diagnostic gradient that demonstrates the ownership trend.
   A 2,000-stage diagnostic is allowed only when lower gradients cannot
   discriminate the hypothesis, and it must use a new project/volume and the
   unchanged ten-minute recovery.
3. Diagnostics are not formal attempts and must not create
   `gate-c-summary.json` or update `gate_c_attempts`. Archive cited raw data as
   an immutable package and bind it from the ADR.
4. After two failed P2 root-cause rounds, freeze P2 code changes and return to
   measurement with a new root-cause report. A performance-only near miss
   within 10% may receive one separate same-root-cause micro-adjustment; safety
   failures never receive this allowance.

The defect disproof metric is API cgroup memory `<=1.10` of the unchanged
first 2,000-stage sample after the full recovery. Terminal lifecycle gauges
must remain zero, FDs must return near baseline, and no OOM/restart may occur.

## Required Regression And Gates

Add focused positive and negative/boundary tests for the proven owner plus:

- subscriber close ownership, cancellation, timeout and double-close;
- ContextVar restoration, transaction rollback and session/pool return;
- task/frame/exception release and coordinated shutdown;
- queue, replay, metric-label and FD cardinality bounds;
- signed cursor tamper/cross-tenant rejection and concurrent tenant isolation;
- Outbox wake/claim/lease/retry/partition order, idempotent durable acceptance
  and terminal `PENDING/CLAIMED/DEAD` behavior.

Preserve the complete RLS, tenant isolation, atomic publication, ordering,
idempotency, signed cursor and fail-closed regression set. Keep Python coverage
at least 90% with no exclusions, empty assertions, forced GC or fake scale
claims.

Run Python unit and real PostgreSQL integration, frontend typecheck/build/unit/
coverage, Playwright, Go fmt/vet/race/test/build, contract drift, SBOM/license,
dependency audit, Trivy and Gitleaks. Require push and pull-request 8/8, Squash
Merge, then protected-main 8/8.

## Fresh Formal Replay

Only after the P2 remediation merges and protected main passes 8/8:

1. Build all source images once from exact clean main without `-SkipBuild` and
   verify source/tree/dual-baseline/process-version labels.
2. Run `PreflightSmoke` with a unique project and volume. Destroy its project,
   network and volume after capture; never reuse preflight state.
3. Use the same verified image digests with a different unique formal project,
   run directory and fresh PostgreSQL volume.
4. Use real Keycloak-issued Tokens, two tenants and at least ten subjects per
   tenant. Never send tenant/subject/role/scope identity headers.
5. Execute unchanged: 20 smoke, 200/five minutes, 500/five minutes,
   1,000/ten minutes, 2,000/thirty minutes and ten-minute recovery.
6. Preserve and bind all source, image, config, Token issuance, delivery,
   Outbox, CPU, memory, FD, restart, PostgreSQL, RLS, terminal lifecycle,
   redacted-log and SHA256 evidence.

If every frozen control passes in one run, create an independent immutable
success-evidence PR and mark
`PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`. If any control fails, archive a
new immutable failure package/PR and retain
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. Both paths require push/PR/main 8/8 and
Squash Merge.

## Permanent Redlines And Stop Rule

Do not modify migrations 0001-0010, frozen contracts, RLS, TenantContext,
SERIALIZABLE transactions, C12, thresholds, workload or Outbox atomicity.
Preserve `FOR UPDATE SKIP LOCKED`, claim token, lease, retry, partition order,
idempotency, durable acceptance, published cursor, signed tenant-bound
Last-Event-ID, strict replay order, duplicate suppression and fail-closed
authorization/cursor validation.

After the independent Gate C evidence PR merges and protected-main CI is
verified, stop. Do not start Gate D soak, DR, Provider acceptance, production
deployment, accessibility/privacy closure or new product work. Gate D requires
separate explicit authorization even if it later becomes eligible.
