# Database migrations

Alembic revisions are immutable after release. Run migrations with the privileged
migration URL, never with the API runtime role:

```powershell
$env:LIYAN_DATABASE_MIGRATION_URL = "postgresql+asyncpg://..."
uv run alembic -c backend/alembic.ini upgrade head
```

Every revision must support offline SQL generation and a tested downgrade until
the corresponding release retention window closes.
