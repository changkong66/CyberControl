# CyberControl System Acceptance Report

## Decision

Protected-main Gate C third-remediation baseline
`01595ae2634cb8114dfb9c591114048cba3864fd` remains a **release candidate**, but
Gate C is **not accepted**. PR #50 merged the third SSE lifecycle, replay and
Outbox remediation after push, pull-request and protected-main workflows each
completed all eight Release Quality Gate jobs successfully. The unchanged Gate
C workload was then rerun from this clean main baseline and a new isolated
PostgreSQL volume; the 2,000-stream stage still failed frozen connection,
replay/event-loss, delivery-latency, Outbox-lag and memory-recovery thresholds.

Formal state:
PHASE7_GATE_C_FAILED_GATE_D_LOCKED.

The project is not SYSTEM_ACCEPTED. Gate A and Gate B remain accepted. The
initial Gate C failure and all three remediation reruns are preserved as
distinct evidence snapshots. Gate D, Gate E, Gate F and Gate G remain serially
locked. No single-host production capacity claim is permitted.

## Evaluated Baseline

- Gate B replay archive baseline:
  `a6024716ebbe2311daf73b9409fd84e9ed512f59`
- Gate B replay archive tree:
  `7cfd4171840d9d0b274f16c5d7ba70a8cc9402dc`
- Evaluated Gate B replay source commit/tree:
  `7e2a1d7cc3efc55ce27044e10959c4f5889a85da` /
  `c9821405359f59fee9fb993873ed3ba7f55e8b00`
