# ADR 0024: Phase 7 Gate C Eleventh P2 RSS Remediation

Process Version: `Gate-C-11-v1.0`

- Status: Root-cause round 1 rejected; round 2 measurement in progress
- Product source: `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Product tree: `f721fca017c247aee93765d5f11fcbc37e12fcfc`
- Engineering baseline: `d5494dd1dce671c30ebfe40e046319d7572a52f5`
- Engineering tree: `cd328fdb84812e46178ebf204f934a371812f034`
- Failure archive: PR [#82](https://github.com/changkong66/CyberControl/pull/82),
  push/PR/main Runs
  [32652339505](https://github.com/changkong66/CyberControl/actions/runs/32652339505),
  [32652673118](https://github.com/changkong66/CyberControl/actions/runs/32652673118), and
  [32652984515](https://github.com/changkong66/CyberControl/actions/runs/32652984515),
  each 8/8

## Problem Boundary

The formal run `gate-c-20260823T144052Z-5fcb917b6388` completed all frozen
20/200/500/1,000/2,000 stages and the ten-minute recovery. Outbox p95/p99,
delivery, monitor completeness, security, durability, isolation and terminal
lifecycle controls passed. The only failed frozen control was API cgroup memory
recovery ratio `1.417200 > 1.10`.

The first/final/peak cgroup samples were
`262144000/371510477/436941619` bytes. Process RSS was
`307265536/416342016/481173504` bytes, USS was
`295247872/405143552/468893696` bytes and PSS was
`298700800/409633792/472241152` bytes. File-backed RSS decreased by `917504`
bytes while anonymous RSS increased by `109993984` bytes. This localizes the
failed control to private anonymous process memory.

At the same first/final samples, jemalloc allocated/active/resident bytes were
`208856952/248397824/258908160` and
`248922368/355414016/367968256`. Live allocated bytes therefore increased by
`40065416`, while the active-minus-allocated gap increased from `39540872` to
`106491648` bytes, a `66950776`-byte fragmentation delta. Process map count
increased from `2259` to `4237`. Retained bytes remained zero and jemalloc used
one arena.

No `liyans_memory_diagnostics_*` sample or `Memory diagnostics snapshot` log
exists in the formal run. The opt-in tracemalloc/object sampler was not active,
so it is disproved as the owner of this run. At recovery end, subscribers,
close owners, queues, replay buffers/caches/tasks and checked-out database
connections were zero; FDs were `30` versus `29` initially. Those observations
disprove those terminal lifecycle inventories as the complete owner, but they
do not yet identify the remaining `40065416` live allocated bytes.

## Single Root-Cause Hypothesis

The runtime currently sets `PYTHONMALLOC=malloc`, routing CPython small-object
domains through the preloaded jemalloc arena. The real 2,000-stream lifecycle
mixes long-lived process state with high-volume short-lived request, task,
serialization and SSE objects. The hypothesis is that this cross-lifetime size
class sharing prevents jemalloc pages from becoming wholly purgeable after
disconnect. It explains the measured `66950776`-byte growth in
active-minus-allocated memory and the mapping growth after all application
lifecycle gauges returned to zero.

The proposed candidate is not yet a decision. It will restore CPython's
process-start `pymalloc` ownership for small Python objects while retaining the
pinned jemalloc preload and existing one-arena, bounded-decay configuration for
raw and general native allocations. No recovery-time allocator action is
permitted.

## Layered A/B/A' Validation

1. **A:** use a clean independent worktree and image from parent engineering
   baseline `d5494dd1...` with the current process-start allocator settings.
2. **B:** use the candidate image with only the allocator-domain ownership
   change. Use the same source, real Keycloak issuance, workload operation,
   Docker hard controls and frozen 200-client stage; each run receives a unique
   Compose project, run directory, network and fresh PostgreSQL volume.
3. **A':** rebuild an independent clean parent image from `d5494dd1...`; do not
   derive it by reverting B. Repeat the same diagnostic.
4. Record synchronized cgroup RSS, RSS/USS/PSS, anonymous/file RSS, map count,
   jemalloc allocated/active/resident/retained/arena values, tasks, FDs,
   subscribers, queues, replay state and pools before load, at stage peak,
   after disconnect and through a ten-minute observation.
5. The 200-client diagnostic may establish direction and causality but cannot
   claim Gate C scale or acceptance. Escalation to a 2,000-client diagnostic is
   allowed only if the lower gradient cannot discriminate the hypothesis.

The hypothesis is disproved if B does not materially reduce both the recovery
RSS ratio and the active-minus-allocated delta relative to independent A and
A', if the allocator domain cannot be verified from process start, or if the
change merely transfers retained memory outside the jemalloc counters.

The formal defect disproof remains unchanged: after an unchanged full mainline
run and fixed ten-minute recovery, API cgroup memory must be `<=1.10` of the
first 2,000-stage sample, terminal lifecycle gauges must be zero, FDs must be
near baseline, and no OOM or restart may occur.

## Change Impact And Semantic Redlines

The maximum candidate write scope is the API runtime image's process-start
allocator declaration plus focused allocator/lifecycle tests and diagnostic
evidence. It does not alter Python application APIs, persistence, streaming or
identity code.

The change must not touch migrations 0001-0010, RLS, `TenantContext`,
SERIALIZABLE transactions, C12, frozen contracts, thresholds, workload,
timeouts, aggregation or Outbox atomicity. It must preserve `FOR UPDATE SKIP
LOCKED`, claim tokens, leases, retries, partition order, idempotent durable
acceptance, published cursors, signed tenant-bound `Last-Event-ID`, strict
replay order, duplicate suppression and fail-closed authorization/cursor
validation. Forced GC, restart recovery, recovery-only trim, grace-period
increase, lower load, extra workers and identity headers are prohibited.

Positive regression must prove the selected allocator domain applies from
process start and releases the deterministic cross-lifetime allocation cohort.
Negative/boundary regression must prove no recovery-only mutation exists and
that task/frame, subscriber, queue/replay, ContextVar, session/pool and FD
lifecycle controls remain bounded. Every existing tenant-isolation, RLS,
ordering, idempotency, atomic publication and signed-cursor test remains
mandatory.

## Evidence Index

- Formal run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260823T144052Z-5fcb917b6388`
- Formal stage timeline:
  `stages/gate-2000/monitor.jsonl`
