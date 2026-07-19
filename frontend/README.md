# CyberControl Frontend Foundation

This directory contains the Phase 6 engineering foundation only. Topic-specific
business pages are intentionally limited to routed empty states.

## Commands

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run typecheck
pnpm --dir frontend run test:coverage
pnpm --dir frontend run build
```

For local Vite development, start the backend on port 8000 and run:

```powershell
pnpm --dir frontend run dev
```

Vite proxies `/health/` and `/internal/` to the backend. Production static assets
are served by `infra/frontend.Dockerfile` and `infra/nginx/frontend.conf`.

## Trust Boundary

- OIDC Authorization Code with PKCE is handled by `oidc-client-ts`.
- OIDC state and tokens use `sessionStorage`; `localStorage` is not used.
- Tenant identity and application permissions are read only from validated
  `tenant_id` and `permissions` claims.
- The client never sends `X-Tenant-ID`, `X-Subject-Ref`, role, or scope headers.
- Allowed tracing headers are `X-Trace-ID`, `X-Session-ID`, and `Last-Event-ID`.
- API success and error documents are runtime validated before use.
- SSE uses authenticated Fetch streams, event ID/sequence deduplication, tenant-
  scoped cursors, heartbeat handling, and reconnect backoff.
- A 401, 403, logout, or OIDC tenant change clears all tenant-scoped caches.

The supported Lucide package is `@lucide/vue`; the requested legacy
`lucide-vue-next` package is deprecated upstream.
