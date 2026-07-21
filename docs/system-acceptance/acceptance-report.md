# CyberControl System Acceptance Report

## Decision

Protected `main` revision `8f0966f96dad8a6be34bd4ab11c985d001dd0185`
is accepted as a **release candidate** with the frontend identity and
internationalization scope complete. PR #30 passed both remote workflows,
merged through the protected branch, passed the merged-main workflow, and was
replayed from a newly recreated external PostgreSQL release volume.

Formal state:
`FRONTEND_IDENTITY_I18N_MAINLINE_REPLAY_ACCEPTED_FINAL_GATES_PENDING`.

The project is not `SYSTEM_ACCEPTED`. High-load SSE, long-duration soak,
independent backup/restore and disaster recovery, sealed Provider integration,
production deployment, cross-browser/WCAG and PII lifecycle evidence remain
open.

## Evaluated Baseline

- Protected `main`: `8f0966f96dad8a6be34bd4ab11c985d001dd0185`
- Source tree: `01c1705debb4b869721b9b9432ed2747064921b8`
- Frontend identity/i18n PR: [#30](https://github.com/changkong66/CyberControl/pull/30)
- Push CI: [Run 29830793779](https://github.com/changkong66/CyberControl/actions/runs/29830793779), 8/8
- Pull-request CI: [Run 29830972987](https://github.com/changkong66/CyberControl/actions/runs/29830972987), 8/8
- Protected-main CI: [Run 29831570652](https://github.com/changkong66/CyberControl/actions/runs/29831570652), 8/8
- Alembic head: `20260720_0010`
- Historical migrations `0001` through `0009`: unchanged
- Mainline evidence: [frontend-identity-i18n-mainline.json](evidence/frontend-identity-i18n-mainline.json)
- Evidence SHA256: `c61ae5e8b5b4c3a516aaf3c8ed746df6217687f963726a5ea05d2c7fae736b6e`
- Browser evidence: [frontend-identity-i18n-browser.json](evidence/frontend-identity-i18n-browser.json)

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
| Python deterministic suite | 449 passed, 1 skipped, 70 deselected |
| Standard PostgreSQL suite | 514 passed, 6 skipped |
| Python coverage | 90.57%; hard threshold 90% |
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

The six standard-suite skips are explicitly reported. They cover separately
configured Keycloak/reconciler integration, the opt-in Docker database restart
probe, and the Windows symbolic-link compatibility case. The clean-volume runner
independently exercised real Keycloak registration and OIDC login. None of these
skips is represented as a passed test.

## Current Boundary

Frontend identity, account administration and three-language workbench scope is
complete and replayed from merged main. The next phase is non-functional and
production acceptance only. Feature development, frozen migration changes and
Topic1-Topic4 semantic changes are outside that phase unless a separately
approved defect ADR proves they are necessary.

## Remaining Release Blockers

1. Merge this current-state replay evidence through protected-main gates.
2. Raise Python coverage toward the 91.19% historical observation or record a
   reviewed disposition; the 90% hard gate must not be lowered.
3. Execute 2,000 authenticated SSE connections with reconnect, cursor recovery,
   duplicate suppression, slow-consumer and tenant-isolation evidence.
4. Complete a minimum eight-hour soak across generation, verification, review,
   release and SSE.
5. Restore a PostgreSQL backup into an independent instance and measure RPO/RTO.
6. Complete database/index/OIDC/Provider failure drills and verify fail-closed behavior.
7. Complete sealed Provider, production deployment, TLS/secrets/monitoring,
   cross-browser/WCAG and PII retention/export/correction/deletion acceptance.

Only after every blocker has reproducible evidence may the state advance to
`SYSTEM_ACCEPTED`.
