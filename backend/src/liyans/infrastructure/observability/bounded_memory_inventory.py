from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Final

from liyans.infrastructure.observability.memory_checkpoints import (
    _atomic_write,
    _json_bytes,
    _sha256,
    _validate_inventory,
)

logger = logging.getLogger(__name__)

INVENTORY_LABELS: Final = ("baseline", "peak", "recovery")
INVENTORY_SIGNAL: Final = getattr(signal, "SIGUSR1", None)
APPROVED_INVENTORY_NAMES: Final = frozenset({"cursor", "platform", "sse"})
SHA_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
PROCESS_VERSION: Final = "Gate-C-12-v1.0"


class BoundedMemoryInventoryRejected(RuntimeError):
    """Raised when the fixed low-interference inventory protocol is violated."""


def _read_kib_file(path: Path, names: frozenset[str]) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, OSError):
        return values
    for line in lines:
        name, separator, raw = line.partition(":")
        if not separator or name not in names:
            continue
        try:
            values[name] = int(raw.strip().split(maxsplit=1)[0]) * 1024
        except (ValueError, IndexError):
            continue
    return values


def _read_process_memory() -> dict[str, int]:
    status = _read_kib_file(
        Path("/proc/self/status"),
        frozenset({"VmRSS", "VmSize", "VmData", "RssAnon", "RssFile", "RssShmem"}),
    )
    smaps = _read_kib_file(
        Path("/proc/self/smaps_rollup"),
        frozenset({"Pss", "Private_Clean", "Private_Dirty", "Private_Hugetlb", "Swap"}),
    )
    values = {
        "rss_bytes": status.get("VmRSS", 0),
        "virtual_bytes": status.get("VmSize", 0),
        "data_bytes": status.get("VmData", 0),
        "rss_anon_bytes": status.get("RssAnon", 0),
        "rss_file_bytes": status.get("RssFile", 0),
        "rss_shmem_bytes": status.get("RssShmem", 0),
        "pss_bytes": smaps.get("Pss", 0),
        "uss_bytes": sum(
            smaps.get(name, 0) for name in ("Private_Clean", "Private_Dirty", "Private_Hugetlb")
        ),
        "swap_bytes": smaps.get("Swap", 0),
    }
    try:
        values["map_count"] = sum(1 for _ in Path("/proc/self/maps").open(encoding="ascii"))
    except (FileNotFoundError, OSError):
        values["map_count"] = 0
    try:
        values["fd_count"] = sum(1 for _ in Path("/proc/self/fd").iterdir())
    except (FileNotFoundError, OSError):
        values["fd_count"] = 0
    return values


def _read_process_maps() -> bytes:
    try:
        return Path("/proc/self/maps").read_bytes()
    except (FileNotFoundError, OSError):
        return b""


