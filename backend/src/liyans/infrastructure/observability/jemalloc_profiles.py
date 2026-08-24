from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import logging
import os
import re
import signal
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Final, Literal
from uuid import uuid4

logger = logging.getLogger(__name__)

PROFILE_SIGNAL: Final = getattr(signal, "SIGUSR2", None)
PROFILE_PROCESS_VERSION: Final = "Gate-C-11-v1.0"
SHA_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
BUILD_ID_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
PROFILE_STATES: Final = ("inactive", "sampling", "complete", "failed")


class JemallocProfileRejected(RuntimeError):
    """Raised when the fixed profiling state machine rejects an operation."""


class _Mallctl:
    """Small, testable ctypes wrapper for jemalloc's process-local mallctl API."""

    def __init__(self, function: Any | None = None) -> None:
        self._function = function
        if function is not None or sys.platform == "win32":
            return
        try:
            library = ctypes.CDLL(None)
            function = library.mallctl
            function.argtypes = [
                ctypes.c_char_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.c_void_p,
                ctypes.c_size_t,
            ]
            function.restype = ctypes.c_int
            self._function = function
        except (AttributeError, OSError):
            self._function = None

    @property
    def available(self) -> bool:
        return self._function is not None

    def read_bool(self, name: str) -> bool | None:
        if self._function is None:
            return None
        value = ctypes.c_bool()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        try:
            result = self._function(
                name.encode("ascii"),
                ctypes.byref(value),
                ctypes.byref(size),
                None,
                0,
            )
        except (OSError, TypeError):
            return None
        return bool(value.value) if result == 0 and size.value == ctypes.sizeof(value) else None

    def write_bool(self, name: str, value: bool) -> int:
        if self._function is None:
            return -1
        requested = ctypes.c_bool(value)
        try:
            return int(
                self._function(
                    name.encode("ascii"),
                    None,
                    None,
                    ctypes.byref(requested),
                    ctypes.sizeof(requested),
                )
            )
        except (OSError, TypeError):
            return -1

    def reset(self) -> int:
        if self._function is None:
            return -1
        try:
            return int(self._function(b"prof.reset", None, None, None, 0))
        except (OSError, TypeError):
            return -1

    def dump(self, path: Path) -> int:
        if self._function is None:
            return -1
        encoded = ctypes.c_char_p(os.fsencode(str(path)))
        try:
            return int(
                self._function(
                    b"prof.dump",
                    None,
                    None,
                    ctypes.byref(encoded),
                    ctypes.sizeof(encoded),
                )
            )
        except (OSError, TypeError):
            return -1


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


def _real_directory(raw: str) -> Path:
    directory = Path(raw)
    if not directory.is_absolute():
        raise ValueError("jemalloc profile directory must be absolute")
    resolved = directory.resolve(strict=True)
    if directory.is_symlink() or not resolved.is_dir():
        raise ValueError("jemalloc profile directory must be a real existing directory")
    return resolved


