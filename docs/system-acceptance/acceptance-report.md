# CyberControl System Acceptance Report

## Decision

Protected-main Gate C remediation baseline
`efa5ff159fad49ac3e16f4f11f90499a3e7ab61c` remains a **release candidate**, but
Gate C is **not accepted**. PR #40 merged the first SSE and Outbox remediation,
and PR #41 enforced a fresh, explicitly named PostgreSQL volume for formal Gate
C execution. Their protected-main CI runs completed all eight Release Quality
Gate jobs successfully. The unchanged Gate C workload was then rerun from this
clean main baseline and a fresh isolated volume; the 2,000-stream stage still
failed frozen reliability, latency and recovery thresholds.

Formal state:
PHASE7_GATE_C_FAILED_GATE_D_LOCKED.

The project is not SYSTEM_ACCEPTED. Gate A and Gate B remain accepted. Both the
initial Gate C failure and the post-remediation rerun are preserved as evidence;
Gate D, Gate E, Gate F and Gate G remain serially locked. No single-host
production capacity claim is permitted.

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
| Python deterministic suite | 556 passed, 1 skipped, 73 deselected |
| Standard PostgreSQL suite | 628 passed, 2 skipped |
| Python coverage | 91.74%; hard threshold 90% |
| Python observation targets | prior current record 91.58% and historical 91.19%; both met locally |
| Vitest | 72 passed |
| Frontend coverage | 89.12% statements, 81.79% branches, 83.79% functions, 92.38% lines |
| Playwright Chromium | 8 passed |
| Browser runtime inspection | three locales rendered; zero console errors/warnings |
| Go fmt/vet/race/test/build | passed |
| Python and Node dependency audit | no known vulnerabilities |
| Gitleaks | local and remote history/worktree gates passed |
| Runtime Trivy | 0 findings at all severities for all three release images |
| SBOM and license policy | passed |

The two standard-suite skips are explicitly reported and are not represented as
passes. They cover the Docker database-restart probe, which requires explicit
operator enablement, and one Windows symbolic-link capability limitation. A
separate complete regression with the database-restart probe enabled passed 627
tests with one platform skip at 91.65% coverage before the final local gate.

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
mainline acceptance, the Gate C harness, the first failed Gate C archive, the
first remediation, the isolated-volume runner, the supply-chain audit fix and
the failed rerun archive are complete on protected main through PR #44. The
current-state snapshot is parent-bound because a Git commit cannot contain its
own final SHA. Its verified parent main is
`5aff4377d2be2468ca62200358b46fbade4834d2`; Run 30136427166 completed all
eight jobs successfully. The live protected-branch head is authoritative for
the status-only commit containing this paragraph. The formal post-remediation
Gate C rerun still failed. Gate D-G and unrelated feature development remain
locked.

PR #42 resolved GHSA-mh99-v99m-4gvg in the frontend development dependency
chain and passed push Run 30134676485, pull-request Run 30134728232 and main
Run 30134940349. PR #44 then archived the immutable failed-rerun evidence and
passed push Run 30135705832, pull-request Run 30135721929 and protected-main
Run 30135914377. Each run completed 8/8 jobs successfully; this documentation
closure does not reinterpret the failed Gate C thresholds as accepted. PR #45
synchronized that archive state and passed push Run 30136239290, pull-request
Run 30136252893 and protected-main Run 30136427166, again with 8/8 successful.

The first remediation's full local quality gate remains valid evidence: 630
Python tests collected, 628 passed, two explicit skips, 91.74% coverage, frozen
contracts unchanged, clean Trivy and Gitleaks results, and no migration or Gate
C threshold changes. It is no longer described as PR-pending. The next allowed
work is a second scoped remediation addressing coordinated generator close,
reconnect/replay completion, Outbox latency and post-ramp memory recovery.

## Remaining Release Blockers

1. Complete a second scoped remediation PR for coordinated async-generator
   close ownership, reconnect/replay completion, Outbox latency and retained
   API memory; do not change the workload or frozen thresholds.
2. After 8/8 push, pull-request and protected-main CI, rerun Gate C from that
   new main baseline and another fresh isolated PostgreSQL volume.
3. Only after Gate C is accepted, complete a minimum eight-hour soak across
   generation, verification, review, release and SSE.
4. Only after Gate D is accepted, restore a PostgreSQL backup into an
   independent instance and measure RPO/RTO.
5. Complete database/index/OIDC/Provider fail-closed drills, sealed Provider
   acceptance, production deployment, cross-browser/WCAG and PII lifecycle
   acceptance.

Only after every blocker has reproducible evidence may the state advance to
SYSTEM_ACCEPTED.
