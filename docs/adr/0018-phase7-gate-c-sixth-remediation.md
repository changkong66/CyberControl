# ADR-0018: Phase 7 Gate C Sixth Remediation Measurement Plan

## Status

Proposed before sixth-remediation behavior changes.

## Context

The fifth protected-main Gate C replay passed the 20, 200 and 500 stream
stages, but stopped during the 1,000-stream stage. The unchanged frozen
controls that failed were:

- commit-to-client p95/p99: `1532/4985 ms` (required `<=1000/3000 ms`);
- Outbox lag p95/p99: `5830.700/8434.789 ms` (required `<=2000/5000 ms`);
- API CPU p95/max: `127.604/131.840` one-core units;
- peak API file descriptors: `1038`.

The run did not execute the 2,000-stream stage or the ten-minute recovery
observation. Its connection and replay success, loss, duplicate-render,
tenant-isolation and Outbox-DEAD controls passed and must remain unchanged.

## Decision

The sixth remediation will first expose bounded, low-cardinality measurements
for the existing ownership boundaries. No threshold, workload, timeout,
event-count or aggregation change is permitted.

| Observed failed control | Root-cause hypothesis to test | Scoped change | Disproof metric | Invariants retained |
| --- | --- | --- | --- | --- |
| API CPU p95/max and commit-to-client p95/p99 | Per-event fan-out work and metric accounting execute inside the tenant lock and scale as subscribers times events. | Measure lock wait, fan-out duration, queue-write duration and serialized event count; perform only allocation-preserving batching or precomputation proven by those measurements. | Fan-out lock wait and per-event CPU remain dominant, or ordered delivery/regression tests fail. | Global sequence order, signed tenant-bound cursor, zero loss/duplicates/leakage. |
| Commit-to-client p95/p99 | Notification bridge, publisher dispatch, subscriber enqueue and socket write are not separately visible, so a scheduling bottleneck is hidden. | Add stage timestamps/counters at existing server boundaries and readiness/wakeup instrumentation. | Stage histograms do not identify a dominant boundary or latency remains unchanged with no workload alteration. | Durable acceptance precedes acknowledgement; no client grace period or early publish. |
| Outbox p95/p99 | Claim polling/wakeup and partition scheduling delay delivery before the sink, while ordered partition processing is retained. | Measure claimable-to-claimed and dispatch-to-authorization/enqueue stages; optimize wake/poll and bounded batch scheduling only where measured. | Claim-to-dispatch remains low while sink/authorization dominates, or partition-order tests fail. | `FOR UPDATE SKIP LOCKED`, leases, retries, partition order and atomic Outbox state transitions. |
| Peak file descriptors and incomplete fail-fast closure evidence | A socket, queue consumer or background task retains ownership after cancellation or shutdown. | Add ownership gauges and deterministic cleanup tests; inspect rather than masking RSS/FD behavior. | Subscriber/task/queue gauges do not return to zero after forced cancellation and recovery. | Single idempotent close owner, awaited cancellation, session rollback, ContextVar restoration. |
| Outbox authorization failures must remain fail-closed | A valid finalized workflow event can cross an end-user authorization boundary when consumed by the dispatcher. | Preserve the fifth-remediation server-derived consumer identity and test valid, invalid and cross-tenant events. | Valid finalized events become `DEAD`, or invalid/cross-tenant events are accepted. | No identity headers, no role broadening, tenant context derived only by the server. |

## Measurement Contract

Metrics use bounded stage/outcome names only. They must not contain tenant IDs,
subjects, cursors, tokens or payloads. The formal rerun must bind raw samples,
container resource data, PostgreSQL terminal evidence and SHA256 manifests to a
fresh source commit and fresh PostgreSQL volume.

## Stop Rule

This ADR does not accept the fifth partial run. Gate C remains
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. Gate D-G remain locked. A formal Gate C
rerun is allowed only after the remediation is merged to protected main and
must use the unchanged frozen workload and thresholds.
