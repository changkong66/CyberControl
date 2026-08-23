# ADR-0023: Phase 7 Gate C Eleventh P0 Remediation

**Status:** Harness monitor-target defect remediated; fresh candidate Smoke restart pending

**Process Version:** `Gate-C-11-v1.0`

## Baseline And Scope

This decision is limited to the P0 controls proven by the tenth formal Gate C
run. It does not open P1 Outbox or P2 RSS remediation.

- product source: `108e8aa0b6e85c304c9bcf4aa3a5c30ec6b5df1a`;
- engineering baseline: `16bab5d90f9a054b5c04f2399248e5b56603185d`;
- engineering tree: `e8a8e5e4a9c062bb74e0d6db1d206cf287f1bf3d`;
- baseline-closure PR: #80;
- baseline-closure protected-main CI: Run `32527996878`, 8/8;
- evaluated tenth-run source: `64792b0420f436d18beea2a301bd4017bc7e7a82`;
- formal state: `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

The tenth run stopped after `smoke-20`. It therefore supplies current evidence
only for P0. The ninth-run Outbox p95 and RSS ratio remain historical signals,
not proof that either control fails on the current product source. P1 may open
only after a new complete formal run proves Outbox p95 above 2,000 ms. P2 may
open only after Outbox passes and the same complete run proves recovery RSS
above 1.10.

## Evidence Index

- run ID: `gate-c-20260815T050434Z-64792b0420f4`;
- immutable run directory:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260815T050434Z-64792b0420f4`;
- repository summary:
  `docs/system-acceptance/evidence/phase7-gate-c-tenth-remediation-summary.json`;
- repository failure analysis:
  `docs/system-acceptance/evidence/phase7-gate-c-tenth-remediation-failure-analysis.md`;
- repository package metadata:
  `docs/system-acceptance/evidence/phase7-gate-c-tenth-remediation-package.json`;
- external package SHA256:
  `036b3c8e09a8ff039b7b30a0d45cf9d67d6939f29690a39b35b9c52e8756e91c`;
- immutable Release ID: `371033270`;
- immutable Release tag:
  `phase7-gate-c-tenth-remediation-failed-20260815-64792b0-evidence-v1`;
- failure archive PR: #76.

Candidate diagnostic evidence:

- A run: `gate-c-11-p0-a-20260821T214559Z-16bab5d`;
- B comparator run: `gate-c-11-p0-b-comparator-20260823T091130Z-ea5ce1b`;
- A' run: `gate-c-11-p0-a-prime-20260823T090935Z-16bab5d`;
- expanded B run: `gate-c-11-p0-b-20260823T090815Z-ea5ce1b`;
- repository summary:
  `docs/diagnostics/phase7-gate-c-eleventh-p0/summary.json`;
- root-cause record:
  `docs/diagnostics/phase7-gate-c-eleventh-p0/root-cause.md`;
- raw package SHA256:
  `761df19ef74b9307d120e04562acaadc0b4016553d0045405c74147176e67aef`;
- immutable diagnostic Release:
  `phase7-gate-c-11-p0-aba-20260823-v3`, Release ID `375173557`;
- immutable diagnostic asset ID: `526077962`, `21,939` bytes, server digest
  `sha256:761df19ef74b9307d120e04562acaadc0b4016553d0045405c74147176e67aef`;
- immutable diagnostic Release URI:
  `https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p0-aba-20260823-v3`;
- package reference:
  `docs/diagnostics/phase7-gate-c-eleventh-p0/package-reference.json`.

GitHub API verification returned `immutable: true`, asset state `uploaded`,
matching bytes and matching server digest. The external-package merge blocker
is therefore closed without making a formal acceptance claim.

The historical run predates this process version and remains recorded with
`process_version: null`. This ADR applies `Gate-C-11-v1.0` only to new
diagnostic, preflight and formal metadata.

## Proven P0 Boundary

The frozen `smoke-20` run had these failed controls:

- delivery p99 `6,850 ms`, required `<=3,000 ms`;
- monitor completeness `31/39 = 0.7948717949`, required `>=0.95`;
- seven `/metrics` `ReadTimeout` observations with an unchanged five-second
  monitor timeout.

