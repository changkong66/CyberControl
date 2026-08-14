# CyberControl System Acceptance Report

## Decision

Protected-main Gate C eighth-remediation baseline
`4f0a7670782c5002a2da6e429c0428d8fef29153` remains a **release candidate**,
but Gate C is **not accepted**. The eighth-remediation workload completed and
stage-locally passed 20, 200, 500, 1,000 and 2,000 authenticated streams plus
the ten-minute recovery observation. The final aggregate failed the frozen
Outbox p95 and post-ramp memory-recovery controls. The last 30 recovery samples
also retained one LIVE subscriber, which violates the required lifecycle
boundary even though it is not a separate frozen finalizer check.

Formal state:
PHASE7_GATE_C_FAILED_GATE_D_LOCKED.

The project is not SYSTEM_ACCEPTED. Gate A and Gate B remain accepted. The
initial Gate C failure and all eight remediation reruns are preserved as
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
- Security dependency PR: [#56](https://github.com/changkong66/CyberControl/pull/56),
  Squash Merge `6f4a58b44ef6e30a850b50aa522b490f525215b1`
- PR #56 push CI: [Run 31255259498](https://github.com/changkong66/CyberControl/actions/runs/31255259498), 8/8
- PR #56 pull-request CI: [Run 31255260722](https://github.com/changkong66/CyberControl/actions/runs/31255260722), 8/8
- PR #56 protected-main CI: [Run 31255474059](https://github.com/changkong66/CyberControl/actions/runs/31255474059), 8/8
- Gate C fifth remediation PR:
  [#58](https://github.com/changkong66/CyberControl/pull/58), Squash Merge
  `76cd099a034a395a89b26496c0d40e0673aaa97d`
- PR #58 push CI: [Run 31264197240](https://github.com/changkong66/CyberControl/actions/runs/31264197240), 8/8
- PR #58 pull-request CI: [Run 31264254111](https://github.com/changkong66/CyberControl/actions/runs/31264254111), 8/8
- PR #58 protected-main CI: [Run 31264518015](https://github.com/changkong66/CyberControl/actions/runs/31264518015), 8/8
- Fifth-remediation failure-evidence branch:
  `codex/phase7-gate-c-fifth-rerun-failure-evidence`
- Gate C sixth remediation PR:
  [#61](https://github.com/changkong66/CyberControl/pull/61), Squash Merge
  `a6979d760701271d579776b082dabe247ac6138b`
- PR #61 push CI: [Run 31537797593](https://github.com/changkong66/CyberControl/actions/runs/31537797593), 8/8
- PR #61 pull-request CI: [Run 31538456518](https://github.com/changkong66/CyberControl/actions/runs/31538456518), 8/8
- PR #61 protected-main CI: [Run 31538917814](https://github.com/changkong66/CyberControl/actions/runs/31538917814), 8/8
- Sixth-remediation failure-evidence PR:
  [#62](https://github.com/changkong66/CyberControl/pull/62), Squash Merge
  `a1f65411e770ec843a861fd87eb9ce1834c04c4a`
- PR #62 push CI: [Run 31544016873](https://github.com/changkong66/CyberControl/actions/runs/31544016873), 8/8
- PR #62 pull-request CI: [Run 31544021134](https://github.com/changkong66/CyberControl/actions/runs/31544021134), 8/8
- PR #62 protected-main CI: [Run 31544460542](https://github.com/changkong66/CyberControl/actions/runs/31544460542), 8/8
- Gate C seventh remediation PR:
  [#64](https://github.com/changkong66/CyberControl/pull/64), Squash Merge
  `fa5b4bd92e4b56704f70b63416906a10c54e0ee1`
- PR #64 push CI: [Run 31592761559](https://github.com/changkong66/CyberControl/actions/runs/31592761559), 8/8
- PR #64 pull-request CI: [Run 31592947063](https://github.com/changkong66/CyberControl/actions/runs/31592947063), 8/8
- PR #64 protected-main CI: [Run 31593377181](https://github.com/changkong66/CyberControl/actions/runs/31593377181), 8/8
- Seventh-remediation failure-evidence PR:
  [#65](https://github.com/changkong66/CyberControl/pull/65), Squash Merge
  `4563ad4696c2cd8cd6aaec3108a287780d236293`
- PR #65 protected-main CI: [Run 31610698379](https://github.com/changkong66/CyberControl/actions/runs/31610698379), 8/8
- Gate C eighth remediation PR:
  [#66](https://github.com/changkong66/CyberControl/pull/66), Squash Merge
  `4f0a7670782c5002a2da6e429c0428d8fef29153`
- PR #66 push CI: [Run 31629029809](https://github.com/changkong66/CyberControl/actions/runs/31629029809), 8/8
- PR #66 pull-request CI: [Run 31629100666](https://github.com/changkong66/CyberControl/actions/runs/31629100666), 8/8
- PR #66 protected-main CI: [Run 31629561293](https://github.com/changkong66/CyberControl/actions/runs/31629561293), 8/8
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

## Gate C Fifth Remediation Rerun Evidence

The fifth-remediation rerun was bound to protected main
`76cd099a034a395a89b26496c0d40e0673aaa97d`, tree
`ffb7c72b3156f1dc271b5b0ec1afc2ce3f2c6870`, with real Keycloak-issued Tokens,
two tenants, twenty real subjects, a fresh PostgreSQL volume and a unique
Compose project. It passed the 20, 200 and 500 stages, then failed at 1,000
streams after 603 seconds. The 2,000-stream and recovery stages were not run.

| Check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Delivery latency p95/p99 ms | 1532 / 4985 | <= 1000 / <= 3000 | FAIL |
| Outbox lag p95/p99 ms | 5830.700 / 8434.789 | <= 2000 / <= 5000 | FAIL |
| Connection success | 1.0 | >= 0.995 | PASS |
| Reconnect/replay success | 1.0 | >= 0.999 | PASS |
| Committed event loss | 0 | 0 | PASS |
| Outbox `DEAD` | 0 | 0 | PASS |
| Cross-tenant leakage | 0 | 0 | PASS |

The measured runtime boundary was API CPU `127.604/131.840` one-core units
(p95/max), peak API file descriptors `1038`, and fail-fast closing owners `826`.
Because recovery was not executed, the closing-owner count is not a memory-leak
acceptance result. PostgreSQL evidence reports migration head `20260720_0010`,
`74/74` FORCE RLS tables, `57` append-only triggers, `103` published Outbox
rows, zero `DEAD` rows and zero foreign-tenant visibility.

Fifth-remediation evidence files:

- Summary: [phase7-gate-c-fifth-remediation-summary.json](evidence/phase7-gate-c-fifth-remediation-summary.json)
- Report: [phase7-gate-c-fifth-remediation-report.md](evidence/phase7-gate-c-fifth-remediation-report.md)
- Failure analysis: [phase7-gate-c-fifth-remediation-failure-analysis.md](evidence/phase7-gate-c-fifth-remediation-failure-analysis.md)
- Database evidence: [phase7-gate-c-fifth-remediation-database-evidence.json](evidence/phase7-gate-c-fifth-remediation-database-evidence.json)
- Environment: [phase7-gate-c-fifth-remediation-environment.json](evidence/phase7-gate-c-fifth-remediation-environment.json)
- Manifest: [phase7-gate-c-fifth-remediation-evidence-manifest.json](evidence/phase7-gate-c-fifth-remediation-evidence-manifest.json)
- Package metadata: [phase7-gate-c-fifth-remediation-package.json](evidence/phase7-gate-c-fifth-remediation-package.json)

The immutable external package is `2,047,902` bytes with SHA256
`566a65a5ac01d1eb6ec0f06a1bc85529bebcf7f53dc37c382d74dcbfa707630e`:
[download evidence package](https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-fifth-remediation-failed-20260808-76cd099/gate-c-20260808T154326Z-76cd099a034a-fifth-remediation-failed-evidence-v1.zip).
The package JWT/credential scan passed with zero hits.

## Gate C Seventh Remediation Rerun Evidence

The seventh-remediation rerun was bound to protected main
`fa5b4bd92e4b56704f70b63416906a10c54e0ee1`, tree
`a9f020fd5cceb7a094439ad4c4089b63d3b473a7`, with newly built images, real
Keycloak-issued Tokens, two tenants, twenty real subjects, a unique Compose
project and a fresh PostgreSQL volume. It executed the complete frozen workload
and the fixed ten-minute recovery observation.

| Check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Active authenticated streams | 2,000 for 1,803s | 2,000 for >=1,800s | PASS |
| Connection / reconnect success | 1.0 / 1.0 | >=0.995 / >=0.999 | PASS |
| Delivery latency p95/p99 | 781 / 990ms | <=1,000 / <=3,000ms | PASS |
| Event loss / duplicate final render | 0 / 0 | 0 / 0 | PASS |
| Cross-tenant leakage / invalid cursor acceptance | 0 / 0 | 0 / 0 | PASS |
| HTTP 5xx / unexpected disconnect | 0 / 0 | <=0.1% / <=0.5% | PASS |
| Outbox `DEAD` | 0 | 0 | PASS |
| Outbox lag p95 | 2,225.796ms | <=2,000ms | **FAIL** |
| Outbox lag p99 | 3,026.102ms | <=5,000ms | PASS |
| Post-ramp API RSS ratio | 1.492792 | <=1.10 | **FAIL** |

The API RSS first/last/peak values were `276404634 / 412614656 / 448371098`
bytes. Final subscribers, closing owners, queued events/bytes, replay buffers,
replay caches and replay tasks were all zero. API file descriptors returned
from 29 to 30 after peaking at 2,039 against a 1,048,576 limit. The API logs
contained zero `aclose()` races, tracebacks, errors, pool timeouts, OOMs or
unplanned restarts. These passed controls must not regress, but they do not
override the two failed aggregate controls.

PostgreSQL terminal evidence reports migration head `20260720_0010`, FORCE RLS
`74/74`, `57` append-only triggers, Outbox `PUBLISHED=221`, `DEAD=0`, and zero
foreign-tenant visibility. The original failed volume and the read-only-derived
forensic volume remain preserved.

Seventh-remediation evidence files:

- Summary: [phase7-gate-c-seventh-remediation-summary.json](evidence/phase7-gate-c-seventh-remediation-summary.json)
- Report: [phase7-gate-c-seventh-remediation-report.md](evidence/phase7-gate-c-seventh-remediation-report.md)
- Failure analysis: [phase7-gate-c-seventh-remediation-failure-analysis.md](evidence/phase7-gate-c-seventh-remediation-failure-analysis.md)
- Database evidence: [phase7-gate-c-seventh-remediation-database-evidence.json](evidence/phase7-gate-c-seventh-remediation-database-evidence.json)
- Environment: [phase7-gate-c-seventh-remediation-environment.json](evidence/phase7-gate-c-seventh-remediation-environment.json)
- Manifest: [phase7-gate-c-seventh-remediation-evidence-manifest.json](evidence/phase7-gate-c-seventh-remediation-evidence-manifest.json)
- Package metadata: [phase7-gate-c-seventh-remediation-package.json](evidence/phase7-gate-c-seventh-remediation-package.json)

The immutable external package is `5,337,204` bytes with SHA256
`a01a16fdfc4f50f14b0a74a234a9e5f332ab20a29451c49096b6f7901236f2fd`:
[download evidence package](https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-seventh-remediation-failed-20260812-fa5b4bd/gate-c-20260812T120720Z-fa5b4bd92e4b-seventh-remediation-failed-evidence-v1.zip).
GitHub reports the prerelease and asset as immutable, and the package
JWT/credential scan passed with zero hits.

## Gate C Eighth Remediation Rerun Evidence

The eighth-remediation rerun was bound to protected main
`4f0a7670782c5002a2da6e429c0428d8fef29153`, tree
`d79b15fce52b8a8b9afe4be361cfbcbba4c7ddc9`, with newly built images, real
Keycloak-issued Tokens, two tenants, twenty real subjects, a unique Compose
project and a fresh PostgreSQL volume. It executed the complete frozen workload
and the fixed ten-minute recovery observation.

| Check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Active authenticated streams | 2,000 for 1,804s | 2,000 for >=1,800s | PASS |
| Connection / reconnect success | 1.0 / 1.0 | >=0.995 / >=0.999 | PASS |
| Delivery latency p95/p99 | 788 / 1,042ms | <=1,000 / <=3,000ms | PASS |
| Event loss / duplicate final render | 0 / 0 | 0 / 0 | PASS |
| Cross-tenant leakage / invalid cursor acceptance | 0 / 0 | 0 / 0 | PASS |
| HTTP 5xx / unexpected disconnect | 0 / 0 | <=0.1% / <=0.5% | PASS |
| Outbox `DEAD` | 0 | 0 | PASS |
| Outbox lag p95 | 2,247.346ms | <=2,000ms | **FAIL** |
| Outbox lag p99 | 3,438.55ms | <=5,000ms | PASS |
| Post-ramp API RSS ratio | 1.393027 | <=1.10 | **FAIL** |

Container RSS first/last/peak was `264660582 / 368679322 / 435054182`
bytes. Process PSS was `300299264 -> 407353344`, USS was
`297070592 -> 404389888`, anonymous RSS was `259416064 -> 363573248`, file
RSS was unchanged and memory-map count moved only from 615 to 619.

The last 30 recovery samples continuously reported one live subscriber.
Closing owners, queued events/bytes, replay buffers/caches and replay tasks were
zero. FDs returned from 29 to 29 after peaking at 2,039. No `aclose()` race,
traceback, error, pool timeout, OOM or unplanned restart was recorded. The
remaining subscriber must be treated as a measured residual, not hidden by the
two frozen finalizer failures.

PostgreSQL terminal evidence reports migration head `20260720_0010`, FORCE RLS
`74/74`, `57` append-only triggers, Outbox `PUBLISHED=223`, terminal
`PENDING/CLAIMED/DEAD=0`, and zero foreign-tenant visibility.

Eighth-remediation evidence files:

- Summary: [phase7-gate-c-eighth-remediation-summary.json](evidence/phase7-gate-c-eighth-remediation-summary.json)
- Report: [phase7-gate-c-eighth-remediation-report.md](evidence/phase7-gate-c-eighth-remediation-report.md)
- Failure analysis: [phase7-gate-c-eighth-remediation-failure-analysis.md](evidence/phase7-gate-c-eighth-remediation-failure-analysis.md)
- Database evidence: [phase7-gate-c-eighth-remediation-database-evidence.json](evidence/phase7-gate-c-eighth-remediation-database-evidence.json)
- Environment: [phase7-gate-c-eighth-remediation-environment.json](evidence/phase7-gate-c-eighth-remediation-environment.json)
- Manifest: [phase7-gate-c-eighth-remediation-evidence-manifest.json](evidence/phase7-gate-c-eighth-remediation-evidence-manifest.json)
- Package metadata: [phase7-gate-c-eighth-remediation-package.json](evidence/phase7-gate-c-eighth-remediation-package.json)

The valid immutable external package is `5,428,919` bytes with SHA256
`b22f81bbcd42fb5dab0c9bc64891fe8b49888663ab9c0f13260b1de313802ff1`:
[download evidence package](https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-eighth-remediation-failed-20260812-4f0a767-evidence-v1/gate-c-20260812T190722Z-4f0a7670782c-eighth-remediation-failed-evidence-v1.zip).
GitHub reports Release ID `369510663` and asset ID `512034056` as immutable.
An earlier immutable empty Release, ID `369509815`, cannot be changed or
deleted and remains disclosed as an audit exception.

## Eighth-Run Source And Runtime Fingerprints

- Compose config SHA256: `177bd0296e2693087106dcf33948115eac89bf9c9cadecb466ff35e376b202f0`
- Raw run manifest SHA256: `86073d65d31a61fcf41f422ad1283fac711ca7a277edf580b38802780d6ccf68`
- `uv.lock` SHA256: `60bf4f22b50f516bebe7f734254d64617e6e08042424d09e606995be10d8cb77`
- `frontend/pnpm-lock.yaml` SHA256: `090ef1ef6a9023a905c233da400a85bf5f6af7b65833cf693c9a8c387579595c`
- API image: `sha256:7c9d1c2fe0f6b064b5bc08aa2623eabfd0d055e633f7c0d1d279126a3d943628`
- Migration image: `sha256:8cc4131b0a0b83e44ba6b496bbf8a81bfec530016ceb66be7cb7a99a9e50d006`
- Mock Provider image: `sha256:d931a03b0b116a403aac98a98df05db5f804ce15d46097cc21cf16589a9a63ee`
- PostgreSQL image: `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`
- Keycloak image: `sha256:2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0`


## Seventh-Run Source And Runtime Fingerprints

- Compose config SHA256: `0963f97984919fadea8bccdfa96d7a2064c9578c6a9d912b8f887050e954b8a6`
- `uv.lock` SHA256: `60bf4f22b50f516bebe7f734254d64617e6e08042424d09e606995be10d8cb77`
- `frontend/pnpm-lock.yaml` SHA256: `090ef1ef6a9023a905c233da400a85bf5f6af7b65833cf693c9a8c387579595c`
- API image: `sha256:1c97a7209094dda18f4cd1b7cc4cef19db8ba891bc03b45b44c259edb5255a44`
- Migration image: `sha256:faa91979d9b67bb4fbfda861b0508cf3226c418e35c77827663dab0eeec3a133`
- Mock Provider image: `sha256:8331fb41c3af6aac9ab5b6380de026128fa8a34c9f5e2a819855c6fd840d7ced`
- Gate C load image: `sha256:a196ad69da024aae07b02de8d61db895b90badf00336eaf19326701bfac6c73a`
- PostgreSQL image: `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`
- Keycloak image: `sha256:2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0`

## Seventh-Run Database Terminal State

- Migration head: `20260720_0010`
- Tenant tables with `tenant_id`: 74
- Tables with RLS and FORCE RLS: 74
- Append-only triggers: 57
- Application, dispatcher and migrator roles are non-superuser and do not have
  `BYPASSRLS`.
- Outbox `PUBLISHED`: 221
- Outbox `PENDING`, `CLAIMED` and `DEAD`: 0
- Adversarial foreign-tenant visible rows: 0

## Quality And Security

| Gate | Current result |
| --- | --- |
| Ruff and frozen contract drift | passed |
| Focused seventh-remediation tests | 92 passed; real PostgreSQL Outbox 12 passed |
| Complete Python/PostgreSQL regression | 711 passed, 4 skipped |
| Python coverage | 91.68%; hard threshold 90% |
| Python observation target | historical 91.19%; met locally |
| Vitest | 72 passed |
| Frontend coverage | 89.12% statements, 81.79% branches, 83.79% functions, 92.38% lines |
| Playwright Chromium | 8 passed |
| Browser runtime inspection | three locales rendered; zero console errors/warnings |
| Go fmt/vet/race/test/build | passed |
| Seventh remediation push/PR/main CI | 8/8 / 8/8 / 8/8 |
| Python and Node dependency audit | no known vulnerabilities |
| Gitleaks | local and remote history/worktree gates passed |
| Runtime Trivy | 0 findings at all severities for all three release images |
| SBOM and license policy | passed |

The four explicit skips are not represented as passes; they cover environment-
conditioned Keycloak, restart-probe and Windows symlink cases. The quality
result is evidence for code readiness only and does not override the failed
final Gate C controls.

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
mainline acceptance, the Gate C harness and eight remediation implementations
are complete on protected main. The current evaluated protected-main baseline
is `4f0a7670782c5002a2da6e429c0428d8fef29153`, tree
`d79b15fce52b8a8b9afe4be361cfbcbba4c7ddc9`; Run 31629561293 completed 8/8.
The eighth formal Gate C replay completed all five stages and recovery, but
failed final Outbox p95 and memory-recovery controls and retained one live
subscriber through the final 30 recovery samples. Gate D-G and unrelated
feature development remain locked.

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
31255915622 at 8/8. The fifth-remediation failure package was archived by PR
#59 after push Run 31531236238 and pull-request Run 31531270251 passed 8/8;
it Squash Merged as `ab44180176e26665692929c6b306c1f184c747ae` and protected-
main Run 31531732396 passed 8/8. PR #58 merged
the fifth remediation as `76cd099a034a395a89b26496c0d40e0673aaa97d` after
push Run 31264197240, pull-request Run 31264254111 and protected-main Run
31264518015 all completed 8/8. None of these closures changes the Gate C
failure.

PR #61 and PR #62 delivered and archived the sixth remediation through 8/8
push, pull-request and protected-main gates. PR #64 then delivered the seventh
remediation as `fa5b4bd92e4b56704f70b63416906a10c54e0ee1` after push Run
31592761559, pull-request Run 31592947063 and protected-main Run 31593377181
all passed 8/8. The complete fresh-volume replay moved every stage-local control
to pass but left the final Outbox p95 and RSS recovery controls failed.

PR #65 archived that seventh failure and passed protected-main Run 31610698379
at 8/8. PR #66 then delivered the eighth remediation as
`4f0a7670782c5002a2da6e429c0428d8fef29153`; push Run 31629029809,
pull-request Run 31629100666 and protected-main Run 31629561293 each passed
8/8. Its fresh-volume replay again passed every stage-local control but failed
Outbox p95 at 2247.346ms and RSS recovery at 1.393027. One live subscriber
remained throughout the final 30 recovery samples.

## Remaining Release Blockers

1. Complete the independent eighth-remediation failure-evidence PR through
   push and pull-request 8/8, Squash Merge and protected-main 8/8.
2. Create a ninth scoped remediation only for the measured one-live-subscriber
   owner, anonymous RSS retention and Outbox p95 tail; preserve every
   stage-local pass and frozen semantic.
3. Add deterministic subscriber-lifecycle, allocation-lifetime and real PostgreSQL Outbox-tail
   regressions, then rerun the unchanged complete Gate C workload from another
   protected-main baseline and fresh isolated PostgreSQL volume.
4. Only after Gate C is accepted, complete a minimum eight-hour soak across
   generation, verification, review, release and SSE.
5. Only after Gate D is accepted, restore a PostgreSQL backup into an
   independent instance and measure RPO/RTO.
6. Complete database/index/OIDC/Provider fail-closed drills, sealed Provider
   acceptance, production deployment, cross-browser/WCAG and PII lifecycle
   acceptance.

Only after every blocker has reproducible evidence may the state advance to
SYSTEM_ACCEPTED.
