from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import ssl
import time
from collections import Counter
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Protocol

from liyans.infrastructure.observability.bounded_memory_inventory import (
    BoundedMemoryInventoryRejected,
    _read_cgroup_memory,
    _read_process_memory,
    build_memory_ledger,
)
from liyans.infrastructure.observability.jemalloc_profiles import _Mallctl
from liyans.infrastructure.observability.metrics import _JemallocStatsReader
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

PROCESS_VERSION = "Gate-C-12-v2.0"
CLASSIFICATION = "NON_ACCEPTANCE_DIAGNOSTIC"
ARMS = ("A", "Measurement", "APrime")
VARIABLES = ("D",)
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
Window = tuple[
    dict[str, int],
    dict[str, int],
    dict[str, object],
    dict[str, object] | None,
    dict[str, object],
]
BRACKET_SAMPLE_COUNT = 5
BRACKET_SAMPLE_SPACING_SECONDS = 0.05
BRACKET_SAMPLE_MAX_SECONDS = 0.25
BRACKET_BURST_MAX_SECONDS = 2.0
BRACKET_SAMPLE_ORDER = (
    "process_before",
    "cgroup_before",
    "jemalloc_epoch_and_stats",
    "cgroup_after",
    "process_after",
)


class Mallctl(Protocol):
    def read_bool(self, name: str) -> bool | None: ...

    def reset(self) -> int: ...

    def write_bool(self, name: str, value: bool) -> int: ...


@dataclass(frozen=True)
class CalibrationConfig:
    total_connections: int = 2000
    maximum_concurrency: int = 200
    admission_rate_per_second: float = 50.0
    idle_seconds: int = 300
    recovery_seconds: int = 600
    sample_interval_seconds: float = 0.1

    def validate(self) -> None:
        if self.total_connections < 1:
            raise ValueError("total connections must be positive")
        if self.maximum_concurrency < 1 or self.maximum_concurrency > self.total_connections:
            raise ValueError("maximum concurrency is outside the connection count")
        if self.admission_rate_per_second <= 0:
            raise ValueError("admission rate must be positive")
        if self.idle_seconds < 0 or self.recovery_seconds < 0:
            raise ValueError("idle and recovery durations cannot be negative")
        if not 0.01 <= self.sample_interval_seconds <= 5.0:
            raise ValueError("sample interval must be between 0.01 and 5 seconds")


@dataclass(frozen=True)
class CalibrationTLS:
    ca_certificate: Path
    server_certificate: Path
    server_hostname: str = "postgres"

    def validate(self) -> None:
        if not self.server_hostname or self.server_hostname != self.server_hostname.strip():
            raise ValueError("TLS server hostname is invalid")
        for label, path in (
            ("CA certificate", self.ca_certificate),
            ("server certificate", self.server_certificate),
        ):
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                raise ValueError(f"calibration {label} must be an absolute regular file")
            _certificate_sha256(path)

    @property
    def ca_sha256(self) -> str:
        return _certificate_sha256(self.ca_certificate)

    @property
    def server_sha256(self) -> str:
        return _certificate_sha256(self.server_certificate)


def _certificate_sha256(path: Path) -> str:
    try:
        pem = path.read_text(encoding="ascii")
        der = ssl.PEM_cert_to_DER_cert(pem)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid PEM certificate: {path}") from exc
    return hashlib.sha256(der).hexdigest()