class JemallocProfileController:
    """Disabled-by-default, two-transition native heap profile controller."""

    def __init__(
        self,
        *,
        directory: Path | None,
        source_metadata: Mapping[str, str],
        mallctl: _Mallctl | None = None,
        signal_number: int | None = PROFILE_SIGNAL,
    ) -> None:
        self._directory = directory
        self._source_metadata = dict(source_metadata)
        self._mallctl = mallctl or _Mallctl()
        self._signal_number = signal_number
        self._loop: asyncio.AbstractEventLoop | None = None
        self._transition_task: asyncio.Task[Path | None] | None = None
        self._signal_installed = False
        self._started = False
        self._state: Literal["inactive", "sampling", "complete", "failed"] = "inactive"
        self._rejected_signals = 0
        self._transition_lock = asyncio.Lock()
        if self.enabled:
            self._validate_source_metadata()

    @classmethod
    def from_environment(cls) -> JemallocProfileController:
        raw_directory = os.getenv("LIYAN_JEMALLOC_PROFILE_DIR", "").strip()
        if not raw_directory:
            return cls(directory=None, source_metadata={})
        metadata = {
            "source_sha": os.getenv("LIYAN_JEMALLOC_PROFILE_SOURCE_SHA", ""),
            "source_tree": os.getenv("LIYAN_JEMALLOC_PROFILE_SOURCE_TREE", ""),
            "product_source_sha": os.getenv("LIYAN_JEMALLOC_PROFILE_PRODUCT_SOURCE_SHA", ""),
            "engineering_baseline_sha": os.getenv(
                "LIYAN_JEMALLOC_PROFILE_ENGINEERING_BASELINE_SHA", ""
            ),
            "process_version": os.getenv("LIYAN_JEMALLOC_PROFILE_PROCESS_VERSION", ""),
            "library_sha256": os.getenv("LIYAN_JEMALLOC_PROFILE_LIBRARY_SHA256", ""),
            "library_build_id": os.getenv("LIYAN_JEMALLOC_PROFILE_LIBRARY_BUILD_ID", ""),
            "image_id": os.getenv("LIYAN_JEMALLOC_PROFILE_IMAGE_ID", ""),
            "image_digest": os.getenv("LIYAN_JEMALLOC_PROFILE_IMAGE_DIGEST", ""),
        }
        return cls(directory=_real_directory(raw_directory), source_metadata=metadata)

    @property
    def enabled(self) -> bool:
        return self._directory is not None

    @property
    def active(self) -> bool:
        return self._state == "sampling"

    @property
    def state(self) -> str:
        return self._state

    @property
    def transition_task(self) -> asyncio.Task[Path | None] | None:
        return self._transition_task

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
                raise ValueError(f"jemalloc profile {name} must be a lowercase Git SHA")
        if self._source_metadata.get("process_version") != PROFILE_PROCESS_VERSION:
            raise ValueError("jemalloc profile process version is not approved")
        if not SHA256_PATTERN.fullmatch(self._source_metadata.get("library_sha256", "")):
            raise ValueError("jemalloc profile library SHA256 is invalid")
        if not BUILD_ID_PATTERN.fullmatch(self._source_metadata.get("library_build_id", "")):
            raise ValueError("jemalloc profile library build ID is invalid")
        if not IMAGE_DIGEST_PATTERN.fullmatch(self._source_metadata.get("image_id", "")):
            raise ValueError("jemalloc profile image ID is required")
        image_digest = self._source_metadata.get("image_digest", "")
        if not IMAGE_DIGEST_PATTERN.fullmatch(image_digest):
            raise ValueError("jemalloc profile image digest is invalid")

    def _readiness(self) -> dict[str, bool]:
        values = {
            "config.prof": self._mallctl.read_bool("config.prof"),
            "config.stats": self._mallctl.read_bool("config.stats"),
            "opt.prof": self._mallctl.read_bool("opt.prof"),
            "prof.active": self._mallctl.read_bool("prof.active"),
        }
        if any(value is None for value in values.values()):
            raise JemallocProfileRejected("jemalloc profiling capability readback is unavailable")
        result = {name: bool(value) for name, value in values.items()}
        if not result["config.prof"] or not result["config.stats"] or not result["opt.prof"]:
            raise JemallocProfileRejected("jemalloc profiling capability is not enabled")
        if result["prof.active"]:
            raise JemallocProfileRejected("jemalloc profiling must start inactive")
        return result

    async def start(self) -> None:
        if not self.enabled or self._started:
            return
        if self._signal_number is None:
            raise JemallocProfileRejected("jemalloc profile SIGUSR2 is unavailable")
        self._readiness()
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(self._signal_number, self._handle_signal)
        except (NotImplementedError, RuntimeError) as exc:
            raise JemallocProfileRejected(
                "jemalloc profile signal ownership is unavailable"
            ) from exc
        self._loop = loop
        self._started = True
        self._signal_installed = True

    def _handle_signal(self) -> None:
        try:
            self._schedule_next()
        except JemallocProfileRejected as exc:
            self._rejected_signals += 1
            logger.error("Jemalloc profile signal rejected: %s", exc)

    def _schedule_next(self) -> asyncio.Task[Path | None]:
        if not self.enabled or not self._started or self._loop is None:
            raise JemallocProfileRejected("jemalloc profile mode is not active")
        if self._transition_task is not None and not self._transition_task.done():
            raise JemallocProfileRejected("a jemalloc profile transition is already running")
        if self._state == "inactive":
            action = self._activate
        elif self._state == "sampling":
            action = self._complete
        elif self._state == "complete":
            raise JemallocProfileRejected("the fixed jemalloc profile sequence is complete")
        else:
            raise JemallocProfileRejected("the jemalloc profile controller is terminally failed")
        task = self._loop.create_task(action(), name=f"jemalloc-profile:{self._state}")
        self._transition_task = task
        task.add_done_callback(self._transition_finished)
        return task

    def _transition_finished(self, task: asyncio.Task[Path | None]) -> None:
        try:
            task.result()
        except BaseException:
            logger.exception("Jemalloc profile transition failed")

    async def activate(self) -> None:
        task = self._schedule_next()
        await asyncio.shield(task)

    async def complete(self) -> Path:
        task = self._schedule_next()
        result = await asyncio.shield(task)
        if result is None:
            raise JemallocProfileRejected("profile completion produced no artifact")
        return result

    async def close(self) -> None:
        if self._signal_installed and self._loop is not None and self._signal_number is not None:
            self._loop.remove_signal_handler(self._signal_number)
            self._signal_installed = False
        task = self._transition_task
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
        self._started = False
        self._loop = None

    def _contained(self, name: str) -> Path:
        if self._directory is None:
            raise JemallocProfileRejected("profile output directory is unavailable")
        candidate = (self._directory / name).resolve()
        try:
            candidate.relative_to(self._directory)
        except ValueError as exc:
            raise JemallocProfileRejected("profile artifact escapes its output directory") from exc
        return candidate

    def _ensure_new(self, *paths: Path) -> None:
        if any(path.exists() for path in paths):
            raise JemallocProfileRejected("profile artifacts already exist")

    async def _activate(self) -> None:
        activated = False
        try:
            async with self._transition_lock:
                if self._state != "inactive":
                    raise JemallocProfileRejected("profile activation is out of order")
                manifest_path = self._contained("activation.manifest.json")
                self._ensure_new(manifest_path)
                started = perf_counter()
                started_at = datetime.now(UTC).isoformat()
                reset_result = self._mallctl.reset()
                if reset_result != 0:
                    raise JemallocProfileRejected(
                        f"prof.reset failed with mallctl code {reset_result}"
                    )
                active_result = self._mallctl.write_bool("prof.active", True)
                if active_result != 0:
                    raise JemallocProfileRejected(
                        f"prof.active=true failed with mallctl code {active_result}"
                    )
                activated = True
                self._write_manifest(
                    manifest_path,
                    action="activate",
                    previous_state="inactive",
                    final_state="sampling",
                    started_at=started_at,
                    started=started,
                    mallctl={"prof.reset": reset_result, "prof.active=true": active_result},
                    artifacts=(),
                )
                self._state = "sampling"
        except BaseException:
            if activated:
                self._mallctl.write_bool("prof.active", False)
            self._state = "failed"
            raise

    async def _complete(self) -> Path:
        try:
            async with self._transition_lock:
                if self._state != "sampling":
                    raise JemallocProfileRejected("profile completion is out of order")
                profile_path = self._contained("profile.heap")
                manifest_path = self._contained("completion.manifest.json")
                self._ensure_new(profile_path, manifest_path)
                started = perf_counter()
                started_at = datetime.now(UTC).isoformat()
                active_result = self._mallctl.write_bool("prof.active", False)
                if active_result != 0:
                    raise JemallocProfileRejected(
                        f"prof.active=false failed with mallctl code {active_result}"
                    )
                dump_result = self._mallctl.dump(profile_path)
                if dump_result != 0:
                    raise JemallocProfileRejected(
                        f"prof.dump failed with mallctl code {dump_result}"
                    )
                if not profile_path.is_file() or profile_path.is_symlink():
                    raise JemallocProfileRejected(
                        "prof.dump did not create a regular profile artifact"
                    )
                self._write_manifest(
                    manifest_path,
                    action="complete",
                    previous_state="sampling",
                    final_state="complete",
                    started_at=started_at,
                    started=started,
                    mallctl={"prof.active=false": active_result, "prof.dump": dump_result},
                    artifacts=(profile_path,),
                )
                self._state = "complete"
                return profile_path
        except BaseException:
            self._state = "failed"
            raise

    def _write_manifest(
        self,
        path: Path,
        *,
        action: str,
        previous_state: str,
        final_state: str,
        started_at: str,
        started: float,
        mallctl: Mapping[str, int],
        artifacts: tuple[Path, ...],
    ) -> None:
        completed = perf_counter()
        document: dict[str, Any] = {
            "schema_version": "cybercontrol.jemalloc-profile-manifest.v1",
            "process_version": PROFILE_PROCESS_VERSION,
            "action": action,
            "previous_state": previous_state,
            "final_state": final_state,
            "started_at_utc": started_at,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "started_monotonic_seconds": started,
            "completed_monotonic_seconds": completed,
            "duration_seconds": round(completed - started, 6),
            "source": self._source_metadata,
            "process": {"pid": os.getpid()},
            "mallctl": dict(mallctl),
            "files": [
                {
                    "path": artifact.name,
                    "size_bytes": artifact.stat().st_size,
                    "sha256": _sha256(artifact),
                }
                for artifact in artifacts
            ],
        }
        _atomic_write(path, _json_bytes(document))
