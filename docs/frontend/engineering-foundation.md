# Frontend Engineering Foundation

## Scope

This checkpoint establishes the frontend runtime and local identity environment.
It does not implement Topic 1-4 business surfaces.

Implemented routes:

- `/login`
- `/auth/callback`
- `/workspace`
- `/knowledge`
- `/learning`
- `/agents`
- `/verification`
- `/reviews`
- `/publications`
- `/forbidden`
- `/error`

Protected routes use OIDC scope guards. Topic routes render stable empty states
until their independent business-page PRs are authorized.

## Local OIDC

The Compose environment starts Keycloak 26.7.0 from a fixed digest and imports
`infra/keycloak/cybercontrol-realm.json`. The realm provides:

- tenant claim: `demo-academy`
- audience: `cybercontrol-api`
- application authorization claim: `permissions` (separate from the OIDC `scope` claim)
- learner role with Topic read and SSE-read permissions
- reviewer role with Topic read, SSE-read, review, and release permissions
- PKCE-only public workbench client
- a local direct-grant client used only for automated environment verification

`infra/postgres/dev/bind-demo-tenant.sql` idempotently binds the existing tenant
record to the Keycloak issuer after migrations complete. It does not modify the
frozen migration chain.

## Security Controls

The browser cannot choose tenant identity. The backend derives tenant context
from the verified bearer token and database binding. The API and SSE clients do
not expose a configuration path for client-controlled identity headers.

Tokens and stream cursors are session-scoped. Cursor keys include tenant and
stream identity. Authorization failure, logout, and tenant changes remove every
tenant-scoped cache entry.

The Nginx runtime is non-root, contains no Node toolchain or source tree, applies
CSP and browser security headers, serves immutable hashed assets, disables cache
and proxy buffering for `/internal/`, and preserves bearer/trace/session/cursor
headers required by the backend.

## Quality Gates

The frontend CI job enforces:

- TypeScript strict mode and Vue type checking
- Vitest unit/integration tests
- coverage thresholds: lines/statements/functions 80%, branches 75%
- production Vite build
- pnpm high/critical vulnerability audit
- deterministic Node SBOM and license policy

The container CI job builds and inspects both backend and frontend images,
enforces non-root/minimal runtimes, performs liveness smoke tests, generates both
container SBOMs, and blocks fixable high/critical Trivy findings.
