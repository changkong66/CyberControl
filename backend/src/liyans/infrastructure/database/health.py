from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True, slots=True)
class DatabaseHealthResult:
    healthy: bool
    latency_ms: float
    error_type: str | None = None


class DatabaseHealthProbe:
    def __init__(self, engine: AsyncEngine, *, timeout_seconds: float = 3.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._engine = engine
        self._timeout_seconds = timeout_seconds

    async def check(self) -> DatabaseHealthResult:
        started = perf_counter()
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except Exception as exc:
            return DatabaseHealthResult(
                healthy=False,
                latency_ms=(perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
            )
        return DatabaseHealthResult(
            healthy=True,
            latency_ms=(perf_counter() - started) * 1000,
        )
