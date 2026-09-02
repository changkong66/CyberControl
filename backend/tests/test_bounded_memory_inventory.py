from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from liyans.infrastructure.observability.bounded_memory_inventory import (
    BoundedMemoryInventoryManager,
    BoundedMemoryInventoryRejected,
    build_memory_ledger,
)
from liyans.infrastructure.observability.metrics import PlatformMetrics

SOURCE = {
    "source_sha": "a" * 40,
    "source_tree": "b" * 40,
    "product_source_sha": "c" * 40,
    "engineering_baseline_sha": "d" * 40,
    "process_version": "Gate-C-12-v2.0",
}
PROCESS = {
    "process_id": 123,
    "rss_bytes": 300,
    "rss_anon_bytes": 200,
    "rss_file_bytes": 90,
    "rss_shmem_bytes": 10,
    "pss_bytes": 280,
    "uss_bytes": 260,
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
ALLOCATOR = {
    "summary": {
        "allocated": 100,
        "active": 120,
        "resident": 150,
        "mapped": 180,
        "metadata": 10,
        "retained": 25,
        "arenas": 1,
    },
    "bins": [{"arena": 0, "index": 1, "live_regions": 2}],
    "large_extents": [],
}


def _manager(directory: Path, **overrides) -> BoundedMemoryInventoryManager:
    values = {
        "directory": directory,
        "source_metadata": SOURCE,
        "allocator_reader": lambda: ALLOCATOR,
        "signal_number": 10,
        "process_reader": lambda: PROCESS,
        "cgroup_reader": lambda: CGROUP,
        "maps_reader": lambda: b"00400000-00401000 r--p fixture\n",
    }
    values.update(overrides)
    return BoundedMemoryInventoryManager(**values)


def _install_signal_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args: None)
    monkeypatch.setattr(loop, "remove_signal_handler", lambda *_args: True)


def test_memory_ledger_separates_accounting_domains_and_reconciles_each_domain() -> None:
    ledger = build_memory_ledger(PROCESS, CGROUP, ALLOCATOR)

    assert ledger["schema_version"] == "cybercontrol.domain-separated-memory-ledger.v1"
    assert ledger["jemalloc_accounting"] == {
        "allocated_bytes": 100,
        "active_bytes": 120,
        "resident_bytes": 150,
        "mapped_bytes": 180,
        "metadata_bytes": 10,
        "retained_bytes": 25,
        "arena_count": 1,
        "allocator_slack_bytes": 20,
        "allocator_resident_gap_bytes": 30,
    }
    assert ledger["linux_process"]["rss_reconciliation_signed_bytes"] == 0
    assert ledger["cgroup_physical"]["unclassified_signed_bytes"] == 50
    assert ledger["cross_domain_non_additive"] == {
        "classification": "NON_ADDITIVE_CROSS_DOMAIN",
        "jemalloc_resident_minus_rss_anon_signed_bytes": -50,
    }


def test_memory_ledger_accepts_jemalloc_resident_above_linux_rss_anon() -> None:
    allocator = {
        **ALLOCATOR,
        "summary": {**ALLOCATOR["summary"], "resident": 250, "mapped": 280},
    }

    ledger = build_memory_ledger(PROCESS, CGROUP, allocator)

    assert (
        ledger["cross_domain_non_additive"]["jemalloc_resident_minus_rss_anon_signed_bytes"] == 50
    )


@pytest.mark.parametrize(
    "allocator",
    (
        None,
        {
            "summary": {
                **ALLOCATOR["summary"],
                "allocated": 130,
                "active": 120,
            }
        },
        {
            "summary": {
                **ALLOCATOR["summary"],
                "active": 160,
                "resident": 150,
            }
        },
    ),
)
def test_memory_ledger_rejects_missing_or_inconsistent_allocator_accounting(allocator) -> None:
    with pytest.raises(BoundedMemoryInventoryRejected):
        build_memory_ledger(PROCESS, CGROUP, allocator)


def test_memory_ledger_rejects_process_reconciliation_above_adr_limit() -> None:
    mib = 1024 * 1024
    process = {
        **PROCESS,
        "rss_bytes": 100 * mib,
        "rss_anon_bytes": 50 * mib,
        "rss_file_bytes": 10 * mib,
        "rss_shmem_bytes": 10 * mib,
    }

    with pytest.raises(BoundedMemoryInventoryRejected, match="components do not reconcile"):
        build_memory_ledger(process, CGROUP, ALLOCATOR)


def test_memory_ledger_keeps_cgroup_drilldowns_non_additive() -> None:
    ledger = build_memory_ledger(
        PROCESS,
        {**CGROUP, "memory_current_bytes": 525, "other_process_rss_bytes": 25},
        ALLOCATOR,
    )
    assert ledger["cgroup_physical"]["drilldowns_non_additive"]["other_process_rss_bytes"] == 25
    assert ledger["cgroup_physical"]["unclassified_signed_bytes"] == 75

    incomplete = build_memory_ledger(
        PROCESS,
        {**CGROUP, "unreadable_process_count": 1},
        ALLOCATOR,
    )
    assert incomplete["cgroup_physical"]["drilldowns_non_additive"]["unreadable_process_count"] == 1


@pytest.mark.asyncio
async def test_fixed_inventory_sequence_writes_bounded_immutable_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    manager.register_inventory("platform", lambda: {"database_pools": {"api": {"size": 10}}})
    _install_signal_stubs(monkeypatch)
    await manager.start()

    for label in ("baseline", "peak", "recovery"):
        manifest_path = await manager.request_inventory()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metadata = json.loads((tmp_path / f"{label}.json").read_text(encoding="utf-8"))
        assert manifest["label"] == label
        assert metadata["label"] == label
        assert metadata["classification"] == "NON_ACCEPTANCE_DIAGNOSTIC"
        assert metadata["ownership_overlays_not_additive"]["platform"]["database_pools"]
        assert metadata["probe_exclusions"] == {
            "tracemalloc": True,
            "gc_object_scan": True,
            "task_frame_scan": True,
            "sampled_profile": True,
        }
        assert {item["path"] for item in manifest["files"]} == {
            f"{label}.json",
            f"{label}.proc-maps.txt",
        }

    with pytest.raises(BoundedMemoryInventoryRejected, match="sequence is complete"):
        await manager.request_inventory()
    await manager.close()


@pytest.mark.asyncio
async def test_inventory_failure_is_fail_closed_and_preserves_existing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = tmp_path / "baseline.json"
    existing.write_text("preserve", encoding="ascii")
    manager = _manager(tmp_path)
    _install_signal_stubs(monkeypatch)
    await manager.start()

    with pytest.raises(BoundedMemoryInventoryRejected, match="already exist"):
        await manager.request_inventory()

    assert existing.read_text(encoding="ascii") == "preserve"
    assert not (tmp_path / "baseline.manifest.json").exists()
    await manager.close()


def test_environment_binding_and_probe_mutex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIYAN_BOUNDED_MEMORY_INVENTORY_DIR", str(tmp_path))
    for name, value in SOURCE.items():
        monkeypatch.setenv(f"LIYAN_BOUNDED_MEMORY_INVENTORY_{name.upper()}", value)

    metrics = PlatformMetrics()
    assert metrics.bounded_memory_inventory.enabled is True

    monkeypatch.setenv("LIYAN_MEMORY_CHECKPOINT_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="mutually exclusive"):
        PlatformMetrics()

    monkeypatch.delenv("LIYAN_MEMORY_CHECKPOINT_DIR")
    monkeypatch.setenv("LIYAN_JEMALLOC_PROFILE_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="mutually exclusive"):
        PlatformMetrics()
