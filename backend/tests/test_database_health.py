from __future__ import annotations

import pytest

from liyans.infrastructure.database.health import DatabaseHealthProbe


class _Connection:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> None:
        if self._error is not None:
            raise self._error


class _Engine:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def connect(self) -> _Connection:
        return _Connection(self._error)


@pytest.mark.asyncio
async def test_database_health_probe_reports_success_and_failure() -> None:
    healthy = await DatabaseHealthProbe(_Engine()).check()  # type: ignore[arg-type]
    failed = await DatabaseHealthProbe(  # type: ignore[arg-type]
        _Engine(RuntimeError("database unavailable"))
    ).check()

    assert healthy.healthy is True
    assert healthy.error_type is None
    assert healthy.latency_ms >= 0
    assert failed.healthy is False
    assert failed.error_type == "RuntimeError"
    assert failed.latency_ms >= 0


def test_database_health_probe_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        DatabaseHealthProbe(_Engine(), timeout_seconds=0)  # type: ignore[arg-type]
