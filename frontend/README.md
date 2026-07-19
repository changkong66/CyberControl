# CyberControl Frontend Workbench

This directory contains the Phase 6 business workbench for the frozen
Phase1.1-Topic4 backend. The workbench is a read-heavy, tenant-scoped client:
it renders authoritative records returned by the API and never manufactures
tenant identity, candidate/report hashes, release authorizations, or evidence.

## Commands

```powershell
pnpm --dir frontend install --frozen-lockfile
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

Vite proxies `/health/` and `/internal/` to the backend. Production static assets
are served by `infra/frontend.Dockerfile` and `infra/nginx/frontend.conf`.

The local Compose stack also starts a pinned, non-root fixture Provider. It
implements the approved Responses Lite boundary for `spark_text` and
`xfyun_code` without external network calls or real vendor credentials. Seed a
reproducible demo after the stack is ready with:

```powershell
.\tools\windows\bootstrap-frontend-demo.ps1
```

The main routes are `/workspace`, `/knowledge`, `/learning`, `/agents`,
`/verification`, `/reviews`, and `/publications`. The route guards use the
coarse navigation permissions in the OIDC token; each API call is still checked
by the backend's fine-grained Scope policy.

## Trust Boundary

- OIDC Authorization Code with PKCE is handled by `oidc-client-ts`.
- OIDC state and tokens use `sessionStorage`; `localStorage` is not used.
- Tenant identity and application permissions are read only from validated
  `tenant_id` and `permissions` claims.
- The client never sends `X-Tenant-ID`, `X-Subject-Ref`, role, or scope headers.
- Allowed tracing headers are `X-Trace-ID`, `X-Session-ID`, and `Last-Event-ID`.
- API Envelope, readiness, and error receipts are runtime validated before the
  typed facade projects business payloads.
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

The supported Lucide package is `@lucide/vue`; the requested legacy
`lucide-vue-next` package is deprecated upstream.