It retained connection and reconnect success `1.0/1.0`, zero committed event
loss, zero final duplicates, zero cross-tenant leakage, zero HTTP 5xx, zero
pool acquisition timeouts and zero Outbox `DEAD`. Later load stages and the
recovery observation were not executed.

## Measured Causal Mechanism

`PlatformMetrics.render()` performs these operations synchronously in the API
event-loop request when memory diagnostics are enabled:

1. refresh jemalloc counters;
2. enumerate `asyncio.all_tasks()` and task stacks;
3. enumerate `gc.get_objects()` and selected object types;
4. take and aggregate a `tracemalloc` snapshot;
5. read process memory maps and counters;
6. serialize the complete Prometheus registry.

The preserved monitor and API logs contain seven timeout/diagnostic pairs.
For each pair, the next heavy diagnostic log and the eventual successful
`GET /metrics` completion are in the same request window:

| Pair | Monitor sample UTC | Heavy diagnostic end after sample | Metrics completion after sample |
| --- | --- | ---: | ---: |
| 1 | `11:16:56.336564` | `10,829.524 ms` | `11,678.280 ms` |
| 2 | `11:17:29.612952` | `10,428.215 ms` | `11,202.234 ms` |
| 3 | `11:18:03.147839` | `10,236.166 ms` | `12,637.230 ms` |
| 4 | `11:18:36.905582` | `11,660.326 ms` | `12,178.456 ms` |
| 5 | `11:19:09.894418` | `12,189.952 ms` | `12,611.267 ms` |
| 6 | `11:19:43.414280` | `11,783.925 ms` | `12,555.407 ms` |
| 7 | `11:20:17.071330` | `10,924.847 ms` | `11,385.538 ms` |

This one-to-one periodic alignment proves that the monitor failures are not
random network loss. The diagnostic request continues for 11.20 to 12.64
seconds after the client reaches its five-second timeout.

The same windows explain the delivery tail. Exactly four publisher probes had
publish calls above 3,000 ms:

| Probe ordinal | Tenant class | Publish latency |
| ---: | --- | ---: |
| 69 | alpha | `6,844.689 ms` |
| 119 | alpha | `9,594.978 ms` |
| 143 | beta | `9,265.422 ms` |
| 168 | beta | `8,973.637 ms` |

All four producer timestamps fall inside heavy diagnostic windows. Each probe
is delivered to ten same-tenant clients, so the four blocked probes account
for exactly 40 delivery observations above 3,000 ms, matching the immutable
failure analysis. This supports one P0 root cause: optional process diagnostics
are owned by the synchronous scrape request and monopolize the application
event loop long enough to delay both monitoring and publisher requests.

## Decision

The remediation will separate scrape exposition from optional heavy process
diagnostics while preserving the current metrics and acceptance aggregation.

1. `/metrics` must never initiate task-stack, object-graph or tracemalloc
   collection. It serves the latest completed fixed-cardinality diagnostic
   gauges and renders the current registry.
2. When explicitly enabled, one application-owned diagnostics sampler runs at
   the configured interval. It has a single owner, never overlaps itself, and
   is cancelled and awaited during coordinated shutdown.
3. Heavy collection executes outside the event-loop request path. The sampler
   records bounded substep durations, total collection duration, task count,
   event-loop runnable delay and success/failure outcome without tenant,
   subject, cursor, Token or event labels.
4. A failed or slow diagnostic sample must retain the previous completed
   gauges and expose a bounded failure/staleness signal. It must not make the
   scrape unavailable or alter business delivery.
5. Prometheus exposition remains current and uncached. Frozen monitor timeout,
   sample interval, metric parsing and completeness aggregation remain
   unchanged.

This is not a recovery-only action and does not disable diagnostics to claim a
pass. It corrects diagnostics ownership so enabling them cannot put heavy heap
inspection on the request event loop.

## Falsifiable Measurements

The candidate is disproved by any of these results:

- any enabled-diagnostics scrape initiates heavy collection;
- diagnostics collection overlaps or leaves its sampler task after shutdown;
- a deterministic blocked collector stops an independent event-loop heartbeat
  or delays the `/metrics` response;
- diagnostic stage labels or metric state grow with tenant, subject, cursor,
  event or task identity;
- any of the frozen security, ordering, replay, idempotency or cleanup controls
  regresses;
