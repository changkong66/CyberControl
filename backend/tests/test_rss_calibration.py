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

import gate_c.rss_calibration as calibration_module  # noqa: E402
from gate_c.generate_calibration_tls import generate_tls_material  # noqa: E402
from gate_c.rss_calibration import (  # noqa: E402
    BRACKET_SAMPLE_ORDER,
    CalibrationConfig,
    CalibrationTLS,
    CalibrationTransition,
    _capture_bracketed_window,
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
    def accounting_snapshot(self) -> dict[str, int]:
        return {
            "allocated": 100,
            "active": 120,
            "resident": 150,
            "mapped": 180,
            "metadata": 10,
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
    "process_id": 123,
    "rss_bytes": 300,
    "rss_anon_bytes": 200,
    "rss_file_bytes": 90,
    "rss_shmem_bytes": 10,
    "pss_bytes": 280,
    "uss_bytes": 260,
    "swap_bytes": 0,
    "fd_count": 7,
    "map_count": 11,
}
CGROUP = {
    "cgroup_inode": 456,
    "memory_current_bytes": 500,
    "anon_bytes": 350,
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
        arm="A", variable="D", run_id="calibration-ready", source=SOURCE
    )

    assert readiness["schema_version"] == "cybercontrol.gate-c-rss-calibration-readiness.v1"
    assert readiness["process_version"] == "Gate-C-12-v2.0"
    assert readiness["classification"] == "NON_ACCEPTANCE_DIAGNOSTIC"
    assert readiness["formal_gate_attempt"] is False
    assert readiness["acceptance_claim"] is False
    assert readiness["source"] == SOURCE
    assert readiness["database_credentials_recorded"] is False
    assert readiness["ready"] is True


@pytest.mark.asyncio
async def test_variable_d_is_passive_and_cannot_reach_legacy_profile_transitions() -> None:
    mallctl = FakeMallctl()
    signal_calls: list[tuple[int, int]] = []
    transition = CalibrationTransition(
        mallctl,
        signal_number=12,
        signal_sender=lambda pid, number: signal_calls.append((pid, number)),
    )

    evidence = await transition.apply("D")

    assert evidence["mode"] == "PASSIVE_DOMAIN_SAMPLING"
    assert evidence["signal_delivered"] is False
    assert [item["operation"] for item in evidence["operations"]] == ["read prof.active=false"]
    assert signal_calls == []
    assert not any(call[0] in {"reset", "write"} for call in mallctl.calls)
    with pytest.raises(ValueError, match="variable is invalid"):
        await transition.apply("F")
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
        variable="D",
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
    assert result["windows"]["recovery"]["sampling"] == {
        "mode": "MINIMAL_CONTROL",
        "sample_count": 1,
    }
    assert result["windows"]["recovery"]["ledger"]["linux_process"]["rss_anon_bytes"] == 200


@pytest.mark.asyncio
async def test_calibration_preserves_bounded_structural_failure_reason(tmp_path: Path) -> None:
    tls = _tls(tmp_path)

    async def connections(
        _url: str, config: CalibrationConfig, connection_tls: CalibrationTLS
    ) -> dict[str, object]:
        return _connection_result(connection_tls, config.total_connections)

    result = await run_calibration(
        arm="A",
        variable="D",
        run_id="calibration-invalid-ledger",
        database_url="postgresql+asyncpg://user:secret@postgres:5432/liyans",
        source=SOURCE,
        tls=tls,
        config=CalibrationConfig(
            total_connections=1,
            maximum_concurrency=1,
            idle_seconds=0,
            recovery_seconds=0,
            sample_interval_seconds=0.01,
        ),
        mallctl=FakeMallctl(),
        allocator_reader=FakeAllocator(),  # type: ignore[arg-type]
        process_reader=lambda: {
            **PROCESS,
            "rss_bytes": 4 * 1024 * 1024,
            "rss_anon_bytes": 1,
            "rss_file_bytes": 0,
            "rss_shmem_bytes": 0,
        },
        cgroup_reader=lambda: CGROUP,
        connection_runner=connections,
    )

    assert result["passed"] is False
    assert result["failure_type"] == "BoundedMemoryInventoryRejected"
    assert result["reason"] == "Linux process RSS components do not reconcile"
    assert "secret" not in str(result)


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
            variable="D",
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

    assert manifest["process_version"] == "Gate-C-12-v2.0"
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
        variable="D",
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


def test_bracketed_sampling_uses_five_fixed_order_samples() -> None:
    events: list[str] = []

    class LoggingAllocator(FakeAllocator):
        def accounting_snapshot(self) -> dict[str, int]:
            events.append("jemalloc_epoch_and_stats")
            return super().accounting_snapshot()

    def process_reader() -> dict[str, int]:
        events.append("process")
        return dict(PROCESS)

    def cgroup_reader() -> dict[str, int]:
        events.append("cgroup")
        return dict(CGROUP)

    window = _capture_bracketed_window(
        process_reader,
        cgroup_reader,
        LoggingAllocator(),  # type: ignore[arg-type]
        sleeper=lambda _seconds: None,
    )

    assert events == ["process", "cgroup", "jemalloc_epoch_and_stats", "cgroup", "process"] * 5
    assert window[4]["sample_count"] == 5
    assert all(sample["order"] == list(BRACKET_SAMPLE_ORDER) for sample in window[4]["samples"])


def test_bracketed_sampling_fails_closed_on_duration_identity_and_spread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter((0.0, 0.0, 0.3))
    monkeypatch.setattr(calibration_module, "perf_counter", lambda: next(ticks))
    with pytest.raises(calibration_module.BoundedMemoryInventoryRejected, match="250 ms"):
        _capture_bracketed_window(
            lambda: dict(PROCESS),
            lambda: dict(CGROUP),
            FakeAllocator(),  # type: ignore[arg-type]
            sleeper=lambda _seconds: None,
        )

    monkeypatch.undo()
    process_calls = 0

    def changed_process() -> dict[str, int]:
        nonlocal process_calls
        sample = process_calls // 2
        process_calls += 1
        return {**PROCESS, "process_id": 123 if sample == 0 else 124}

    with pytest.raises(calibration_module.BoundedMemoryInventoryRejected, match="process_id"):
        _capture_bracketed_window(
            changed_process,
            lambda: dict(CGROUP),
            FakeAllocator(),  # type: ignore[arg-type]
            sleeper=lambda _seconds: None,
        )

    process_calls = 0

    def changed_process_within_bracket() -> dict[str, int]:
        nonlocal process_calls
        process_calls += 1
        return {**PROCESS, "process_id": 123 if process_calls % 2 else 124}

    with pytest.raises(calibration_module.BoundedMemoryInventoryRejected, match="within a bracket"):
        _capture_bracketed_window(
            changed_process_within_bracket,
            lambda: dict(CGROUP),
            FakeAllocator(),  # type: ignore[arg-type]
            sleeper=lambda _seconds: None,
        )

    cgroup_calls = 0

    def changed_cgroup() -> dict[str, int]:
        nonlocal cgroup_calls
        sample = cgroup_calls // 2
        cgroup_calls += 1
        return {**CGROUP, "cgroup_inode": 456 if sample == 0 else 789}

    with pytest.raises(calibration_module.BoundedMemoryInventoryRejected, match="cgroup_inode"):
        _capture_bracketed_window(
            lambda: dict(PROCESS),
            changed_cgroup,
            FakeAllocator(),  # type: ignore[arg-type]
            sleeper=lambda _seconds: None,
        )

    process_calls = 0

    def unstable_process() -> dict[str, int]:
        nonlocal process_calls
        sample = process_calls // 2
        process_calls += 1
        rss_anon = 200 if sample < 4 else 10 * 1024 * 1024
        return {
            **PROCESS,
            "rss_bytes": rss_anon + 100,
            "rss_anon_bytes": rss_anon,
        }

    with pytest.raises(calibration_module.BoundedMemoryInventoryRejected, match="RssAnon spread"):
        _capture_bracketed_window(
            unstable_process,
            lambda: dict(CGROUP),
            FakeAllocator(),  # type: ignore[arg-type]
            sleeper=lambda _seconds: None,
        )


def test_bracketed_sampling_fails_closed_on_burst_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = [0.0]
    for index in range(5):
        ticks.extend((index * 0.1, index * 0.1 + 0.01))
    ticks.append(2.1)
    values = iter(ticks)
    monkeypatch.setattr(calibration_module, "perf_counter", lambda: next(values))

    with pytest.raises(calibration_module.BoundedMemoryInventoryRejected, match="two seconds"):
        _capture_bracketed_window(
            lambda: dict(PROCESS),
            lambda: dict(CGROUP),
            FakeAllocator(),  # type: ignore[arg-type]
            sleeper=lambda _seconds: None,
        )


def _ledger() -> dict[str, object]:
    return {
        "schema_version": "cybercontrol.domain-separated-memory-ledger.v1",
        "cgroup_physical": {
            "memory_current_bytes": 500,
            "anon_bytes": 350,
            "file_bytes": 50,
            "kernel_bytes": 50,
            "unclassified_signed_bytes": 50,
            "drilldowns_non_additive": {},
        },
        "linux_process": {
            "vmrss_bytes": 100,
            "rss_anon_bytes": 80,
            "rss_file_bytes": 20,
            "rss_shmem_bytes": 0,
            "pss_bytes": 90,
            "uss_bytes": 80,
            "swap_bytes": 0,
            "fd_count": 7,
            "map_count": 11,
            "rss_reconciliation_signed_bytes": 0,
            "rss_reconciliation_limit_bytes": 1024 * 1024,
        },
        "jemalloc_accounting": {
            "allocated_bytes": 100,
            "active_bytes": 120,
            "resident_bytes": 150,
            "mapped_bytes": 180,
            "metadata_bytes": 10,
            "retained_bytes": 25,
            "arena_count": 1,
            "allocator_slack_bytes": 20,
            "allocator_resident_gap_bytes": 30,
        },
        "cross_domain_non_additive": {
            "classification": "NON_ADDITIVE_CROSS_DOMAIN",
            "jemalloc_resident_minus_rss_anon_signed_bytes": 70,
        },
    }


def _measurement_sampling() -> dict[str, object]:
    samples = [
        {
            "index": index,
            "order": list(BRACKET_SAMPLE_ORDER),
            "started_monotonic_seconds": float(index),
            "completed_monotonic_seconds": float(index) + 0.01,
            "duration_seconds": 0.01,
            "process_representative": {"process_id": 123},
            "cgroup_representative": {"cgroup_inode": 456},
            "process_before": {"process_id": 123},
            "process_after": {"process_id": 123},
            "cgroup_before": {"cgroup_inode": 456},
            "cgroup_after": {"cgroup_inode": 456},
        }
        for index in range(1, 6)
    ]
    return {
        "schema_version": "cybercontrol.gate-c-bracketed-domain-sampling.v1",
        "mode": "FIVE_SAMPLE_BRACKETED_DOMAIN",
        "sample_count": 5,
        "required_sample_count": 5,
        "spacing_seconds": 0.05,
        "sample_max_seconds": 0.25,
        "burst_max_seconds": 2.0,
        "burst_duration_seconds": 0.25,
        "process_rss_anon": {"spread": 0, "spread_limit": 8 * 1024 * 1024},
        "cgroup_memory_current": {"spread": 0, "spread_limit": 8 * 1024 * 1024},
        "samples": samples,
    }


def _arm(name: str, *, multiplier: float = 1.0) -> dict[str, object]:
    sampling = (
        _measurement_sampling()
        if name == "Measurement"
        else {"mode": "MINIMAL_CONTROL", "sample_count": 1}
    )
    return {
        "schema_version": "cybercontrol.gate-c-rss-calibration-arm.v1",
        "process_version": "Gate-C-12-v2.0",
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "formal_gate_attempt": False,
        "acceptance_claim": False,
        "run_id": f"run-{name}",
        "arm": name,
        "variable": "D",
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
            "baseline": {
                "process": {"rss_bytes": 100},
                "ledger": _ledger(),
                "sampling": sampling,
            },
            "recovery": {
                "process": {"rss_bytes": 110},
                "ledger": _ledger(),
                "sampling": sampling,
            },
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


def test_comparator_rejects_tampered_measurement_sampling() -> None:
    measurement = _arm("Measurement")
    measurement["windows"]["baseline"]["sampling"]["samples"][0]["order"] = ["wrong"]

    with pytest.raises(ValueError, match="sample order"):
        compare_arms(_arm("A"), measurement, _arm("APrime"))


def test_comparator_rejects_tampered_ledger_and_zero_tolerance_claim() -> None:
    measurement = _arm("Measurement")
    measurement["windows"]["recovery"]["ledger"]["jemalloc_accounting"]["allocator_slack_bytes"] = (
        19
    )
    with pytest.raises(ValueError, match="allocator ledger is inconsistent"):
        compare_arms(_arm("A"), measurement, _arm("APrime"))

    measurement = _arm("Measurement")
    measurement["zero_tolerance"]["evidence_integrity"] = False
    with pytest.raises(ValueError, match="zero-tolerance controls"):
        compare_arms(_arm("A"), measurement, _arm("APrime"))
