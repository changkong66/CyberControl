# Phase 1.1 Step 7: PostgreSQL Integration and Fault Testing

## Test architecture

```mermaid
flowchart TD
    RUNNER["Pytest async integration runner"] --> MIGRATION["Alembic head assertion"]
    RUNNER --> APPROLE["Non-superuser API pool"]
    RUNNER --> MIGRATOR["Non-superuser migration pool"]
    APPROLE --> PG["Ephemeral PostgreSQL"]
    MIGRATOR --> PG
    RUNNER --> TX["Transactions and Savepoints"]
    RUNNER --> RLS["Cross-tenant RLS attacks"]
    RUNNER --> CONCURRENCY["Idempotency, Outbox and audit races"]
    RUNNER --> RECOVERY["Connection kill and service restart"]
    RUNNER --> IMMUTABLE["Audit mutation injection"]
```

## Automated matrix

| ID | Scenario | Required result |
|---|---|---|
| TX-01 | Outer transaction success | All writes commit together |
| TX-02 | Exception in outer transaction | Business and Outbox writes both disappear |
| TX-03 | Exception inside Savepoint | Nested writes roll back; outer writes commit |
| TX-04 | Two SERIALIZABLE writers | One conflict retries in a fresh transaction; no lost update |
| DB-01 | PostgreSQL backend terminates current connection | Current transaction fails; next pooled transaction succeeds |
| RLS-01 | API query without `app.tenant_id` | Zero tenant rows returned |
| RLS-02 | Tenant B reads Tenant A resources | Zero rows returned |
| RLS-03 | Tenant B inserts a Tenant A row | SQLSTATE `42501` |
| RLS-04 | Pool reused after Tenant A transaction | Transaction-local tenant context does not leak |
| AUTH-01 | Valid issuer and tenant binding | Server creates authorized TenantContext |
| AUTH-02 | Wrong issuer or suspended tenant | Request denied before route execution |
| IDEM-01 | Eight same-key/same-digest contenders | Exactly one reservation winner |
| IDEM-02 | Same key with two concurrent digests | One winner; one deterministic conflict |
| IDEM-03 | Buffered/processing lease expires | A new worker takes over; old owner is rejected |
| OUTBOX-01 | Business transaction rolls back | No Outbox row remains |
| OUTBOX-02 | Two workers claim ten rows | Ten unique claims, zero overlap |
| OUTBOX-03 | Claimed worker crashes | Lease expires; another worker reclaims and confirms |
| AUDIT-01 | Ten concurrent appends | Continuous sequence and valid full hash chain |
| AUDIT-02 | API role attempts mutation | SQLSTATE `42501` |
| AUDIT-03 | Table owner attempts mutation | Append-only trigger returns SQLSTATE `55000` |
| SSE-01 | Replay adapter is reconstructed | Events and sequence remain durable |
| SSE-02 | Retention cleanup reaches last event | Highest sequence watermark is retained |
| APP-01 | FastAPI lifespan closes and reopens | Next SSE event continues the prior sequence |

## Execution

```powershell
$env:LIYAN_TEST_DATABASE_URL = "postgresql+asyncpg://app:secret@127.0.0.1:5432/liyans"
$env:LIYAN_TEST_MIGRATION_DATABASE_URL = "postgresql+asyncpg://migrator:secret@127.0.0.1:5432/liyans"
./tools/windows/run-postgres-integration.ps1
```

Tests use unique tenant IDs and do not depend on ordering between test functions.
The database role used by the application must be non-superuser and must not have
`BYPASSRLS`; the suite rejects an environment that masks RLS failures through an
overprivileged runtime URL.

## Quantitative acceptance

- All integration cases pass with no retries hidden by the test runner.
- Serialization retry budget is at most three attempts.
- Outbox claim overlap is exactly zero.
- Cross-tenant read leakage is exactly zero rows.
- Audit sequence gaps and hash mismatches are exactly zero.
- Service restart produces no SSE sequence reuse.
- Connection termination recovery completes within the pool checkout timeout.
- The local acceptance run completes in under 30 seconds excluding image setup.

Validated on 2026-07-14 against an ephemeral PostgreSQL 17.10 instance using the
same SQL feature set targeted by the PostgreSQL 16 Compose service:

- PostgreSQL integration tests: `15 passed` in approximately 4.8 seconds.
- Full Python suite with database tests enabled: `66 passed`.
- Combined `liyans` and `liyans_contracts` statement coverage: `86%`.
- Alembic head: `20260714_0002`; autogenerate drift: none.

Step 8 therefore sets the initial CI coverage red line to 85%. Raising the gate
requires sustained coverage above the new threshold; lowering it requires an ADR.

## Fault containment

The suite never disables RLS, audit triggers, or permission grants. Expected
database exceptions are asserted by SQLSTATE. Tests that kill a backend connection
use only the session owned by the runtime role and verify immediate pool recovery.
All destructive database lifecycle operations are delegated to ephemeral CI
services rather than production-like shared environments.
