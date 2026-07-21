# CyberControl Frontend Workbench

This directory contains the Phase 6 business workbench and the Phase 7.x
identity/internationalization extension for the frozen Phase1.1-Topic4
backend. The tenant-scoped client renders authoritative records returned by
the API and never manufactures tenant identity, candidate/report hashes,
release authorizations, or evidence.

## Commands

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run generate:validators
pnpm --dir frontend run check:validators
pnpm --dir frontend run typecheck
pnpm --dir frontend run test:coverage
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend run test:e2e
pnpm --dir frontend run build
```

For local Vite development, start the backend on port 8000 and run:

```powershell
pnpm --dir frontend run dev
```

Vite proxies `/api/`, `/health/`, and `/internal/` to the backend. Production
static assets are served by `infra/frontend.Dockerfile` and
`infra/nginx/frontend.conf`.

The local Compose stack also starts a pinned, non-root fixture Provider. It
implements the approved Responses Lite boundary for `spark_text` and
`xfyun_code` without external network calls or real vendor credentials. Seed a
reproducible demo after the stack is ready with:

```powershell
.\tools\windows\bootstrap-frontend-demo.ps1
```

The identity routes are `/register`, `/account/recovery`, `/account/profile`,
and `/tenant/accounts`. The business routes remain `/workspace`, `/knowledge`,
`/learning`, `/agents`, `/verification`, `/reviews`, and `/publications`.
Route guards use coarse navigation permissions from the OIDC token; each API
call is still checked by the backend's fine-grained Scope policy.

The interface supports `zh-CN`, `zh-TW`, and `en-US`. The selected locale is
stored in `sessionStorage`, mapped to Keycloak through `ui_locales`, and may be
persisted as the user's non-sensitive account preference.

## Trust Boundary

- OIDC Authorization Code with PKCE is handled by `oidc-client-ts`.
- OIDC state and tokens use `sessionStorage`; `localStorage` is not used.
- Keycloak remains the only password and credential authority. Registration
  never stores a password in application state after submission.
- Tenant identity and application permissions are read only from validated
  `tenant_id` and `permissions` claims.
- The client never sends `X-Tenant-ID`, `X-Subject-Ref`, role, or scope headers.
- Allowed tracing headers are `X-Trace-ID`, `X-Session-ID`, and `Last-Event-ID`.
- API Envelope, readiness, and error receipts are runtime validated before the
  typed facade projects business payloads.
- Runtime validators are AJV standalone modules generated during development
  and checked for drift during typecheck, build, and container build. The
  browser never compiles JSON Schema or uses dynamic code generation.
- API request targets must be same-origin root paths. Absolute and
  scheme-relative request paths are rejected before credentials are read.
- Public registration calls explicitly disable authentication; Nginx also
  clears `Authorization` on `/api/` as defense in depth.
- SSE uses authenticated Fetch streams, event ID/sequence deduplication, tenant-
  scoped cursors, heartbeat handling, and reconnect backoff.
- A 401, 403, logout, or OIDC tenant change clears all tenant-scoped caches.
- C12 release actions call only the server-derived v2 authorization and commit
  endpoints. The deprecated v1 publication routes are not used by the client.
- The browser has no method that creates a complete Topic4 Verification
  Request. Topic3 Candidate identifiers are projected to their deterministic
  verification IDs only for navigation, then revalidated by the server read API.
- `Idempotency-Key` is generated per mutating operation; it is an operation
  contract header, not a tenant or identity header.

See `docs/frontend/identity-i18n-acceptance.md` for the current branch-level
acceptance evidence and remaining mainline gates.

The supported Lucide package is `@lucide/vue`; the requested legacy
`lucide-vue-next` package is deprecated upstream.
