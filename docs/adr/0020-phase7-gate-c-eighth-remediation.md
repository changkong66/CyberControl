# ADR-0020: Phase 7 Gate C Eighth Remediation Measurement Plan

## Status

Proposed before eighth-remediation behavior changes.

## Context

The protected-main seventh-remediation replay completed the unchanged 20, 200,
500, 1,000 and 2,000 authenticated-stream stages and the fixed ten-minute
recovery observation. Every stage-local control passed. The final decision
remained failed because two frozen aggregate controls did not pass:

- Outbox created-to-published p95 was `2225.796 ms` against `<=2000 ms`;
  p99 was `3026.102 ms` and passed its `<=5000 ms` control.
- post-ramp API RSS was `1.492792` of the frozen pre-ramp baseline against
  `<=1.10`; first/last/peak RSS was
  `276404634/412614656/448371098` bytes.

The same replay proved connection and reconnect success `1.0/1.0`, delivery
p95/p99 `781/990 ms`, zero committed loss, zero final duplicate rendering,
zero cross-tenant leakage, zero invalid-cursor acceptance, zero HTTP 5xx, zero
Outbox `DEAD`, zero pool acquisition timeouts and zero OOM or restart. Terminal
subscriber, close-owner, queued event/byte, replay-buffer/cache and replay-task
gauges were zero. File descriptors returned from 29 initially to 30 finally.
These controls are not tradeable for either remediation.

The preserved Outbox histograms contain 221 lifecycle observations. Their
aggregate sums were:

- claimable-to-claimed: `76.225 s` (approximately `345 ms` mean), with 203
  observations within one second and all within 2.5 seconds;
- claimed-to-dispatch-start: `24.719 s` (approximately `112 ms` mean);
- dispatch-to-durable-acceptance: `71.387 s` (approximately `323 ms` mean);
- claimed-to-published: `96.487 s` (approximately `437 ms` mean);
- created-to-published: `172.712 s` (approximately `781 ms` mean).

Production currently never calls `OutboxPublisher.wake()`. The publisher waits
on a fixed 0.5-second polling fallback after an empty claim. PostgreSQL has no
Outbox wake channel; the existing `liyans_sse_events_v1` channel is only the
durable SSE-row notification path. This proves avoidable wake jitter exists,
but aggregate timestamps alone do not prove that it accounts for every event
around the failing p95 boundary.

The memory evidence disproves a live SSE-owner leak as the complete cause:
terminal SSE lifecycle gauges and file descriptors returned to baseline. The
API image uses CPython 3.11 on Alpine/musl and contains native NumPy, FAISS and
OpenBLAS dependencies. The process reported 51 PID/thread units at the first,
peak and last samples.

An isolated 2,000-connection reproduction established the retaining mechanism.
After all connections closed, active asyncio tasks and file descriptors returned
to baseline, while private anonymous RSS did not. Tracemalloc retained only
approximately 4.2 MB and object inventories did not retain request, response or
task populations. The standard Starlette ASGI 2.3 path allocates one AnyIO task
group and cancel scope per stream. A response with explicit asyncio task
ownership reduced the retained high-water state, but did not pass the 1.10
ratio on musl. A process-start jemalloc configuration alone also did not pass.
The combination returned the same reproduction from 42,048 KB to 44,644 KB,
or `1.062`, with three baseline tasks and baseline file descriptors. This is
the selected, falsifiable production configuration; no recovery-time action is
required.

## Decision

The eighth remediation is restricted to changes supported by the measurements
below. A candidate change is rejected when its disproof metric fails or when it
weakens a preserved control.

| Failed control | Proven fact or falsifiable mechanism | Candidate scoped change | Quantitative disproof metric | Preserved controls |
| --- | --- | --- | --- | --- |
| Outbox p95 | Proven: the production publisher has no commit wake and can sleep for the 0.5-second poll interval after a transaction commits. Hypothesis: wake jitter materially contributes to the events around p95. | Emit a static, non-PII PostgreSQL notification in the same transaction as Outbox append and add a reconnecting listener that only calls the existing idempotent `wake()`. Keep polling as the durable fallback. | A committed append does not wake promptly; a rollback emits a wake; listener loss prevents polling recovery; or unchanged-workload created-to-published p95 remains above 2000 ms. | `FOR UPDATE SKIP LOCKED`, claim token/lease, retry, partition order, durable acceptance, published cursor, atomic Outbox state and fail-closed authorization. |
| Outbox p95 | The current aggregate histograms cannot correlate a p95 event across all lifecycle segments. | Add bounded, low-cardinality wake/listener outcomes and segment timing. Use internal identifiers only in redacted acceptance evidence, never metric labels or application logs. | Metric label state grows with tenants, messages, cursors or subjects, or lifecycle measurements move durable work after `PUBLISHED`. | No PII, tenant ID, Token, cursor or payload labels; no early acknowledgement. |
| RSS recovery | Proven: the ASGI 2.3 streaming path creates per-stream AnyIO task-group/cancel-scope allocation pressure. Explicit cancel-and-await ownership reduces the retained high-water state without retaining tasks or descriptors. | Use an application-owned streaming response for ASGI <2.4. It explicitly owns the send and disconnect tasks, propagates send failures, and cancels and awaits the peer task before returning. | Cancellation, disconnect or shutdown leaves either task running, changes wire output, causes an `aclose()` race or loses a subscriber. | Single close owner, awaited cancellation, ContextVar restoration and Starlette-compatible response semantics. |
| RSS recovery | Proven: musl remains above the ratio after the application objects are released; jemalloc alone is insufficient, while explicit response ownership plus process-start jemalloc and `PYTHONMALLOC=malloc` reached `1.062` in the 2,000-connection reproduction. | Install Alpine's pinned repository jemalloc package in the runtime image and configure it from process start with bounded decay. Do not invoke allocator controls during recovery. | The image fails SBOM/license/security gates; latency or CPU regresses; or unchanged formal recovery finishes above 1.10. | No forced GC, trim, restart, worker increase, changed baseline or reduced workload. |

## Implementation Constraints

The transactional wake is a hint, not a source of truth. Notification loss,
listener reconnect or process restart must converge through the existing
polling and durable Outbox rows. No migration from `0001` through `0010` is
modified. The notification payload is constant and carries no tenant, subject,
cursor, Token, envelope or event identifier.

Memory diagnostics must discard incomplete monitor samples where the API
container is absent. They must record RSS, PSS and private memory from `/proc`
without changing the frozen RSS baseline or aggregation. Tracemalloc and object
inventories are diagnostic evidence; `gc.collect()`, `malloc_trim`, process
restart and a recovery-only action are prohibited as fixes.

The runtime allocator is part of the built image, not an acceptance-script
override. `PYTHONMALLOC=malloc`, `LD_PRELOAD=/usr/lib/libjemalloc.so.2` and the
bounded jemalloc decay configuration apply before Python starts. The image and
new package remain subject to the existing SBOM, license, vulnerability and
dependency gates.

## Acceptance Contract

The formal replay remains the unchanged frozen workload on a new protected-main
commit, fresh images, a unique Compose project and a fresh PostgreSQL volume.
Outbox p95/p99 must be `<=2000/5000 ms`; post-ramp RSS must be `<=1.10` of the
frozen pre-ramp baseline. Every previously passing control must remain passing.

## Stop Rule

This ADR does not accept the seventh replay. The formal state remains
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. Gate D-G remain locked until an independent
Gate C success-evidence PR is merged through protected-main 8/8, and Gate D
still requires separate explicit authorization.
