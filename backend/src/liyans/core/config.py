from __future__ import annotations

import asyncio
import inspect
import logging
import tomllib
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liyans.core.hashing import sha256_hex

logger = logging.getLogger(__name__)

ConfigValidator = Callable[[dict[str, Any]], None]
ConfigListener = Callable[["ConfigSnapshot"], None | Awaitable[None]]
ConfigRejectionListener = Callable[[Path, Exception], None | Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    path: Path
    version: str
    digest: str
    loaded_at_monotonic: float
    document: dict[str, Any]


class HotReloadingTomlConfig:
    def __init__(
        self,
        path: Path,
        *,
        validator: ConfigValidator,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._path = path
        self._validator = validator
        self._poll_interval_seconds = poll_interval_seconds
        self._listeners: list[ConfigListener] = []
        self._rejection_listeners: list[ConfigRejectionListener] = []
        self._snapshot: ConfigSnapshot | None = None
        self._last_mtime_ns: int | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def snapshot(self) -> ConfigSnapshot:
        if self._snapshot is None:
            raise RuntimeError("configuration has not been loaded")
        return self._snapshot

    def add_listener(self, listener: ConfigListener) -> None:
        self._listeners.append(listener)

    def add_rejection_listener(self, listener: ConfigRejectionListener) -> None:
        self._rejection_listeners.append(listener)

    async def load(self) -> ConfigSnapshot:
        raw = self._path.read_bytes()
        document = tomllib.loads(raw.decode("utf-8"))
        self._validator(document)
        snapshot = ConfigSnapshot(
            path=self._path,
            version=str(document.get("policy_version", document.get("version", "unknown"))),
            digest=sha256_hex(raw),
            loaded_at_monotonic=asyncio.get_running_loop().time(),
            document=document,
        )
        for listener in self._listeners:
            result = listener(snapshot)
            if inspect.isawaitable(result):
                await result
        self._snapshot = snapshot
        self._last_mtime_ns = self._path.stat().st_mtime_ns
        return snapshot

    async def start(self) -> None:
        if self._task is not None:
            return
        await self.load()
        self._closed = False
        self._task = asyncio.create_task(self._watch(), name=f"config:{self._path.name}")

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _watch(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._poll_interval_seconds)
            try:
                mtime_ns = self._path.stat().st_mtime_ns
            except FileNotFoundError:
                continue
            if mtime_ns == self._last_mtime_ns:
                continue
            try:
                await self.load()
            except Exception as exc:
                for listener in self._rejection_listeners:
                    try:
                        result = listener(self._path, exc)
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        logger.exception(
                            "Configuration rejection listener failed for %s",
                            self._path,
                        )
                self._last_mtime_ns = mtime_ns
