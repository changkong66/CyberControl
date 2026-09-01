from __future__ import annotations

import asyncio
import json
import ssl
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOAD_ROOT = ROOT / "tests" / "load"
if str(LOAD_ROOT) not in sys.path:
    sys.path.insert(0, str(LOAD_ROOT))

from gate_c.generate_calibration_tls import generate_tls_material  # noqa: E402
from gate_c.rss_calibration import (  # noqa: E402
    CalibrationConfig,
    CalibrationTLS,
    CalibrationTransition,
    create_verified_tls_context,
    instrumentation_readiness,
    percentile,
    run_calibration,
)
from gate_c.rss_calibration_compare import compare_arms  # noqa: E402


class FakeMallctl:
    def __init__(self) -> None:
        self.values = {
            "config.prof": True,
            "config.stats": True,
            "opt.prof": True,
            "prof.active": False,
        }
        self.calls: list[tuple[str, object]] = []

    def read_bool(self, name: str) -> bool | None:
        self.calls.append(("read", name))
        return self.values.get(name)

    def reset(self) -> int:
        self.calls.append(("reset", None))
        return 0

    def write_bool(self, name: str, value: bool) -> int:
        self.calls.append(("write", (name, value)))
        self.values[name] = value
        return 0


class FakeAllocator:
    def snapshot(self) -> dict[str, int]:
        return {
            "allocated": 100,
            "active": 120,
            "resident": 150,
            "retained": 0,
            "arenas": 1,
        }


class BlockingTransition:
    def __init__(self) -> None:
        self.closed = False

    @property
    def profiler_active(self) -> bool:
        return False

    def validate_capability(self) -> None:
        return None

    async def apply(self, _variable: str) -> dict[str, object]:
        return {
            "signal_delivered": True,
            "operations": [],
            "prof_active_after_transition": False,
        }

    async def close(self) -> None:
        self.closed = True


SOURCE = {
    "source_sha": "a" * 40,
    "source_tree": "b" * 40,
    "product_source_sha": "c" * 40,
    "engineering_baseline_sha": "d" * 40,
    "image_id": "sha256:" + "1" * 64,
    "image_digest": "sha256:" + "2" * 64,
    "image_lock_sha256": "3" * 64,
    "build_receipt_sha256": "4" * 64,
    "library_sha256": "e" * 64,
    "library_build_id": "f" * 40,
}
PROCESS = {
    "rss_bytes": 300,
    "rss_anon_bytes": 200,
    "rss_file_bytes": 90,
    "rss_shmem_bytes": 10,
}
CGROUP = {
    "memory_current_bytes": 500,
    "file_bytes": 50,
    "kernel_bytes": 50,
    "other_process_rss_bytes": 0,
    "unreadable_process_count": 0,
}


def _tls(tmp_path: Path, name: str = "tls", hostname: str = "postgres") -> CalibrationTLS:
    directory = tmp_path / name
    directory.mkdir()
    generate_tls_material(directory, hostname)
    return CalibrationTLS(
        ca_certificate=(directory / "ca.crt").resolve(),
        server_certificate=(directory / "server.crt").resolve(),
        server_hostname=hostname,
    )


def _connection_result(tls: CalibrationTLS, total: int = 4) -> dict[str, object]:
    return {
        "requested": total,
        "successful": total,
        "failed": 0,
        "sample_completeness": 1.0,
        "failure_types": {},
        "distinct_backend_pids": total,
        "tls_connections": total,
        "tls": {
            "required": True,
            "ca_verified": True,
            "hostname_verified": True,
            "server_hostname": tls.server_hostname,
            "ca_certificate_sha256": tls.ca_sha256,
            "server_certificate_sha256": tls.server_sha256,
            "versions": ["TLSv1.3"],
            "ciphers": ["TLS_AES_256_GCM_SHA384"],
            "bits": [256],
        },
        "duration_seconds": 0.01,
        "connection_latency_ms": {"p50": 1.0, "p95": 2.0, "p99": 2.0, "maximum": 2.0},
        "delivery_latency_ms": {"p50": 0.1, "p95": 0.2, "p99": 0.2, "maximum": 0.2},
    }


def test_percentile_is_nearest_rank_and_validated() -> None:
    assert percentile([4, 1, 3, 2], 0.50) == 2
    assert percentile([4, 1, 3, 2], 0.95) == 4
    assert percentile([], 0.95) == 0
    with pytest.raises(ValueError, match="between"):
        percentile([1], 1.1)


