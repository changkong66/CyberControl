# Gate C Third Remediation Root-Cause Measurement Plan

## Scope

This note is bound to protected-main source `bf9b4d11484f27593d7c41640f15f9a402a94754`.
It records the measurements required before and during the third scoped
remediation. Gate C thresholds and `tests/load/gate-c-workload.v1.json` are
frozen and are not changed by this work.

## Observed Failures

The fresh-volume second-remediation run sustained 2,000 authenticated streams
for 1,805 seconds, but observed connection success `0.9840098401`, reconnect /
replay success `0.9685230024`, committed event loss `1,700`, Outbox lag p95/p99
`10277.417/11538.743 ms`, post-ramp memory ratio `1.480965`, and 14 concurrent
async-generator close errors.

## Measurement-to-Change Map

| Observed signal | Measurement | Allowed remediation |
| --- | --- | --- |
| `aclose(): asynchronous generator is already running` | Count active `anext` tasks, close-owner state, cancellation reason, pending cleanup tasks and subscriber removal order | Replace implicit async-generator ownership with an explicit single-owner response iterator and idempotent subscription close handle; cancel and await child tasks before removal |
| Connection success and admission p95/p99 collapse at 2,000 | Separate Keycloak token acquisition, HTTP admission, subscription registration, latest-sequence lookup, replay query and first-byte timestamps | Bound replay/latest work per tenant, avoid per-event irrelevant fanout, and expose admission rejection/timeout counters without increasing client timeouts or reducing load |
| Reconnect/replay failure and 1,700 committed-event loss | Record Last-Event-ID, subscriber state transitions, replay target sequence, buffered/live merge range, gap detection and final delivered sequence; never record token or PII | Preserve `REPLAYING -> LIVE`, contiguous sequence validation, durable replay and fail-closed cursor handling; repair only proven gaps |
| Outbox lag p95/p99 | Record created, claimed, published and client-observed timestamps, partition, batch size, claim lease and retry outcome | Keep `SKIP LOCKED`, lease, retry, partition ordering and atomic completion; reduce claim/query overhead and process independent partitions concurrently |
| Post-ramp memory ratio | Sample RSS, tracemalloc top allocations, subscriber/queue/replay cache/pending task gauges before ramp, during ramp, at unload and after 10 minutes | Remove actual retained references and bound replay/cache/task lifetime; `gc.collect()` and threshold changes are forbidden |
| CI heartbeat race in PostgreSQL SSE regression | Wait for the next non-heartbeat event until a bounded deadline and separately test a true notification/replay gap | Make the regression deterministic without weakening production heartbeat or Gate C semantics |

## Evidence Requirements

- Unit and real PostgreSQL tests must prove cancellation cleanup, ContextVar
  restoration, pool return, ordered replay, duplicate suppression, cursor
  fail-closed behavior, Outbox lease recovery and multi-tenant isolation.
- Runtime measurements must contain no access token, password, verification
  code, tenant-secret or raw PII.
- The formal rerun must use the unchanged frozen threshold/workload files,
  real Keycloak tokens, two tenants, at least ten real subjects per tenant and
  a new isolated PostgreSQL volume.
- Any failed threshold remains `PHASE7_GATE_C_FAILED_GATE_D_LOCKED` and is
  archived as a new immutable evidence package.
