# Frontend Identity And Internationalization Acceptance

## Status

- Date: 2026-07-21
- Branch: `codex/frontend-identity-i18n`
- Base commit: `d197f0e495228caf8752b866e733863b5a78d3e6`
- Evidence state: `LOCAL_BRANCH_RELEASE_CANDIDATE`
- Mainline state: pending commit, pull request, and 8/8 Release Quality Gates
- System state: not `SYSTEM_ACCEPTED`

This is current branch evidence, not a rewrite of an earlier acceptance
snapshot. Mainline acceptance must be recorded only after the protected PR is
merged and replayed from the resulting `main` commit.

## Delivered Scope

- Three UI locales: `zh-CN`, `zh-TW`, and `en-US` with `zh-CN` fallback.
- Keycloak `ui_locales` mapping and account recovery through
  `kc_action=UPDATE_PASSWORD`.
- Public email/phone registration UI and typed API facade.
- Own-profile read/update and verified email/phone change UI.
- Tenant account list, detail, immutable audit view, CAS disable, and restore.
- Session-only OIDC and locale storage, tenant cache cleanup, and route guards.
- Static JSON Schema validators compatible with strict CSP.
- Nginx `/api/` proxy, security-header inheritance, immutable asset cache, and
  no-store HTML/API behavior.

No backend migration, Topic1-Topic4 frozen contract, RLS policy, transaction,
Outbox, SSE, or C12 publication semantic was changed by this branch.

## Automated Evidence

| Gate | Result |
| --- | --- |
| TypeScript strict typecheck | PASS |
| Vitest | 72 passed |
| Statements | 89.12% |
| Branches | 81.79% |
| Functions | 83.79% |
| Lines | 92.38% |
| Playwright Chromium, CI-equivalent 2 workers | 8 passed |
| Vite production build | PASS, no chunk warning |
| pnpm audit, high threshold | No known vulnerabilities |
| Node CycloneDX SBOM | 333 components |
| Node license policy | PASS |
| Real PostgreSQL full regression | 514 passed, 6 skipped |
| Python coverage | 90.55%, CI threshold 90% |
| Backend container Trivy inventory | 0 vulnerabilities |
| Frontend container Trivy inventory | 0 vulnerabilities |
| Gitleaks history and working tree | No leaks found |

The initial unrestricted local Playwright run was intentionally not used as
final evidence because it ran concurrently with coverage and production build
and one navigation was aborted under host contention. The isolated,
CI-equivalent 2-worker run completed 8/8 without retries, including email and
normalized phone registration plus verified contact change.

## Real Runtime Evidence

Environment:

- Compose project: `cybercontrol-identity-i18n`
- PostgreSQL volume: `cybercontrol-identity-i18n_liyans-postgres`
- Frontend: `http://localhost:5173`
- API: `http://localhost:8000`
- Keycloak: `http://localhost:8080`
- Frontend image: `sha256:876cb21ba1ac8cd988bdcb87d1370bc9235c538e0a41f8302fcc4dcdfe591ea4`
- Runtime user: `65532:65532`
- Runtime image size: 7,721,172 bytes
- Runtime root filesystem: 248 entries; no Node, pnpm, source tree,
  `package.json`, or `/workspace`

Real Google Chrome validation passed for:

- nonblank `/login` under `script-src 'self'` with no `unsafe-eval`;
- `zh-CN`, `zh-TW`, and `en-US` switching;
- recovery authorization carrying `kc_action=UPDATE_PASSWORD` and
  `ui_locales=en`;
- real email challenge, loopback-only fixture verification, and registration;
- a rejected wrong verification code followed by a successful corrected-code
  retry with a payload-aware idempotency key;
- real Keycloak Authorization Code + PKCE login;
- OIDC user stored in `sessionStorage`, not `localStorage`;
- learner-only `demo-academy` claims;
- authenticated profile API and learner rejection from `/tenant/accounts`;
- no client `X-Tenant-ID`, subject, role, or Scope headers;
- public registration requests without `Authorization`;
- zero application console messages on the successful authenticated pages;
- 390x844 Traditional Chinese registration without horizontal overflow.

Audit references for the synthetic browser account:

- Registration ID: `422270b4-bf26-4173-8565-19c7c6e43dc0`
- Account ID: `fa132ae1-0e6b-4676-8e54-b4e59d10b3f5`

The generated password and verification code were process-local and discarded.
Screenshots were visually inspected from the host temporary directory and were
not committed because they contain synthetic account identifiers.

## Security Conclusions

- Public identity requests cannot inherit a stale Bearer Token.
- Request targets cannot override the trusted API origin.
- Tenant, subject, role, and Scope headers remain runtime-reserved and rejected.
- Account responses fail closed when their tenant differs from the trusted OIDC
  tenant.
- Invitation tokens are retained only in component memory and removed from the
  browser URL after capture.
- Passwords, verification codes, Tokens, email, and phone values are redacted
  from client error state.
- Identical idempotent retries reuse their key, while changed verification or
  business payloads rotate the key before reaching the backend replay guard.
- CSP remains strict; standalone validators contain no `eval`, `new Function`,
  or CommonJS `require`.

## Remaining Gates

1. Split and commit implementation, test, and documentation changes.
2. Push `codex/frontend-identity-i18n` and create the protected pull request.
3. Require all 8 Release Quality Gates to pass.
4. Squash merge only after CI is green.
5. Rebuild and replay identity/i18n acceptance from the resulting `main` SHA.
6. Continue Phase 7 production acceptance only from that immutable mainline
   baseline and the isolated release PostgreSQL volume.

Real SMS/email providers, production secrets, final release-volume replay,
2,000 authenticated SSE connections, soak, DR, and final deployment acceptance
remain out of scope for this branch-level result.
