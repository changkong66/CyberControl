# ADR-0006: SSE Release Gate and Replay Semantics

**Status:** Accepted

## Decision

Unverified candidate content is staged. Public content is materialized only in
an atomic publication transaction that consumes a one-time release authorization
bound to the exact candidate version and hash. SSE delivery is at least once,
with signed cursors and idempotent frontend reducers.

## Consequences

- Progress may stream before verification; resource bodies may not.
- Slow clients are disconnected and recover from the durable public event log.
- Database uncertainty closes the publication gate.
