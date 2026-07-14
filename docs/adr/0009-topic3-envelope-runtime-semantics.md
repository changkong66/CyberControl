# ADR-0009: Topic 3 Envelope Runtime Semantics

**Status:** Accepted

## Context

Five generation agents share a frozen Envelope/Block/Candidate wrapper while
retaining ownership of different payloads. Async execution, SSE, retries, and
future verifier feedback require deterministic behavior across process boundaries.

## Decision

- Pydantic is the canonical contract source; JSON Schema, TypeScript, and Go are generated.
- Envelope v1 rejects unknown fields and binds exact blueprint/candidate versions.
- Delivery is at least once with semantic-digest idempotency.
- Sequence starts at zero per partition and advances only after successful handling.
- Gaps are buffered within a fixed bound; sequence skipping is prohibited.
- Cross-agent payload conversion requires an explicit versioned adapter.
- SSE fragments carry exact UTF-8 hashes and use tenant-bound HMAC replay cursors.
- In-memory stores are executable development adapters only. PostgreSQL outbox,
  idempotency, audit, and durable event-log adapters are production requirements.

## Consequences

Retry metadata may change without producing a false idempotency conflict. A reused
key with different message meaning is quarantined. Slow SSE consumers recover from
the durable log. Topic 4 adds verifier feedback messages without mutating the
Topic 3 positive generation path.