def create_verified_tls_context(tls: CalibrationTLS) -> ssl.SSLContext:
    tls.validate()
    context = ssl.create_default_context(
        purpose=ssl.Purpose.SERVER_AUTH,
        cafile=str(tls.ca_certificate),
    )
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _source_binding_from_environment() -> dict[str, str]:
    binding = {
        "source_sha": os.environ.get("GATE_C_SOURCE_SHA", ""),
        "source_tree": os.environ.get("GATE_C_SOURCE_TREE", ""),
        "product_source_sha": os.environ.get("GATE_C_PRODUCT_SOURCE_SHA", ""),
        "engineering_baseline_sha": os.environ.get("GATE_C_ENGINEERING_BASELINE_SHA", ""),
        "image_id": os.environ.get("GATE_C_DIAGNOSTIC_IMAGE_ID", ""),
        "image_digest": os.environ.get("GATE_C_DIAGNOSTIC_IMAGE_DIGEST", ""),
        "image_lock_sha256": os.environ.get("GATE_C_IMAGE_LOCK_SHA256", ""),
        "build_receipt_sha256": os.environ.get("GATE_C_BUILD_RECEIPT_SHA256", ""),
        "library_sha256": os.environ.get("GATE_C_JEMALLOC_PROFILE_LIBRARY_SHA256", ""),
        "library_build_id": os.environ.get("GATE_C_JEMALLOC_PROFILE_LIBRARY_BUILD_ID", ""),
    }
    for name in ("source_sha", "source_tree", "product_source_sha", "engineering_baseline_sha"):
        if GIT_SHA.fullmatch(binding[name]) is None:
            raise ValueError(f"{name} must be a full lowercase Git SHA")
    for name in ("image_id", "image_digest"):
        if SHA256.fullmatch(binding[name]) is None:
            raise ValueError(f"{name} must be a sha256 image digest")
    for name in ("image_lock_sha256", "build_receipt_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", binding[name]) is None:
            raise ValueError(f"{name} must be a lowercase SHA256")
    if re.fullmatch(r"[0-9a-f]{64}", binding["library_sha256"]) is None:
        raise ValueError("library_sha256 must be a lowercase SHA256")
    if re.fullmatch(r"[0-9a-f]{40}", binding["library_build_id"]) is None:
        raise ValueError("library_build_id must be a lowercase build ID")
    return binding


class CalibrationTransition:
    def __init__(
        self,
        mallctl: Mallctl,
        *,
        signal_number: int | None = None,
        signal_sender: Callable[[int, int], None] = os.kill,
    ) -> None:
        self._mallctl = mallctl
        # Retain the constructor shape for callers while making ADR-0033 D
        # incapable of reaching the superseded signal/profile transition path.
        self._legacy_signal_arguments = (signal_number, signal_sender)

    def validate_capability(self) -> None:
        values = {name: self._mallctl.read_bool(name) for name in ("config.stats", "prof.active")}
        if any(value is None for value in values.values()):
            raise RuntimeError("jemalloc accounting capability readback is unavailable")
        if not values["config.stats"]:
            raise RuntimeError("jemalloc accounting capability is unavailable")
        if values["prof.active"]:
            raise RuntimeError("jemalloc profiling must remain inactive for variable D")

    @property
    def profiler_active(self) -> bool | None:
        return self._mallctl.read_bool("prof.active")

    async def apply(self, variable: str) -> dict[str, object]:
        if variable != "D":
            raise ValueError("calibration variable is invalid")
        self.validate_capability()
        started = perf_counter()
        active = self._mallctl.read_bool("prof.active")
        completed = perf_counter()
        if active is not False:
            raise RuntimeError("jemalloc profiling became active during passive calibration")
        return {
            "signal": None,
            "signal_delivered": False,
            "mode": "PASSIVE_DOMAIN_SAMPLING",
            "operations": [
                {
                    "operation": "read prof.active=false",
                    "result": 0,
                    "started_monotonic_seconds": started,
                    "completed_monotonic_seconds": completed,
                    "duration_ms": round(1000 * (completed - started), 6),
                }
            ],
            "prof_active_after_transition": False,
        }

    async def close(self) -> None:
        if self._mallctl.read_bool("prof.active") is not False:
            raise RuntimeError("jemalloc profiling became active during passive calibration")


