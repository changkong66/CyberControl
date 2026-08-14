# ADR-0021: Phase 7 Gate C Ninth Remediation Measurement Plan

## Status

Proposed before ninth-remediation behavior changes.

## Context

The eighth-remediation replay evaluated source
`4f0a7670782c5002a2da6e429c0428d8fef29153` with the frozen Gate C
thresholds and workload. All 20, 200, 500, 1,000 and 2,000 authenticated
stream stages and the fixed ten-minute recovery observation completed. The
formal result remained failed because three terminal controls did not pass:

- one `LIVE` subscriber remained throughout the final 30 recovery samples;
- API RSS ended at `1.393027` of the frozen pre-ramp baseline, above `1.10`;
- Outbox created-to-published p95 was `2247.346 ms`, above `2000 ms`.

The replay preserved connection and reconnect success `1.0/1.0`, delivery
p95/p99 `788/1042 ms`, zero committed loss, zero final duplicate rendering,
zero cross-tenant leakage, zero invalid-cursor acceptance, zero HTTP 5xx, zero
Outbox `DEAD`, zero pool acquisition timeouts, zero OOM or restart and zero
asynchronous-generator close races. Final close-owner, queued event/byte,
replay-buffer/cache and replay-task gauges were zero. These controls are not
tradeable for the ninth remediation.

The immutable eighth package has SHA256
`b22f81bbcd42fb5dab0c9bc64891fe8b49888663ab9c0f13260b1de313802ff1`.
Historical evidence and PostgreSQL volumes remain unchanged.

### Residual subscriber ownership

`OwnedStreamingResponse` owns the ASGI 2.3 send and disconnect tasks. It
cancels and awaits both tasks, but it does not explicitly close its
`body_iterator`. A deterministic path reproduces the residual owner:

1. the body iterator yields a frame;
2. the ASGI `send` call blocks;
3. the disconnect listener completes first;
4. the send task is cancelled outside `TenantScopedSSEStream.__anext__`;
5. no owner invokes the iterator's `aclose()`;
6. the broker retains the live subscriber.

The response must therefore complete task cancellation and body-iterator close
as one cancellation-safe cleanup operation. `TenantScopedSSEStream` remains
the single idempotent subscription-close owner.

### Outbox p95 tail ownership

An isolated copy of the eighth-run PostgreSQL volume contains 223 published
Outbox rows. The exact created-to-published distribution is:

- p50 `322.087 ms`;
- p90 `1687.089 ms`;
- p95 `2247.346 ms`;
- p99 `3438.550 ms`;
- maximum `4716.569 ms`.

The p95 tail is concentrated in the ordered five-event Topic 4 partitions.
`topic4.verification.control_plane_prepared` at partition sequence 1 has p95
`3078.259 ms`, and `topic4.verification.state_changed` at sequence 2 has p95
`3499.209 ms`; sequence 0 `topic4.verification.accepted` has p95
`1684.902 ms`.

The current durable acceptance path is:

`OutboxPublisher -> MessageBusOutboxSink -> domain SSE consumer ->
SSEBroker.publish -> PostgreSQL replay append -> synchronous live fan-out`.

With up to 2,000 live subscribers, the Outbox consumer waits for synchronous
fan-out before the message bus reports durable acceptance and before the
dispatcher marks the Outbox row `PUBLISHED`. PostgreSQL already emits a
transactional notification when the replay row is committed, and the ready
notification bridge performs ordered, gap-closing delivery from durable
replay. Outbox projection can therefore complete after durable replay append,
without performing the same synchronous fan-out, only when that notification
bridge is configured and ready. API and local configurations without a ready
bridge retain immediate `publish()` behavior.

### RSS ownership

The production image starts CPython with `PYTHONMALLOC=malloc` and jemalloc,
but its current configuration creates 64 arenas under the 16-CPU Docker
allocation and retains virtual memory. Eighth-run container RSS moved from
`264660582` to `368679322` bytes; PSS and USS increased consistently, while
map count was nearly flat. This pattern is not explained by the final SSE
lifecycle gauges.