def test_instrumentation_readiness_is_source_bound_and_non_formal() -> None:
    readiness = instrumentation_readiness(
        arm="A", variable="S", run_id="calibration-ready", source=SOURCE
    )

    assert readiness["schema_version"] == "cybercontrol.gate-c-rss-calibration-readiness.v1"
    assert readiness["process_version"] == "Gate-C-12-v1.0"
    assert readiness["classification"] == "NON_ACCEPTANCE_DIAGNOSTIC"
    assert readiness["formal_gate_attempt"] is False
    assert readiness["acceptance_claim"] is False
    assert readiness["source"] == SOURCE
    assert readiness["database_credentials_recorded"] is False
    assert readiness["ready"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("variable", "expected_operations", "active_after"),
    (
        ("S", ["read prof.active=false"], False),
        ("R", ["prof.reset"], False),
        ("P", ["prof.active=true"], True),
        ("F", ["prof.reset", "prof.active=true"], True),
    ),
)
async def test_transition_changes_exactly_one_declared_variable(
    variable: str,
    expected_operations: list[str],
    active_after: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mallctl = FakeMallctl()
    transition = CalibrationTransition(mallctl, signal_number=12)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args: None)
    monkeypatch.setattr(loop, "remove_signal_handler", lambda *_args: True)
    transition._signal_sender = lambda *_args: transition._handle_signal()

    evidence = await transition.apply(variable)

    assert [item["operation"] for item in evidence["operations"]] == expected_operations
    assert evidence["prof_active_after_transition"] is active_after
    await transition.close()
    assert mallctl.values["prof.active"] is False


@pytest.mark.asyncio
async def test_calibration_control_is_non_formal_and_reconciles_ledgers(tmp_path: Path) -> None:
    tls = _tls(tmp_path)

    async def connections(
        _url: str, config: CalibrationConfig, connection_tls: CalibrationTLS
    ) -> dict[str, object]:
        return _connection_result(connection_tls, config.total_connections)

    result = await run_calibration(
        arm="A",
        variable="S",
        run_id="calibration-a",
        database_url="postgresql+asyncpg://user:secret@postgres:5432/liyans",
        source=SOURCE,
        tls=tls,
        config=CalibrationConfig(
            total_connections=4,
            maximum_concurrency=2,
            admission_rate_per_second=50,
            idle_seconds=0,
            recovery_seconds=0,
            sample_interval_seconds=0.01,
        ),
        mallctl=FakeMallctl(),
        allocator_reader=FakeAllocator(),  # type: ignore[arg-type]
        process_reader=lambda: PROCESS,
        cgroup_reader=lambda: CGROUP,
        connection_runner=connections,
    )

    assert result["passed"] is True
    assert result["formal_gate_attempt"] is False
    assert result["acceptance_claim"] is False
    assert result["database"]["credentials_recorded"] is False
    assert result["database"]["tls"]["hostname_verified"] is True
    assert "secret" not in str(result)
    assert result["windows"]["recovery"]["ledger"]["rss_anon_bytes"] == 200


