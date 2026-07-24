from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

_DELIMITER = re.compile(rb"\r\n\r\n|\n\n|\r\r")


class FrameActivityScanner:
    def __init__(self, callback: Callable[[bool], None]) -> None:
        self._callback = callback
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)
        while True:
            match = _DELIMITER.search(self._buffer)
            if match is None:
                return
            frame = bytes(self._buffer[: match.start()])
            del self._buffer[: match.end()]
            lines = frame.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
            heartbeat = bool(lines) and all(not line or line.startswith(b":") for line in lines)
            self._callback(heartbeat)


class TrackingEventSource:
    def __init__(
        self,
        response: Any,
        *,
        activity_callback: Callable[[bool], None],
        chunk_size: int = 4096,
    ) -> None:
        self._response = response
        self._scanner = FrameActivityScanner(activity_callback)
        self._chunk_size = chunk_size

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._response.iter_content(chunk_size=self._chunk_size):
            if not chunk:
                continue
            self._scanner.feed(chunk)
            yield chunk

    def close(self) -> None:
        self._response.close()


@dataclass(frozen=True, slots=True)
class ProbeEvent:
    run_id: str
    tenant_id: str
    probe_id: str
    ordinal: int
    producer_started_ns: int
    payload: dict[str, Any]


def parse_probe_event(data: str) -> ProbeEvent:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Gate C SSE data must be an object")
    run_id = str(value.get("gate_c_run_id", ""))
    tenant_id = str(value.get("gate_c_tenant_id", ""))
    probe_id = str(value.get("gate_c_probe_id", ""))
    ordinal = value.get("gate_c_probe_ordinal")
    producer_started_ns = value.get("gate_c_producer_started_ns")
    if not run_id or not tenant_id or not probe_id:
        raise ValueError("Gate C SSE probe identity is incomplete")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise ValueError("Gate C SSE probe ordinal is invalid")
    if (
        not isinstance(producer_started_ns, int)
        or isinstance(producer_started_ns, bool)
        or producer_started_ns <= 0
    ):
        raise ValueError("Gate C producer timestamp is invalid")
    return ProbeEvent(
        run_id=run_id,
        tenant_id=tenant_id,
        probe_id=probe_id,
        ordinal=ordinal,
        producer_started_ns=producer_started_ns,
        payload=value,
    )


def redact_sensitive(value: str) -> str:
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._~-]+", "Bearer [REDACTED]", value)
    return re.sub(
        r'(?i)(password|access_token|refresh_token|verification_code)(["\s:=]+)[^,}\s]+',
        r"\1\2[REDACTED]",
        redacted,
    )
