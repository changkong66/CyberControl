# ADR 0025: Phase 7 Gate C Eleventh P2 Measurement Redesign

Process Version: `Gate-C-11-v1.0`

- Status: Rejected after A/measurement/A' diagnostic execution
- Product source: `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Product tree: `f721fca017c247aee93765d5f11fcbc37e12fcfc`
- Engineering parent: `3e4410667dcc20a8c413d1188c38dfe2edf5f11b`
- Engineering tree: `755ebda910a21d823de77ae77d699cb6ca4a600f`
- Parent protected-main CI:
  [Run 32661964184](https://github.com/changkong66/CyberControl/actions/runs/32661964184),
  8/8
- Root-cause domain: P2 RSS recovery
- Classification: measurement design only
- Formal Gate C attempt: no
- Acceptance claim: no

## Decision Boundary

P2 product-code changes remain frozen after the two unsuccessful root-cause
rounds recorded by ADR 0024. This ADR defines a lower-interference measurement
design. It does not authorize an allocator, cache, pool, streaming or runtime
behavior candidate. Implementation may begin only after this design is merged
through push, pull-request, Squash Merge and protected-main 8/8.

The formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; Gate D-G remain
locked.

## Evidence And Remaining Unknown

The formal 2,000-stream failure left `109,993,984` bytes of anonymous RSS and a
cgroup recovery ratio of `1.417200`. Round 2 reproduced the same accounting
shape at 200 streams: jemalloc live allocation plus active-minus-allocated
slack explained `96.9025%` of the RSS delta. Subscribers, requests, tasks and
frames returned to terminal baseline, but the absolute top-eight tracemalloc
records could not identify the retaining allocation path.

Round 2 also established two measurement defects:

1. Repeated `gc.get_objects()`, `asyncio.all_tasks()`, task-stack enumeration
   and tracemalloc snapshots held the GIL long enough to distort event-loop and
   workload latency.
2. `liyans_database_pool_checked_out{pool="api"}` reached `-2` while the real
   PostgreSQL sessions were idle. Increment/decrement event accounting is not
   an admissible pool ownership signal until it is replaced or reconciled with
   the pool's absolute checked-out state.

The pinned Alpine jemalloc reports `config.prof=false` and
`config.stats=true`. Call-stack allocation profiling is therefore unavailable
in the evaluated image. This design must use point-in-time bin and large-extent
statistics; it must not report them as jemalloc call-stack profiles.

## Measurement Hypothesis

A baseline-to-recovery tracemalloc diff grouped by the complete allocation
traceback, combined with synchronized jemalloc bin/large-extent deltas and
bounded cache/pool inventories, can distinguish three falsifiable owners:

- reachable traced Python allocations;
- untraced native live allocation associated with a bounded library/pool
  inventory;
- allocator size-class or page slack without a corresponding live-object
  increase.

The hypothesis is disproved if the profiler materially changes the residual or
latency relative to independent controls, if snapshots cannot be correlated at
the same lifecycle points, or if the combined inventories still cannot map the
residual to one actionable owner.

## A / Measurement / A' Design

All arms use real Keycloak issuance, two tenants, twenty provisioned subjects,
the frozen `ramp-200` stage, a unique Compose project and run directory, and a
fresh PostgreSQL volume. They use the same Docker hard controls, frozen
threshold/workload hashes and host environment fingerprint.

1. **A control:** exact protected-main product image with legacy heavy memory
   sampling disabled. Hold a 300-second idle baseline, run the real 200-stream
   stage, then observe 600 seconds of recovery using only the existing external
   monitor and fixed-cardinality `/proc`/jemalloc metrics.
2. **Measurement arm:** diagnostic-instrumented image with tracemalloc enabled
   from process start, no periodic object/task/snapshot scan, and exactly two
   explicit checkpoints: after the 300-second idle baseline and at the end of
   the 600-second recovery. No checkpoint runs during load.
3. **A' control:** independent no-cache rebuild from the exact protected-main
   parent, not a revert of the measurement arm. Repeat A with fresh resources.

The complete load is not repeated for profiler causality. A 2,000-stream
diagnostic or formal replay is prohibited until this lower gradient identifies
an actionable owner and a separate candidate passes its required regression
and quality gates.

## Checkpoint Contract

The measurement arm exposes no HTTP diagnostic route and accepts no identity
headers. A process-local, opt-in signal trigger is allowed only when an
explicit checkpoint directory is configured at process start. The first and
second approved signals map to the fixed labels `baseline` and `recovery`;
duplicate or unknown checkpoints fail closed.

Each checkpoint must be written atomically and contain:

- pre-capture RSS, PSS, private/anonymous/file RSS and map count;
- tracemalloc current/peak values and a serialized snapshot;
- jemalloc allocated/active/resident/retained values;
- every active small-bin size, allocation, live-region and slab count;
- every active large-extent size, allocation and live-extent count;
- GC generation counters and bounded object-type counts;
- task-type and frame inventories collected only after the snapshot;
- actual pool size, checked-in, checked-out and overflow values by approved
  pool name;
- SQLAlchemy compiled-cache entries and asyncpg statement-cache entries;
- cursor-encoder entries, SSE queue/replay/subscriber inventories and
  Prometheus label-state cardinality counts;
- checkpoint duration, process/source metadata and SHA256 for every artifact.

The offline comparator must load both snapshots and emit every non-zero
baseline-to-recovery statistic grouped by complete innermost allocation
traceback. Repository summaries may contain bounded top contributors, but the
immutable diagnostic package must retain the complete redacted JSONL diff.
Object values, SQL text, tenant IDs, subjects, cursors, Tokens and credentials
must never be serialized.

## Observation Integrity Preconditions

Before the measurement arm is eligible to run:

1. A deterministic regression must reproduce that event deltas can make the
   checked-out gauge negative while the real pool reports zero.
2. The exposed gauge must be derived from the pool's absolute checked-out
   reader and remain nonnegative through success, cancellation, acquisition
   failure and shutdown.
3. A real PostgreSQL integration regression must prove the metric returns to
   zero and all connections are returned after cancellation and timeout.
4. The checkpoint trigger must prove single ownership, atomic completion,
   duplicate rejection, shutdown waiting and path containment.
5. Unit tests must prove no periodic heavy sampler starts in checkpoint mode
   and no signal handler exists when the mode is disabled.

These are observability-integrity changes, not evidence that a pool owns the
RSS residual.

## Quantitative Disproof Metrics

Let the control value be the median of independent A and A'. The measurement
design is rejected if any of the following is true:

- measurement-arm baseline-to-recovery RSS delta differs from control by more
  than `max(8 MiB, 10% of the control delta)`;
- measurement-arm delivery p95, connection p95 or event-loop lag p95 is more
  than `10%` above control, after excluding the two idle checkpoint windows;
- either checkpoint takes longer than 30 seconds, overlaps load, is incomplete
  or changes terminal lifecycle gauges;
- pool inventory, PostgreSQL sessions and the exported pool gauge disagree at
  either endpoint;
- tracemalloc plus explicit native/cache inventories cannot explain at least
  `90%` of the control-adjusted RSS delta;
- the complete traceback diff does not identify a bounded, testable owner or
  bin/extent growth is not repeatable.

Passing these limits makes the data admissible for a new root-cause report. It
does not unfreeze product-code changes by itself and does not prove the formal
`<=1.10` recovery control.

## Change Impact And Redlines

The maximum implementation scope is diagnostic checkpoint ownership,
point-in-time allocator/cache/pool inventories, an offline comparator, runner
support for a diagnostic recovery window, and focused tests. The implementation
must be disabled by default and must not create a formal summary, write
`gate_c_attempts`, update acceptance state or alter formal finalization.

It must not change migrations 0001-0010, RLS, `TenantContext`, SERIALIZABLE
transactions, C12, frozen contracts, threshold/workload files, timeout or
aggregation semantics, Keycloak authority, Outbox claim/lease/retry/order,
durable acceptance, atomic publication, signed tenant cursors, replay order,
subscriber close ownership or client behavior. Forced GC, allocator purge,
restart recovery, cache-limit changes, extra workers, grace-period changes and
identity headers remain prohibited.

## Evidence Index

- ADR 0024:
  `docs/adr/0024-phase7-gate-c-eleventh-p2-rss-remediation.md`
- Round-2 root-cause report:
  `docs/diagnostics/phase7-gate-c-eleventh-p2/round2-root-cause.md`
- Round-2 comparison:
  `docs/diagnostics/phase7-gate-c-eleventh-p2/round2-comparison.json`
- Immutable round-2 package SHA256:
  `554dc9991f8844fb7193d8fefb8fee292e97f208dbc699c869e94e8320403498`
- Immutable round-2 Release:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-round2-20260824-v1
- P2 evidence closure PR:
  [#84](https://github.com/changkong66/CyberControl/pull/84)
- P2 evidence push/PR/main runs:
  [32661358204](https://github.com/changkong66/CyberControl/actions/runs/32661358204),
  [32661662082](https://github.com/changkong66/CyberControl/actions/runs/32661662082), and
  [32661964184](https://github.com/changkong66/CyberControl/actions/runs/32661964184),
  each 8/8

## Stop Conditions

Any semantic, security, zero-tolerance or environment-hard-redline failure
rejects the measurement branch. If the A/measurement/A' controls show material
profiler interference or fail to identify one bounded owner, archive the real
diagnostic result and keep P2 frozen. Do not start another candidate, formal
Gate C replay or Gate D work.

## Diagnostic Outcome

The design was executed against protected main
`a57d0ce57427804ede3f3c620fda2a93b3a300ff` and tree
`963fcf73113e39a1e5868fae3957f4adfc102a4c`. The first A attempt was
`INFRA_ABORTED` before load because the isolated virtual environment lacked the
locked load extra. After dependency synchronization, independent A2 and A'
controls both passed the real 200-stream stage and fixed 600-second recovery.

The measurement arm is rejected. Its connection p95 was `17,989ms`, compared
with the `673ms` control median, and its delivery p95 was `1,175ms`, compared
with the `45.5ms` control median. Both exceed the permitted `+10%` interference
limit by orders of magnitude. The synchronized pre-capture RSS delta was
`59,334,656` bytes, `28,721,152` bytes above the `30,613,504`-byte control
median; the permitted difference was `8,388,608` bytes. API CPU p95 was
`101.98` one-core units versus a `25.165` control median. The measurement arm
also lost five monitor samples and did not sustain the required 304 seconds.

The checkpoints themselves completed in `5.649232/7.326742` seconds and the
complete traceback diff was generated, but the profiler materially changed
the workload and residual it was intended to explain. Its ownership data is
therefore not admissible for selecting a product behavior change. Terminal SSE
inventories were zero and the functional/security zero-tolerance controls
remained intact in all completed arms.

P2 product-code changes remain frozen. This result does not authorize another
candidate, a formal Gate C replay, Gate C acceptance or Gate D work. The
structured comparison, root-cause report and immutable package reference are
stored under `docs/diagnostics/phase7-gate-c-eleventh-p2/`.

The immutable diagnostic package SHA256 is
`10fb9477558ad203e1163198d8e28a941d16d922b6919d2711fdf6f69e22d92b`:
https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-adr0025-measurement-rejected-20260824-v1