@pytest.mark.asyncio
async def test_calibration_cancellation_cleans_up_and_propagates(tmp_path: Path) -> None:
    tls = _tls(tmp_path)
    transition = BlockingTransition()
    entered = asyncio.Event()

    async def connections(
        _url: str, _config: CalibrationConfig, _tls_value: CalibrationTLS
    ) -> dict[str, object]:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    task = asyncio.create_task(
        run_calibration(
            arm="A",
            variable="S",
            run_id="cancelled-calibration",
            database_url="postgresql+asyncpg://user:secret@postgres:5432/liyans",
            source=SOURCE,
            config=CalibrationConfig(
                total_connections=1,
                maximum_concurrency=1,
                admission_rate_per_second=1,
                idle_seconds=0,
                recovery_seconds=0,
                sample_interval_seconds=0.01,
            ),
            tls=tls,
            transition=transition,  # type: ignore[arg-type]
            allocator_reader=FakeAllocator(),  # type: ignore[arg-type]
            process_reader=lambda: PROCESS,
            cgroup_reader=lambda: CGROUP,
            connection_runner=connections,
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert transition.closed is True


def test_tls_generator_is_ephemeral_bounded_and_fail_closed(tmp_path: Path) -> None:
    tls = _tls(tmp_path)
    manifest = json.loads((tls.ca_certificate.parent / "tls-manifest.json").read_text())

    assert manifest["process_version"] == "Gate-C-12-v1.0"
    assert manifest["server_hostname"] == "postgres"
    assert manifest["ca_private_key_persisted"] is False
    assert "PRIVATE KEY" not in str(manifest)
    assert not (tls.ca_certificate.parent / "ca.key").exists()
    assert len(tls.ca_sha256) == 64
    with pytest.raises(FileExistsError, match="already exists"):
        generate_tls_material(tls.ca_certificate.parent, "postgres")


async def _perform_tls_handshake(
    tls: CalibrationTLS,
    client_context: ssl.SSLContext,
    server_hostname: str,
) -> None:
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(
        str(tls.server_certificate), str(tls.server_certificate.parent / "server.key")
    )

    async def close_client(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(close_client, "127.0.0.1", 0, ssl=server_context)
    try:
        port = int(server.sockets[0].getsockname()[1])
        _reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            port,
            ssl=client_context,
            server_hostname=server_hostname,
        )
        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_tls_context_verifies_ca_and_hostname(tmp_path: Path) -> None:
    tls = _tls(tmp_path)
    await _perform_tls_handshake(tls, create_verified_tls_context(tls), "postgres")

    wrong_ca = _tls(tmp_path, "wrong-ca")
    with pytest.raises(ssl.SSLCertVerificationError):
        await _perform_tls_handshake(tls, create_verified_tls_context(wrong_ca), "postgres")
    with pytest.raises(ssl.SSLCertVerificationError):
        await _perform_tls_handshake(tls, create_verified_tls_context(tls), "not-postgres")


@pytest.mark.asyncio
async def test_non_tls_database_result_is_zero_tolerance_failure(tmp_path: Path) -> None:
    tls = _tls(tmp_path)

    async def non_tls_connections(
        _url: str, config: CalibrationConfig, connection_tls: CalibrationTLS
    ) -> dict[str, object]:
        result = _connection_result(connection_tls, config.total_connections)
        result["tls_connections"] = 0
        result["tls"] = {
            **result["tls"],
            "ca_verified": False,
            "hostname_verified": False,
            "versions": [],
            "ciphers": [],
            "bits": [],
        }
        return result

    result = await run_calibration(
        arm="A",
        variable="S",
        run_id="calibration-non-tls",
        database_url="postgresql+asyncpg://user:secret@postgres:5432/liyans",
        source=SOURCE,
        config=CalibrationConfig(
            total_connections=1,
            maximum_concurrency=1,
            idle_seconds=0,
            recovery_seconds=0,
            sample_interval_seconds=0.01,
        ),
        tls=tls,
        mallctl=FakeMallctl(),
        allocator_reader=FakeAllocator(),  # type: ignore[arg-type]
        process_reader=lambda: PROCESS,
        cgroup_reader=lambda: CGROUP,
        connection_runner=non_tls_connections,
    )

    assert result["zero_tolerance"]["tls_verification"] is False
    assert result["passed"] is False


def _arm(name: str, *, multiplier: float = 1.0) -> dict[str, object]:
    return {
        "schema_version": "cybercontrol.gate-c-rss-calibration-arm.v1",
        "process_version": "Gate-C-12-v1.0",
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "run_id": f"run-{name}",
        "arm": name,
        "variable": "S",
        "source": SOURCE,
        "config": {"fixed": True},
        "database": {"driver": "postgresql+asyncpg", "host": "postgres"},
        "connections": {
            "sample_completeness": 1.0,
            "connection_latency_ms": {"p95": 10 * multiplier},
            "delivery_latency_ms": {"p95": 2 * multiplier},
        },
        "runtime": {
            "cpu_one_core_units_p95": 0.2 * multiplier,
            "event_loop_lag_p95_ms": 1 * multiplier,
        },
        "windows": {
            "baseline": {"process": {"rss_bytes": 100}},
            "recovery": {"process": {"rss_bytes": 110}},
        },
        "zero_tolerance": {"evidence_integrity": True},
        "passed": True,
    }


def test_comparator_applies_exact_interference_formulas() -> None:
    result = compare_arms(_arm("A"), _arm("Measurement", multiplier=1.05), _arm("APrime"))

    assert result["passed"] is True
    assert result["metrics"]["connection_p95_ms"]["measurement_to_control_ratio"] == 1.05
    assert result["rss"]["limit_bytes"] == 8 * 1024 * 1024


def test_comparator_rejects_drift_and_cross_source_arms() -> None:
    result = compare_arms(_arm("A"), _arm("Measurement"), _arm("APrime", multiplier=1.5))
    assert result["passed"] is False

    wrong_source = _arm("APrime")
    wrong_source["source"] = {**SOURCE, "source_sha": "9" * 40}
    with pytest.raises(ValueError, match="same source"):
        compare_arms(_arm("A"), _arm("Measurement"), wrong_source)
