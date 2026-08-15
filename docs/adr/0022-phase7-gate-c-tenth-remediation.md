# ADR-0022: Phase 7 Gate C Tenth Remediation Measurements

**Status:** Proposed

## Context

The ninth protected-main Gate C replay completed every frozen workload stage
and the ten-minute recovery observation, but the aggregate controls still
failed:

- created-to-published Outbox p95 was `3102.698 ms` against `<=2000 ms`;
- post-ramp API RSS ratio was `1.416064` against `<=1.10`.

The evidence proves the failures, but does not identify their owners. This
remediation therefore starts with bounded, non-PII lifecycle measurements and
must not change the frozen workload, thresholds, aggregation, or durable
delivery semantics.

## Measurements And Falsifiable Hypotheses

| Failure control | Candidate mechanism | Required measurement | Disproof metric |
| --- | --- | --- | --- |
| Outbox p95 | wake/poll delay or claim scheduling | Correlate one internal event key through `created`, `claimable`, `claimed`, dispatch start/end, service-principal authorization, durable acceptance, `PUBLISHED`, notification and SSE enqueue. Record bounded histograms for each segment and the exact p95 cohort. | Under the unchanged formal workload, created-to-published p95 `<=2000 ms`, p99 `<=5000 ms`, `DEAD=0`, terminal `PENDING/CLAIMED=0`, and partition order unchanged. |
| Outbox p95 | transaction/session acquisition, partition head-of-line blocking, or event-loop delay | Add queue/claim batch size, claim transaction duration, per-partition wait, dispatch duration, mark-published duration, wake-to-claim delay and event-loop scheduling observations without tenant or cursor labels. | No segment or wait reason may remain unbounded at the p95 cohort; claim release/renewal tests leave no long-lived claims after cancellation or timeout. |
| RSS ratio | reachable Python objects, task/frame exceptions, metric state, pools, queues, replay buffers or serialization payloads | Capture synchronized bounded inventories at baseline, 2,000 streams, forced disconnect and recovery: tracemalloc current/peak, object type counts, live task names and frames, subscriber/queue/replay ownership, metric state cardinality, pool checkout state, RSS/USS/PSS/anonymous/file RSS and allocator statistics. | Recovery RSS `<=1.10` of the frozen pre-ramp baseline, lifecycle gauges zero, FD count near baseline, and no OOM/restart. The owning inventory must actually shrink after disconnect. |
| RSS ratio | native allocator arena high-water state | Compare Python-traced bytes with process anonymous RSS and allocator statistics from process start. Any allocator configuration change must be justified by the comparison and verified from startup. | A production change is rejected unless native allocation is the measured owner and the unchanged recovery control passes without restart or recovery-only trimming. |

## Constraints

This ADR preserves `FOR UPDATE SKIP LOCKED`, claim leases, retries,
partition ordering, idempotent durable acceptance, the Outbox atomic state
transition, signed tenant-bound SSE cursors, strict sequence ordering,
TenantContext, RLS, SERIALIZABLE transactions and C12 semantics. No client
identity headers, broader service roles, forced GC, process restart, timeout
increase, grace period, lower load or changed metric aggregation is allowed.

All measurements have fixed-cardinality labels and use internal correlation
identifiers only in bounded evidence files. Tenant IDs, cursor values, Tokens,
credentials and PII are excluded from logs and metric labels.

## Decision

Implement measurement first, then apply only a causal fix supported by the
captured evidence. Each behavior change must include a deterministic unit or
real PostgreSQL regression that fails without the change, passes with it, and
proves claim release, ordering, tenant isolation and lifecycle cleanup.

## Measured Tenth-Remediation Decision

The ninth-run terminal metrics recorded 223 published Outbox messages and
7,224 empty claim polls during the 1,805-second stage. The dispatcher executed
the expired-claim recovery updates on every one of those polls, even when no
claim was expired. This is a measured scheduling and database-work amplifier
that is consistent with the remaining created-to-published tail, but it is not
treated as the sole cause until the new per-batch traces confirm the segment.

The scoped behavior change keeps recovery available on the first claim and
whenever an expired row is detected, while avoiding the two no-op recovery
updates between bounded recovery checkpoints. The checkpoint is at most one
second for the frozen 30-second lease and an indexed existence probe still
detects an expired claim between checkpoints. This changes neither lease
duration, claim ownership, retries, ordering, durable acceptance nor the
atomic PUBLISHED transition. Its disproof is an unchanged-workload Outbox p95
above 2,000 ms, any non-terminal claim, DEAD row, ordering violation or tenant
leakage.

The RSS change is measurement-only at this point. Opt-in diagnostics record
Python allocations, object types, task/frame counts, process RSS/USS/PSS
proxies, anonymous/file RSS, mappings and allocator statistics without tenant
or cursor labels. No allocator or cache policy is changed until a diagnostic
run identifies a reachable owner or native allocation mechanism.

## Existing Allocator Evidence

The ninth-run `gate-2000/monitor.jsonl` already separates file-backed memory
from anonymous/native memory. The first sample recorded process RSS
`307,769,344` bytes, anonymous RSS `257,699,840`, file RSS `50,069,504`,
jemalloc allocated/active/resident `211,110,032/248,905,728/257,269,760`
bytes, and map count `2,097`. The final recovery sample recorded process RSS
`413,544,448`, anonymous RSS `363,474,944`, unchanged file RSS `50,069,504`,
jemalloc allocated/active/resident `249,026,632/351,956,992/362,364,928`
bytes, and map count `4,286`. This correlates the failed ratio with anonymous
allocator active/resident high-water rather than file mappings, but does not
prove that allocator trimming alone is safe or sufficient. The tenth
remediation therefore retains the existing process-start allocator settings,
adds opt-in allocation/object/task evidence, and defers any allocator policy
change until the unchanged formal replay supplies a causal before/after
comparison.

A separate non-formal local diagnostic Smoke after API restart observed
`tracemalloc_current_bytes=11,777,016`, jemalloc allocated/resident about
`166/179MB`, and zero checked-out database connections. It is a readiness
measurement only and is not a Gate C scale or recovery result.

## Quality-gate timing observation

The unchanged Topic 2 and Topic 3 planner performance tests passed locally in
three consecutive runs after this remediation. The first three protected GitHub
runner attempts for this branch measured the pre-existing planner assertions at
`6.2646-6.5499 s` and `5.4224-5.5165 ms`, respectively, while PostgreSQL,
frontend, Go, supply-chain and container gates passed. This is recorded as a
runner-baseline signal only; no test budget, aggregation, workload or acceptance
criterion is changed, and the planner code is outside this remediation diff.