def _cgroup_directory() -> Path | None:
    try:
        entries = Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, OSError):
        return None
    unified = next((line.partition("0::")[2] for line in entries if line.startswith("0::")), "")
    if not unified:
        return None
    root = Path("/sys/fs/cgroup").resolve()
    candidate = (root / unified.lstrip("/")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _read_cgroup_memory() -> dict[str, int]:
    directory = _cgroup_directory()
    if directory is None:
        return {}
    try:
        current = int((directory / "memory.current").read_text(encoding="ascii").strip())
        raw_stat = (directory / "memory.stat").read_text(encoding="ascii").splitlines()
        process_ids = {
            int(value)
            for value in (directory / "cgroup.procs").read_text(encoding="ascii").splitlines()
        }
    except (FileNotFoundError, OSError, ValueError):
        return {}
    stats: dict[str, int] = {}
    for line in raw_stat:
        name, separator, raw = line.partition(" ")
        if not separator:
            continue
        try:
            stats[name] = int(raw)
        except ValueError:
            continue
    other_process_rss = 0
    unreadable_processes = 0
    for process_id in process_ids - {os.getpid()}:
        status = _read_kib_file(Path(f"/proc/{process_id}/status"), frozenset({"VmRSS"}))
        if "VmRSS" not in status:
            unreadable_processes += 1
        else:
            other_process_rss += status["VmRSS"]
    return {
        "memory_current_bytes": current,
        "anon_bytes": stats.get("anon", 0),
        "file_bytes": stats.get("file", 0),
        "kernel_bytes": stats.get("kernel", 0),
        "sock_bytes": stats.get("sock", 0),
        "slab_bytes": stats.get("slab", 0),
        "pagetables_bytes": stats.get("pagetables", 0),
        "kernel_stack_bytes": stats.get("kernel_stack", 0),
        "other_process_rss_bytes": other_process_rss,
        "unreadable_process_count": unreadable_processes,
    }


def build_memory_ledger(
    process: Mapping[str, int],
    cgroup: Mapping[str, int],
    allocator: Mapping[str, object] | None,
) -> dict[str, object]:
    if allocator is None or not isinstance(allocator.get("summary"), Mapping):
        raise BoundedMemoryInventoryRejected("jemalloc allocation summary is unavailable")
    summary = allocator["summary"]
    required = ("allocated", "active", "resident")
    if any(not isinstance(summary.get(name), int) for name in required):
        raise BoundedMemoryInventoryRejected("jemalloc allocation summary is incomplete")
    allocated = int(summary["allocated"])
    active = int(summary["active"])
    resident = int(summary["resident"])
    rss_anon = int(process.get("rss_anon_bytes", 0))
    physical = {
        "allocator_payload_bytes": allocated,
        "allocator_slack_bytes": active - allocated,
        "allocator_resident_gap_bytes": resident - active,
        "non_jemalloc_anon_bytes": rss_anon - resident,
    }
    if rss_anon <= 0 or any(value < 0 for value in physical.values()):
        raise BoundedMemoryInventoryRejected("physical memory partition is negative or empty")
    if sum(physical.values()) != rss_anon:
        raise BoundedMemoryInventoryRejected("physical memory partition does not reconcile")

    process_rss = int(process.get("rss_bytes", 0))
    required_cgroup = (
        "memory_current_bytes",
        "file_bytes",
        "kernel_bytes",
        "other_process_rss_bytes",
        "unreadable_process_count",
    )
    if any(not isinstance(cgroup.get(name), int) for name in required_cgroup):
        raise BoundedMemoryInventoryRejected("cgroup bridge inputs are incomplete")
    if int(cgroup["unreadable_process_count"]) != 0:
        raise BoundedMemoryInventoryRejected("cgroup process RSS inventory is incomplete")
    cgroup_current = int(cgroup.get("memory_current_bytes", 0))
    file_cache = int(cgroup.get("file_bytes", 0))
    kernel = int(cgroup.get("kernel_bytes", 0))
    other_process_rss = int(cgroup.get("other_process_rss_bytes", 0))
    if cgroup_current <= 0 or min(file_cache, kernel, other_process_rss) < 0:
        raise BoundedMemoryInventoryRejected("cgroup bridge input is negative or empty")
    bridge = {
        "api_process_rss_bytes": process_rss,
        "other_process_rss_bytes": other_process_rss,
        "cgroup_file_cache_bytes": file_cache,
        "kernel_memory_bytes": kernel,
        "signed_reconciliation_residual_bytes": (
            cgroup_current - process_rss - other_process_rss - file_cache - kernel
        ),
    }
    return {
        "physical_partition": physical,
        "rss_anon_bytes": rss_anon,
        "rss_file_bytes": int(process.get("rss_file_bytes", 0)),
        "rss_shmem_bytes": int(process.get("rss_shmem_bytes", 0)),
        "cgroup_bridge": bridge,
    }


class BoundedMemoryInventoryManager:
    def __init__(
        self,
        *,
        directory: Path | None,
        source_metadata: Mapping[str, str],
        allocator_reader: Callable[[], Mapping[str, object] | None],
        signal_number: int | None = INVENTORY_SIGNAL,
        process_reader: Callable[[], Mapping[str, int]] = _read_process_memory,
        cgroup_reader: Callable[[], Mapping[str, int]] = _read_cgroup_memory,
        maps_reader: Callable[[], bytes] = _read_process_maps,
    ) -> None:
        self._directory = self._validate_directory(directory)
        self._source_metadata = dict(source_metadata)
        self._allocator_reader = allocator_reader
        self._signal_number = signal_number
        self._process_reader = process_reader
        self._cgroup_reader = cgroup_reader
        self._maps_reader = maps_reader
        self._inventory_readers: dict[str, Callable[[], Mapping[str, object]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active_task: asyncio.Task[Path] | None = None
        self._next_inventory = 0
        self._started = False
        self._signal_installed = False
        self._rejected_signals = 0
        if self.enabled:
            self._validate_source_metadata()

    @classmethod
    def from_environment(
        cls,
        *,
        allocator_reader: Callable[[], Mapping[str, object] | None],
    ) -> BoundedMemoryInventoryManager:
        raw_directory = os.getenv("LIYAN_BOUNDED_MEMORY_INVENTORY_DIR", "").strip()
        return cls(
            directory=Path(raw_directory) if raw_directory else None,
            source_metadata={
                "source_sha": os.getenv("LIYAN_BOUNDED_MEMORY_INVENTORY_SOURCE_SHA", ""),
                "source_tree": os.getenv("LIYAN_BOUNDED_MEMORY_INVENTORY_SOURCE_TREE", ""),
                "product_source_sha": os.getenv(
                    "LIYAN_BOUNDED_MEMORY_INVENTORY_PRODUCT_SOURCE_SHA", ""
                ),
                "engineering_baseline_sha": os.getenv(
                    "LIYAN_BOUNDED_MEMORY_INVENTORY_ENGINEERING_BASELINE_SHA", ""
                ),
                "process_version": os.getenv("LIYAN_BOUNDED_MEMORY_INVENTORY_PROCESS_VERSION", ""),
            },
            allocator_reader=allocator_reader,
        )

    @staticmethod
    def _validate_directory(directory: Path | None) -> Path | None:
        if directory is None:
            return None
        if not directory.is_absolute():
            raise ValueError("bounded memory inventory directory must be absolute")
        resolved = directory.resolve(strict=True)
        if not resolved.is_dir() or directory.is_symlink():
            raise ValueError("bounded memory inventory directory must be a real directory")
        return resolved

    @property
    def enabled(self) -> bool:
        return self._directory is not None

    @property
    def active_task(self) -> asyncio.Task[Path] | None:
        return self._active_task

    @property
    def rejected_signals(self) -> int:
        return self._rejected_signals

    def _validate_source_metadata(self) -> None:
        for name in ("source_sha", "source_tree", "product_source_sha", "engineering_baseline_sha"):
            if not SHA_PATTERN.fullmatch(self._source_metadata.get(name, "")):
                raise ValueError(f"bounded memory inventory {name} must be a lowercase Git SHA")
        if self._source_metadata.get("process_version") != PROCESS_VERSION:
            raise ValueError("bounded memory inventory process version is not approved")

    def register_inventory(
        self,
        name: str,
        reader: Callable[[], Mapping[str, object]],
    ) -> None:
        if name not in APPROVED_INVENTORY_NAMES:
            raise ValueError("bounded memory inventory name is not approved")
        if self._started:
            raise RuntimeError("bounded memory inventories cannot change after start")
        self._inventory_readers[name] = reader

    async def start(self) -> None:
        if not self.enabled or self._started:
            return
        if self._signal_number is None:
            raise RuntimeError("bounded memory inventory SIGUSR1 is unavailable")
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(self._signal_number, self._handle_signal)
        except (NotImplementedError, RuntimeError) as exc:
            raise RuntimeError("bounded memory inventory signal ownership is unavailable") from exc
        self._loop = loop
        self._started = True
        self._signal_installed = True

    def _handle_signal(self) -> None:
        try:
            self._schedule_next()
        except BoundedMemoryInventoryRejected as exc:
            self._rejected_signals += 1
            logger.error("Bounded memory inventory signal rejected: %s", exc)

    def _schedule_next(self) -> asyncio.Task[Path]:
        if not self.enabled or not self._started or self._loop is None:
            raise BoundedMemoryInventoryRejected("bounded inventory mode is not active")
        if self._active_task is not None and not self._active_task.done():
            raise BoundedMemoryInventoryRejected("a bounded inventory is already running")
        if self._next_inventory >= len(INVENTORY_LABELS):
            raise BoundedMemoryInventoryRejected("the fixed bounded inventory sequence is complete")
        label = INVENTORY_LABELS[self._next_inventory]
        self._next_inventory += 1
        task = self._loop.create_task(
            self._capture(label),
            name=f"bounded-memory-inventory:{label}",
        )
        self._active_task = task
        task.add_done_callback(self._capture_finished)
        return task

    def _capture_finished(self, task: asyncio.Task[Path]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Bounded memory inventory capture failed")

    async def request_inventory(self) -> Path:
        return await asyncio.shield(self._schedule_next())

    async def close(self) -> None:
        if self._signal_installed and self._loop is not None and self._signal_number is not None:
            self._loop.remove_signal_handler(self._signal_number)
            self._signal_installed = False
        task = self._active_task
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
        self._started = False
        self._loop = None

    async def _capture(self, label: str) -> Path:
        if label not in INVENTORY_LABELS:
            raise BoundedMemoryInventoryRejected("bounded inventory label is not approved")
        return await asyncio.to_thread(self._capture_synchronous, label)

    def _capture_synchronous(self, label: str) -> Path:
        if self._directory is None:
            raise RuntimeError("bounded memory inventory directory is unavailable")
        paths = {
            "metadata": self._contained_path(f"{label}.json"),
            "maps": self._contained_path(f"{label}.proc-maps.txt"),
            "manifest": self._contained_path(f"{label}.manifest.json"),
        }
        if any(path.exists() for path in paths.values()):
            raise BoundedMemoryInventoryRejected("bounded inventory artifacts already exist")
        started = perf_counter()
        started_at = datetime.now(UTC).isoformat()
        process = dict(self._process_reader())
        cgroup = dict(self._cgroup_reader())
        allocator = self._allocator_reader()
        if allocator is not None:
            allocator = dict(allocator)
            _validate_inventory(allocator)
        inventories: dict[str, object] = {}
        for name, reader in sorted(self._inventory_readers.items()):
            inventory = dict(reader())
            _validate_inventory(inventory)
            inventories[name] = inventory
        ledger = build_memory_ledger(process, cgroup, allocator)
        maps = self._maps_reader()
        completed = perf_counter()
        metadata: dict[str, Any] = {
            "schema_version": "cybercontrol.bounded-memory-inventory.v1",
            "process_version": PROCESS_VERSION,
            "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
            "label": label,
            "started_at_utc": started_at,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "started_monotonic_seconds": started,
            "completed_monotonic_seconds": completed,
            "duration_seconds": round(completed - started, 6),
            "source": self._source_metadata,
            "process": {"pid": os.getpid(), "python_version": sys.version.split()[0]},
            "process_memory": process,
            "cgroup_memory": cgroup,
            "allocator": allocator,
            "ownership_overlays_not_additive": inventories,
            "memory_ledger": ledger,
            "rejected_signal_count": self._rejected_signals,
            "probe_exclusions": {
                "tracemalloc": True,
                "gc_object_scan": True,
                "task_frame_scan": True,
                "sampled_profile": True,
            },
        }
        _atomic_write(paths["maps"], maps)
        _atomic_write(paths["metadata"], _json_bytes(metadata))
        manifest = {
            "schema_version": "cybercontrol.bounded-memory-inventory-manifest.v1",
            "process_version": PROCESS_VERSION,
            "label": label,
            "source": self._source_metadata,
            "files": [
                {
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in (paths["metadata"], paths["maps"])
            ],
        }
        _atomic_write(paths["manifest"], _json_bytes(manifest))
        return paths["manifest"]

    def _contained_path(self, name: str) -> Path:
        if self._directory is None:
            raise RuntimeError("bounded memory inventory directory is unavailable")
        path = (self._directory / name).resolve(strict=False)
        if path.parent != self._directory:
            raise ValueError("bounded memory inventory artifact escaped its directory")
        return path
