# Phase 7 Gate C Seventh-Remediation Failure Analysis

## Scope

This analysis is bound to protected-main source
`fa5b4bd92e4b56704f70b63416906a10c54e0ee1`, tree
`a9f020fd5cceb7a094439ad4c4089b63d3b473a7`, and the complete fresh-volume
run `gate-c-20260812T120720Z-fa5b4bd92e4b`. It records measured boundaries,
not an unproven root-cause claim.

## Proven Improvements

The seventh remediation moved the failure boundary past every stage-local
control. The run sustained 2,000 authenticated streams for 1,803 seconds and
completed the unchanged ten-minute recovery observation. Connection success,
reconnect/replay success, zero loss, zero duplicate final render, zero tenant
leakage, delivery p95/p99 and Outbox `DEAD=0` all passed.

The 2,000-stage delivery p95/p99 improved to `781/990ms`. Final SSE lifecycle
gauges were zero, API FDs returned from 29 to 30, and there were no asynchronous
generator close races, tracebacks, OOMs, restarts or pool acquisition timeouts.

## Remaining Failure 1: Outbox p95

The database terminal result measured created-to-published Outbox p95/p99 at
`2225.796/3026.102ms`. The frozen limits are `2000/5000ms`; only p95 failed,
by `225.796ms`. This margin is not a waiver.

The final process histogram had 221 lifecycle observations. All events were
claimable immediately. Of those, 203 were claimed within one second and 211
were published within 2.5 seconds. Claim-batch execution itself was generally
small, while created-to-claimed, durable acceptance and published marking each
contributed to the tail. The next remediation must derive per-event correlated
timelines from existing stage timestamps before changing polling, batching or
concurrency.

Disproof metric: under the unchanged workload, created-to-published p95 must be
`<=2000ms` and p99 `<=5000ms`, with `DEAD=0`, no long-lived `CLAIMED/PENDING`,
and unchanged partition order, lease, retry and durable-acceptance semantics.

## Remaining Failure 2: RSS Recovery

API RSS was `276404634` bytes at the first 2,000-stage monitor sample,
`448371098` bytes at peak, and `412614656` bytes after the fixed recovery
window. The resulting ratio was `1.492792`, above the `1.10` limit.

At the terminal sample, subscribers, closing subscriptions, queued events and
bytes, replay buffers, replay caches and replay tasks were all zero. File
descriptors returned to 30. Therefore the evidence does not support blaming a
remaining subscriber/queue/cache object. Candidate owners still requiring
measurement include allocator arenas, histogram label/state storage, Python
container high-water retention, database/HTTP object pools and request/frame
allocation churn. None is yet proven.

Disproof metric: object/allocation snapshots must identify the retained owner,
and the unchanged ten-minute observation must end at or below `1.10` of the
pre-ramp API RSS without forced GC, process restart or metric suppression.

## Constraints For The Next Remediation

Do not change migrations 0001-0010, frozen contracts, thresholds, workload,
RLS, TenantContext, SERIALIZABLE transactions, Outbox atomicity, C12, Keycloak
authority, connection/event counts, timeouts, grace periods or aggregation.
Preserve all controls that passed. Gate D-G remain locked.
