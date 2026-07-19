# Infrastructure

`docker-compose.yml` is the local PostgreSQL, Keycloak, FastAPI, and Vue baseline.
`backend.Dockerfile` builds the Python 3.11 API. `frontend.Dockerfile` builds the
Vue application and copies only static assets into a non-root Nginx runtime.
`nginx/frontend.conf` proxies authenticated API and SSE traffic without buffering.

```powershell
docker compose -f infra/docker-compose.yml up --build
```

The workbench is available at `http://localhost:5173`, Keycloak at
`http://localhost:8080`, and the API at `http://localhost:8000`. Local identities:

- `learner` / `learner-local-only`
- `reviewer` / `reviewer-local-only`

These credentials are deterministic development fixtures, not reusable secrets.
Production must use a secret manager, organization-managed OIDC, PostgreSQL
backups, durable outbox/SSE adapters, and isolated code workers.
