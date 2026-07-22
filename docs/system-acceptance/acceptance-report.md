# CyberControl System Acceptance Report

## Decision

Protected `main` revision `7e2a1d7cc3efc55ce27044e10959c4f5889a85da`
is accepted as a **release candidate**. PR #34 archived the hash-bound academic
Gate B evidence and PR #35 added the ADR-0013 C3 semantic verifier v2 while
preserving v1 behavior. Both changes passed their push and pull-request Release
Quality Gates at 8/8 before protected Squash Merge. The resulting main revision
then passed Release Quality Gates Run 29887219266 at 8/8.

Formal state:
`PHASE7_GATE_B_MAINLINE_ACCEPTED_GATE_C_READY`.

The project is not `SYSTEM_ACCEPTED`. Gate A and Gate B are accepted. The final
Gate B replay was executed from the merged protected-main source and tree, using
a fresh isolated PostgreSQL 16 volume, restricted roles and clean source. It
classified all 72 records correctly, produced zero unsafe
`CONTRADICTED -> SUPPORTED` decisions, passed all RLS/replay controls, verified
86 content-addressed artifacts, left `cybercontrol_release_postgres` untouched,
and removed its temporary container and volume. Gate C is the only newly
unlocked execution gate; Gates D-G remain serially locked.

## Evaluated Baseline

- Protected `main` and evaluated Gate B source:
  `7e2a1d7cc3efc55ce27044e10959c4f5889a85da`
- Protected-main and evaluated Gate B tree:
  `c9821405359f59fee9fb993873ed3ba7f55e8b00`
- Gate B evidence PR: [#34](https://github.com/changkong66/CyberControl/pull/34),
  Squash Merge `412085e1586e3d497e5e6f944d4f34e258896d8b`
- PR #34 push CI: [Run 29886312423](https://github.com/changkong66/CyberControl/actions/runs/29886312423), 8/8
- PR #34 pull-request CI: [Run 29886314403](https://github.com/changkong66/CyberControl/actions/runs/29886314403), 8/8
- C3 remediation PR: [#35](https://github.com/changkong66/CyberControl/pull/35),
  Squash Merge `7e2a1d7cc3efc55ce27044e10959c4f5889a85da`
- PR #35 retargeted push CI: [Run 29886959510](https://github.com/changkong66/CyberControl/actions/runs/29886959510), 8/8
- PR #35 retargeted pull-request CI: [Run 29886962210](https://github.com/changkong66/CyberControl/actions/runs/29886962210), 8/8
- Current protected-main CI: [Run 29887219266](https://github.com/changkong66/CyberControl/actions/runs/29887219266), 8/8
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
| Python deterministic suite | 453 passed, 1 skipped, 70 deselected |
| Standard PostgreSQL suite | 559 passed, 4 skipped |
| Python coverage | 90.94%; hard threshold 90% |
| Historical Python observation | 91.19%; not met by the standard-gate run |
| Vitest | 72 passed |
| Frontend coverage | 89.12% statements, 81.79% branches, 83.79% functions, 92.38% lines |
| Playwright Chromium | 8 passed |
| Browser runtime inspection | three locales rendered; zero console errors/warnings |
| Go fmt/vet/race/test/build | passed |
| Python and Node dependency audit | no known vulnerabilities |
| Gitleaks | local and remote history/worktree gates passed |
| Runtime Trivy | 0 findings at all severities for all three release images |
| SBOM and license policy | passed |

The four standard-suite skips are explicitly reported and are not represented
as passed tests. The latest PostgreSQL integration result and coverage value are
the PR #35 clean-commit observation recorded in that protected PR.

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

Frontend identity, account administration, three-language workbench and Gate B
mainline acceptance are complete. This current-state evidence must first pass a
protected evidence PR. After that archive merges, Gate C may execute the 2,000
authenticated SSE load plan. Gates D-G and unrelated feature development remain
locked.

## Remaining Release Blockers

1. Merge this current-state Gate B replay archive through a protected evidence
   PR with 8/8 green checks.
2. Raise the current 90.94% Python coverage toward the 91.19% historical
   observation or record a reviewed disposition; the 90% hard gate must not be
   lowered.
3. Execute 2,000 authenticated SSE connections with
   reconnect, cursor recovery,
   duplicate suppression, slow-consumer and tenant-isolation evidence.
4. After Gate C is accepted, complete a minimum eight-hour soak across
   generation, verification, review,
   release and SSE.
5. After Gate D is accepted, restore a PostgreSQL backup into an independent
   instance and measure RPO/RTO.
6. After Gate E is accepted, complete database/index/OIDC/Provider failure
   drills and verify fail-closed behavior.
7. Complete sealed Provider, production deployment, TLS/secrets/monitoring,
   cross-browser/WCAG and PII retention/export/correction/deletion acceptance.

Only after every blocker has reproducible evidence may the state advance to
`SYSTEM_ACCEPTED`.
