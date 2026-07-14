# ADR-0001: Monorepo and Runtime Boundaries

**Status:** Accepted

## Decision

Use one repository with a modular FastAPI control plane, a Vue 3 application,
shared generated contracts, and separately deployable workers for sandboxed
code execution and CPU-heavy validation.

## Rationale

The domains share contracts and transactions, so independent microservices for
every agent would add failure modes before they add useful isolation. Code
execution and heavy workers need process-level isolation and remain separately
deployable.

## Consequences

- Domain modules cannot import each other's infrastructure internals.
- Cross-domain communication uses application services or versioned events.
- The sandbox service has no provider credentials or direct core database access.
