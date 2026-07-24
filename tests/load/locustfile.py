from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from itertools import cycle
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

import gevent
from gate_c.config import (
    Credential,
    Workload,
    credential_fingerprint,
    credentials_for_worker,
    is_duplicate_replay_client,
    is_slow_consumer,
    load_credentials,
)
from gate_c.publisher import ProbePublisher
from gate_c.recorder import GateCRecorder
from gate_c.sse_client import TrackingEventSource, parse_probe_event
from gate_c.token_provider import TokenProvider
from locust import HttpUser, between, events, task
from locust.env import Environment
from locust.runners import (
    STATE_CLEANUP,
    STATE_STOPPED,
    STATE_STOPPING,
    LocalRunner,
    MasterRunner,
    WorkerRunner,
)
from sseclient import SSEClient


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


RUN_ID = _required("GATE_C_RUN_ID")
STAGE = _required("GATE_C_STAGE")
STAGE_RESULTS_DIR = Path(_required("GATE_C_STAGE_RESULTS_DIR"))
WORKLOAD = Workload.load(Path(_required("GATE_C_WORKLOAD_PATH")))
CREDENTIALS = load_credentials(Path(_required("GATE_C_CREDENTIALS_PATH")))
BASELINES = json.loads(Path(_required("GATE_C_BASELINE_CURSOR_PATH")).read_text(encoding="utf-8"))
TOTAL_SECONDS = int(_required("GATE_C_STAGE_TOTAL_SECONDS"))


class IdentityAllocator:
    def __init__(
        self,
        credentials: tuple[Credential, ...],
        *,
        worker_index: int,
        worker_processes: int,
    ) -> None:
        self._values = cycle(credentials)
        self._worker_index = worker_index
        self._worker_processes = worker_processes
        self._local_slot = 0
        self._lock = Lock()

    def next(self) -> tuple[Credential, int]:
        with self._lock:
            credential = next(self._values)
            global_slot = self._local_slot * self._worker_processes + self._worker_index
            self._local_slot += 1
            return credential, global_slot


TOKEN_PROVIDER = TokenProvider(
    token_url=(
        f"{_required('GATE_C_KEYCLOAK_BASE_URL').rstrip('/')}/realms/"
        "cybercontrol/protocol/openid-connect/token"
    ),
    client_id="cybercontrol-cli",
    refresh_skew_seconds=WORKLOAD.integer("token_refresh_skew_seconds"),
)


@dataclass(slots=True)
class RuntimeState:
    allocator: IdentityAllocator | None = None
    recorder: GateCRecorder | None = None
    publisher: ProbePublisher | None = None
    snapshot_greenlet: Any = None
    test_started_at: float | None = None
    fault_at_seconds: float = 0.0


STATE = RuntimeState()


def _recorder() -> GateCRecorder:
    if STATE.recorder is None:
        raise RuntimeError("Gate C recorder is not initialized")
    return STATE.recorder


def _allocator() -> IdentityAllocator:
    if STATE.allocator is None:
        raise RuntimeError("Gate C identity allocator is not initialized")
    return STATE.allocator


