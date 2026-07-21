# Next Stage Prompt: Frontend Identity And Three-Language Workbench

```text
# CyberControl Phase 7.3: frontend registration, account management and i18n

Execute this task only after the current identity-mainline evidence PR is merged
and its protected-main Release Quality Gates pass. Always branch from the latest
remote main; do not assume a stale SHA.

The project is RELEASE_CANDIDATE, not SYSTEM_ACCEPTED.

## Fixed facts

- Protected main currently includes identity backend PR #27 and acceptance PR #28.
- Current accepted main before the evidence PR: bc9836532f6300e91dc7c0a906b07dabe754c138.
- Protected-main CI Run 29801095074 passed 8/8 jobs.
- Clean external-volume evidence is in
  docs/system-acceptance/evidence/identity-mainline.json.
- Alembic head is 20260720_0010; migrations 0001-0010 are immutable for this task.
- Keycloak Authorization Code + PKCE is the only identity and password authority.
- TenantID, roles and scopes come only from verified OIDC claims and backend TenantContext.
- Existing RLS, SERIALIZABLE, CAS, audit, Outbox, SSE and C12 semantics are frozen.
- Current quality evidence: 519 Python passed, 1 skipped, 91.33% coverage;
  54 Vitest; 3 Playwright; push/PR/main gates each 8/8.
- No real SMS, email, AI Provider or production secret may enter source, logs or fixtures.

## Branch and sequencing

1. Confirm the evidence PR is merged and latest main CI is 8/8 green.
2. From latest main create `codex/frontend-identity-i18n`.
3. Do not modify backend Python, migrations, generated identity contract meaning,
   repository governance or historical acceptance snapshots.
4. Complete i18n infrastructure before page implementation.
5. Complete registration before account self-service and tenant administration.
6. Complete Vitest and Playwright before opening the PR.
7. Merge only after push and PR workflows are both 8/8 green.
8. Replay registered-user OIDC and the trusted release chain from merged main.

Any backend contract gap, dirty source, failed CI, identity ambiguity or security
boundary uncertainty stops the task. Document the gap instead of changing the
frozen backend in this PR.

## Existing backend APIs to consume

Public registration:

- POST /api/auth/verification-challenges
- POST /api/auth/verification-challenges/verify
- POST /api/auth/register/email
- POST /api/auth/register/phone

Authenticated account self-service:

- GET /internal/accounts/me
- PATCH /internal/accounts/me
- POST /internal/accounts/me/verification-challenges
- POST /internal/accounts/me/verification-challenges/verify
- POST /internal/accounts/me/contact

Tenant administration:

- GET /internal/tenant/accounts
- GET /internal/tenant/accounts/{account_id}
- GET /internal/tenant/accounts/{account_id}/audit
- POST /internal/tenant/accounts/{account_id}/disable
- POST /internal/tenant/accounts/{account_id}/restore
- GET /internal/tenant/registrations/{registration_id}

The development verification-code inbox is loopback-only test infrastructure.
Production UI must never depend on it.

## Internationalization foundation

- Add and lock `vue-i18n` using the existing pnpm workflow.
- Locales: `zh-CN`, `zh-TW`, `en-US`.
- Default and missing-key fallback: `zh-CN`.
- Store the authenticated user's preference through the existing profile API.
- Persist only a non-sensitive pre-login locale preference in session-scoped storage.
- Map application locale to Keycloak `ui_locales`; use explicit mapping when
  Keycloak expects `en` instead of `en-US`.
- Configure the Keycloak realm/login theme for Simplified Chinese, Traditional
  Chinese and English without enabling Keycloak native public self-registration.
- Move all user-visible shell, auth, registration, account, validation, error,
  empty-state, date and number text into message catalogs.
- Add a CI test that fails on missing locale keys or user-visible hard-coded text
  in the new identity surfaces.
- Do not claim that academic source data, historical AI output or persisted
  knowledge content has been translated.

## Required routes and behavior

### /register

- Email and E.164 phone segmented modes.
- Normalize identifiers before request submission.
- Request and verify a challenge, then submit the matching versioned register command.
- Use a 60-second resend countdown, password policy feedback and accessible errors.
- Every write uses a fresh valid Idempotency-Key.
- Use uniform user-facing responses that do not reveal whether an account exists.
- Never log password, code, Token or raw contact data.
- Registration success never auto-logs in; redirect to the standard OIDC login.

### /account/profile

- Load the current account through the authenticated profile endpoint.
- Edit display name and locale with expected-version CAS.
- Email or phone changes require a new challenge and verification.
- Handle CAS conflicts by reloading authoritative state and preserving a safe user draft.
- Never expose TenantID, subject, roles or scopes as editable fields.

### /tenant/accounts

- Require account administration read/write scopes in router and command guards.
- List only the current tenant's accounts and show status, masked contacts and audit history.
- Disable or restore with expected-version CAS and explicit confirmation.
- Learner/reviewer users without admin scope receive the standard 403 surface.
- No cross-tenant cache entry may survive logout, 401/403 or OIDC tenant change.

### /account/recovery

- Delegate password recovery to Keycloak's supported OIDC/account action flow.
- Do not add an application password-reset endpoint or store recovery secrets.
- Preserve and validate post-recovery return targets against a local allowlist.

## Security requirements

- Continue using session-scoped OIDC storage; never use localStorage for Tokens.
- Never send X-Tenant-ID, X-Subject-Ref, role or scope identity headers.
- Send only Authorization, valid X-Trace-ID, X-Session-ID, Idempotency-Key and
  Last-Event-ID where the existing client permits them.
- Validate every response Envelope and runtime schema.
- Redact password, verification code, Token, raw email and raw phone from logs,
  telemetry, test traces and screenshots.
- Clear identity/profile/account caches and SSE cursors on logout, 401/403 or tenant change.
- Keep CSP, non-root container and Nginx proxy-buffering controls unchanged.

## Tests

Vitest and MSW must cover:

- email and phone registration success;
- duplicate/anti-enumeration response, invalid or expired code, rate limit and network failure;
- idempotent retry and conflicting replay handling;
- registered account redirected to and authenticated through existing OIDC PKCE;
- profile edit, locale persistence, contact re-verification and CAS conflict;
- learner/reviewer/admin route and command separation;
- tenant-change, logout and 401/403 cache cleanup;
- locale switching, `zh-CN` fallback, missing-key failure and Keycloak `ui_locales` mapping;
- password/code/Token/PII redaction from client logs and error objects.

Playwright must cover desktop and mobile:

1. choose locale before login;
2. register by local email fixture without exposing the code in browser logs;
3. complete OIDC login as the new learner;
4. edit profile and locale;
5. confirm learner cannot access tenant administration;
6. confirm tenant-admin can list, inspect, disable and restore the account;
7. verify account switching clears prior-tenant state;
8. verify all three locales render without overflow or missing-key placeholders.

Maintain frontend thresholds at statements/functions/lines >=80% and branches
>=75%. TypeScript strict, build, pnpm audit, SBOM/license, Trivy and Gitleaks must
all pass.

## Delivery and replay

- Commit i18n foundation, identity pages, tests and evidence separately with
  allowed Conventional Commit types.
- Create a standard PR to protected main; no admin override or ruleset changes.
- Require both push and pull_request workflows to pass all eight jobs.
- Squash Merge only when GitHub reports mergeable_state=clean.
- Wait for merged-main 8/8 CI.
- Recreate the protected release volume only after verifying labels and no mounts.
- Replay registration -> OIDC -> Topic1 -> Topic3 -> Topic4 -> C12 -> SSE from
  merged main and archive source SHA, dataset hashes and image IDs.

Stop after the frontend identity/i18n replay is archived. The 2,000-SSE, eight-hour
soak, DR, sealed Provider and production-operation gates remain separate final tasks.
Do not mark SYSTEM_ACCEPTED.
```
