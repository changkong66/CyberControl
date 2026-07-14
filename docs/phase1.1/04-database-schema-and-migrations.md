# Phase 1.1 Step 4: Database Schema and Migrations

## Layered architecture

```mermaid
flowchart TD
    BOOTSTRAP["One-time bootstrap superuser"] --> MIGRATOR["Non-superuser migration role"]
    MIGRATOR --> REV["Immutable Alembic revision"]
    REV --> TENANT["tenants"]
    TENANT --> ARTIFACT["artifacts"]
    TENANT --> IDEMPOTENCY["idempotency_records"]
    TENANT --> OUTBOX["outbox_messages"]
    TENANT --> AUDIT["audit_events"]
    TENANT --> SSE["sse_events"]
    APP["Non-superuser API role"] --> RLS["Forced tenant RLS"]
    RLS --> TENANT
    RLS --> ARTIFACT
    RLS --> IDEMPOTENCY
    RLS --> OUTBOX
    RLS --> AUDIT
    RLS --> SSE
    AUDIT --> IMMUTABLE["UPDATE/DELETE rejection trigger"]
```

## Schema ownership and compatibility

- `tenant_id` remains the frozen string identity used by Topic 1, Topic 2, and
  the Topic 3 Envelope. The database does not replace it with an incompatible UUID.
- Artifact provenance binds exact Envelope, Blueprint, Candidate, and Block identities.
- Outbox uniqueness enforces one Envelope per tenant and one sequence per
  tenant/partition pair.
- Idempotency keys are tenant-scoped, digest-bound, lease-aware, and retained
  with explicit expiry.
- Audit evidence is append-only, strictly sequenced per tenant, and chained with
  SHA-256 hashes.
- SSE events use a monotonic per-tenant replay sequence and explicit retention expiry.

## Security controls

All six tables have PostgreSQL row-level security enabled and forced. Both `USING`
and `WITH CHECK` compare the row tenant to transaction-local `app.tenant_id`. An
unset tenant context therefore returns no rows and rejects writes. The local
Compose environment separates the owner migration role from the non-superuser API
role. The bootstrap superuser is never used by the API or Alembic; production
credentials must come from a secret manager.

The API role cannot execute DDL or modify/delete audit events. A database trigger
also rejects audit updates and deletes if privileges are accidentally broadened.

## Migration operations

```powershell
$env:LIYAN_DATABASE_MIGRATION_URL = "postgresql+asyncpg://owner:secret@host:5432/liyans"
uv run --frozen alembic -c backend/alembic.ini upgrade head
uv run --frozen alembic -c backend/alembic.ini current --check-heads
uv run --frozen alembic -c backend/alembic.ini check
```

Released revisions are immutable. Destructive downgrade is limited to controlled
rollback windows and requires an explicit PowerShell switch in the repository tool.

## Acceptance thresholds

- One linear Alembic head and no model/migration drift.
- Upgrade, downgrade, and re-upgrade succeed against PostgreSQL 16.
- All six tables expose stable primary keys, foreign keys, checks, and query indexes.
- RLS is enabled and forced on every tenant table.
- Cross-tenant reads return zero rows; cross-tenant writes fail.
- Audit UPDATE and DELETE fail with SQLSTATE `55000`.
- Offline SQL generation succeeds without external services.

## Risk containment

Migration execution uses `NullPool`, one transaction per revision, and a dedicated
owner URL. The API service waits for the migration container to complete. A failed
migration prevents API startup. Backups and expand-contract migrations are required
before destructive production revisions.
