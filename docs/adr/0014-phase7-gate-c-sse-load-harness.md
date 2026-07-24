# ADR-0014: Phase 7 Gate C SSE Load Harness

## Status

Accepted before Gate C execution.

## Decision

Gate C uses the locked Locust 2.x runtime in Linux multi-process mode and the
locked `sseclient-py` parser. The system under test remains the protected-main
FastAPI, PostgreSQL and Keycloak runtime; only low-cardinality pool metrics are
enabled for acceptance observability.

The load runner provisions two acceptance-only tenants and twenty real
Keycloak principals in an isolated environment. It obtains signed tokens from
Keycloak, sends no client-controlled tenant identity headers, and consumes the
authenticated Topic 4 SSE endpoint with signed `Last-Event-ID` cursors.

Periodic Topic 3 workflows use the frozen Topic 4 `zh-CN` locale. Five percent
of client slots are assigned deterministically to slow consumers; their 100 ms
processing delay remains below the configured 5 events/second per-tenant burst
rate, so the latency SLO is not made mathematically unachievable by the harness.
After the environment health gate, tool containers use `--no-deps` so measured
load cannot restart migrations or Keycloak configuration jobs.

The load generator and system under test may share the current workstation.
Such a result is explicitly a single-host acceptance result and cannot be used
as a production cluster capacity claim.

The runtime exposes only low-cardinality database-pool observability for this
acceptance: configured pool capacity, checked-out connections and acquisition
timeouts. SQLAlchemy checkout/checkin hooks and the session boundary record
these metrics without changing transaction, RLS or wire behavior. The runner
also samples container PID 1 file descriptors, memory, network I/O and restart
state, so pool saturation and descriptor exhaustion are measured rather than
inferred from PostgreSQL session counts alone.

## Evidence Boundary

Thresholds and workload are versioned before execution. Runtime credentials,
tokens and passwords are ephemeral and excluded from evidence. Machine-readable
results bind the source commit, tree, image identifiers, Compose configuration,
host resources and tool versions. Each stage first completes its stable window,
then performs one forced disconnect; a disjoint deterministic five percent
sample reconnects from the baseline cursor so duplicate replay suppression is
exercised in the real load. A real signed token is retained until its expiry and
then presented to the API; the expected result is 401. Failed thresholds are
archived without unlocking Gate D.

## Compatibility

This decision adds load tooling and low-cardinality runtime observability only.
It changes no migration, wire contract, tenant policy, transaction, Outbox, SSE
or publication behavior.
