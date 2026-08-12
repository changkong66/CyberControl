# ADR-0019: Phase 7 Gate C Seventh Remediation Measurement Plan

## Status

Proposed before seventh-remediation behavior changes.

## Context

Protected-main sixth-remediation replay reached 1,000 authenticated streams for
603 seconds and stopped on the unchanged latency controls. The measured values
were:

- commit-to-client p95/p99: `1805/7190 ms` against `1000/3000 ms`;
- Outbox created-to-published p95/p99: `10102.261/11812.566 ms` against
  `2000/5000 ms`;
- connection establishment p95/p99: `21888/25735 ms` with zero Keycloak token
  acquisition failures;
- API CPU p95/max: `128.502/145.910` one-core units and peak file descriptors
  `1038`.

The same run proved zero committed event loss, zero duplicate final rendering,
zero cross-tenant leakage, zero HTTP 5xx, zero Outbox `DEAD`, zero pool
acquisition timeouts and zero asynchronous-generator close races. The 2,000
stream and ten-minute recovery stages were not executed. Those passing
invariants remain release controls and are not tradeable for latency.

The preserved stage histograms narrow the performance boundary without proving
a single cause. Tenant-lock wait was approximately 4 ms cumulative and locked
fan-out approximately 0.915 s cumulative for the observed notification set,
while `published_to_client` recorded 639,875 per-subscriber observations and
approximately 61,344 s cumulative observation time. Outbox histograms showed
claimable-to-claimed and dispatch-to-durable-acceptance as material stages;
all 105 observed messages eventually reached `PUBLISHED`.

## Decision

The seventh remediation is limited to evidence-backed scheduling and allocation
changes. Each change has a disproof metric and retains the existing trust and
durability boundaries.

| Failed control | Measured hypothesis | Scoped change | Disproof metric | Invariants retained |
| --- | --- | --- | --- | --- |
| Commit-to-client p95/p99, API CPU and file descriptors | Every response owns a 0.5-second disconnect watcher and probes request disconnect around every event. At scale this creates thousands of runnable tasks and repeated ASGI calls in addition to the server's cancellation signal. | On the locked Uvicorn ASGI 2.3 path, use Starlette's response-level disconnect listener as the cancellation owner and keep explicit idempotent `aclose()` for direct shutdown/tests. Retain the watcher fallback for direct iterators and ASGI 2.4+ paths where `StreamingResponse` does not listen on `receive`. | Cancellation, forced close, double-close or ContextVar tests leak a subscriber, pending task, queue item or replay task; a supported ASGI path lacks a disconnect owner; real replay reports a disconnect gap. | Single close owner, awaited cancellation, ordered replay, signed tenant cursor, zero loss/duplicates/leakage. |
| Commit-to-client CPU and allocation pressure | The immutable event JSON is cached, but the static SSE frame body is rebuilt and UTF-8 encoded for every subscriber. | Cache only the tenant-independent encoded event body on `SSEEvent`; construct the frame by joining the per-client signed cursor with that immutable body. | Wire bytes, multiline data parsing, event type, cursor binding or frame compatibility tests differ; RSS/CPU does not improve without changing workload. | SSE v1 framing and signed Last-Event-ID semantics. |
| Outbox p95/p99 and event-loop runnable time | The publisher performs two expired-claim UPDATEs on every empty poll. The sixth run recorded 2,505 empty claims in the 1,000-stream stage while no claim or pool failure occurred. | Replace the two mutually exclusive recovery UPDATEs with one atomic `CASE` UPDATE before every claim. Do not rate-limit recovery: an expired partition head must be recoverable on the next poll even with the production 30-second lease. Every claim still uses `FOR UPDATE SKIP LOCKED`, lease ownership and retry state. | Claimable-to-claimed p95/p99 remains unchanged, one recovery pass issues more than one UPDATE, or an expired PENDING/DEAD transition is delayed beyond the next claim. | Lease duration, retries, partition order, claim token/worker ownership and atomic PENDING/CLAIMED/DEAD transitions. |
| Outbox dispatch and authorization latency | Workflow events are materially slower than simple domain events; durable acceptance includes the existing server-derived dispatcher context and consumer completion. | Add no early acknowledgement and no role broadening. Preserve stage instrumentation and isolate scheduling changes to claim recovery and response allocation; reject any change that moves durable work after `PUBLISHED`. | Valid finalized events become `DEAD`, invalid/cross-tenant events are accepted, or `PUBLISHED` precedes durable acceptance. | TenantContext derivation, authorization, idempotency, durable acceptance and Outbox atomicity. |

## Measurement Contract

Metrics remain bounded by the existing operation/outcome/stage labels and contain
no tenant IDs, subjects, cursors, tokens or payloads. Formal Gate C must still
bind the fresh source commit, image IDs, Compose and lock hashes, real Keycloak
Token issuance, raw stage metrics, PostgreSQL terminal evidence and a SHA256
manifest to a new run directory and fresh PostgreSQL volume.

## Stop Rule

This ADR does not accept the sixth partial run. The formal state remains
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. Gate D-G remain locked. A seventh
remediation replay is permitted only after the code is merged through protected
main 8/8 and must execute the unchanged frozen workload and thresholds.