- any fresh candidate Smoke has `/metrics` `ReadTimeout`, monitor completeness
  below 0.95 or delivery p99 above 3,000 ms.

The positive P0 disproof target is three independent fresh-resource Smoke
runs, with the same candidate image digest, each satisfying all frozen Smoke
controls, monitor completeness `>=0.95`, zero metrics timeout and all
zero-tolerance controls.

## A/B/A' Validation Boundary

This logical ownership defect uses the low-cost deterministic layer:

- A: on the exact parent implementation, a controlled heavy collector invoked
  by a scrape prevents an event-loop heartbeat and delays the scrape;
- B: with the candidate, the same controlled collector runs under the owned
  sampler while the heartbeat and scrape complete independently;
- A': an independent worktree at the exact parent commit reproduces A without
  reverting the candidate branch.

Only after deterministic A/B/A', focused integration coverage and the full
Release Quality Gates pass may candidate Smoke begin. Full Gate C is not an
A/B/A' test tool.

The identical 14-test blob produced A `9 passed / 5 failed`, B `14 passed`,
and A' `9 passed / 5 failed`. The expanded B regression set produced `24/24`
passes. An operation-level collector measurement with 200,000 retained local
objects recorded `4.3581012s` total collection, `4.2072045s` tracemalloc
snapshot time, and `0.2290000s` maximum event-loop heartbeat lag. This is not
a Gate C client-scale claim; it proves that worker duration and residual GIL
delay are separately measurable and leaves fresh Smoke as the required P0
disproof.

## Change Impact And Semantic Redlines

Expected code scope is limited to metrics collection ownership, application
lifespan task ownership, focused tests, diagnostic metadata, execution-mode
isolation, image provenance labels and this ADR. Diagnostic and preflight modes
are non-formal by construction; only `Full` may invoke the formal finalizer,
and `PreflightSmoke` verifies removal of its exact project/network/volume.
The change does not touch migrations `0001-0010`, RLS, TenantContext,
SERIALIZABLE transactions, C12, frozen contracts, threshold/workload files,
SSE cursor signing, replay ordering, Outbox claim/lease/retry/partition logic,
durable acceptance or atomic publication.

Every implementation commit must include positive and negative tests for
sampler readiness, timeout/failure isolation, cancellation and double-stop,
fixed label cardinality and unchanged scrape output. The mandatory core
semantic regression set remains required even though this P0 change does not
modify those modules.

## Local Release Quality Gate Result

The complete local Release Quality Gate suite passed on committed candidate
`f2b5769065bb56932ddd6d43a8d70a937414a170`. The observed results were:

- conventional commit subjects: 11 validated;
- Ruff and frozen contract regeneration/drift: passed;
- Go fmt, vet, race, test and build: passed;
- frontend typecheck, build, audit, SBOM and license checks: passed;
- Python audit, SBOM and license checks: passed;
- deterministic Python: `665 passed, 1 skipped, 86 deselected`;
- real PostgreSQL/Keycloak: `751 passed, 1 environment skip`;
- Python coverage: `91.91%`;
- migrations `0001 -> 0010 -> base -> 0010` and schema drift: passed;
- production container, non-root and minimal-runtime checks: passed;
- Trivy: zero vulnerabilities;
- Gitleaks history and worktree scans: zero leaks.

The separately executed frontend coverage suite reported 72 tests across 14
files and 92.38% line coverage. Playwright passed 8/8. Windows reserved the
configured `5113-5212` port interval after a Docker restart, so the browser
suite used temporary port 5275; its configuration was restored and is absent
from the committed diff.

The first fresh integration environment omitted the real `keycloak-config`
bootstrap service. Two identity tests then failed closed because Keycloak
returned empty server-side user attributes. Running `keycloak-config` made
those same tests pass 2/2. The final quality suite used a new fully configured
environment, `cybercontrol-gate-c-11-quality-final2-20260823`, with fresh
PostgreSQL volume
`cybercontrol-gate-c-11-quality-final2-20260823_liyans-postgres`. This is an
environment-bootstrap diagnosis, not a product pass or failure reinterpretation.

## Candidate Smoke Execution Contract

Commits `34a8841`, `dac33b4` and `f2b5769` make the three candidate Smoke arms
explicit and independently disposable:

