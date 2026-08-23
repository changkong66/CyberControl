# Gate C Eleventh P2 Measurement Instrumentation Change Impact

Process Version: `Gate-C-11-v1.0`

## Binding

- ADR: `docs/adr/0025-phase7-gate-c-eleventh-p2-measurement-redesign.md`
- Product source: `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Engineering parent: `cca2194382d8e2730fc32cf4341589acf11f1c53`
- Parent tree: `ca8d18701471b11f12e4c72ea1411205262e84a0`
- Parent protected-main CI:
  [Run 32663785036](https://github.com/changkong66/CyberControl/actions/runs/32663785036),
  8/8
- Classification: diagnostic instrumentation, not product remediation
- Formal Gate C attempt: no
- Acceptance claim: no

## Changed Surface

The implementation replaces event-delta database-pool accounting with an
absolute SQLAlchemy pool reader. It adds a process-local, opt-in `SIGUSR1`
checkpoint owner, complete offline tracemalloc traceback comparison, jemalloc
bin/large-extent inventories, bounded pool/cache/SSE/cursor/Prometheus
inventories and diagnostic runner support for a 300-second idle baseline and
600-second recovery window.

Checkpoint mode is disabled unless an absolute existing output directory and
all source bindings are provided at process start. It has no HTTP route and
accepts no identity input. It is mutually exclusive with the legacy periodic
heavy sampler. Only `baseline` and `recovery` are accepted, artifacts cannot be
overwritten, shutdown waits for an in-flight owner, and each file is bound by
SHA256 before the manifest becomes visible.

The runner override is loaded only with explicit `-MemoryCheckpoints` in
`DiagnosticStages`. It requires exactly `ramp-200`, 300 idle seconds and 600
recovery seconds. `Full`, `PreflightSmoke` and ordinary diagnostic controls do
not receive the bind mount, signal trigger or profiler configuration.

## Core Semantic Redlines

The branch does not modify migrations 0001-0010, RLS, `TenantContext`,
SERIALIZABLE transaction behavior, C12, frozen contracts, threshold/workload
files, Outbox claim/lease/retry/order, durable acceptance, atomic publication,
Keycloak authority, signed cursors, replay order, subscriber close ownership,
timeouts, client grace periods, workers or metric aggregation.

No forced GC, allocator purge, restart recovery, cache-bound change or
behavior candidate is introduced. Pool and cache access is read-only and used
only in endpoint checkpoint inventories. Tracemalloc data contains allocation
tracebacks and sizes, not object values; task inventories contain type and
code locations, not frame locals.

## Regression Coverage

- deterministic reproduction of negative event-delta accounting and proof
  that the absolute pool reader remains nonnegative;
- real PostgreSQL cancellation and pool-timeout tests proving checked-out
  terminal zero and inspecting adapter/driver caches;
- checkpoint disabled-mode, source/path validation, single ownership, fixed
  sequence, overwrite rejection, shutdown waiting and numeric inventory bounds;
- offline manifest hash rejection and complete traceback-delta retention;
- production Alpine/jemalloc runtime capability check for active bin and
  large-extent values;
- runner parsing, diagnostic-only override, no-cache A' build support,
  continuous recovery monitoring and 30-second end-to-end checkpoint limit;
- all existing tenant isolation, Outbox, streaming, cursor, lifecycle and
  quality-gate suites remain mandatory.

## Stop Boundary

This implementation only enables the reviewed A / measurement / A' experiment.
It does not identify an RSS owner, unfreeze P2 behavior changes, authorize a
formal Gate C replay or change the formal state. Any profiler interference,
incomplete checkpoint, hash/source mismatch, semantic regression or failure to
identify one bounded owner requires evidence archival with P2 still frozen.

Formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; Gate D-G remain
locked.
