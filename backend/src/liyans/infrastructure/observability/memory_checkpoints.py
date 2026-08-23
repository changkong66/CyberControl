from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import logging
import math
import os
import re
import signal
import sys
import tracemalloc
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Final
from uuid import uuid4

logger = logging.getLogger(__name__)

CHECKPOINT_LABELS: Final = ("baseline", "recovery")
CHECKPOINT_SIGNAL: Final = getattr(signal, "SIGUSR1", None)
APPROVED_INVENTORY_NAMES: Final = frozenset({"cursor", "platform", "sse"})
SHA_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
MAX_INVENTORY_DEPTH: Final = 8
MAX_INVENTORY_ITEMS: Final = 4096


class MemoryCheckpointRejected(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(document: object) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_process_memory() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            name, separator, raw = line.partition(":")
            if not separator or name not in {
                "VmRSS",
                "VmSize",
                "VmPeak",
                "VmData",
                "RssAnon",
                "RssFile",
                "RssShmem",
            }:
                continue
            values[name.lower() + "_bytes"] = int(raw.strip().split(maxsplit=1)[0]) * 1024
    except (FileNotFoundError, OSError, ValueError):
        pass
    try:
        for line in Path("/proc/self/smaps_rollup").read_text(encoding="ascii").splitlines():
            name, separator, raw = line.partition(":")
            if not separator or name not in {
                "Rss",
                "Pss",
                "Private_Clean",
                "Private_Dirty",
                "Anonymous",
                "Swap",
            }:
                continue
            values["smaps_" + name.lower() + "_bytes"] = (
                int(raw.strip().split(maxsplit=1)[0]) * 1024
            )
    except (FileNotFoundError, OSError, ValueError):
        pass
    try:
        with Path("/proc/self/maps").open(encoding="ascii") as stream:
            values["memory_map_count"] = sum(1 for _ in stream)
    except (FileNotFoundError, OSError):
        pass
    return values


def _read_process_maps() -> bytes:
    try:
        return Path("/proc/self/maps").read_bytes()
    except (FileNotFoundError, OSError):
        return b""


def _object_type_inventory() -> list[dict[str, int | str]]:
    counts: Counter[str] = Counter()
    for value in gc.get_objects():
        value_type = type(value)
        counts[f"{value_type.__module__}.{value_type.__qualname__}"[:256]] += 1
    return [{"type": name, "count": count} for name, count in counts.most_common(256)]


def _validate_inventory(value: object, *, depth: int = 0) -> int:
    if depth > MAX_INVENTORY_DEPTH:
        raise ValueError("diagnostic inventory exceeds its maximum depth")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("diagnostic inventory contains a non-finite value")
    if isinstance(value, bool | int | float) or value is None:
        return 1
    if isinstance(value, Mapping):
        total = 0
        for key, nested in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError("diagnostic inventory contains an invalid key")
            total += _validate_inventory(nested, depth=depth + 1)
        if total > MAX_INVENTORY_ITEMS:
            raise ValueError("diagnostic inventory exceeds its item bound")
        return total
    if isinstance(value, list | tuple):
        total = sum(_validate_inventory(item, depth=depth + 1) for item in value)
        if total > MAX_INVENTORY_ITEMS:
            raise ValueError("diagnostic inventory exceeds its item bound")
        return total
    raise ValueError("diagnostic inventory may contain only numeric state")


class MemoryCheckpointManager:
    def __init__(
        self,
        *,
        directory: Path | None,
        source_metadata: Mapping[str, str],
        allocator_reader: Callable[[], Mapping[str, object] | None],
        traceback_frames: int = 25,
        signal_number: int | None = CHECKPOINT_SIGNAL,
    ) -> None:
        self._directory = self._validate_directory(directory)
        self._source_metadata = dict(source_metadata)
        self._allocator_reader = allocator_reader
        self._traceback_frames = max(1, min(25, int(traceback_frames)))
        self._signal_number = signal_number
        self._inventory_readers: dict[str, Callable[[], Mapping[str, object]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active_task: asyncio.Task[Path] | None = None
        self._next_checkpoint = 0
        self._started = False
        self._signal_installed = False
        self._rejected_signals = 0
        if self.enabled:
            self._validate_source_metadata()
            if not tracemalloc.is_tracing():
                tracemalloc.start(self._traceback_frames)

    @classmethod
    def from_environment(
        cls,
        *,
        allocator_reader: Callable[[], Mapping[str, object] | None],
    ) -> MemoryCheckpointManager:
        raw_directory = os.getenv("LIYAN_MEMORY_CHECKPOINT_DIR", "").strip()
        directory = Path(raw_directory) if raw_directory else None
        return cls(
            directory=directory,
            source_metadata={
                "source_sha": os.getenv("LIYAN_MEMORY_CHECKPOINT_SOURCE_SHA", ""),
                "source_tree": os.getenv("LIYAN_MEMORY_CHECKPOINT_SOURCE_TREE", ""),
                "product_source_sha": os.getenv("LIYAN_MEMORY_CHECKPOINT_PRODUCT_SOURCE_SHA", ""),
                "engineering_baseline_sha": os.getenv(
                    "LIYAN_MEMORY_CHECKPOINT_ENGINEERING_BASELINE_SHA", ""
                ),
                "process_version": os.getenv("LIYAN_MEMORY_CHECKPOINT_PROCESS_VERSION", ""),
            },
            allocator_reader=allocator_reader,
            traceback_frames=int(os.getenv("LIYAN_MEMORY_CHECKPOINT_FRAMES", "25")),
        )

    @staticmethod
    def _validate_directory(directory: Path | None) -> Path | None:
        if directory is None:
            return None
        if not directory.is_absolute():
            raise ValueError("memory checkpoint directory must be absolute")
        resolved = directory.resolve(strict=True)
        if not resolved.is_dir() or directory.is_symlink():
            raise ValueError("memory checkpoint directory must be a real existing directory")
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
        for name in (
            "source_sha",
            "source_tree",
            "product_source_sha",
            "engineering_baseline_sha",
        ):
            if not SHA_PATTERN.fullmatch(self._source_metadata.get(name, "")):
                raise ValueError(f"memory checkpoint {name} must be a lowercase Git SHA")
        if self._source_metadata.get("process_version") != "Gate-C-11-v1.0":
            raise ValueError("memory checkpoint process version is not approved")

    def register_inventory(
        self,
        name: str,
        reader: Callable[[], Mapping[str, object]],
    ) -> None:
        if name not in APPROVED_INVENTORY_NAMES:
            raise ValueError("memory checkpoint inventory name is not approved")
        if self._started:
            raise RuntimeError("memory checkpoint inventories cannot change after start")
        self._inventory_readers[name] = reader

    async def start(self) -> None:
        if not self.enabled or self._started:
            return
        if self._signal_number is None:
            raise RuntimeError("memory checkpoint SIGUSR1 is unavailable")
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(self._signal_number, self._handle_signal)
        except (NotImplementedError, RuntimeError) as exc:
            raise RuntimeError("memory checkpoint signal ownership is unavailable") from exc
        self._loop = loop
        self._started = True
        self._signal_installed = True

    def _handle_signal(self) -> None:
        try:
            self._schedule_next()
        except MemoryCheckpointRejected as exc:
            self._rejected_signals += 1
            logger.error("Memory checkpoint signal rejected: %s", exc)

    def _schedule_next(self) -> asyncio.Task[Path]:
        if not self.enabled or not self._started or self._loop is None:
            raise MemoryCheckpointRejected("checkpoint mode is not active")
        if self._active_task is not None and not self._active_task.done():
            raise MemoryCheckpointRejected("a checkpoint is already running")
        if self._next_checkpoint >= len(CHECKPOINT_LABELS):
            raise MemoryCheckpointRejected("the fixed checkpoint sequence is complete")
        label = CHECKPOINT_LABELS[self._next_checkpoint]
        self._next_checkpoint += 1
        task = self._loop.create_task(
            self._capture_checkpoint(label),
            name=f"memory-checkpoint:{label}",
        )
        self._active_task = task
        task.add_done_callback(self._checkpoint_finished)
        return task

    def _checkpoint_finished(self, task: asyncio.Task[Path]) -> None:
        try:
            task.result()
        except BaseException:
            logger.exception("Memory checkpoint capture failed")

    async def request_checkpoint(self) -> Path:
        task = self._schedule_next()
        return await asyncio.shield(task)

    async def close(self) -> None:
        if self._signal_installed and self._loop is not None:
            if self._signal_number is not None:
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

    async def _capture_checkpoint(self, label: str) -> Path:
        if label not in CHECKPOINT_LABELS:
            raise MemoryCheckpointRejected("checkpoint label is not approved")
        if self._directory is None:
            raise RuntimeError("memory checkpoint directory is unavailable")
        artifact_names = (
            f"{label}.tracemalloc",
            f"{label}.proc-maps.txt",
            f"{label}.json",
            f"{label}.manifest.json",
        )
        if any(self._contained_path(name).exists() for name in artifact_names):
            raise MemoryCheckpointRejected("checkpoint artifacts already exist")
        started = perf_counter()
        started_at = datetime.now(UTC).isoformat()
        snapshot_path = self._contained_path(f"{label}.tracemalloc")
        synchronous = await asyncio.to_thread(
            self._capture_synchronous,
            snapshot_path,
        )
        task_inventory = await self._task_inventory()
        inventories: dict[str, object] = {}
        for name, reader in sorted(self._inventory_readers.items()):
            inventory = dict(reader())
            _validate_inventory(inventory)
            inventories[name] = inventory
        metadata = {
            "schema_version": "cybercontrol.memory-checkpoint.v1",
            "process_version": "Gate-C-11-v1.0",
            "label": label,
            "started_at_utc": started_at,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "duration_seconds": round(perf_counter() - started, 6),
            "source": self._source_metadata,
            "process": {
                "pid": os.getpid(),
                "python_version": sys.version.split()[0],
            },
            "pre_capture_memory": synchronous["pre_capture_memory"],
            "post_capture_memory": _read_process_memory(),
            "tracemalloc": synchronous["tracemalloc"],
            "allocator": synchronous["allocator"],
            "gc": synchronous["gc"],
            "object_types": synchronous["object_types"],
            "tasks": task_inventory,
            "inventories": inventories,
            "rejected_signal_count": self._rejected_signals,
        }
        maps_path = self._contained_path(f"{label}.proc-maps.txt")
        _atomic_write(maps_path, synchronous["process_maps"])
        metadata_path = self._contained_path(f"{label}.json")
        _atomic_write(metadata_path, _json_bytes(metadata))
        manifest = {
            "schema_version": "cybercontrol.memory-checkpoint-manifest.v1",
            "label": label,
            "source": self._source_metadata,
            "files": [
                {
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in (metadata_path, maps_path, snapshot_path)
            ],
        }
        manifest_path = self._contained_path(f"{label}.manifest.json")
        _atomic_write(manifest_path, _json_bytes(manifest))
        return manifest_path

    def _capture_synchronous(self, snapshot_path: Path) -> dict[str, Any]:
        if not tracemalloc.is_tracing():
            raise RuntimeError("tracemalloc must run from process start in checkpoint mode")
        pre_capture_memory = _read_process_memory()
        current, peak = tracemalloc.get_traced_memory()
        snapshot = tracemalloc.take_snapshot()
        temporary = snapshot_path.parent / f".{snapshot_path.name}.{uuid4().hex}.tmp"
        try:
            snapshot.dump(str(temporary))
            temporary.replace(snapshot_path)
        finally:
            temporary.unlink(missing_ok=True)
        allocator = self._allocator_reader()
        if allocator is not None:
            _validate_inventory(allocator)
        return {
            "pre_capture_memory": pre_capture_memory,
            "tracemalloc": {
                "current_bytes": current,
                "peak_bytes": peak,
                "trace_count": len(snapshot.traces),
            },
            "allocator": allocator,
            "gc": {
                "generation_counts": list(gc.get_count()),
                "generation_stats": gc.get_stats(),
            },
            "object_types": _object_type_inventory(),
            "process_maps": _read_process_maps(),
        }

    async def _task_inventory(self) -> dict[str, object]:
        task_types: Counter[str] = Counter()
        frames: Counter[str] = Counter()
        tasks = list(asyncio.all_tasks())
        for index, task in enumerate(tasks, start=1):
            coroutine_type = type(task.get_coro())
            task_types[f"{coroutine_type.__module__}.{coroutine_type.__qualname__}"[:256]] += 1
            for frame in task.get_stack(limit=32):
                code = frame.f_code
                frames[f"{code.co_filename}:{code.co_name}:{frame.f_lineno}"[:512]] += 1
            if index % 64 == 0:
                await asyncio.sleep(0)
        return {
            "total": len(tasks),
            "frame_total": sum(frames.values()),
            "types": [
                {"type": name, "count": count} for name, count in task_types.most_common(256)
            ],
            "frames": [
                {"location": name, "count": count} for name, count in frames.most_common(512)
            ],
        }

    def _contained_path(self, name: str) -> Path:
        if self._directory is None:
            raise RuntimeError("memory checkpoint directory is unavailable")
        path = (self._directory / name).resolve(strict=False)
        if path.parent != self._directory:
            raise ValueError("memory checkpoint artifact escaped its configured directory")
        return path