A controlled same-image 48-thread allocation/free test, without forced GC or
allocator trimming, produced these recovery ratios:

- current 64-arena configuration: `1.6443`;
- `narenas:2`: `1.1832`;
- `narenas:1`: `1.1851`;
- `narenas:1,tcache:false`: `1.1339`;
- `narenas:1,retain:false`: `1.07124`.

The selected candidate is a process-start setting:

`background_thread:true,dirty_decay_ms:1000,muzzy_decay_ms:1000,narenas:1,retain:false`.

It is not a recovery-only trim and does not change the frozen RSS baseline or
aggregation. Fixed-cardinality jemalloc gauges expose allocated, active,
resident and retained bytes plus arena count when jemalloc is available.

## Decision

| Failed control | Scoped change | Quantitative disproof metric | Preserved controls |
| --- | --- | --- | --- |
| Final subscriber `1` | After cancelling and awaiting ASGI send/disconnect tasks, explicitly and cancellation-safely close the response body iterator. Add the blocked-send disconnect regression. | Any disconnect, cancellation, double-close or shutdown path leaves a subscriber, close owner, queue, replay state or response task nonzero, or emits an `aclose()` race warning. | Single idempotent close owner, ContextVar restoration, session/pool return and wire-compatible ASGI response behavior. |
| Outbox p95 `2247.346 ms` | Add `SSEBroker.persist()` for durable replay append without live fan-out. Use it for Outbox SSE projections only while the configured PostgreSQL notification bridge is ready; otherwise use existing immediate `publish()`. | Unchanged-workload Outbox p95/p99 remain above `2000/5000 ms`; a ready bridge misses, duplicates or reorders an event; bridge loss prevents durable replay recovery; or `PENDING/CLAIMED/DEAD` remains terminally nonzero. | `FOR UPDATE SKIP LOCKED`, claim token, lease, retry, partition order, idempotent durable acceptance, published cursor, atomic Outbox state, signed tenant cursor and fail-closed authorization. |
| RSS ratio `1.393027` | Configure jemalloc from process start with one arena and `retain:false`; export fixed-cardinality allocator gauges without tenant, subject, Token, cursor or payload labels. | Unchanged ten-minute recovery ends above `1.10`, allocator metrics grow in label cardinality, CPU/latency regresses, FDs do not return near baseline, or an OOM/restart occurs. | No forced GC, trim, process restart, worker increase, changed baseline, reduced load, larger timeout or grace period. |

## Implementation Constraints

Durable-only persistence is permitted only for an Outbox projection whose
live delivery is owned by a ready PostgreSQL notification bridge. PostgreSQL
replay storage remains the source of truth. A notification is only a wake hint;
reconnect and overflow recovery must converge through ordered replay. A bridge
that is disabled or not ready must not cause a silent live-delivery gap.

No migration from `0001` through `0010`, frozen contract, RLS policy,
TenantContext authority, SERIALIZABLE transaction, C12 rule, Gate C threshold
or workload changes. No client identity header, fabricated Token, early
publication acknowledgement, weakened ordering, forced GC, allocator trim,
timeout increase, grace period or metric aggregation change is allowed.

## Acceptance Contract

The formal replay must use the protected main produced by the remediation PR,
fresh images built without `-SkipBuild`, a unique Compose project, a fresh
PostgreSQL volume, real Keycloak-issued Tokens, two tenants and at least ten
subjects per tenant. The frozen 20, 200, 500, 1,000 and 2,000 stages and fixed
ten-minute recovery observation remain unchanged.

Every frozen threshold must pass. In particular, Outbox p95/p99 must be
`<=2000/5000 ms`, post-ramp RSS must be `<=1.10`, and all terminal subscriber,
queue, replay and close-owner gauges must be zero. Any failure retains
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

## Stop Rule

This ADR does not accept the eighth replay. Gate D-G remain locked. Gate D is
not started by this task even if an independent Gate C success-evidence PR is
later merged through protected-main 8/8.