- Formal summary:
  `docs/system-acceptance/evidence/phase7-gate-c-eleventh-remediation-summary.json`
- Failure analysis:
  `docs/system-acceptance/evidence/phase7-gate-c-eleventh-remediation-failure-analysis.md`
- Package reference:
  `docs/system-acceptance/evidence/phase7-gate-c-eleventh-remediation-package.json`
- Immutable package SHA256:
  `205517caae21e184d079219454e9e66903083839b9af87c6cc1d45b2bc604ab8`
- Immutable Release:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-eleventh-remediation-failed-20260823-5fcb917-evidence-v1
- Initial P2 analysis:
  `docs/diagnostics/phase7-gate-c-eleventh-p2/initial-analysis.json`

Diagnostic package references and final A/B/A' results must be appended here
before a behavior commit is eligible for review.

### Root-Cause Round 1 Result

The A/B/A' comparison rejected the proposed allocator-domain change. A and A'
were independent parent images; A' was rebuilt with `--no-cache`. B removed
only `PYTHONMALLOC=malloc`. All three real 200-stream stages passed, but B's
cgroup recovery ratio was `1.213483` versus `1.195388/1.185319` in A/A', and
its RSS ratio was only marginally lower at `1.126844` versus
`1.143331/1.137403`. B reduced jemalloc active-minus-allocated growth to
`1,287,688` bytes from `9,214,816/7,641,872`, while anonymous RSS still grew
`28,217,344` bytes. This proves allocation accounting moved outside jemalloc
without materially solving total retention. B also exposed API pool gauge `-1`
throughout recovery. The candidate was reverted and was not escalated to a
2,000-stream diagnostic.

- Comparison: `docs/diagnostics/phase7-gate-c-eleventh-p2/round1-comparison.json`
- Root-cause record:
  `docs/diagnostics/phase7-gate-c-eleventh-p2/round1-root-cause.md`
- Package reference:
  `docs/diagnostics/phase7-gate-c-eleventh-p2/round1-package-reference.json`
- Immutable package SHA256:
  `24f9affca5033099bdcd8bae3622dc2ea00fef8c3bf844df6701fa1f930e2d2a`
- Immutable Release:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-aba-round1-20260824-v1

Round 2 retains the parent allocator and enables the existing opt-in bounded
diagnostic sampler from process start. It must identify whether live allocated
bytes remain reachable from Python objects/tasks/frames or are native
high-water state before another behavior candidate is permitted.

## Stop Conditions

Any semantic, security, functional or zero-tolerance regression rejects the
candidate immediately. If A/B/A' does not establish allocator ownership, no
allocator change may be committed as a fix; return to synchronized ownership
measurement. After two failed P2 root-cause rounds, freeze P2 code changes and
produce a new complete root-cause report.

This ADR does not accept Gate C. Formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; Gate D-G remain
locked.