- `ColdDeployment` starts from newly created project, network and PostgreSQL
  volume resources;
- `ControlledApiRestart` performs a controlled API restart and waits for the
  service to return healthy before starting the frozen Smoke stage;
- `StableIdle` holds the fresh deployment idle for five minutes before the
  frozen Smoke stage;
- all source-built service images use stable source-SHA references, and their
  OCI provenance labels are checked before load begins;
- every candidate Smoke removes and verifies removal of its exact Compose
  containers, network and PostgreSQL volume on exit.

The three Smoke arms must use one image digest while retaining unique projects,
run directories and volumes. This contract has deterministic tests, but no
candidate Smoke result is claimed here. M1 remains pending.

## Candidate Smoke Infrastructure Interruption

The first cold-deployment attempt, run
`gate-c-harness-20260823T122253Z` at candidate `a7e1a5e529b0`, did not start
the API or any load stage. Docker rejected the PostgreSQL host binding because
the Windows excluded TCP range `5385-5484` contained the default port `5432`.
Its execution metadata records `classification: HARNESS_SMOKE`,
`formal_gate_attempt: false` and `acceptance_claim: false`; it is neither a
formal Gate C attempt nor an M1 result.

The failed startup exposed that `docker compose down` retained the internal
`liyans-runtime` named volume even though containers, network and the explicit
PostgreSQL volume were removed. Commit `f27cc03` changes ephemeral Harness and
Preflight cleanup to `down --volumes`, verifies zero project-labelled Compose
volumes, and retains the explicit PostgreSQL-volume verification. Focused
runner regressions pass 27/27. The exact interrupted-run volume was removed
only after its project label was verified; its run directory and diagnostic
metadata remain preserved.

## Candidate Smoke Monitor-Target Abort

The next cold-deployment run, `gate-c-harness-20260823T130417Z`, reached and
completed the frozen `smoke-20` workload at committed candidate `2f529f1`.
Every functional, security, delivery and runtime control passed, including
delivery p95/p99 `28/122 ms`, connection and reconnect success `1.0/1.0`, and
zero loss, duplicate final render, tenant leakage, HTTP 5xx, pool timeout and
Outbox `DEAD`. The stage nevertheless failed correctly because monitor
completeness was `0/36`, below the frozen `0.95` minimum.

All 36 Prometheus scrapes succeeded and the API log records 36 HTTP 200
responses. Separately, all 36 database samples failed with
`ConnectionRefusedError`. The Compose deployment published PostgreSQL on host
port `59032` to avoid the Windows excluded range, while `Start-GateMonitor`
still used a hard-coded `127.0.0.1:5432` database URL. This is an execution
harness target mismatch, not evidence that the product P0 implementation or
database failed. It is classified `HARNESS_SMOKE_MONITOR_TARGET_ABORT`, makes
no M1 or acceptance claim, and stops the remaining two Smoke scenarios.

The immutable sanitized diagnostic package is Release ID `375216712`, tag
`phase7-gate-c-11-p0-smoke-harness-monitor-abort-20260823-v1`, asset ID
`526237661`, `9,436` bytes, SHA256
`405ab328c655d549423b5c929907ef6eeccb80e7beafcce71089d129d05aab6c`.
The server digest matches and GitHub reports `immutable: true`. Its repository
index is
`docs/diagnostics/phase7-gate-c-eleventh-p0/harness-monitor-abort-package-reference.json`.
The untouched raw directory has 34 files bound by its own SHA256 manifest.

The corrective change adds one validated `PostgresHostPort` runner input,
uses it for both Compose publication and the monitor database URL, and records
it in execution and environment metadata. The pre-fix regression fails because
the binding is absent; it passes after the change. Product code, frozen
aggregation and every semantic redline remain unchanged. Because the runner
changed, the three independent Smoke observations restart from the next exact
committed HEAD and must share its rebuilt image digests.

## Stop Conditions

- Any semantic, security, functional or zero-tolerance regression rejects the
  candidate immediately.
- A failed P0 root-cause round is archived and counted only against P0.
- Two consecutive failed P0 root-cause rounds freeze further P0 code changes
  until a new complete root-cause report is produced. P1/P2 counters remain
  independent, but neither may be claimed from stale ninth-run evidence.
- Gate D-G remain locked regardless of P0 progress.