class RuntimeSampler:
    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._samples: list[dict[str, int | float]] = []
        self._lag_ms: list[float] = []
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def samples(self) -> tuple[dict[str, int | float], ...]:
        return tuple(self._samples)

    @property
    def lag_ms(self) -> tuple[float, ...]:
        return tuple(self._lag_ms)

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("runtime sampler already started")
        self._task = asyncio.create_task(self._run(), name="rss-calibration:runtime-sampler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        previous_wall = perf_counter()
        previous_cpu = time.process_time()
        while not self._stop.is_set():
            expected = loop.time() + self._interval
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            now = perf_counter()
            cpu = time.process_time()
            memory = _read_process_memory()
            wall_delta = max(now - previous_wall, 1e-9)
            self._samples.append(
                {
                    "monotonic_seconds": now,
                    "rss_bytes": memory.get("rss_bytes", 0),
                    "rss_anon_bytes": memory.get("rss_anon_bytes", 0),
                    "cpu_one_core_units": max(0.0, (cpu - previous_cpu) / wall_delta),
                }
            )
            self._lag_ms.append(max(0.0, 1000 * (loop.time() - expected)))
            previous_wall = now
            previous_cpu = cpu


async def _run_connections(
    database_url: str,
    config: CalibrationConfig,
    tls: CalibrationTLS,
) -> dict[str, object]:
    url = make_url(database_url)
    if url.drivername != "postgresql+asyncpg":
        raise ValueError("calibration requires the postgresql+asyncpg driver")
    if url.host != tls.server_hostname:
        raise ValueError("database host does not match the verified TLS server hostname")
    ssl_context = create_verified_tls_context(tls)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        echo=False,
        connect_args={
            "command_timeout": 35.0,
            "ssl": ssl_context,
            "server_settings": {
                "application_name": "gate-c-rss-calibration",
                "timezone": "UTC",
                "statement_timeout": "30000",
                "idle_in_transaction_session_timeout": "60000",
            },
        },
    )
    semaphore = asyncio.Semaphore(config.maximum_concurrency)
    started = asyncio.get_running_loop().time()
    connection_ms: list[float] = []
    delivery_ms: list[float] = []
    failures: Counter[str] = Counter()
    backend_pids: set[int] = set()
    tls_connections = 0
    tls_versions: set[str] = set()
    tls_ciphers: set[str] = set()
    tls_bits: set[int] = set()

    async def connect(index: int) -> None:
        nonlocal tls_connections
        target = started + (index / config.admission_rate_per_second)
        await asyncio.sleep(max(0.0, target - asyncio.get_running_loop().time()))
        delivered = asyncio.get_running_loop().time()
        delivery_ms.append(max(0.0, 1000 * (delivered - target)))
        try:
            async with semaphore:
                connection_started = perf_counter()
                async with engine.connect() as connection:
                    result = await connection.execute(
                        text(
                            "SELECT pid, ssl, version, cipher, bits FROM pg_stat_ssl "
                            "WHERE pid = pg_backend_pid()"
                        )
                    )
                    row = result.one()
                    if not isinstance(row.pid, int) or row.pid <= 0:
                        raise RuntimeError("PostgreSQL did not return a backend PID")
                    if row.ssl is not True:
                        raise RuntimeError("PostgreSQL calibration connection is not TLS")
                    if (
                        not isinstance(row.version, str)
                        or not row.version.startswith("TLSv")
                        or not isinstance(row.cipher, str)
                        or not row.cipher
                        or not isinstance(row.bits, int)
                        or row.bits < 128
                    ):
                        raise RuntimeError("PostgreSQL TLS session metadata is invalid")
                    backend_pids.add(row.pid)
                    tls_connections += 1
                    tls_versions.add(row.version)
                    tls_ciphers.add(row.cipher)
                    tls_bits.add(row.bits)
                connection_ms.append(1000 * (perf_counter() - connection_started))
        except Exception as exc:
            failures[type(exc).__name__] += 1

    try:
        await asyncio.gather(*(connect(index) for index in range(config.total_connections)))
    finally:
        await engine.dispose()
    completed = asyncio.get_running_loop().time()
    successful = len(connection_ms)
    return {
        "requested": config.total_connections,
        "successful": successful,
        "failed": sum(failures.values()),
        "sample_completeness": successful / config.total_connections,
        "failure_types": dict(sorted(failures.items())),
        "distinct_backend_pids": len(backend_pids),
        "tls_connections": tls_connections,
        "tls": {
            "required": True,
            "ca_verified": tls_connections == successful,
            "hostname_verified": tls_connections == successful,
            "server_hostname": tls.server_hostname,
            "ca_certificate_sha256": tls.ca_sha256,
            "server_certificate_sha256": tls.server_sha256,
            "versions": sorted(tls_versions),
            "ciphers": sorted(tls_ciphers),
            "bits": sorted(tls_bits),
        },
        "duration_seconds": round(completed - started, 6),
        "connection_latency_ms": {
            "p50": round(percentile(connection_ms, 0.50), 6),
            "p95": round(percentile(connection_ms, 0.95), 6),
            "p99": round(percentile(connection_ms, 0.99), 6),
            "maximum": round(max(connection_ms, default=0.0), 6),
        },
        "delivery_latency_ms": {
            "p50": round(percentile(delivery_ms, 0.50), 6),
            "p95": round(percentile(delivery_ms, 0.95), 6),
            "p99": round(percentile(delivery_ms, 0.99), 6),
            "maximum": round(max(delivery_ms, default=0.0), 6),
        },
    }


