from __future__ import annotations

import asyncio
import hashlib
import json
import tracemalloc
from pathlib import Path

import pytest

import liyans.infrastructure.observability.memory_checkpoints as checkpoint_module
from liyans.infrastructure.observability.memory_checkpoints import (
    MemoryCheckpointManager,
    MemoryCheckpointRejected,
    _validate_inventory,
)

SOURCE = {
    "source_sha": "a" * 40,
    "source_tree": "b" * 40,
    "product_source_sha": "c" * 40,
    "engineering_baseline_sha": "d" * 40,
    "process_version": "Gate-C-12-v1.0",
}


@pytest.fixture(autouse=True)
def _restore_tracemalloc_state():
    already_tracing = tracemalloc.is_tracing()
    yield
    if not already_tracing and tracemalloc.is_tracing():
        tracemalloc.stop()


class _FastSnapshot:
    traces = (1,)

    def dump(self, path: str) -> None:
        Path(path).write_bytes(b"deterministic-test-snapshot")


@pytest.fixture
def fast_checkpoint_capture(monkeypatch) -> None:
    monkeypatch.setattr(tracemalloc, "take_snapshot", _FastSnapshot)
    monkeypatch.setattr(checkpoint_module, "_object_type_inventory", lambda: [])
    monkeypatch.setattr(checkpoint_module, "_read_process_maps", lambda: b"test-map\n")


def _manager(directory: Path | None) -> MemoryCheckpointManager:
    return MemoryCheckpointManager(
        directory=directory,
        source_metadata=SOURCE,
        allocator_reader=lambda: {
            "summary": {"allocated": 1, "active": 2},
            "bins": [],
            "large_extents": [],
        },
        signal_number=10,
    )


@pytest.mark.asyncio
async def test_disabled_checkpoint_mode_registers_no_signal(monkeypatch) -> None:
    loop = asyncio.get_running_loop()
    registered: list[object] = []
    monkeypatch.setattr(loop, "add_signal_handler", lambda *args: registered.append(args))
    manager = _manager(None)

    await manager.start()

    assert manager.enabled is False
    assert registered == []
    assert manager.active_task is None


def test_checkpoint_configuration_rejects_relative_symlink_and_invalid_source(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="absolute"):
        _manager(Path("relative"))
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError, match="source_sha"):
        MemoryCheckpointManager(
            directory=target,
            source_metadata={**SOURCE, "source_sha": "invalid"},
            allocator_reader=lambda: None,
        )
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are not available")
    with pytest.raises(ValueError, match="real existing"):
        _manager(link)


@pytest.mark.asyncio
async def test_checkpoint_has_single_owner_fixed_sequence_and_atomic_manifests(
    tmp_path: Path,
    monkeypatch,
    fast_checkpoint_capture,
) -> None:
    del fast_checkpoint_capture
    loop = asyncio.get_running_loop()
    handlers: dict[object, object] = {}
    monkeypatch.setattr(
        loop,
        "add_signal_handler",
        lambda key, value: handlers.update({key: value}),
    )
    monkeypatch.setattr(
        loop,
        "remove_signal_handler",
        lambda key: handlers.pop(key, None) is not None,
    )
    manager = _manager(tmp_path)
    manager.register_inventory("platform", lambda: {"database_pools": {"api": {"checked_out": 0}}})
    manager.register_inventory("sse", lambda: {"subscribers": 0, "queued_bytes": 0})
    manager.register_inventory("cursor", lambda: {"entries": 2, "capacity": 8192})

    await manager.start()
    baseline = await manager.request_checkpoint()
    recovery = await manager.request_checkpoint()

    assert baseline.name == "baseline.manifest.json"
    assert recovery.name == "recovery.manifest.json"
    for manifest_path, label in ((baseline, "baseline"), (recovery, "recovery")):
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert document["label"] == label
        assert document["source"] == SOURCE
        assert len(document["files"]) == 3
        for record in document["files"]:
            artifact = tmp_path / record["path"]
            assert artifact.stat().st_size == record["size_bytes"]
            assert hashlib.sha256(artifact.read_bytes()).hexdigest() == record["sha256"]
        metadata = json.loads((tmp_path / f"{label}.json").read_text(encoding="utf-8"))
        assert metadata["inventories"]["platform"]["database_pools"]["api"] == {"checked_out": 0}
        assert "tenant-secret-value" not in json.dumps(metadata)

    with pytest.raises(MemoryCheckpointRejected, match="sequence"):
        await manager.request_checkpoint()
    with pytest.raises(MemoryCheckpointRejected, match="label"):
        await manager._capture_checkpoint("unknown")
    with pytest.raises(MemoryCheckpointRejected, match="already exist"):
        await manager._capture_checkpoint("baseline")
    await manager.close()
    assert handlers == {}


@pytest.mark.asyncio
async def test_checkpoint_close_waits_for_inflight_owner(
    tmp_path: Path,
    monkeypatch,
    fast_checkpoint_capture,
) -> None:
    del fast_checkpoint_capture
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args: None)
    monkeypatch.setattr(loop, "remove_signal_handler", lambda *_args: True)
    manager = _manager(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()
    original_capture = manager._capture_checkpoint

    async def controlled_capture(label: str) -> Path:
        started.set()
        await release.wait()
        return await original_capture(label)

    monkeypatch.setattr(manager, "_capture_checkpoint", controlled_capture)
    await manager.start()
    task = manager._schedule_next()
    await started.wait()
    close_task = asyncio.create_task(manager.close())
    await asyncio.sleep(0)
    assert close_task.done() is False

    release.set()
    await close_task
    assert task.done()


def test_inventory_rejects_object_values(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(ValueError, match="approved"):
        manager.register_inventory("tenant", lambda: {"count": 1})
    with pytest.raises(ValueError, match="numeric state"):
        _validate_inventory({"unsafe": object()})
    with pytest.raises(ValueError, match="non-finite"):
        _validate_inventory({"unsafe": float("inf")})
    assert tracemalloc.is_tracing()
