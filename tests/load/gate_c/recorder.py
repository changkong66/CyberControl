from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from gate_c.sse_client import ProbeEvent


@dataclass(slots=True)
class ClientState:
    tenant_id: str
    principal_fingerprint: str
    slow_consumer: bool
    duplicate_replay_client: bool
    first_ordinal: int | None = None
    last_ordinal: int | None = None
    rendered_events: int = 0
    duplicate_received: int = 0
    duplicate_rendered: int = 0
    missing_ordinals: set[int] = field(default_factory=set)
    reconnect_attempts: int = 0
    reconnect_successes: int = 0
    heartbeats: int = 0
    last_activity_ns: int | None = None
    maximum_activity_gap_ms: float = 0.0
    duplicate_replay_armed: bool = False
    duplicate_replay_attempts: int = 0
    duplicate_replay_suppressions: int = 0


class MillisecondDistribution:
    def __init__(self) -> None:
        self._values: Counter[int] = Counter()
        self._count = 0
        self._maximum = 0

    def observe(self, value_ms: float) -> None:
        value = max(0, round(value_ms))
        self._values[value] += 1
        self._count += 1
        self._maximum = max(self._maximum, value)

    def percentile(self, percentile: float) -> int | None:
        if self._count == 0:
            return None
        rank = max(1, int(self._count * percentile + 0.999999))
        cumulative = 0
        for value in sorted(self._values):
            cumulative += self._values[value]
            if cumulative >= rank:
                return value
        return self._maximum

    def document(self) -> dict[str, Any]:
        return {
            "count": self._count,
            "p50_ms": self.percentile(0.50),
            "p95_ms": self.percentile(0.95),
            "p99_ms": self.percentile(0.99),
            "maximum_ms": self._maximum if self._count else None,
            "distribution_ms": dict(sorted(self._values.items())),
        }


