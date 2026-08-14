# Phase 7 Gate C Eighth-Remediation Failure Analysis

## Scope

This analysis is bound to protected-main source
`4f0a7670782c5002a2da6e429c0428d8fef29153`, tree
`d79b15fce52b8a8b9afe4be361cfbcbba4c7ddc9`, and the complete fresh-volume
run `gate-c-20260812T190722Z-4f0a7670782c`. It records measured boundaries,
not an unproven root-cause claim.

## Proven Boundary

The eighth replay passed every stage-local control through 2,000 authenticated
streams and completed the fixed recovery observation. Connection and reconnect
success, event loss, final duplicates, tenant leakage, invalid-cursor
acceptance, HTTP 5xx, unexpected disconnects, pool timeouts, Outbox `DEAD`, OOM
and unplanned restarts all remained at their required values.

Delivery p95/p99 at 2,000 streams was `788/1042ms`. FDs returned to baseline,
all Outbox rows reached `PUBLISHED`, and queues, replay structures, close owners
and replay tasks reached zero. These passing controls must not be weakened.

## Remaining Failure 1: Outbox p95

The database terminal result measured created-to-published Outbox p95/p99 at
`2247.346/3438.55ms`. The frozen limits are `2000/5000ms`; only p95 failed, by
`247.346ms`. This margin is not a waiver.

There were 223 published lifecycle observations and no terminal
`PENDING/CLAIMED/DEAD` row. The aggregate alone does not prove whether the
remaining tail is wake/poll jitter, transaction/session acquisition, claim
scheduling, partition head-of-line blocking, service authorization, durable
acceptance, published marking, notification handoff or event-loop delay. The
next remediation must correlate individual non-PII event timelines around the
p90-p99 boundary before selecting a change.

Disproof metric: under the unchanged workload, created-to-published p95 must be
`<=2000ms` and p99 `<=5000ms`, with `DEAD=0`, no long-lived
`CLAIMED/PENDING`, and unchanged partition order, lease, retry, authorization
and durable-acceptance semantics.

## Remaining Failure 2: Anonymous Memory Retention

Container RSS was `264660582` bytes at the first 2,000-stage monitor sample,
`435054182` bytes at peak and `368679322` bytes after recovery. The ratio was
`1.393027`, above `1.10`. PSS and USS increased by approximately 107 MB, while
anonymous RSS increased from `259416064` to `363573248` bytes. File RSS was
unchanged and map count changed only from 615 to 619. This narrows the owner
toward reachable/native anonymous allocation rather than file-backed mappings,
but does not prove a specific allocator or Python object chain.

Disproof metric: synchronized object/allocation and native-memory evidence must
identify the retaining owner, and the unchanged ten-minute observation must end
at or below `1.10` of the frozen pre-ramp RSS without forced GC, restart,
recovery-only trimming, baseline changes or metric suppression.

## Newly Proven Lifecycle Residual

All final 30 recovery samples reported one live subscriber. Closing owners,
queued events/bytes, replay buffers/caches and replay tasks were zero. This
contradicts the required terminal lifecycle boundary even though the frozen
finalizer did not independently fail it. The retained subscriber may or may not
explain the anonymous-memory delta; ownership must be traced rather than
assumed.

Disproof metric: after every formal disconnect and throughout recovery,
subscriber and live-subscriber gauges must reach and remain zero, while close
ownership, task awaiting, ContextVar restoration, session/pool return and FD
baseline remain correct.

## Audit Exception

Immutable Release ID `369509815` exists with zero assets because it was made
immutable before upload. It cannot be altered or deleted. The valid package is
on immutable Release ID `369510663`, asset ID `512034056`, with verified size
and SHA256. Both records are preserved.

## Constraints For The Next Remediation

Do not change migrations 0001-0010, frozen contracts, thresholds, workload,
RLS, TenantContext, SERIALIZABLE transactions, Outbox atomicity, C12, Keycloak
authority, connection/event counts, timeouts, grace periods or aggregation.
Preserve every passing safety, delivery, ordering and isolation control. Gate
D-G remain locked.