def _allocator_snapshot(reader: _JemallocStatsReader) -> dict[str, object]:
    summary = reader.accounting_snapshot()
    if summary is None:
        raise RuntimeError("jemalloc statistics are unavailable")
    return {"summary": summary}


def _median_integer(values: Sequence[int]) -> int:
    if not values:
        raise BoundedMemoryInventoryRejected("bounded sampling produced no values")
    return int(median(values))


def _representative_mapping(
    before: Mapping[str, int],
    after: Mapping[str, int],
    *,
    identity_field: str,
) -> dict[str, int]:
    if set(before) != set(after) or any(
        not isinstance(value, int) for value in (*before.values(), *after.values())
    ):
        raise BoundedMemoryInventoryRejected("bounded sample domain fields changed")
    if before.get(identity_field) != after.get(identity_field):
        raise BoundedMemoryInventoryRejected(
            f"bounded sampling {identity_field} changed within a bracket"
        )
    return {name: _median_integer((before[name], after[name])) for name in before}


def _aggregate_mappings(samples: Sequence[Mapping[str, int]]) -> dict[str, int]:
    if not samples or any(set(sample) != set(samples[0]) for sample in samples[1:]):
        raise BoundedMemoryInventoryRejected("bounded sample domains are inconsistent")
    return {name: _median_integer([int(sample[name]) for sample in samples]) for name in samples[0]}


def _distribution(values: Sequence[int]) -> dict[str, int]:
    center = _median_integer(values)
    return {
        "minimum": min(values),
        "maximum": max(values),
        "median": center,
        "median_absolute_deviation": _median_integer([abs(value - center) for value in values]),
        "spread": max(values) - min(values),
    }


def _validate_identity(samples: Sequence[Mapping[str, int]], name: str) -> None:
    values = {sample.get(name) for sample in samples}
    if len(values) != 1 or None in values:
        raise BoundedMemoryInventoryRejected(f"bounded sampling {name} changed or is unavailable")


