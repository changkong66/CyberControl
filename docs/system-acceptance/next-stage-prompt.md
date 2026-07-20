# Next Stage Prompt: Registration, Accounts And Three-Language Workbench

```text
# CyberControl Phase 7.2: additive identity self-service and i18n

Continue only after the mainline evidence PR for protected main
40c9a590614d3fb57011061fac02669d86946240 is merged and its CI is green.
The project is currently RELEASE_CANDIDATE, not SYSTEM_ACCEPTED.

## Fixed facts

- Protected main: 40c9a590614d3fb57011061fac02669d86946240
- PR #25 merged; protected-main CI Run 29729849367 passed 8/8
- Merged-main clean-volume replay passed from
  docs/system-acceptance/evidence/release-eligible-mainline.json
- PostgreSQL volume used: cybercontrol_release_postgres
- Alembic head: 20260716_0009; migrations 0001-0009 and frozen Topic contracts are immutable
- Keycloak OIDC Authorization Code + PKCE is the only identity and password authority
- Existing tenant context, FORCE RLS, SERIALIZABLE, CAS, append-only audit, Outbox and C12 semantics are frozen
- Current local quality evidence: 474 passed, 1 skipped, Python coverage 91.21%; 54 Vitest; 3 Playwright
- No real SMS, email, AI-provider or production secret may enter source, logs or fixtures

## Mandatory sequencing

1. Merge the documentation-only mainline evidence PR.
2. Create and merge the backend registration/account PR with all Release Quality Gates green.
3. Rebase frontend work from the merged backend main and create the frontend registration/i18n PR.
4. Run a clean-volume registration-to-OIDC replay from merged main.
5. Only then continue to the final G0-G12 non-functional gates.

Any failed CI, dirty source, missing evidence, contract drift or security ambiguity stops the sequence.

## Backend PR: Keycloak-backed registration and account projection

Create a branch from the latest protected main. Add an ADR before coding:

- Keycloak alone stores passwords and password hashes.
- The application database stores only non-secret account projections and encrypted contact values plus lookup digests.
- Keycloak Admin API is an external side effect; use a registration state machine, idempotency, retry, compensation and reconciliation.
- Default production registration requires a server-verified invitation; local demo may use demo-academy only under explicit development configuration.
- New accounts receive learner only. Reviewer/admin roles and tenant changes are server-authorized and never client-controlled.

Add only migration 0010. Every new table must have FORCE RLS, append-only protections where applicable, audit and Outbox coverage. Do not modify 0001-0009.

Add versioned contracts and generated Python/JSON Schema/TypeScript/Go artifacts:

- UserRegisterByEmailCommandV1
- UserRegisterByPhoneCommandV1
- VerificationChallengeRequestV1
- VerificationChallengeVerifyV1
- AccountProfileV1
- AccountAdminViewV1

Required server capabilities:

- email and E.164 phone registration
- verification challenge send/verify with hashed codes, five-minute expiry, attempt limits and multidimensional rate limits
- uniform anti-enumeration responses
- Idempotency-Key on every write and replay conflict detection
- current-user profile read/edit for non-sensitive fields
- verified contact change workflow
- tenant-admin account list/detail and suspend/restore
- audit and Outbox records for every lifecycle change
- reconciliation for Keycloak success/database failure, timeout and retry paths
- real PostgreSQL and real Keycloak integration tests for RLS, concurrency, compensation and permissions

The local fixture must use a loopback-only test inbox, never console-print a usable code, and never contain real credentials.

## Frontend PR: registration, account management and i18n

Branch from the merged backend main. Use the existing Vue 3, Pinia, Router, AJV, OIDC PKCE and fetch/SSE layers. Do not add identity headers or change Topic1-Topic4 contracts.

Locales:

- zh-CN (default fallback)
- zh-TW
- en-US

Move all user-visible shell, login, registration, account, permission, validation, error, empty-state, date and number text into vue-i18n messages. Pass ui_locales to Keycloak; do not transmit language or tenant identity in custom headers. Do not claim that academic knowledge or historical AI content has been translated.

Routes:

- /register
- /account/profile
- /account/recovery
- /tenant/accounts

Security requirements:

- token remains in the existing session-scoped OIDC storage, never localStorage
- no X-Tenant-ID, X-Subject-Ref, role or Scope request headers
- tenant identity is display/cache context only and comes from verified claims
- passwords, codes, tokens and raw PII are absent from logs, telemetry and error reports
- 401/403, logout and tenant change clear private caches and SSE cursors
- all responses pass Envelope and runtime schema validation

Required tests:

- registration success, duplicate, invalid/expired code, rate limit and network failure
- registered account logs in through existing PKCE and receives correct tenant/learner scopes
- contact re-verification and profile editing
- learner/reviewer/admin access separation and cross-tenant cache clearing
- locale switch, fallback and missing-key detection, including Keycloak ui_locales
- mobile layout, accessibility and Playwright end-to-end coverage

## Acceptance and release rules

- Keep Python coverage >= 91.19% observed and CI threshold unchanged at 90%.
- Keep frontend thresholds at statements/functions/lines >=80% and branches >=75%.
- Run real PostgreSQL, real Keycloak, contract drift, Go race, SBOM/license, Trivy and Gitleaks gates.
- Commit implementation, tests and evidence separately; use conventional messages.
- Every evidence record includes source SHA, migration head, dataset version/hash, image IDs and exact command flags.
- Do not start 2,000-SSE, soak, DR or sealed-provider final gates until registration/i18n is merged and replayed from main.
- Do not mark SYSTEM_ACCEPTED until all final non-functional and production-operation evidence is complete.
```
