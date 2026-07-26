# ADR-0016: Phase 7 Gate C Fourth Remediation Measurement Plan

## Status

Accepted before fourth-remediation behavior changes.

## Context

The protected-main Gate C third rerun on source
`01595ae2634cb8114dfb9c591114048cba3864fd` sustained 2,000 authenticated SSE
streams for the required window but failed the frozen controls for connection
success, reconnect replay success, committed-event loss, delivery latency,
Outbox lag and post-ramp memory recovery. The run preserved zero cross-tenant
leakage, zero duplicate final renders, zero HTTP 5xx, zero Outbox `DEAD`,
zero pool-acquisition timeouts and zero OOM or unplanned restarts. It also
eliminated the previous asynchronous-generator `aclose()` race.

The fourth remediation is therefore scoped to continuity, admission, delivery
latency and lifecycle ownership. It must not modify migrations `0001-0010`,
frozen contracts, RLS, TenantContext, OIDC authority, SERIALIZABLE semantics,
Outbox atomicity, C12 publication semantics, Gate C thresholds or Gate C
workload.

## Decision

The remediation will add low-cardinality lifecycle measurements and behavior
changes only where they directly disprove one failed control:

| Failed control | Working hypothesis | Change boundary | Disproof metric |
| --- | --- | --- | --- |
| 1,350 committed events lost by 100 duplicate-replay clients | Reconnect subscriptions can enter LIVE with a valid contiguous replay but still miss events committed before the terminal observation boundary because live fan-out and replay catchup are not explicitly tail-synchronized. | Preserve signed cursor validation, duplicate suppression and fail-closed gaps; add explicit replay terminal catchup and counters for replay acquisition, merge, handoff, gap and terminal catchup outcomes. | Every duplicate-replay subscriber reaches the publisher terminal ordinal exactly once; final duplicate renders remain zero. |
| 40 failed reconnect attempts | Reconnect failures are concentrated in admission/replay synchronization rather than Keycloak token issuance. | Separate token latency from stream admission, replay acquisition and disconnect outcomes; do not fabricate JWTs or increase client timeouts. | Per-reason counters attribute every failed attempt, and connection/reconnect success meets the frozen threshold. |
| Commit-to-client p95/p99 and Outbox p95/p99 lag | Delays may come from claim polling, partition scheduling, notification fan-out, or replay catchup rather than one opaque end-to-end value. | Retain `FOR UPDATE SKIP LOCKED`, leases, retries, partition ordering and sink confirmation; measure created-to-claimed, claimed-to-published and published-to-client independently. | Outbox p95/p99 and delivery p95/p99 meet frozen thresholds with zero `DEAD`, zero sequence gaps and zero duplicate final rendering. |
| Post-ramp memory ratio and residual subscribers/cache | Subscribers, queue entries, replay cache entries or background tasks remain owned after disconnect/recovery. | Preserve the single close owner; add gauges for active/live/replaying/closing subscribers, queued events/bytes, replay-cache tenants/events/bytes, replay tasks and pending close tasks. | After fixed recovery, subscriber and task gauges drain and RSS returns within the frozen recovery ratio without forced garbage collection. |
| Timing-sensitive two-instance notification test | The test can publish before both bridges and subscribers are durably synchronized, conflating readiness with true notification loss. | Add an explicit readiness barrier and bounded non-heartbeat wait; keep a separate regression for a real notification/replay gap. | The regression is deterministic, still fails on genuine gaps, and does not hide notification latency by only increasing timeouts. |

Historical failure-volume analysis established that the Outbox delay is not
primarily claim polling. `topic3.workflow.created` remained claimed while
`Topic3WorkflowOutboxConsumer` awaited the complete Agent workflow through the
in-memory `AsyncTaskQueue`. The same partition's `workflow.started`, task and
finalization events consequently waited behind a 6-15 second head item. The
measured created-to-published p95 values were 14.2 seconds for
`workflow.created`, 12.7 seconds for `workflow.started`, 10.1 seconds for
`agent-task.completed`, and 11.2 seconds for `workflow.finalized`.

The fourth remediation therefore treats an immutable PostgreSQL Topic 3
session snapshot in `PLANNED` or `RUNNING` as the durable execution authority.
The trigger consumer persists `RUNNING`, waits for bounded queue acceptance,
and then completes. A recovery coordinator discovers only tenant identifiers
through the existing `liyans_dispatcher` Outbox `SELECT` grant, enters a normal
trusted `TenantContext`, and queries recoverable sessions through the regular
`liyans_app` connection and `FORCE RLS`. It reconciles on startup and
periodically. This closes the crash window that would otherwise make
enqueue-only acknowledgement unsafe, without adding a migration, acknowledging
publication before a durable recovery fact exists, or granting the dispatcher
access to Topic 3 tables.

The SSE hot path also limits low-cardinality gauge refreshes to ten per second
while forcing exact lifecycle values on open, close and cache expiry. Prior
Gate C evidence showed millions of redundant gauge writes during dequeue; the
new bound removes that allocation pressure without changing event delivery or
the frozen metric aggregation.

## Compatibility

This ADR authorizes only measured remediation inside the existing SSE broker,
PostgreSQL notification bridge, Outbox publisher and their tests. It adds no
client-controlled identity headers and no new infrastructure. Gate C remains
failed until a new protected-main rerun on a fresh PostgreSQL volume passes all
frozen controls and the independent success evidence PR merges through 8/8 CI.
