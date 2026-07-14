# Infrastructure

`docker-compose.yml` is the local PostgreSQL and FastAPI baseline.
`backend.Dockerfile` builds the Python 3.11 API. `nginx/sse.conf` documents the
mandatory no-buffering and timeout settings for SSE.

```powershell
docker compose -f infra/docker-compose.yml up --build
```

The Compose credentials and tags are development-only. Production must use a
secret manager, digest-pinned images, locked dependencies, SBOM evidence,
PostgreSQL backups, durable outbox/SSE adapters, and isolated code workers.
