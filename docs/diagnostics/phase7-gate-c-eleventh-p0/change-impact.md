# ADR-0023 Change Impact

Process Version: `Gate-C-11-v1.0`

## Change Surface

Behavior commit `ea5ce1bd6c915a6488df62f65aeacad75ba8aa79` changes:

- `backend/src/liyans/infrastructure/observability/metrics.py`: diagnostics
  ownership, lifecycle, fixed-cardinality measurements, and scrape timing;
- `backend/src/liyans/main.py`: start and first-in-shutdown ownership through
  the existing `AsyncExitStack`;
- `backend/tests/test_metrics.py`: positive and reverse-boundary regressions;
- `backend/tests/test_api.py`: application lifespan ownership regression.

Relative to the failing-test commit, this is 408 inserted and 29 deleted lines
across four files. It contains no formatting-only refactor or unrelated feature.

## Core Semantics

The change does not modify migrations `0001-0010`, PostgreSQL RLS,
`TenantContext`, SERIALIZABLE transaction handling, C12, frozen contracts,
thresholds, workload, service-principal authorization, SSE cursor signing,
replay order, Outbox claim/lease/retry/partition handling, durable acceptance,
or atomic publication.

It adds no identity headers, role broadening, forced GC, process restart,
timeout increase, grace period, worker-process scaling, load reduction, or
aggregation change.

## Regression Mapping

- scrape isolation: a scrape must not invoke the heavy collector;
- scheduling: a controlled collector must not prevent a scrape or heartbeat;
- ownership: duplicate start has one task and duplicate close is idempotent;
- shutdown: close waits for an in-flight worker and leaves no sampler task;
- failure: the last completed values survive and failure/staleness is exposed;
- cardinality: unknown metric and stage labels are discarded;
- application lifecycle: FastAPI lifespan starts and closes the sampler;
- existing surface: metrics exposition, middleware, allocator metrics, health,
  authentication, and identity-header rejection regressions remain green.

The mandatory full semantic regression set remains a pre-merge requirement.
