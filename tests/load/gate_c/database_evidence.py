from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from gate_c.config import Workload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture Gate C PostgreSQL evidence.")
    parser.add_argument("--bootstrap-url", required=True)
    parser.add_argument("--runtime-url", required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


async def _percentiles(connection: asyncpg.Connection, expression: str) -> dict[str, float]:
    row = await connection.fetchrow(
        f"""
        SELECT
            coalesce(percentile_cont(0.95) WITHIN GROUP (ORDER BY {expression}), 0) AS p95,
            coalesce(percentile_cont(0.99) WITHIN GROUP (ORDER BY {expression}), 0) AS p99
        FROM outbox_messages
        WHERE state = 'PUBLISHED' AND published_at IS NOT NULL
        """  # noqa: S608 - expression is a constant controlled by this module.
    )
    return {"p95_ms": round(float(row["p95"]), 3), "p99_ms": round(float(row["p99"]), 3)}


async def _runtime_rls(
    runtime_url: str,
    tenant_ids: tuple[str, ...],
) -> dict[str, Any]:
    connection = await asyncpg.connect(runtime_url)
    try:
        async with connection.transaction():
            await connection.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_ids[0])
            own = await connection.fetchval(
                "SELECT count(*) FROM sse_events WHERE tenant_id = $1", tenant_ids[0]
            )
            foreign = await connection.fetchval(
                "SELECT count(*) FROM sse_events WHERE tenant_id = $1", tenant_ids[1]
            )
        return {"own_tenant_visible": int(own), "foreign_tenant_visible": int(foreign)}
    finally:
        await connection.close()


async def _run(args: argparse.Namespace) -> int:
    workload = Workload.load(args.workload)
    connection = await asyncpg.connect(args.bootstrap_url)
    try:
        migration_head = await connection.fetchval("SELECT version_num FROM alembic_version")
        roles = await connection.fetch(
            """
            SELECT rolname, rolsuper, rolbypassrls
            FROM pg_roles
            WHERE rolname IN ('liyans_app', 'liyans_migrator', 'liyans_dispatcher')
            ORDER BY rolname
            """
        )
        outbox_states = await connection.fetch(
            "SELECT state, count(*) AS count FROM outbox_messages GROUP BY state ORDER BY state"
        )
        event_rows = await connection.fetch(
            """
            SELECT tenant_id, count(*) AS count, min(sequence) AS minimum_sequence,
                   max(sequence) AS maximum_sequence
            FROM sse_events
            WHERE data ? 'gate_c_run_id'
            GROUP BY tenant_id
            ORDER BY tenant_id
            """
        )
        force_rls = await connection.fetchrow(
            """
            SELECT
                count(*) FILTER (WHERE c.relrowsecurity) AS rls_tables,
                count(*) FILTER (WHERE c.relforcerowsecurity) AS force_rls_tables
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN information_schema.columns cols
              ON cols.table_schema = n.nspname AND cols.table_name = c.relname
            WHERE n.nspname = 'public' AND cols.column_name = 'tenant_id'
              AND c.relkind = 'r'
            """
        )
        append_only_triggers = await connection.fetchval(
            """
            SELECT count(*) FROM pg_trigger
            WHERE NOT tgisinternal AND tgname LIKE '%append_only%'
            """
        )
        outbox_lag = await _percentiles(
            connection,
            "extract(epoch FROM (published_at - created_at)) * 1000",
        )
    finally:
        await connection.close()
    document = {
        "schema_version": "cybercontrol.gate-c-postgres-evidence.v1",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "migration_head": str(migration_head),
        "roles": [dict(row) for row in roles],
        "outbox_states": {str(row["state"]): int(row["count"]) for row in outbox_states},
        "outbox_lag": outbox_lag,
        "gate_c_sse_events": [dict(row) for row in event_rows],
        "tenant_tables": int(force_rls["rls_tables"]),
        "force_rls_tables": int(force_rls["force_rls_tables"]),
        "append_only_triggers": int(append_only_triggers),
        "rls_adversarial_read": await _runtime_rls(args.runtime_url, workload.tenant_ids),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "migration_head": migration_head}))
    return 0


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
