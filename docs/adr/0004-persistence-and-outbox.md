# ADR-0004: PostgreSQL, Immutable Artifacts, and Transactional Outbox

**Status:** Accepted

## Decision

PostgreSQL stores authoritative workflow state, audit metadata, idempotency, and
outbox records. Large bodies and reports are immutable hash-addressed artifacts.
State changes, audit events, and outbox records commit atomically.

## Consequences

- At-least-once delivery is expected; consumers are idempotent.
- Topic 4 data uses separate schemas and cannot modify frozen Topic 1 tables.
- Caches and metrics are never business truth sources.