class GateCRecorder:
    def __init__(self, *, run_id: str, stage: str, output_dir: Path) -> None:
        self.run_id = run_id
        self.stage = stage
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.process_id = os.getpid()
        self._lock = Lock()
        self._clients: dict[str, ClientState] = {}
        self._counters: Counter[str] = Counter()
        self._active_streams = 0
        self._delivery = MillisecondDistribution()
        self._token = MillisecondDistribution()
        self._connection = MillisecondDistribution()
        self._snapshot_path = output_dir / f"active-streams-{self.process_id}.jsonl"

    def register_client(
        self,
        client_id: str,
        tenant_id: str,
        *,
        principal_fingerprint: str,
        slow_consumer: bool,
        duplicate_replay_client: bool,
    ) -> None:
        with self._lock:
            self._clients[client_id] = ClientState(
                tenant_id=tenant_id,
                principal_fingerprint=principal_fingerprint,
                slow_consumer=slow_consumer,
                duplicate_replay_client=duplicate_replay_client,
            )

    def token_acquired(self, latency_ms: float, *, refreshed: bool) -> None:
        with self._lock:
            self._token.observe(latency_ms)
            self._counters["token_acquisitions"] += 1
            self._counters["token_refreshes" if refreshed else "token_initial_acquisitions"] += 1

    def token_failed(self) -> None:
        with self._lock:
            self._counters["token_acquisition_failures"] += 1

    def connect_attempt(self, *, reconnect: bool) -> None:
        with self._lock:
            self._counters["connection_attempts"] += 1
            if reconnect:
                self._counters["reconnect_attempts"] += 1

    def stream_opened(self, client_id: str, *, reconnect: bool, latency_ms: float) -> None:
        with self._lock:
            self._counters["connection_successes"] += 1
            self._connection.observe(latency_ms)
            self._active_streams += 1
            if reconnect:
                state = self._clients[client_id]
                state.reconnect_attempts += 1
                state.reconnect_successes += 1
                self._counters["reconnect_successes"] += 1

    def arm_duplicate_replay(self, client_id: str) -> None:
        with self._lock:
            state = self._clients[client_id]
            if state.duplicate_replay_armed:
                raise RuntimeError("duplicate replay is already armed")
            state.duplicate_replay_armed = True
            state.duplicate_replay_attempts += 1
            self._counters["duplicate_replay_attempts"] += 1

    def stream_failed(self, *, status_code: int | None) -> None:
        with self._lock:
            self._counters["connection_failures"] += 1
            if status_code is not None and status_code >= 500:
                self._counters["http_5xx"] += 1

    def stream_closed(self, *, planned: bool) -> None:
        with self._lock:
            self._active_streams = max(0, self._active_streams - 1)
            self._counters["planned_disconnects" if planned else "unexpected_disconnects"] += 1

    def activity(self, client_id: str, *, heartbeat: bool) -> None:
        now = time.time_ns()
        with self._lock:
            state = self._clients[client_id]
            if state.last_activity_ns is not None:
                gap = (now - state.last_activity_ns) / 1_000_000
                state.maximum_activity_gap_ms = max(state.maximum_activity_gap_ms, gap)
            state.last_activity_ns = now
            if heartbeat:
                state.heartbeats += 1
                self._counters["heartbeats"] += 1

    def invalid_event(self) -> None:
        with self._lock:
            self._counters["invalid_events"] += 1

    def non_probe_event(self) -> None:
        with self._lock:
            self._counters["non_probe_events"] += 1

    def record_probe(self, client_id: str, probe: ProbeEvent) -> bool:
        now_ns = time.time_ns()
        with self._lock:
            state = self._clients[client_id]
            if probe.run_id != self.run_id:
                self._counters["foreign_run_events"] += 1
                return False
            if probe.tenant_id != state.tenant_id:
                self._counters["cross_tenant_leakage"] += 1
                return False
            if state.last_ordinal is None:
                state.first_ordinal = probe.ordinal
                if probe.ordinal > 0:
                    state.missing_ordinals.update(range(probe.ordinal))
            elif probe.ordinal > state.last_ordinal + 1:
                state.missing_ordinals.update(range(state.last_ordinal + 1, probe.ordinal))
            elif probe.ordinal <= state.last_ordinal:
                if probe.ordinal in state.missing_ordinals:
                    state.missing_ordinals.remove(probe.ordinal)
                else:
                    state.duplicate_received += 1
                    self._counters["duplicate_received"] += 1
                    if state.duplicate_replay_armed:
                        state.duplicate_replay_armed = False
                        state.duplicate_replay_suppressions += 1
                        self._counters["duplicate_replay_suppressions"] += 1
                    return False
            state.last_ordinal = max(state.last_ordinal or 0, probe.ordinal)
            state.rendered_events += 1
            self._counters["rendered_events"] += 1
            self._delivery.observe((now_ns - probe.producer_started_ns) / 1_000_000)
            return True

    def snapshot(self) -> None:
        with self._lock:
            document = {
                "captured_at_unix_ns": time.time_ns(),
                "process_id": self.process_id,
                "active_streams": self._active_streams,
                "connection_successes": self._counters["connection_successes"],
                "unexpected_disconnects": self._counters["unexpected_disconnects"],
            }
        with self._snapshot_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, sort_keys=True) + "\n")

    def write_summary(self) -> Path:
        with self._lock:
            clients = {
                client_id: {
                    "tenant_id": state.tenant_id,
                    "principal_fingerprint": state.principal_fingerprint,
                    "slow_consumer": state.slow_consumer,
                    "duplicate_replay_client": state.duplicate_replay_client,
                    "first_ordinal": state.first_ordinal,
                    "last_ordinal": state.last_ordinal,
                    "rendered_events": state.rendered_events,
                    "duplicate_received": state.duplicate_received,
                    "duplicate_rendered": state.duplicate_rendered,
                    "missing_count": len(state.missing_ordinals),
                    "reconnect_attempts": state.reconnect_attempts,
                    "reconnect_successes": state.reconnect_successes,
                    "heartbeats": state.heartbeats,
                    "maximum_activity_gap_ms": round(state.maximum_activity_gap_ms, 3),
                    "duplicate_replay_armed": state.duplicate_replay_armed,
                    "duplicate_replay_attempts": state.duplicate_replay_attempts,
                    "duplicate_replay_suppressions": state.duplicate_replay_suppressions,
                }
                for client_id, state in sorted(self._clients.items())
            }
            document: dict[str, Any] = {
                "schema_version": "cybercontrol.gate-c-worker-result.v1",
                "run_id": self.run_id,
                "stage": self.stage,
                "process_id": self.process_id,
                "counters": dict(sorted(self._counters.items())),
                "active_streams_at_stop": self._active_streams,
                "delivery_latency_upper_bound": self._delivery.document(),
                "token_acquisition_latency": self._token.document(),
                "connection_establishment_latency": self._connection.document(),
                "clients": clients,
            }
        path = self.output_dir / f"worker-result-{self.process_id}.json"
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