- Gate B evidence PR: [#34](https://github.com/changkong66/CyberControl/pull/34),
  Squash Merge `412085e1586e3d497e5e6f944d4f34e258896d8b`
- PR #34 push CI: [Run 29886312423](https://github.com/changkong66/CyberControl/actions/runs/29886312423), 8/8
- PR #34 pull-request CI: [Run 29886314403](https://github.com/changkong66/CyberControl/actions/runs/29886314403), 8/8
- C3 remediation PR: [#35](https://github.com/changkong66/CyberControl/pull/35),
  Squash Merge `7e2a1d7cc3efc55ce27044e10959c4f5889a85da`
- PR #35 retargeted push CI: [Run 29886959510](https://github.com/changkong66/CyberControl/actions/runs/29886959510), 8/8
- PR #35 retargeted pull-request CI: [Run 29886962210](https://github.com/changkong66/CyberControl/actions/runs/29886962210), 8/8
- Gate B replay-source main CI: [Run 29887219266](https://github.com/changkong66/CyberControl/actions/runs/29887219266), 8/8
- Gate B replay archive PR: [#36](https://github.com/changkong66/CyberControl/pull/36),
  Squash Merge `a6024716ebbe2311daf73b9409fd84e9ed512f59`
- PR #36 push CI: [Run 29888597039](https://github.com/changkong66/CyberControl/actions/runs/29888597039), 8/8
- PR #36 pull-request CI: [Run 29888658077](https://github.com/changkong66/CyberControl/actions/runs/29888658077), 8/8
- Post-merge protected-main CI: [Run 29888873754](https://github.com/changkong66/CyberControl/actions/runs/29888873754), 8/8
- Gate C harness PR: [#38](https://github.com/changkong66/CyberControl/pull/38),
  Squash Merge `63d62f071176185da33c195dbdf682186b3e8c9e`
- Gate C failed-evidence PR: [#39](https://github.com/changkong66/CyberControl/pull/39),
  Squash Merge `865735015f6600f88d79b34ddbe7ba06e635f72e`
- PR #39 push CI: [Run 30098903881](https://github.com/changkong66/CyberControl/actions/runs/30098903881), 8/8
- PR #39 pull-request CI: [Run 30098946720](https://github.com/changkong66/CyberControl/actions/runs/30098946720), 8/8
- PR #39 post-merge main CI: [Run 30099327555](https://github.com/changkong66/CyberControl/actions/runs/30099327555), 8/8
- Gate C remediation PR: [#40](https://github.com/changkong66/CyberControl/pull/40),
  Squash Merge `8c204342d46cdd8bf134b3978968f41b81e239e9`
- PR #40 push CI: [Run 30125197208](https://github.com/changkong66/CyberControl/actions/runs/30125197208), 8/8
- PR #40 pull-request CI: [Run 30125230776](https://github.com/changkong66/CyberControl/actions/runs/30125230776), 8/8
- PR #40 post-merge main CI: [Run 30125601140](https://github.com/changkong66/CyberControl/actions/runs/30125601140), 8/8
- Gate C isolated-volume runner PR:
  [#41](https://github.com/changkong66/CyberControl/pull/41), Squash Merge
  `efa5ff159fad49ac3e16f4f11f90499a3e7ab61c`
- PR #41 push CI: [Run 30126517607](https://github.com/changkong66/CyberControl/actions/runs/30126517607), 8/8
- PR #41 pull-request CI: [Run 30126539422](https://github.com/changkong66/CyberControl/actions/runs/30126539422), 8/8
- PR #41 post-merge main CI: [Run 30126848516](https://github.com/changkong66/CyberControl/actions/runs/30126848516), 8/8
- Gate C second remediation PR:
  [#47](https://github.com/changkong66/CyberControl/pull/47), Squash Merge
  `7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8`
- PR #47 push CI: [Run 30157996109](https://github.com/changkong66/CyberControl/actions/runs/30157996109), 8/8
- PR #47 pull-request CI: [Run 30158060313](https://github.com/changkong66/CyberControl/actions/runs/30158060313), 8/8
- PR #47 post-merge main CI: [Run 30158839398](https://github.com/changkong66/CyberControl/actions/runs/30158839398), 8/8
- Gate C third remediation PR:
  [#50](https://github.com/changkong66/CyberControl/pull/50), Squash Merge
  `01595ae2634cb8114dfb9c591114048cba3864fd`
- PR #50 push CI: [Run 30171031219](https://github.com/changkong66/CyberControl/actions/runs/30171031219), 8/8
- PR #50 pull-request CI: [Run 30171054312](https://github.com/changkong66/CyberControl/actions/runs/30171054312), 8/8
- PR #50 post-merge main CI: [Run 30171222537](https://github.com/changkong66/CyberControl/actions/runs/30171222537), 8/8
- Frontend identity/i18n PR: [#30](https://github.com/changkong66/CyberControl/pull/30)
- Evidence PR: [#32](https://github.com/changkong66/CyberControl/pull/32)
- Alembic head: `20260720_0010`
- Historical migrations `0001` through `0009`: unchanged
- Gate B mainline report: [phase7-c3-mainline-replay.json](evidence/phase7-c3-mainline-replay.json)
- Gate B internal report SHA256:
  `53097324fa556c593ed63d3721a9a3e9509a1088d5ef820ca18df954e5d3a18b`
- Gate B report file SHA256:
  `de6fc5d9a99dcdbaba261351df6be53be732191c67146f5a3694015c6d486421`
- Artifact manifest SHA256:
  `0051e36d9f0da848a14e071a19b50551714bd171a6948ac6b8fe0d76d264e212`
- PostgreSQL environment SHA256:
  `eac9258d33c9cde87e3d451d736513248d953fe37e513532c4ced73987614e9e`

## Closure Delivered

### Identity And Account Surfaces

- Email and E.164 phone registration are available without creating a second
  identity authority.
- Keycloak remains the only password, password-hash and OIDC subject authority.
- Registration uses verification challenges, payload-aware idempotency and
  standard anti-enumeration responses.
- Profile updates and verified contact changes use the frozen backend APIs and
  expected-version conflict handling.
- Tenant account administration is scope guarded; a learner receives HTTP 403.
- Account recovery delegates to Keycloak and does not introduce an application
  password reset store.
- OIDC state remains session scoped. Browser local storage contains no Token.
- The frontend sends no `X-Tenant-ID`, `X-Subject-Ref`, role or scope identity
  headers.

### Three-Language Workbench

- Application locales: `zh-CN`, `zh-TW`, `en-US`.
- Keycloak locale handoff maps application locale to `ui_locales`.
- Login, registration, account profile, tenant administration, navigation,
  validation, error and empty-state text use the locale catalog.
- Runtime browser inspection rendered Simplified Chinese, Traditional Chinese
  and English with zero console errors and zero warnings.
- This acceptance does not claim that historical academic content or generated
  teaching material has been translated.

### Frontend Runtime Boundary

- API Envelopes and response bodies are validated against generated CSP-safe
  validators.
- Idempotency keys are reused only for identical retries and rotate when the
  request payload changes.
- Passwords, codes, Tokens and contact PII are redacted from client diagnostics.
- The frontend runtime image runs as `65532:65532`; the backend runs as
  `10001:10001`.
- The release frontend image is the hardened Nginx runtime and does not include
  the Node build environment.

## Clean External-Volume Replay

The prior acceptance stack was stopped without `--volumes`. No development
volume was deleted. The external volume `cybercontrol_release_postgres` was
confirmed unused, recreated by exact name, and restored with these labels:

- `com.cybercontrol.purpose=release-acceptance`
- `com.cybercontrol.data-class=isolated-clean-postgres`

The runner asserted initial business counts `0|0|0|0|0` and then executed:

`registration -> OIDC login -> Topic1 -> Topic2 -> Topic3 -> C1-C12 -> C12 release -> authenticated SSE`

| Stage | Result |
| --- | --- |
| Registration | email challenge verified; registration `COMPLETED` |
| OIDC | the newly registered account logged in through Keycloak |
| Authorization | new account learner-only; tenant administration returned 403 |
| Administration | tenant-admin could view the account projection |
| Topic1/Topic2 | authority graph, learner profile and local knowledge index passed |
| Topic3 | Lecturer generation `COMPLETED`; immutable Candidate persisted |
| Topic4 | 10 Claims; all required module results supported; decision `RELEASE` |
| C12 | server-derived one-time authorization committed atomically |
| Replay defense | same key returned the same publication; changed replay returned 409 |
| Final state | `RELEASED` |
| SSE | durable replay and authenticated Bearer stream passed |

Immutable identifiers for this replay:

- Registration: `c5bf41c3-2345-4424-abef-2906c80d866f`
- Account: `8a0b37b3-fae1-4ff3-93ef-0e718ef7c2ad`
- Candidate: `686141c0-47e6-5bd3-88f1-45089eb7bd2e`
- Verification: `c8542f23-8f67-5391-b398-1bcfee06aeb1`
- Report: `6f816b75-d170-5e78-a013-bc5e07ea3d70`
- Authorization: `b8c962de-61ac-584e-b019-b005e4d00066`
- Publication batch: `9b4c4763-0581-5b70-af40-1f67a75dac44`
- Public event: `e7b97911-36ee-53d1-a9ef-21095f098dac`


## Gate C Failed Evidence

The formal Gate C run was executed from clean protected-main source 63d62f071176185da33c195dbdf682186b3e8c9e
with a fresh Gate C PostgreSQL volume and real Keycloak-issued Tokens. It reached
2,000 active authenticated streams for 1,804 seconds on a single host, but failed
the frozen acceptance checks below.

| Check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Connection success rate | 0.992556 | >= 0.995 | FAIL |
| Reconnect/replay success | 0.985222 | >= 0.999 | FAIL |
| Committed event loss | 590 | 0 | FAIL |
| Duplicate replay suppression | 88/100 | all | FAIL |
| Publisher failures | 1 | 0 | FAIL |
| Outbox lag p95/p99 ms | 10522.787 / 11662.747 | <= 2000 / <= 5000 | FAIL |
| Post-ramp memory ratio | 1.933333 | <= 1.10 | FAIL |

Controls that passed in the same 2,000-stream stage include zero HTTP 5xx, zero
cross-tenant leakage, zero duplicate final render, zero Outbox DEAD, zero pool
acquisition timeout, no OOM or unplanned restart, and delivery latency p95/p99
of 965 ms / 1490 ms.

Evidence files:

- Summary: [phase7-gate-c-summary.json](evidence/phase7-gate-c-summary.json)
- Report: [phase7-gate-c-report.md](evidence/phase7-gate-c-report.md)
- Failure analysis: [phase7-gate-c-failure-analysis.md](evidence/phase7-gate-c-failure-analysis.md)
- Manifest: [phase7-gate-c-evidence-manifest.json](evidence/phase7-gate-c-evidence-manifest.json)
- Database evidence: [phase7-gate-c-database-evidence.json](evidence/phase7-gate-c-database-evidence.json)
- Evidence package metadata: [phase7-gate-c-package.json](evidence/phase7-gate-c-package.json)

The raw evidence package is retained as a GitHub prerelease asset at
https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-failed-20260724-63d62f0/gate-c-20260724T120822Z-63d62f071176-failed-evidence-v1.zip and outside Git as
gate-c-20260724T120822Z-63d62f071176-failed-evidence-v1.zip with SHA256 ed3e3357f2a54368513cc0364416202d9fb2a086db95f5346184f72bb7b5d48c and
1913634 bytes. The generated manifest and finalization scan
record no JWT-like secrets and no remaining secrets directory.

## Gate C Remediation Rerun Evidence

The unchanged Gate C workload was rerun from clean protected-main source
`efa5ff159fad49ac3e16f4f11f90499a3e7ab61c`, tree
`6378f7c2ba11e20dce1c3c728d868e2aed489e60`, with real Keycloak-issued
Tokens and fresh volume `cybercontrol_gate_c_rerun_efa5ff1_20260725`. The
`smoke-20`, `ramp-200`, `ramp-500` and `ramp-1000` stages passed. The final stage
reached 2,000 active streams for 1,804 seconds but failed the frozen checks
below.

| Check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Connection success rate | 0.989120 | >= 0.995 | FAIL |
| Reconnect/replay success | 0.978474 | >= 0.999 | FAIL |
| Committed event loss | 350 | 0 | FAIL |
| Duplicate replay suppression | 100/100 | all | PASS |
| Publisher failures | 0 | 0 | PASS |
| Delivery latency p95/p99 ms | 1183 / 1805 | <= 1000 / <= 3000 | FAIL / PASS |
| Outbox lag p95/p99 ms | 13703.788 / 14728.932 | <= 2000 / <= 5000 | FAIL |
| Post-ramp memory ratio | 1.660323 | <= 1.10 | FAIL |

Controls that remained successful include zero HTTP 5xx, zero unexpected
disconnects, zero duplicate final render, zero cross-tenant leakage, zero
invalid cursor acceptance, zero Outbox `DEAD`, zero pool acquisition timeout,
zero OOM or unplanned restart, host CPU p95/max of 48.5%/61.4%, and 74/74
tenant tables with FORCE RLS.

The first remediation improved duplicate replay suppression from 88/100 to
100/100, removed the publisher failure and reduced event loss and retained
memory, but did not satisfy Gate C. Coordinated shutdown logs still contain
`aclose(): asynchronous generator is already running`, and one SQLAlchemy
connection termination recorded `CancelledError`.

Current rerun evidence files:

- Summary: [phase7-gate-c-rerun-summary.json](evidence/phase7-gate-c-rerun-summary.json)
- Report: [phase7-gate-c-rerun-report.md](evidence/phase7-gate-c-rerun-report.md)
- Failure analysis: [phase7-gate-c-rerun-failure-analysis.md](evidence/phase7-gate-c-rerun-failure-analysis.md)
- Manifest: [phase7-gate-c-rerun-evidence-manifest.json](evidence/phase7-gate-c-rerun-evidence-manifest.json)
- Database evidence: [phase7-gate-c-rerun-database-evidence.json](evidence/phase7-gate-c-rerun-database-evidence.json)
- Environment: [phase7-gate-c-rerun-environment.json](evidence/phase7-gate-c-rerun-environment.json)
- Package metadata: [phase7-gate-c-rerun-package.json](evidence/phase7-gate-c-rerun-package.json)

The complete 1,888,203-byte raw package is retained as a GitHub prerelease
asset with SHA256
`21a0bf5e7c8ef30869bcf277582408d179b451e658f48a9c6b18f6a87bd27cb8`:
https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-rerun-failed-20260725-efa5ff1/gate-c-20260724T211823Z-efa5ff159fad-rerun-failed-evidence-v1.zip.

## Gate C Second Remediation Rerun Evidence

The unchanged Gate C workload was rerun from clean protected-main source
`7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8`, tree
`c33f8ccdb077c923d8310c869e0bf9f1096cfd5b`, with real Keycloak-issued Tokens
and fresh volume `cybercontrol_gate_c_second_7ff03ce_20260725`. The
`smoke-20`, `ramp-200`, `ramp-500` and `ramp-1000` stages passed. The final
stage reached 2,000 active streams for 1,805 seconds but failed the frozen
checks below.

| Check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Connection success rate | 0.984010 | >= 0.995 | FAIL |
| Reconnect/replay success | 0.968523 | >= 0.999 | FAIL |
| Committed event loss | 1,700 | 0 | FAIL |
| Duplicate replay suppression | 100/100 | all | PASS |
| Publisher failures | 0 | 0 | PASS |
| Delivery latency p95/p99 ms | 995 / 1721 | <= 1000 / <= 3000 | PASS |
| Outbox lag p95/p99 ms | 10277.417 / 11538.743 | <= 2000 / <= 5000 | FAIL |
| Post-ramp memory ratio | 1.480965 | <= 1.10 | FAIL |

Controls that remained successful include zero HTTP 5xx, zero unexpected
disconnects, zero duplicate final render, zero cross-tenant leakage, zero
invalid cursor acceptance, zero Outbox `DEAD`, zero pool acquisition timeout,
zero OOM or unplanned restart, host CPU p95/max of 27.6%/46.0%, and 74/74
tenant tables with FORCE RLS.

The second remediation improved Outbox latency and memory recovery relative to
the first rerun, but did not satisfy Gate C. The final-stage API log still
contains 14 `aclose(): asynchronous generator is already running` errors. The
failure remains concentrated in 2,000-stream connection admission,
reconnect/replay completion, event delivery, Outbox latency and retained API
memory; the evidence does not show a tenant-isolation, C12 or Outbox-atomicity
violation.

Current second-remediation evidence files:

- Summary: [phase7-gate-c-second-remediation-summary.json](evidence/phase7-gate-c-second-remediation-summary.json)
- Report: [phase7-gate-c-second-remediation-report.md](evidence/phase7-gate-c-second-remediation-report.md)
- Failure analysis: [phase7-gate-c-second-remediation-failure-analysis.md](evidence/phase7-gate-c-second-remediation-failure-analysis.md)
- Manifest: [phase7-gate-c-second-remediation-evidence-manifest.json](evidence/phase7-gate-c-second-remediation-evidence-manifest.json)
- Database evidence: [phase7-gate-c-second-remediation-database-evidence.json](evidence/phase7-gate-c-second-remediation-database-evidence.json)
- Environment: [phase7-gate-c-second-remediation-environment.json](evidence/phase7-gate-c-second-remediation-environment.json)
- Package metadata: [phase7-gate-c-second-remediation-package.json](evidence/phase7-gate-c-second-remediation-package.json)

The complete 1,964,853-byte raw package is retained as a GitHub prerelease
asset with SHA256
`ce0e03ced13c27ce875574f8154cc217b7ab889ead59a5f1ea743b66bbad73d6`:
https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-second-remediation-failed-20260725-7ff03ce/gate-c-20260725T134112Z-7ff03ce0c4af-second-remediation-failed-evidence-v1.zip.

## Gate C Third Remediation Rerun Evidence

The unchanged workload was rerun from clean protected-main source
`01595ae2634cb8114dfb9c591114048cba3864fd`, tree
`e319baaec6f1ba40e4d4069b6e0f78bf37b27bb0`, with real Keycloak-issued Tokens
and fresh volume `cybercontrol_gate_c_third_20260725t192105z`. The 20, 200,
500 and 1,000 connection stages passed. The final stage sustained 2,000 active
authenticated streams for 1,804 seconds but still failed frozen controls.

| Check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Connection success rate | 0.990099 | >= 0.995 | FAIL |
| Reconnect/replay success | 0.980392 | >= 0.999 | FAIL |
| Committed event loss | 1,350 | 0 | FAIL |
| Delivery latency p95/p99 ms | 1830 / 3267 | <= 1000 / <= 3000 | FAIL |
| Outbox lag p95/p99 ms | 12149.778 / 14295.416 | <= 2000 / <= 5000 | FAIL |
| Post-ramp memory ratio | 1.388368 | <= 1.10 | FAIL |

The third remediation eliminated the prior `aclose(): asynchronous generator is
already running` shutdown error. It did not meet the remaining reliability or
latency thresholds: 40 of 4,040 connection attempts failed, the 100
duplicate-replay clients ended behind the final committed ordinal, and the final
recovery sample still retained 17 subscribers, 82 queued events and 1,085 replay
cache events. Zero cross-tenant leakage, duplicate final render, HTTP 5xx,
Outbox `DEAD`, pool-acquisition timeout, OOM and unplanned restart controls
remained intact.

Third-remediation evidence files:

- Summary: [phase7-gate-c-third-remediation-summary.json](evidence/phase7-gate-c-third-remediation-summary.json)
- Report: [phase7-gate-c-third-remediation-report.md](evidence/phase7-gate-c-third-remediation-report.md)
- Failure analysis: [phase7-gate-c-third-remediation-failure-analysis.md](evidence/phase7-gate-c-third-remediation-failure-analysis.md)
- Manifest: [phase7-gate-c-third-remediation-evidence-manifest.json](evidence/phase7-gate-c-third-remediation-evidence-manifest.json)
- Database evidence: [phase7-gate-c-third-remediation-database-evidence.json](evidence/phase7-gate-c-third-remediation-database-evidence.json)
- Environment: [phase7-gate-c-third-remediation-environment.json](evidence/phase7-gate-c-third-remediation-environment.json)
- Package metadata: [phase7-gate-c-third-remediation-package.json](evidence/phase7-gate-c-third-remediation-package.json)

The complete 3,502,256-byte raw package is retained as a GitHub prerelease
asset with SHA256
`027e4c47e2ef10b381a7e48b0b342eebd54f40f8b4fca259f35216917f4a3403`:
https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-third-remediation-failed-20260725-01595ae/gate-c-20260725T192105Z-01595ae2634c-third-remediation-failed-evidence-v1.zip.

## Gate C Fourth Remediation Rerun Evidence

PR #52 merged the fourth remediation into protected main at
`97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504`, tree
`bad6b0f9e7008b934a54681f9f304a786ee9afe7`. Push Run 30195808808 and
pull-request Run 30195810215 passed 8/8. Protected-main Run 30196139462
attempt 2 also passed 8/8; attempt 1 failed while the runner pulled the
PostgreSQL service image and did not establish a product-test failure.

After Docker Desktop and the D-drive capacity gate recovered, the unchanged
formal workload used real Keycloak Tokens, Compose project
`cybercontrol-gate-c-97bfa5f-20260808t0840z` and fresh PostgreSQL volume
`cybercontrol_gate_c_97bfa5f_20260808t0840z`. The 20, 200 and 500 connection
stages passed. The 1,000 connection stage sustained 1,000 active streams for
603 seconds but failed frozen controls, so the fail-fast harness did not run
the 2,000 stage or recovery observation.

| Check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Delivery latency p95/p99 ms | 1631 / 6132 | <= 1000 / <= 3000 | FAIL |
| Outbox `DEAD` | 2 | 0 | FAIL |
| Outbox lag p95/p99 ms | 6292.587 / 8712.164 | <= 2000 / <= 5000 | FAIL |

Connection success and reconnect/replay success remained `1.0`; committed
event loss, duplicate final render, cross-tenant leakage, HTTP 5xx, pool
acquisition timeout, OOM and unplanned restart remained zero. Terminal
PostgreSQL evidence reports 74/74 FORCE RLS tables and migration head
`20260720_0010`. Both DEAD rows are `topic3.workflow.finalized` events that
exhausted 3/3 attempts with `LIYAN-AUTH-FORBIDDEN`. This proves an authorization
failure in the durable finalized-event delivery path; it does not yet identify
which trusted-context boundary is defective.

Fourth-remediation evidence files:

- Summary: [phase7-gate-c-fourth-remediation-summary.json](evidence/phase7-gate-c-fourth-remediation-summary.json)
- Report: [phase7-gate-c-fourth-remediation-report.md](evidence/phase7-gate-c-fourth-remediation-report.md)
- Failure analysis: [phase7-gate-c-fourth-remediation-failure-analysis.md](evidence/phase7-gate-c-fourth-remediation-failure-analysis.md)
- Manifest: [phase7-gate-c-fourth-remediation-evidence-manifest.json](evidence/phase7-gate-c-fourth-remediation-evidence-manifest.json)
- Database evidence: [phase7-gate-c-fourth-remediation-database-evidence.json](evidence/phase7-gate-c-fourth-remediation-database-evidence.json)
- Environment: [phase7-gate-c-fourth-remediation-environment.json](evidence/phase7-gate-c-fourth-remediation-environment.json)
- Package metadata: [phase7-gate-c-fourth-remediation-package.json](evidence/phase7-gate-c-fourth-remediation-package.json)

The complete 1,881,710-byte raw package is retained as a GitHub prerelease
asset with SHA256
`9b2c4c116752197bf10dd1bc9d29409e59bdca1eca7be3cd4a0df1d1bef26f8d`:
https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-fourth-remediation-failed-20260808-97bfa5f/gate-c-20260808T083601Z-97bfa5fef7e1-fourth-remediation-failed-evidence-v1.zip.
The immutable ZIP's generated Markdown report contains control characters and
unexpanded PowerShell expressions. Its raw metrics and internal manifest remain
unchanged; the repository report is a disclosed normalized derivative of the
immutable summary and PostgreSQL evidence JSON.
Independent failure-evidence PR
[#55](https://github.com/changkong66/CyberControl/pull/55) is the current archive
closure and does not change the failed Gate C decision.


## Source And Runtime Fingerprints

- Compose config SHA256: `753f194f5d0863270e88db16c7120845bd3ccfa741075edfca2a99fba582657f`
- `uv.lock` SHA256: `a8785433e7f7f5889cca945ebc445f432e352e281caf57bd84b117a0cbb56ecb`
- `frontend/pnpm-lock.yaml` SHA256: `3deaa86d71b429a38db5eb2d99db110794448acf2c6958befca5d369b717b295`
- Backend image: `sha256:2b8576edf35d31903b0deecf3c1a3ad8f045a92f405e5c6408cf87cf719c344a`
- Frontend image: `sha256:bdb772e9172bf7f59607bf95ca2d20deab8e1019709419176df99e12fca8b5f2`
- Mock Provider image: `sha256:beadb8d8873079e74c72716e6dd53fd23d437a5f6dd2d7202516c3218260ab27`
- Trivy findings at all severities: backend 0, frontend 0, Mock Provider 0

## Database Invariants

- Tenant tables with `tenant_id`: 74
- Tables with RLS and FORCE RLS: 74
- Append-only triggers: 57
- Audit hash-chain breaks: 0
- Outbox `DEAD`: 0
- Outbox `PENDING` or `CLAIMED`: 0
- Outbox `PUBLISHED`: 29
- Foreign-tenant visible Topic4 verifications: 0
- Foreign-tenant visible identity accounts: 0
- Plaintext contact matches in encrypted identity columns: 0
- Authorization consumptions: exactly 1
- Committed publication batches: exactly 1
- Public publication stream events: exactly 1

## Quality And Security

| Gate | Current result |
| --- | --- |
| Ruff and frozen contract drift | passed |
| Python/real PostgreSQL/real Keycloak suite | 680 passed, 1 skipped |
| Python coverage | 92.14%; hard threshold 90% |
| Python observation target | historical 91.19%; met locally |
| Vitest | 72 passed |
| Frontend coverage | 89.12% statements, 81.79% branches, 83.79% functions, 92.38% lines |
| Playwright Chromium | 8 passed |
| Browser runtime inspection | three locales rendered; zero console errors/warnings |
| Go fmt/vet/race/test/build | passed |
| Fourth remediation push/PR/main CI | 8/8 / 8/8 / 8/8 |
| Python and Node dependency audit | no known vulnerabilities |
| Gitleaks | local and remote history/worktree gates passed |
| Runtime Trivy | 0 findings at all severities for all three release images |
| SBOM and license policy | passed |

The explicit Python skip is not represented as a pass. The third-remediation
quality result is evidence for code readiness only; it does not override the
failed formal 2,000-stream Gate C controls.

## Phase 7.4 Progress

Gate A preflight passed from clean tooling commit
`f81a31a9753055aeedcc9962362482634798801e`. It records the D-drive Docker
Desktop location, external release volume, source/lock fingerprints, image
digests, network topology and host resource limits without storing container
environment values.

Gate B materialized a 100,000-record deterministic synthetic performance corpus
at `D:\CyberControlAcceptance\phase7\datasets\phase7-c2-synthetic-retrieval-performance.v1.jsonl`.
Its SHA256 is `12614d0eb5a59dccf841d1ef8479efec905fa7cff3d7f4d5f6214e9fe9dd4393`.
The corpus is eligible only for retrieval performance measurements. It cannot be
used to claim academic accuracy, hallucination rates, or breadth of coverage.

Gate B now contains 72 licensed academic records, balanced as 24 `SUPPORTED`,
24 `CONTRADICTED`, and 24 `INSUFFICIENT_EVIDENCE`. The exact facts, source
ledger and review policy are SHA256-bound to the named owner-review decision.
The review packet explicitly discloses the single-maintainer conflict and does
not claim independent institutional peer review.

ADR-0013 adds `C3AcademicHandlerV2` and `SemanticClaimVerifierV2` as explicit
compatibility extensions. The default `C3AcademicHandler` and
`ClaimFactVerifier` retain v1 behavior and the artifact schema remains
`c3-academic-finding.v1`. Runtime inputs contain only `ClaimV1` and immutable
`EvidenceRefV1`; fact IDs, topic labels, expected outcomes and reviewer
rationales are not available to product logic.

The historical local Gate B run is retained at
[phase7-c3-accuracy.json](evidence/phase7-c3-accuracy.json). The authoritative
mainline replay is bound to source commit
`7e2a1d7cc3efc55ce27044e10959c4f5889a85da` and tree
`c9821405359f59fee9fb993873ed3ba7f55e8b00`. It used PostgreSQL 16.14 on a new
isolated volume with `liyans_app` and `liyans_migrator` both non-superuser and
without `BYPASSRLS`. Accuracy was 72/72; all three class precision/recall values
and abstention accuracy were `1.0`; missing and nondeterministic results were
zero; cross-tenant visibility was zero; changed-content replay was rejected.

PR #34 passed push Run 29886312423 and pull-request Run 29886314403. After it
was Squash Merged, PR #35 was retargeted to `main`, passed push Run 29886959510
and pull-request Run 29886962210, and was Squash Merged. The resulting main
passed Run 29887219266. Each run completed all eight jobs successfully. The
clean-source Gate B replay then verified 86 artifacts totaling 360,284 bytes.
The formal replay used neither the development database nor
`cybercontrol_release_postgres`; metadata for the release volume was identical
before and after, and the temporary replay container and volume were removed.

## Current Boundary

Frontend identity, account administration, three-language workbench, Gate B
mainline acceptance, the Gate C harness and four remediation implementations
are complete on protected main. The current evidence archive is merged at
`40c8a4c076b59d9c9fd3384454df7f4eab9a6f98`, tree
`071d7804d7c465153b4c17b84d2a1a0a8ecfebd3`; protected-main Run 31255915622
completed all eight jobs successfully. The fourth formal Gate C replay remains
bound to evaluated source `97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504`, tree
`bad6b0f9e7008b934a54681f9f304a786ee9afe7`, and failed at `ramp-1000`;
`gate-2000` was not executed. Gate D-G and unrelated feature development remain
locked.

PR #42 resolved GHSA-mh99-v99m-4gvg in the frontend development dependency
chain and passed push Run 30134676485, pull-request Run 30134728232 and main
Run 30134940349. PR #44 then archived the immutable failed-rerun evidence and
passed push Run 30135705832, pull-request Run 30135721929 and protected-main
Run 30135914377. Each run completed 8/8 jobs successfully; this documentation
closure does not reinterpret the failed Gate C thresholds as accepted. PR #45
synchronized that archive state and passed push Run 30136239290, pull-request
Run 30136252893 and protected-main Run 30136427166, again with 8/8 successful.

PR #47 delivered the second remediation at
`7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8` after push Run 30157996109,
pull-request Run 30158060313 and protected-main Run 30158839398 each passed 8/8.
PR #48 then archived the immutable second-remediation failure evidence at
`a2834c4c541a7b752e8f38c5cb5449af1f08d504` after push Run 30163755928 and
pull-request Run 30163777964 passed 8/8. Its first protected-main attempt
encountered a Docker BuildKit image-pull timeout and one timing-sensitive
PostgreSQL SSE notification assertion; rerunning the unchanged commit as
attempt 2 completed protected-main Run 30163981110 with 8/8 jobs. This rerun
does not alter the Gate C failure result. PR #50 then delivered the third
remediation at `01595ae2634cb8114dfb9c591114048cba3864fd` after push Run
30171031219, pull-request Run 30171054312 and protected-main Run 30171222537
each passed 8/8. It removed the asynchronous-generator close error but did not
satisfy the frozen 2,000-stream continuity, delivery, Outbox or memory controls.
PR #52 then merged the fourth remediation after push Run 30195808808 and
pull-request Run 30195810215 passed 8/8. Protected-main Run 30196139462 attempt
2 passed 8/8. Its fresh-volume replay passed through 500 streams, then failed
at 1,000 streams because delivery p95/p99 exceeded the frozen limit and two
`topic3.workflow.finalized` Outbox events became `DEAD` with
`LIYAN-AUTH-FORBIDDEN`. No Gate D work is authorized.

New advisory data initially blocked PR #55 on `cryptography`, `undici`,
`fast-uri`, `brace-expansion`, `nanoid` and `postcss`. Independent security PR
#56 patched those dependencies and passed push Run 31255259498, pull-request
Run 31255260722 and protected-main Run 31255474059 at 8/8. PR #55 then passed
push Run 31255692354 and pull-request Run 31255694689 at 8/8, Squash Merged as
`40c8a4c076b59d9c9fd3384454df7f4eab9a6f98`, and passed protected-main Run
31255915622 at 8/8. This archive closure does not change the Gate C failure.

## Remaining Release Blockers

1. Complete a fifth scoped remediation PR for the
   `topic3.workflow.finalized` Outbox authorization failure and the remaining
   delivery/Outbox latency; do not bypass authorization or change the workload
   or frozen thresholds.
2. Add deterministic unit and real PostgreSQL regressions for trusted-context
   propagation, retry/DEAD behavior, partition ordering and 1,000-stream
   delivery latency, then require 8/8 push, pull-request and protected-main CI.
3. Rerun Gate C from that new main baseline and another fresh isolated
   PostgreSQL volume. The 2,000 stage remains unproven until the lower stages
   pass in the same formal run.
4. Only after Gate C is accepted, complete a minimum eight-hour soak across
   generation, verification, review, release and SSE.
5. Only after Gate D is accepted, restore a PostgreSQL backup into an
   independent instance and measure RPO/RTO.
6. Complete database/index/OIDC/Provider fail-closed drills, sealed Provider
   acceptance, production deployment, cross-browser/WCAG and PII lifecycle
   acceptance.

Only after every blocker has reproducible evidence may the state advance to
SYSTEM_ACCEPTED.
