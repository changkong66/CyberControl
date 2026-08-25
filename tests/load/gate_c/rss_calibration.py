from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import signal
import ssl
import time
from collections import Counter
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from liyans.infrastructure.observability.bounded_memory_inventory import (
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

PROCESS_VERSION = "Gate-C-12-v1.0"
CLASSIFICATION = "NON_ACCEPTANCE_DIAGNOSTIC"
ARMS = ("A", "Measurement", "APrime")
VARIABLES = ("S", "R", "P", "F")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
Window = tuple[dict[str, int], dict[str, int], dict[str, object], dict[str, object] | None]


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
        signal_number: int | None = getattr(signal, "SIGUSR2", None),
        signal_sender: Callable[[int, int], None] = os.kill,
    ) -> None:
        self._mallctl = mallctl
        self._signal_number = signal_number
        self._signal_sender = signal_sender
        self._loop: asyncio.AbstractEventLoop | None = None
        self._transition: asyncio.Task[None] | None = None
        self._completed = asyncio.Event()
        self._variable = ""
        self._requested_at = 0.0
        self._operations: list[dict[str, int | str | bool]] = []
        self._activated = False
        self._signal_installed = False
        self._error: BaseException | None = None

    def validate_capability(self) -> None:
        values = {
            name: self._mallctl.read_bool(name)
            for name in ("config.prof", "config.stats", "opt.prof", "prof.active")
        }
        if any(value is None for value in values.values()):
            raise RuntimeError("jemalloc profiling capability readback is unavailable")
        if not values["config.prof"] or not values["config.stats"] or not values["opt.prof"]:
            raise RuntimeError("jemalloc profiling capability is unavailable")
        if values["prof.active"]:
            raise RuntimeError("jemalloc profiling must start inactive")

    @property
    def profiler_active(self) -> bool | None:
        return self._mallctl.read_bool("prof.active")

    async def apply(self, variable: str) -> dict[str, object]:
        if variable not in VARIABLES:
            raise ValueError("calibration variable is invalid")
        if self._signal_number is None:
            raise RuntimeError("calibration signal is unavailable")
        self.validate_capability()
        self._variable = variable
        self._loop = asyncio.get_running_loop()
        try:
            self._loop.add_signal_handler(self._signal_number, self._handle_signal)
        except (NotImplementedError, RuntimeError) as exc:
            raise RuntimeError("calibration signal ownership is unavailable") from exc
        self._signal_installed = True
        self._requested_at = perf_counter()
        self._signal_sender(os.getpid(), self._signal_number)
        await asyncio.wait_for(self._completed.wait(), timeout=5.0)
        if self._transition is not None:
            await self._transition
        if self._error is not None:
            raise self._error
        return {
            "signal": int(self._signal_number),
            "delivery_latency_ms": round(
                1000
                * (float(self._operations[0]["started_monotonic_seconds"]) - self._requested_at),
                6,
            ),
            "operations": self._operations,
            "prof_active_after_transition": bool(self._mallctl.read_bool("prof.active")),
        }

    def _handle_signal(self) -> None:
        if self._loop is None or self._transition is not None:
            self._error = RuntimeError("calibration signal was duplicated or out of order")
            self._completed.set()
            return
        self._transition = self._loop.create_task(
            self._apply_variable(),
            name=f"rss-calibration:{self._variable}",
        )
        self._transition.add_done_callback(self._transition_finished)

    def _transition_finished(self, task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except BaseException as exc:
            self._error = exc
        finally:
            self._completed.set()

    async def _apply_variable(self) -> None:
        await asyncio.sleep(0)
        started = perf_counter()
        if self._variable == "S":
            active = self._mallctl.read_bool("prof.active")
            if active is not False:
                raise RuntimeError("S mallctl no-op did not verify inactive profiling")
            result = 0
            operation = "read prof.active=false"
        elif self._variable == "R":
            result = self._mallctl.reset()
            operation = "prof.reset"
        elif self._variable == "P":
            result = self._mallctl.write_bool("prof.active", True)
            operation = "prof.active=true"
            self._activated = result == 0
        else:
            reset_result = self._mallctl.reset()
            self._record_operation("prof.reset", reset_result, started)
            if reset_result != 0:
                raise RuntimeError(f"prof.reset failed with mallctl code {reset_result}")
            started = perf_counter()
            result = self._mallctl.write_bool("prof.active", True)
            operation = "prof.active=true"
            self._activated = result == 0
        self._record_operation(operation, result, started)
        if result != 0:
            raise RuntimeError(f"{operation} failed with mallctl code {result}")

    def _record_operation(self, operation: str, result: int, started: float) -> None:
        completed = perf_counter()
        self._operations.append(
            {
                "operation": operation,
                "result": result,
                "started_monotonic_seconds": started,
                "completed_monotonic_seconds": completed,
                "duration_ms": round(1000 * (completed - started), 6),
            }
        )

    async def close(self) -> None:
        try:
            if self._activated:
                started = perf_counter()
                result = self._mallctl.write_bool("prof.active", False)
                self._record_operation("prof.active=false", result, started)
                if result != 0:
                    raise RuntimeError(f"prof.active=false failed with mallctl code {result}")
                self._activated = False
            if self._mallctl.read_bool("prof.active") is not False:
                raise RuntimeError("jemalloc profiling remained active after calibration")
        finally:
            if (
                self._signal_installed
                and self._loop is not None
                and self._signal_number is not None
            ):
                self._loop.remove_signal_handler(self._signal_number)
            self._signal_installed = False
            self._loop = None


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
    summary = reader.snapshot()
    if summary is None:
        raise RuntimeError("jemalloc statistics are unavailable")
    return {"summary": summary}


def _capture_window(
    process_reader: Callable[[], dict[str, int]],
    cgroup_reader: Callable[[], dict[str, int]],
    allocator: _JemallocStatsReader,
) -> Window:
    return process_reader(), cgroup_reader(), _allocator_snapshot(allocator), None


def _reconcile_windows(baseline: Window, recovery: Window) -> tuple[Window, Window]:
    baseline_ledger = build_memory_ledger(baseline[0], baseline[1], baseline[2])
    recovery_ledger = build_memory_ledger(recovery[0], recovery[1], recovery[2])
    return (*baseline[:3], baseline_ledger), (*recovery[:3], recovery_ledger)


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
            },
            "recovery": {
                "process": recovery[0],
                "cgroup": recovery[1],
                "allocator": recovery[2],
                "ledger": recovery[3],
            },
        },
        "zero_tolerance": zero_tolerance,
        "failure_type": failure,
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
    baseline: Window = ({}, {}, {}, None)
    recovery: Window = ({}, {}, {}, None)
    connections: dict[str, object] = {}
    failure: str | None = None
    try:
        transition.validate_capability()
        if config.idle_seconds:
            await asyncio.sleep(config.idle_seconds)
        baseline = _capture_window(process_reader, cgroup_reader, allocator)
        if arm == "Measurement":
            transition_evidence = await transition.apply(variable)
            transition_evidence["signal_delivered"] = True
        connections = await connection_runner(database_url, config, tls)
        await transition.close()
        if config.recovery_seconds:
            await asyncio.sleep(config.recovery_seconds)
        recovery = _capture_window(process_reader, cgroup_reader, allocator)
    except asyncio.CancelledError:
        with suppress(Exception):
            await asyncio.shield(transition.close())
        raise
    except Exception as exc:
        failure = type(exc).__name__
        try:
            await transition.close()
        except Exception:
            failure = f"{failure}+TransitionCloseFailure"
    finally:
        await sampler.stop()

    if failure is None:
        try:
            baseline, recovery = _reconcile_windows(baseline, recovery)
        except Exception as exc:
            failure = type(exc).__name__

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
        profiler_active=transition.profiler_active,
    )


def _write_new_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")


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
    parser = argparse.ArgumentParser(description="Run one ADR-0032 RSS calibration arm.")
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
    parser.add_argument("--idle-seconds", type=int, default=300)
    parser.add_argument("--recovery-seconds", type=int, default=600)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    database_url = _database_url_from_arguments(arguments)
    config = CalibrationConfig(
        idle_seconds=arguments.idle_seconds,
        recovery_seconds=arguments.recovery_seconds,
    )
    document = asyncio.run(
        run_calibration(
            arm=arguments.arm,
            variable=arguments.variable,
            run_id=arguments.run_id,
            database_url=database_url,
            source=_source_binding_from_environment(),
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
