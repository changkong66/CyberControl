from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import psutil
import requests

_METRIC = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([0-9.eE+-]+)$")
_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")
_SIZE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kmgtpe]?i?b)?\s*$", re.IGNORECASE)


def _size_bytes(value: str) -> int | None:
    match = _SIZE.fullmatch(value)
    if match is None:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    units = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }
    multiplier = units.get(unit)
    return None if multiplier is None else round(number * multiplier)


def _split_stat_bytes(value: str) -> tuple[int | None, int | None]:
    parts = [part.strip() for part in value.split("/", 1)]
    if len(parts) != 2:
        return None, None
    return _size_bytes(parts[0]), _size_bytes(parts[1])


def _file_descriptor_metrics(executable: str, name: str) -> dict[str, int | None]:
    script = (
        "set -- /proc/1/fd/*; printf '%s\\n' \"$#\"; "
        'awk \'$1 == "Max" && $2 == "open" && $3 == "files" '
        "{ print $4; exit }' /proc/1/limits"
    )
    result = subprocess.run(  # noqa: S603 - executable and container name come from Docker.
        [executable, "exec", name, "sh", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines or not lines[0].isdigit():
        raise RuntimeError("container file descriptor count is invalid")
    limit = None
    if len(lines) > 1 and lines[1].isdigit():
        limit = int(lines[1])
    return {"open": int(lines[0]), "limit": limit}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture Gate C host and runtime metrics.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--metrics-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    return parser


def _percent(value: str) -> float:
    return float(value.strip().removesuffix("%"))


def _docker_executable() -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("docker is required for Gate C monitoring")
    return executable


def _docker_stats(project: str) -> list[dict[str, Any]]:
    if _PROJECT.fullmatch(project) is None:
        raise ValueError("Gate C Compose project name is invalid")
    executable = _docker_executable()
    names = subprocess.run(  # noqa: S603 - executable and arguments are validated.
        [
            executable,
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.Names}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if not names:
        return []
    inspect = subprocess.run(  # noqa: S603 - executable and container names are Docker output.
        [executable, "inspect", *names],
        check=True,
        capture_output=True,
        text=True,
    )
    states = {
        str(item["Name"]).lstrip("/"): {
            "restart_count": int(item.get("RestartCount", 0)),
            "oom_killed": bool(item.get("State", {}).get("OOMKilled", False)),
            "status": str(item.get("State", {}).get("Status", "unknown")),
            "service": str(
                item.get("Config", {})
                .get("Labels", {})
                .get("com.docker.compose.service", "unknown")
            ),
        }
        for item in json.loads(inspect.stdout)
    }
    completed = subprocess.run(  # noqa: S603 - executable and container names are Docker output.
        [executable, "stats", "--no-stream", "--format", "{{json .}}", *names],
        check=True,
        capture_output=True,
        text=True,
    )
    records: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        name = str(raw.get("Name"))
        network_rx, network_tx = _split_stat_bytes(str(raw.get("NetIO", "")))
        block_read, block_write = _split_stat_bytes(str(raw.get("BlockIO", "")))
        memory_used, memory_limit = _split_stat_bytes(str(raw.get("MemUsage", "")))
        record: dict[str, Any] = {
            "name": raw.get("Name"),
            "cpu_percent_one_core_units": _percent(str(raw.get("CPUPerc", "0%"))),
            "memory_percent": _percent(str(raw.get("MemPerc", "0%"))),
            "memory_usage": raw.get("MemUsage"),
            "memory_usage_bytes": memory_used,
            "memory_limit_bytes": memory_limit,
            "network_io": raw.get("NetIO"),
            "network_rx_bytes": network_rx,
            "network_tx_bytes": network_tx,
            "block_io": raw.get("BlockIO"),
            "block_read_bytes": block_read,
            "block_write_bytes": block_write,
            "pids": int(raw.get("PIDs", 0)),
            **states.get(name, {}),
        }
        try:
            descriptors = _file_descriptor_metrics(executable, name)
            record["open_file_descriptors"] = descriptors["open"]
            record["file_descriptor_limit"] = descriptors["limit"]
        except Exception as exc:
            record["file_descriptor_error"] = type(exc).__name__
        records.append(record)
    return records


def _platform_metrics(url: str) -> dict[str, float]:
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, timeout=5, allow_redirects=False)
    response.raise_for_status()
    values: dict[str, float] = {}
    for line in response.text.splitlines():
        match = _METRIC.fullmatch(line)
        if match is not None:
            labels = match.group(2)
            key = match.group(1) if labels is None else f"{match.group(1)}{{{labels}}}"
            values[key] = float(match.group(3))
    return values


async def _database_metrics(connection: asyncpg.Connection) -> dict[str, Any]:
    connections = await connection.fetchval(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    )
    application_rows = await connection.fetch(
        """
        SELECT coalesce(application_name, '') AS application_name,
               state, count(*) AS count
        FROM pg_stat_activity
        WHERE datname = current_database()
        GROUP BY application_name, state
        ORDER BY application_name, state
        """
    )
    states = await connection.fetch(
        "SELECT state, count(*) AS count FROM outbox_messages GROUP BY state ORDER BY state"
    )
    oldest_open_ms = await connection.fetchval(
        """
        SELECT coalesce(max(extract(epoch FROM (now() - created_at)) * 1000), 0)
        FROM outbox_messages
        WHERE state IN ('PENDING', 'CLAIMED')
        """
    )
    return {
        "connections": int(connections),
        "application_connections": sum(
            int(row["count"])
            for row in application_rows
            if str(row["application_name"]).startswith("liyans-")
        ),
        "active_application_connections": sum(
            int(row["count"])
            for row in application_rows
            if str(row["application_name"]).startswith("liyans-") and str(row["state"]) == "active"
        ),
        "connections_by_application": [dict(row) for row in application_rows],
        "outbox_states": {str(row["state"]): int(row["count"]) for row in states},
        "oldest_open_outbox_ms": round(float(oldest_open_ms), 3),
    }


async def _run(args: argparse.Namespace) -> int:
    if args.interval_seconds < 1 or args.interval_seconds > 60:
        raise SystemExit("--interval-seconds must be between 1 and 60")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    psutil.cpu_percent(interval=None)
    connection: asyncpg.Connection | None = None
    while not args.stop_file.exists():
        started = time.monotonic()
        record: dict[str, Any] = {
            "captured_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "captured_at_unix_ns": time.time_ns(),
            "host_cpu_percent": psutil.cpu_percent(interval=None),
            "host_memory": dict(psutil.virtual_memory()._asdict()),
        }
        try:
            record["containers"] = _docker_stats(args.project)
        except Exception as exc:
            record["docker_error"] = type(exc).__name__
        try:
            record["platform_metrics"] = _platform_metrics(args.metrics_url)
        except Exception as exc:
            record["metrics_error"] = type(exc).__name__
        try:
            if connection is None or connection.is_closed():
                connection = await asyncpg.connect(args.database_url)
            record["database"] = await _database_metrics(connection)
        except Exception as exc:
            record["database_error"] = type(exc).__name__
            if connection is not None:
                await connection.close()
                connection = None
        with args.output.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        delay = max(0.0, args.interval_seconds - (time.monotonic() - started))
        await asyncio.sleep(delay)
    if connection is not None:
        await connection.close()
    return 0


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
