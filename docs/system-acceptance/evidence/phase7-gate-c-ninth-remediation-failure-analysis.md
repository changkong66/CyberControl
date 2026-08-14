# Phase 7 Gate C Ninth-Remediation Failure Analysis

## Scope

This analysis is bound to protected-main source
`993ed9719dfb363238fe3c2f075f1d7e7e269b40`, tree
`8dcbe0c2c23b618c851acc9e4b5de4dd4f3681c5`, and the complete fresh-volume run
`gate-c-20260814T163148Z-993ed9719dfb`. It records measured boundaries and
does not claim an unproven root cause.

## Proven Boundary

The ninth replay completed smoke-20, ramp-200, ramp-500, ramp-1000,
gate-2000 and the fixed recovery observation. Connection and reconnect success,
zero event loss, zero final duplicate rendering, zero tenant leakage, invalid
cursor rejection, HTTP 5xx, pool timeouts, Outbox `DEAD`, OOM and unplanned
restart controls all passed. Final subscriber, close-owner, queue, replay-cache
and replay-task gauges were zero.

## Remaining Failure 1: Outbox p95 Tail

Created-to-published Outbox p95/p99 was `3102.698/3935.444ms`; the frozen
limits are `2000/5000ms`. The p95 breach is `1102.698ms`; p99 passed. The
terminal state had `PUBLISHED=223` and no `PENDING`, `CLAIMED` or `DEAD` rows.
The aggregate does not identify whether the tail is caused by wake/poll delay,
claim scheduling, transaction or session acquisition, partition scheduling,
authorization, durable acceptance, published marking or event-loop delay.
No causal fix is asserted in this archive.

The next remediation must correlate individual non-PII event timelines from
transaction commit through claimable, claim, dispatch, server-derived
authorization, durable acceptance, published marking, notification and SSE
enqueue. It must preserve `FOR UPDATE SKIP LOCKED`, leases, retries, partition
order, idempotency, durable acceptance and atomic Outbox semantics.

Disproof metric: under the unchanged formal workload, created-to-published p95
must be `<=2000ms` and p99 `<=5000ms`, with `DEAD=0`, no long-lived
`CLAIMED/PENDING`, unchanged partition order and zero tenant leakage.

## Remaining Failure 2: API RSS Recovery

The API container memory was `261095424` bytes at the first gate-2000 sample,
`437256192` at peak and `369727898` after recovery, producing the frozen ratio
`1.416064` against `<=1.10`. Process RSS, PSS, USS and anonymous RSS all
remained elevated after recovery. File RSS stayed constant at `50069504` bytes,
while map count increased from `2097` to `4286`. This is evidence of anonymous
or reachable/native allocation pressure, not proof of a particular owner.

The next remediation must compare synchronized tracemalloc/object inventories,
task/frame references, metric state, pools, serialization buffers, queues,
replay structures and native allocator behavior. `gc.collect()`, process
restart, recovery-only trimming, changed baseline, lower cache limits without
ownership proof and changed aggregation are not fixes.

Disproof metric: the unchanged ten-minute recovery must finish at API RSS
`<=1.10` of the frozen pre-ramp baseline, terminal lifecycle gauges zero, FDs
near baseline and no OOM or restart.

## Constraints

Do not modify migrations `0001-0010`, frozen contracts, thresholds, workload,
RLS, TenantContext, SERIALIZABLE transactions, Outbox atomicity, C12 or
identity authority. Preserve every passing reliability, ordering, replay and
tenant-isolation control. Gate D-G remain locked.