def _capture_bracketed_window(
    process_reader: Callable[[], dict[str, int]],
    cgroup_reader: Callable[[], dict[str, int]],
    allocator: _JemallocStatsReader,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> Window:
    burst_started = perf_counter()
    samples: list[dict[str, object]] = []
    process_representatives: list[dict[str, int]] = []
    cgroup_representatives: list[dict[str, int]] = []
    allocator_summaries: list[dict[str, int]] = []
    for index in range(BRACKET_SAMPLE_COUNT):
        sample_started = perf_counter()
        process_before = process_reader()
        cgroup_before = cgroup_reader()
        allocator_snapshot = _allocator_snapshot(allocator)
        cgroup_after = cgroup_reader()
        process_after = process_reader()
        sample_completed = perf_counter()
        duration = sample_completed - sample_started
        if duration > BRACKET_SAMPLE_MAX_SECONDS:
            raise BoundedMemoryInventoryRejected("bounded domain sample exceeded 250 ms")
        process_value = _representative_mapping(
            process_before,
            process_after,
            identity_field="process_id",
        )
        cgroup_value = _representative_mapping(
            cgroup_before,
            cgroup_after,
            identity_field="cgroup_inode",
        )
        summary = allocator_snapshot["summary"]
        if not isinstance(summary, Mapping) or any(
            not isinstance(value, int) for value in summary.values()
        ):
            raise BoundedMemoryInventoryRejected("bounded allocator sample is invalid")
        allocator_value = {str(name): int(value) for name, value in summary.items()}
        build_memory_ledger(process_value, cgroup_value, allocator_snapshot)
        process_representatives.append(process_value)
        cgroup_representatives.append(cgroup_value)
        allocator_summaries.append(allocator_value)
        samples.append(
            {
                "index": index + 1,
                "order": list(BRACKET_SAMPLE_ORDER),
                "started_monotonic_seconds": sample_started,
                "completed_monotonic_seconds": sample_completed,
                "duration_seconds": round(duration, 6),
                "process_before": process_before,
                "cgroup_before": cgroup_before,
                "allocator": allocator_snapshot,
                "cgroup_after": cgroup_after,
                "process_after": process_after,
                "process_representative": process_value,
                "cgroup_representative": cgroup_value,
            }
        )
        if index + 1 < BRACKET_SAMPLE_COUNT:
            sleeper(BRACKET_SAMPLE_SPACING_SECONDS)

    burst_completed = perf_counter()
    burst_duration = burst_completed - burst_started
    if burst_duration > BRACKET_BURST_MAX_SECONDS:
        raise BoundedMemoryInventoryRejected("bounded domain burst exceeded two seconds")
    _validate_identity(process_representatives, "process_id")
    _validate_identity(cgroup_representatives, "cgroup_inode")
    process = _aggregate_mappings(process_representatives)
    cgroup = _aggregate_mappings(cgroup_representatives)
    allocator_summary = _aggregate_mappings(allocator_summaries)
    rss_anon = [sample["rss_anon_bytes"] for sample in process_representatives]
    cgroup_current = [sample["memory_current_bytes"] for sample in cgroup_representatives]
    rss_distribution = _distribution(rss_anon)
    cgroup_distribution = _distribution(cgroup_current)
    for name, distribution in (
        ("RssAnon", rss_distribution),
        ("cgroup current", cgroup_distribution),
    ):
        spread_limit = max(8 * 1024 * 1024, round(distribution["median"] * 0.10))
        distribution["spread_limit"] = spread_limit
        if distribution["spread"] > spread_limit:
            raise BoundedMemoryInventoryRejected(f"bounded {name} spread exceeded its limit")
    allocator_snapshot = {"summary": allocator_summary}
    sampling = {
        "schema_version": "cybercontrol.gate-c-bracketed-domain-sampling.v1",
        "mode": "FIVE_SAMPLE_BRACKETED_DOMAIN",
        "sample_count": len(samples),
        "required_sample_count": BRACKET_SAMPLE_COUNT,
        "spacing_seconds": BRACKET_SAMPLE_SPACING_SECONDS,
        "sample_max_seconds": BRACKET_SAMPLE_MAX_SECONDS,
        "burst_max_seconds": BRACKET_BURST_MAX_SECONDS,
        "burst_started_monotonic_seconds": burst_started,
        "burst_completed_monotonic_seconds": burst_completed,
        "burst_duration_seconds": round(burst_duration, 6),
        "process_rss_anon": rss_distribution,
        "cgroup_memory_current": cgroup_distribution,
        "samples": samples,
    }
    return process, cgroup, allocator_snapshot, None, sampling


def _capture_window(
    process_reader: Callable[[], dict[str, int]],
    cgroup_reader: Callable[[], dict[str, int]],
    allocator: _JemallocStatsReader,
    *,
    bracketed: bool,
) -> Window:
    if bracketed:
        return _capture_bracketed_window(process_reader, cgroup_reader, allocator)
    return (
        process_reader(),
        cgroup_reader(),
        _allocator_snapshot(allocator),
        None,
        {"mode": "MINIMAL_CONTROL", "sample_count": 1},
    )


def _reconcile_windows(baseline: Window, recovery: Window) -> tuple[Window, Window]:
    baseline_ledger = build_memory_ledger(baseline[0], baseline[1], baseline[2])
    recovery_ledger = build_memory_ledger(recovery[0], recovery[1], recovery[2])
    return (*baseline[:3], baseline_ledger, baseline[4]), (
        *recovery[:3],
        recovery_ledger,
        recovery[4],
    )


def _failure_details(exc: Exception, phase: str) -> tuple[str, str]:
    reason = (
        str(exc)
        if isinstance(exc, BoundedMemoryInventoryRejected)
        else f"{type(exc).__name__} during {phase}"
    )
    return type(exc).__name__, reason


def _result_document(
    *,
    arm: str,
    variable: str,
    run_id: str,
    database_url: str,
    source: Mapping[str, str],
    config: CalibrationConfig,
    started_at: str,
    started: float,
    completed: float,
    transition_evidence: Mapping[str, object],
    connections: Mapping[str, object],
    sampler: RuntimeSampler,
    baseline: Window,
    recovery: Window,
    failure: str | None,
    failure_reason: str | None,
    profiler_active: bool | None,
) -> dict[str, object]:
    cpu_values = [float(sample["cpu_one_core_units"]) for sample in sampler.samples]
    rss_values = [int(sample["rss_bytes"]) for sample in sampler.samples]
    successful = int(connections.get("successful", 0))
    requested = int(connections.get("requested", config.total_connections))
    failure_types = connections.get("failure_types", {})
    tls_evidence = connections.get("tls", {})
    if not isinstance(tls_evidence, Mapping):
        tls_evidence = {}
    zero_tolerance = {
        "connection_failure": successful == requested,
        "bad_address": "OSError" not in failure_types,
        "pool_timeout": "TimeoutError" not in failure_types,
        "oom_or_unplanned_restart": failure not in {"MemoryError", "SystemExit"},
        "terminal_prof_active": profiler_active is False,
        "tls_verification": (
            successful == requested
            and int(connections.get("tls_connections", 0)) == requested
            and tls_evidence.get("required") is True
            and tls_evidence.get("ca_verified") is True
            and tls_evidence.get("hostname_verified") is True
        ),
        "evidence_integrity": failure is None,
    }
    url = make_url(database_url)
    return {
        "schema_version": "cybercontrol.gate-c-rss-calibration-arm.v1",
        "process_version": PROCESS_VERSION,
        "classification": CLASSIFICATION,
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "run_id": run_id,
        "arm": arm,
        "variable": variable,
        "source": dict(source),
        "config": asdict(config),
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "started_monotonic_seconds": started,
        "completed_monotonic_seconds": completed,
        "duration_seconds": round(completed - started, 6),
        "database": {
            "driver": url.drivername,
            "host": url.host,
            "database": url.database,
            "credentials_recorded": False,
            "tls": dict(tls_evidence),
        },
        "transition": dict(transition_evidence),
        "connections": dict(connections),
        "runtime": {
            "samples": len(sampler.samples),
            "cpu_one_core_units_p95": round(percentile(cpu_values, 0.95), 6),
            "event_loop_lag_p95_ms": round(percentile(sampler.lag_ms, 0.95), 6),
            "peak_rss_bytes": max(rss_values, default=0),
        },
        "windows": {
            "baseline": {
                "process": baseline[0],
                "cgroup": baseline[1],
                "allocator": baseline[2],
                "ledger": baseline[3],
                "sampling": baseline[4],
            },
            "recovery": {
                "process": recovery[0],
                "cgroup": recovery[1],
                "allocator": recovery[2],
                "ledger": recovery[3],
                "sampling": recovery[4],
            },
        },
        "zero_tolerance": zero_tolerance,
        "failure_type": failure,
        "reason": failure_reason,
        "passed": all(zero_tolerance.values()) and successful == config.total_connections,
    }


async def run_calibration(
    *,
    arm: str,
    variable: str,
    run_id: str,
    database_url: str,
    source: Mapping[str, str],
    config: CalibrationConfig,
    tls: CalibrationTLS,
    mallctl: Mallctl | None = None,
    allocator_reader: _JemallocStatsReader | None = None,
    transition: CalibrationTransition | None = None,
    process_reader: Callable[[], dict[str, int]] = _read_process_memory,
    cgroup_reader: Callable[[], dict[str, int]] = _read_cgroup_memory,
    connection_runner: Callable[
        [str, CalibrationConfig, CalibrationTLS], Coroutine[Any, Any, dict[str, object]]
    ] = _run_connections,
) -> dict[str, object]:
    if arm not in ARMS or variable not in VARIABLES:
        raise ValueError("calibration arm or variable is invalid")
    config.validate()
    tls.validate()
    sampler = RuntimeSampler(config.sample_interval_seconds)
    transition = transition or CalibrationTransition(mallctl or _Mallctl())
    allocator = allocator_reader or _JemallocStatsReader()
    started_at = datetime.now(UTC).isoformat()
    started = perf_counter()
    sampler.start()
    transition_evidence: dict[str, object] = {
        "signal_delivered": False,
        "operations": [],
        "prof_active_after_transition": False,
    }
    baseline: Window = ({}, {}, {}, None, {})
    recovery: Window = ({}, {}, {}, None, {})
    connections: dict[str, object] = {}
    failure: str | None = None
    failure_reason: str | None = None
    try:
        transition.validate_capability()
        if config.idle_seconds:
            await asyncio.sleep(config.idle_seconds)
        baseline = _capture_window(
            process_reader, cgroup_reader, allocator, bracketed=arm == "Measurement"
        )
        if arm == "Measurement":
            transition_evidence = {
                "signal_delivered": False,
                "operations": [
                    {
                        "operation": "five-sample bracketed domain capture",
                        "result": 0,
                    }
                ],
                "prof_active_after_transition": False,
                "sampling_enabled": True,
            }
        connections = await connection_runner(database_url, config, tls)
        await transition.close()
        if config.recovery_seconds:
            await asyncio.sleep(config.recovery_seconds)
        recovery = _capture_window(
            process_reader, cgroup_reader, allocator, bracketed=arm == "Measurement"
        )
    except asyncio.CancelledError:
        with suppress(Exception):
            await asyncio.shield(transition.close())
        raise
    except Exception as exc:
        failure, failure_reason = _failure_details(exc, "calibration execution")
        try:
            await transition.close()
        except Exception:
            failure = f"{failure}+TransitionCloseFailure"
            failure_reason = f"{failure_reason}; passive transition close failed"
    finally:
        await sampler.stop()

    if failure is None:
        try:
            baseline, recovery = _reconcile_windows(baseline, recovery)
        except Exception as exc:
            failure, failure_reason = _failure_details(exc, "ledger reconciliation")

    completed = perf_counter()
    return _result_document(
        arm=arm,
        variable=variable,
        run_id=run_id,
        database_url=database_url,
        source=source,
        config=config,
        started_at=started_at,
        started=started,
        completed=completed,
        transition_evidence=transition_evidence,
        connections=connections,
        sampler=sampler,
        baseline=baseline,
        recovery=recovery,
        failure=failure,
        failure_reason=failure_reason,
        profiler_active=transition.profiler_active,
    )


def _write_new_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")


def instrumentation_readiness(
    *, arm: str, variable: str, run_id: str, source: dict[str, str]
) -> dict[str, object]:
    return {
        "schema_version": "cybercontrol.gate-c-rss-calibration-readiness.v1",
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "run_id": run_id,
        "arm": arm,
        "variable": variable,
        "source": source,
        "database_credentials_recorded": False,
        "ready": True,
        "ready_at_utc": datetime.now(UTC).isoformat(),
    }


def _database_url_from_arguments(arguments: argparse.Namespace) -> str:
    if arguments.database_url:
        return str(arguments.database_url)
    password_path = arguments.database_password_file
    if not password_path.is_absolute() or not password_path.is_file() or password_path.is_symlink():
        raise ValueError("calibration database password file must be an absolute regular file")
    password = password_path.read_text(encoding="utf-8").strip()
    if not password or "\n" in password or "\r" in password:
        raise ValueError("calibration database password file is invalid")
    return URL.create(
        "postgresql+asyncpg",
        username=arguments.database_user,
        password=password,
        host=arguments.database_host,
        port=arguments.database_port,
        database=arguments.database_name,
    ).render_as_string(hide_password=False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one ADR-0033 RSS calibration arm.")
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--variable", choices=VARIABLES, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--database-url", default=os.getenv("LIYAN_DATABASE_URL", ""))
    parser.add_argument("--database-host", default="postgres")
    parser.add_argument("--database-port", type=int, default=5432)
    parser.add_argument("--database-name", default="gate_c_calibration")
    parser.add_argument("--database-user", default="gate_c_calibration")
    parser.add_argument(
        "--database-password-file",
        type=Path,
        default=Path("/run/gate-c-secrets/postgres-password"),
    )
    parser.add_argument(
        "--tls-ca",
        type=Path,
        default=Path(os.getenv("GATE_C_POSTGRES_TLS_CA", "/run/gate-c-tls/ca.crt")),
    )
    parser.add_argument(
        "--tls-server-certificate",
        type=Path,
        default=Path(os.getenv("GATE_C_POSTGRES_TLS_SERVER_CERT", "/run/gate-c-tls/server.crt")),
    )
    parser.add_argument(
        "--tls-server-hostname",
        default=os.getenv("GATE_C_POSTGRES_TLS_SERVER_HOSTNAME", "postgres"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--readiness-output", type=Path, required=True)
    parser.add_argument("--idle-seconds", type=int, default=300)
    parser.add_argument("--recovery-seconds", type=int, default=600)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.readiness_output.resolve() == arguments.output.resolve():
        raise ValueError("calibration readiness and result outputs must be distinct")
    database_url = _database_url_from_arguments(arguments)
    source = _source_binding_from_environment()
    config = CalibrationConfig(
        idle_seconds=arguments.idle_seconds,
        recovery_seconds=arguments.recovery_seconds,
    )
    _write_new_json(
        arguments.readiness_output,
        instrumentation_readiness(
            arm=arguments.arm,
            variable=arguments.variable,
            run_id=arguments.run_id,
            source=source,
        ),
    )
    document = asyncio.run(
        run_calibration(
            arm=arguments.arm,
            variable=arguments.variable,
            run_id=arguments.run_id,
            database_url=database_url,
            source=source,
            config=config,
            tls=CalibrationTLS(
                ca_certificate=arguments.tls_ca,
                server_certificate=arguments.tls_server_certificate,
                server_hostname=arguments.tls_server_hostname,
            ),
        )
    )
    _write_new_json(arguments.output, document)
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