class GateCSSEUser(HttpUser):
    wait_time = between(0.01, 0.05)

    def on_start(self) -> None:
        self.credential, global_slot = _allocator().next()
        self.client_id = str(uuid4())
        self.baseline_cursor = str(BASELINES["cursors"][self.credential.tenant_id]["cursor"])
        self.cursor = self.baseline_cursor
        self.connected_once = False
        self.current_response = None
        self.has_probe = False
        self.forced_disconnect_used = False
        self.duplicate_replay_client = is_duplicate_replay_client(
            global_slot, WORKLOAD.integer("duplicate_replay_percent")
        )
        self.duplicate_replay_used = False
        self.slow_consumer = is_slow_consumer(
            global_slot, WORKLOAD.integer("slow_consumer_percent")
        )
        _recorder().register_client(
            self.client_id,
            self.credential.tenant_id,
            principal_fingerprint=credential_fingerprint(self.credential),
            slow_consumer=self.slow_consumer,
            duplicate_replay_client=self.duplicate_replay_client,
        )

    def on_stop(self) -> None:
        if self.current_response is not None:
            self.current_response.close()

    def _stopping(self) -> bool:
        runner = self.environment.runner
        return runner is None or runner.state in {STATE_STOPPING, STATE_STOPPED, STATE_CLEANUP}

    def _get_token(self) -> Any | None:
        try:
            token = TOKEN_PROVIDER.get(self.credential)
            if not token.from_cache:
                _recorder().token_acquired(token.acquisition_ms, refreshed=token.refreshed)
            return token
        except Exception:
            _recorder().token_failed()
            gevent.sleep(1)
            return None

    def _open_stream(
        self,
        token: Any,
        *,
        reconnect: bool,
        replay_cursor: str,
        intentional_duplicate_replay: bool,
    ) -> Any | None:
        _recorder().connect_attempt(reconnect=reconnect)
        headers = {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token.value}",
            "Cache-Control": "no-cache",
            "Last-Event-ID": replay_cursor,
            "X-Trace-ID": uuid4().hex,
            "X-Session-ID": str(uuid4()),
        }
        connection_started = time.perf_counter()
        response = self.client.get(
            WORKLOAD.stream_path,
            headers=headers,
            stream=True,
            timeout=(10, None),
            name="GET /internal/topic4/sse/stream",
        )
        self.current_response = response
        if response.status_code != 200 or "text/event-stream" not in response.headers.get(
            "Content-Type", ""
        ):
            _recorder().stream_failed(status_code=response.status_code)
            response.close()
            self.current_response = None
            gevent.sleep(1)
            return None
        _recorder().stream_opened(
            self.client_id,
            reconnect=reconnect,
            latency_ms=(time.perf_counter() - connection_started) * 1000,
        )
        self.connected_once = True
        if intentional_duplicate_replay:
            self.duplicate_replay_used = True
            _recorder().arm_duplicate_replay(self.client_id)
        return response

    def _should_force_disconnect(self) -> bool:
        test_started_at = STATE.test_started_at
        if test_started_at is None or self.forced_disconnect_used:
            return False
        return time.monotonic() - test_started_at >= STATE.fault_at_seconds

    def _consume_events(self, source: TrackingEventSource) -> bool:
        for event in SSEClient(source).events():
            if event.id:
                self.cursor = event.id
            if event.event != WORKLOAD.event_type:
                _recorder().non_probe_event()
                continue
            try:
                probe = parse_probe_event(event.data)
            except (ValueError, json.JSONDecodeError):
                _recorder().invalid_event()
                continue
            if _recorder().record_probe(self.client_id, probe):
                self.has_probe = True
            if self.slow_consumer:
                gevent.sleep(WORKLOAD.integer("slow_consumer_delay_ms") / 1000)
            if self._should_force_disconnect():
                self.forced_disconnect_used = True
                return True
            if self._stopping():
                return True
        return False

    @task
    def consume_stream(self) -> None:
        reconnect = self.connected_once
        token = self._get_token()
        if token is None:
            return
        replay_cursor = self.cursor
        intentional_duplicate_replay = (
            reconnect
            and self.duplicate_replay_client
            and not self.duplicate_replay_used
            and self.has_probe
        )
        if intentional_duplicate_replay:
            replay_cursor = self.baseline_cursor
        response = self._open_stream(
            token,
            reconnect=reconnect,
            replay_cursor=replay_cursor,
            intentional_duplicate_replay=intentional_duplicate_replay,
        )
        if response is None:
            return
        planned = False
        source = TrackingEventSource(
            response,
            activity_callback=lambda heartbeat: _recorder().activity(
                self.client_id, heartbeat=heartbeat
            ),
        )
        try:
            planned = self._consume_events(source)
        except Exception:
            planned = self._stopping()
        finally:
            source.close()
            self.current_response = None
            _recorder().stream_closed(planned=planned or self._stopping())


def _snapshot_loop() -> None:
    while True:
        _recorder().snapshot()
        gevent.sleep(1)


@events.init.add_listener
def on_locust_init(environment: Environment, **_kwargs: object) -> None:
    if isinstance(environment.runner, MasterRunner):
        return
    credentials = CREDENTIALS
    worker_index = 0
    worker_processes = 1
    if isinstance(environment.runner, WorkerRunner):
        worker_index = environment.runner.worker_index
        worker_processes = WORKLOAD.worker_processes
        credentials = credentials_for_worker(
            CREDENTIALS,
            worker_index=worker_index,
            worker_processes=worker_processes,
        )
    STATE.allocator = IdentityAllocator(
        credentials,
        worker_index=worker_index,
        worker_processes=worker_processes,
    )
    STATE.recorder = GateCRecorder(run_id=RUN_ID, stage=STAGE, output_dir=STAGE_RESULTS_DIR)
    STATE.test_started_at = time.monotonic()
    STATE.fault_at_seconds = float(_required("GATE_C_FAULT_AT_SECONDS"))
    STATE.snapshot_greenlet = gevent.spawn(_snapshot_loop)


@events.test_start.add_listener
def on_test_start(environment: Environment, **_kwargs: object) -> None:
    if isinstance(environment.runner, (MasterRunner, LocalRunner)):
        STATE.publisher = ProbePublisher(
            run_id=RUN_ID,
            stage=STAGE,
            output_dir=STAGE_RESULTS_DIR,
            total_seconds=TOTAL_SECONDS,
        )
        STATE.publisher.start()


@events.test_stop.add_listener
def on_test_stop(**_kwargs: object) -> None:
    if STATE.publisher is not None:
        STATE.publisher.stop()
        STATE.publisher = None
    if STATE.recorder is not None:
        STATE.recorder.snapshot()
        STATE.recorder.write_summary()


@events.quitting.add_listener
def on_quitting(**_kwargs: object) -> None:
    if STATE.snapshot_greenlet is not None:
        STATE.snapshot_greenlet.kill(block=False)
    if STATE.recorder is not None:
        STATE.recorder.write_summary()
