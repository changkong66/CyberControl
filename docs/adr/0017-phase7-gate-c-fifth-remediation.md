# ADR-0017: Phase 7 Gate C Fifth Remediation Trusted Consumer Plan

## Status

Accepted before fifth-remediation behavior changes.

## Context

The fourth protected-main Gate C replay on source
`97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504` passed 20, 200 and 500
authenticated streams. The 1,000-stream stage failed commit-to-client and
Outbox latency controls and left two `topic3.workflow.finalized` rows `DEAD`.
Both rows exhausted three attempts with `LIYAN-AUTH-FORBIDDEN`.

The production Outbox sink establishes a server-derived dispatcher context
with the `system:outbox-dispatcher` role and `topic3:dispatch` scope. The
finalized-event consumer then calls the public Topic 3 runtime loader, whose
learner ownership policy is intentionally designed for end-user requests. A
background dispatcher is therefore evaluated as if it were the learner that
owns the generation session. Existing integration coverage published the
event under a privileged test-user context and did not exercise this trusted
boundary.

## Decision

| Failed control | Root-cause hypothesis | Change boundary | Disproof metric |
| --- | --- | --- | --- |
| Two finalized events became `DEAD` with `LIYAN-AUTH-FORBIDDEN` | The finalized consumer reuses the dispatcher context at an end-user authorization boundary. | Require the exact server-derived dispatcher role/scope, then enter an idempotently restored, tenant-bound service context with only `topic3:workflow:consume` and `topic4:verification:write`. Add a dedicated Topic 3 internal loader; preserve the public learner policy. | A valid sequence-2 finalized event is `PUBLISHED`; missing dispatcher authority and cross-tenant events remain fail-closed with zero Topic 4 acceptance. |
| Outbox p95/p99 `6292.587/8712.164 ms` | Authorization retries and partition blocking inflate durable delivery latency. | Record low-cardinality `claimed -> dispatch`, `dispatch -> durable acceptance`, and authorization decision metrics without changing polling, leases, ordering or acknowledgement. | Formal Outbox p95/p99 pass with `DEAD=0`; a deterministic authorization rejection remains visible and is never acknowledged. |
| Commit-to-client p95/p99 `1631/6132 ms` | Finalized-event retries delay the same partition and downstream SSE projection. | Preserve atomic publication and consumer confirmation; correlate accepted delivery with existing SSE enqueue/client metrics. | Formal commit-to-client p95/p99 pass with zero event loss, duplicate final rendering or cross-tenant delivery. |
| 1,000-stream admission p95/p99 `19964/23705 ms` | Admission delay is independent from successful Keycloak token issuance and may be HTTP/subscriber/replay scheduling. | Keep the existing admission stage metrics and do not change client timeouts, grace periods or workload. | A fresh Gate C rerun attributes token, HTTP admission, authentication, subscriber registration, replay handoff and first-event latency separately. |

The service consumer identity is not copied from client input or the original
event author. It is constructed inside the registered server consumer after
the dispatcher context and envelope tenant are validated. The new scope is
narrower than `topic3:admin` and `topic3:learner:any`; it authorizes only the
immutable runtime read needed to create Topic 4 verification work.

## Compatibility And Stop Rule

This remediation changes no migration, frozen contract, RLS policy,
SERIALIZABLE transaction, Outbox atomicity, C12 publication semantic, Gate C
threshold or workload. Historical failed evidence remains immutable. Gate C
remains failed and Gate D-G remain locked until a fresh protected-main run on
a new PostgreSQL volume passes every frozen control and its independent
evidence PR merges through 8/8 CI.
