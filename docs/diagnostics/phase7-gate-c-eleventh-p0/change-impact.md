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

## Execution Contract

Commits `6465519`, `4e22371`, `34a8841`, `dac33b4` and `f2b5769` add the
process-level regression and runner implementation required by
`Gate-C-11-v1.0`:

- `DiagnosticStages` records selected stages and non-passing diagnostic
  summaries without invoking the formal finalizer or making an acceptance
  claim;
- `PreflightSmoke` records `PREFLIGHT_CHECK`, runs only the frozen Smoke stage,
  and always verifies deletion of its exact Compose containers, network and
  explicitly named PostgreSQL volume;
- `Full` remains protected-main-only, now rejects `SkipBuild`, builds every
  source-built service image, and is the only mode allowed to invoke the formal
  finalizer;
- source-built images carry and are checked against source/tree, product source,
  engineering baseline and process-version labels before any workload starts;
- candidate Smoke exposes independent `ColdDeployment`,
  `ControlledApiRestart` and five-minute `StableIdle` scenarios, all using
  unique disposable projects, networks and PostgreSQL volumes;
- stable source-SHA image references let those independent projects use one
  verified candidate image digest without inheriting runtime state;
- formal summaries and manifests reject non-formal or unknown-process execution
  metadata and preserve both baseline SHAs.

These are execution provenance and isolation controls. They do not alter
application runtime settings, frozen workload/threshold aggregation, client
timeouts, database configuration, identity authority or acceptance semantics.

## Local Quality Evidence

The complete local suite passed at committed candidate
`f2b5769065bb56932ddd6d43a8d70a937414a170`: deterministic Python
`665 passed, 1 skipped, 86 deselected`; real PostgreSQL/Keycloak `751 passed,
1 environment skip`; Python coverage 91.91%; frontend 72 tests with 92.38%
line coverage; Playwright 8/8; and all Ruff, contract, migration, Go,
frontend build/typecheck, audit, SBOM/license, production-container, Trivy and
Gitleaks controls passed. Trivy and Gitleaks reported zero findings.

An earlier fresh integration environment omitted the real `keycloak-config`
bootstrap and correctly produced two fail-closed identity-test failures from
empty server-derived Keycloak attributes. After the bootstrap was run, those
same tests passed 2/2. The authoritative complete suite ran in a separate,
fully configured environment named
`cybercontrol-gate-c-11-quality-final2-20260823` with fresh PostgreSQL volume
`cybercontrol-gate-c-11-quality-final2-20260823_liyans-postgres`.

Windows reserved ports `5113-5212` after the Docker restart. Playwright was
therefore measured on temporary port 5275; the configuration was restored and
no port change is committed. Neither local quality nor runner-contract tests
are M1 or formal Gate C acceptance. Three real candidate Smoke runs remain
mandatory.

## Smoke Infrastructure Interruption

Cold-deployment run `gate-c-harness-20260823T122253Z` stopped before API
startup because the host excluded TCP range `5385-5484` contained PostgreSQL
port 5432. The preserved metadata classifies it as non-formal Harness Smoke and
makes no acceptance claim. No workload or product control was evaluated.

That failed startup revealed one project-labelled `liyans-runtime` volume left
by Compose after containers, network and the explicit PostgreSQL volume were
removed. Commit `f27cc03` changes only the ephemeral Harness/Preflight cleanup
path to include `--volumes` and verifies zero remaining project-labelled
volumes. The exact interrupted-run volume was removed after label validation;
the diagnostic run directory remains preserved. Ruff and all 27 focused runner
regressions pass after the formatting-only follow-up `7e31cba`.

## Monitor Target Correction

The subsequent cold run reached the workload but failed only monitor
completeness: Compose published PostgreSQL on `59032`, while the host monitor
was hard-coded to `5432`. The raw evidence records 36/36 successful metrics
scrapes, 36/36 refused database samples, and all non-monitor frozen Smoke
controls passing. Remaining Smoke scenarios were not started.

The corrective diff is limited to the Windows Gate C runner, one positive and
reverse-boundary runner regression, this impact record, the ADR and the
diagnostic package index. It adds a validated `PostgresHostPort`, binds both
Compose and the monitor to it, and records it in execution/environment
metadata. It does not change product images, application behavior, database
settings, monitor timeout, sampling interval, aggregation, thresholds or
workload. The exact Harness resources were destroyed and the non-formal abort
package is immutable at SHA256
`405ab328c655d549423b5c929907ef6eeccb80e7beafcce71089d129d05aab6c`.
