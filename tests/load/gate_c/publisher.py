from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from itertools import cycle
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

import requests

from gate_c.config import Credential, Workload, load_credentials
from gate_c.token_provider import TokenProvider


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _http_failure(exc: Exception) -> dict[str, Any]:
    if not isinstance(exc, requests.HTTPError) or exc.response is None:
        return {"status_code": None, "error_code": None}
    error_code = None
    try:
        document = exc.response.json()
        if isinstance(document, dict):
            error = document.get("error")
            if isinstance(error, dict):
                error_code = error.get("code")
            if error_code is None:
                error_code = document.get("error_code")
    except ValueError:
        pass
    return {
        "status_code": int(exc.response.status_code),
        "error_code": None if error_code is None else str(error_code),
    }


class ProbePublisher:
    def __init__(
        self,
        *,
        run_id: str,
        stage: str,
        output_dir: Path,
        total_seconds: int,
    ) -> None:
        self.run_id = run_id
        self.stage = stage
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.total_seconds = total_seconds
        self.workload = Workload.load(Path(_required("GATE_C_WORKLOAD_PATH")))
        credentials = load_credentials(Path(_required("GATE_C_CREDENTIALS_PATH")))
        self.publishers = tuple(value for value in credentials if value.publisher)
        if {value.tenant_id for value in self.publishers} != set(self.workload.tenant_ids):
            raise RuntimeError("Gate C requires one publisher for every tenant")
        self.api_base_url = _required("GATE_C_API_BASE_URL").rstrip("/")
        self.token_provider = TokenProvider(
            token_url=(
                f"{_required('GATE_C_KEYCLOAK_BASE_URL').rstrip('/')}/realms/"
                "cybercontrol/protocol/openid-connect/token"
            ),
            client_id="cybercontrol-cli",
            refresh_skew_seconds=self.workload.integer("token_refresh_skew_seconds"),
        )
        self.session = requests.Session()
        self.session.trust_env = False
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._ordinals = dict.fromkeys(self.workload.tenant_ids, 0)
        self._counters: dict[str, int] = {
            "publish_attempts": 0,
            "publish_successes": 0,
            "publish_failures": 0,
            "workflow_attempts": 0,
            "workflow_successes": 0,
            "workflow_failures": 0,
            "expired_token_probe_attempts": 0,
            "expired_token_probe_rejections": 0,
            "expired_token_probe_unexpected_acceptances": 0,
            "expired_token_probe_failures": 0,
        }
        self._events_path = output_dir / "publisher-events.jsonl"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="gate-c-probe-publisher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
        self._write_summary()

    def _append(self, document: dict[str, Any]) -> None:
        with self._lock, self._events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, sort_keys=True) + "\n")

    def _headers(self, credential: Credential) -> dict[str, str]:
        token = self.token_provider.get(credential)
        return {
            "Authorization": f"Bearer {token.value}",
            "Accept": "application/json",
            "X-Trace-ID": uuid4().hex,
            "X-Session-ID": str(uuid4()),
        }

    def publish_marker(self, credential: Credential, marker_name: str) -> dict[str, Any]:
        started_ns = time.time_ns()
        response = self.session.post(
            f"{self.api_base_url}{self.workload.publish_path}",
            headers=self._headers(credential),
            json={
                "event_type": self.workload.event_type,
                "data": {
                    "gate_c_run_id": self.run_id,
                    "gate_c_tenant_id": credential.tenant_id,
                    "gate_c_probe_id": str(uuid4()),
                    "gate_c_probe_ordinal": 0,
                    "gate_c_producer_started_ns": started_ns,
                    "gate_c_marker": marker_name,
                },
            },
            timeout=30,
            allow_redirects=False,
        )
        response.raise_for_status()
        document = response.json()
        return {
            "tenant_id": credential.tenant_id,
            "cursor": str(document["cursor"]),
            "sequence": int(document["sequence"]),
        }

    def _publish_probe(self, credential: Credential) -> None:
        ordinal = self._ordinals[credential.tenant_id]
        self._ordinals[credential.tenant_id] += 1
        probe_id = str(uuid4())
        started_ns = time.time_ns()
        padding_size = max(0, self.workload.integer("probe_payload_bytes") - 256)
        payload = {
            "gate_c_run_id": self.run_id,
            "gate_c_stage": self.stage,
            "gate_c_tenant_id": credential.tenant_id,
            "gate_c_probe_id": probe_id,
            "gate_c_probe_ordinal": ordinal,
            "gate_c_producer_started_ns": started_ns,
            "padding": "x" * padding_size,
        }
        self._counters["publish_attempts"] += 1
        try:
            response = self.session.post(
                f"{self.api_base_url}{self.workload.publish_path}",
                headers=self._headers(credential),
                json={"event_type": self.workload.event_type, "data": payload},
                timeout=30,
                allow_redirects=False,
            )
            response.raise_for_status()
            result = response.json()
            acknowledged_ns = time.time_ns()
            self._counters["publish_successes"] += 1
            self._append(
                {
                    "record_type": "probe",
                    "tenant_id": credential.tenant_id,
                    "probe_id": probe_id,
                    "ordinal": ordinal,
                    "producer_started_ns": started_ns,
                    "acknowledged_ns": acknowledged_ns,
                    "publish_latency_ms": round((acknowledged_ns - started_ns) / 1_000_000, 3),
                    "sequence": int(result["sequence"]),
                    "cursor_sha256": hashlib.sha256(
                        str(result["cursor"]).encode("utf-8")
                    ).hexdigest(),
                }
            )
        except Exception as exc:
            self._counters["publish_failures"] += 1
            self._append(
                {
                    "record_type": "probe_failure",
                    "tenant_id": credential.tenant_id,
                    "probe_id": probe_id,
                    "ordinal": ordinal,
                    "error_type": type(exc).__name__,
                }
            )

    def _trigger_workflow(self, credential: Credential) -> None:
        operation_id = uuid4()
        session_id = uuid4()
        self._counters["workflow_attempts"] += 1
        try:
            response = self.session.post(
                f"{self.api_base_url}/internal/topic3/generations",
                headers={
                    **self._headers(credential),
                    "Idempotency-Key": f"gate-c:{self.run_id}:{credential.tenant_id}:{session_id}",
                },
                json={
                    "schema_version": "topic3.generation-command.v1",
                    "operation_id": str(operation_id),
                    "generation_session_id": str(session_id),
                    "learner_ref": credential.subject_ref,
                    "course_id": credential.course_id,
                    "target_kp_ids": [credential.target_kp_id],
                    "requested_resources": ["Lecturer_Doc"],
                    "lecturer_depth": "ENGINEERING",
                    "learning_goal": "Gate C transactional Outbox and SSE acceptance.",
                    "locale": "zh-CN",
                    "max_parallelism": 1,
                    "allow_partial": False,
                    "requested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                },
                timeout=60,
                allow_redirects=False,
            )
            response.raise_for_status()
            self._counters["workflow_successes"] += 1
            self._append(
                {
                    "record_type": "workflow",
                    "tenant_id": credential.tenant_id,
                    "generation_session_id": str(session_id),
                    "accepted": True,
                }
            )
        except Exception as exc:
            self._counters["workflow_failures"] += 1
            self._append(
                {
                    "record_type": "workflow_failure",
                    "tenant_id": credential.tenant_id,
                    "generation_session_id": str(session_id),
                    "error_type": type(exc).__name__,
                    **_http_failure(exc),
                }
            )

    def _probe_expired_token(self, token_value: str, *, expired_for_seconds: float) -> None:
        self._counters["expired_token_probe_attempts"] += 1
        try:
            response = self.session.get(
                f"{self.api_base_url}{self.workload.stream_path}",
                headers={
                    "Accept": "text/event-stream",
                    "Authorization": f"Bearer {token_value}",
                    "X-Trace-ID": uuid4().hex,
                    "X-Session-ID": str(uuid4()),
                },
                stream=True,
                timeout=(10, 10),
                allow_redirects=False,
            )
            status_code = response.status_code
            response.close()
            if status_code == 401:
                self._counters["expired_token_probe_rejections"] += 1
            else:
                self._counters["expired_token_probe_unexpected_acceptances"] += 1
            self._append(
                {
                    "record_type": "expired_token_probe",
                    "status_code": status_code,
                    "expired_for_seconds": round(expired_for_seconds, 3),
                }
            )
        except Exception as exc:
            self._counters["expired_token_probe_failures"] += 1
            self._append(
                {
                    "record_type": "expired_token_probe_failure",
                    "error_type": type(exc).__name__,
                    "expired_for_seconds": round(expired_for_seconds, 3),
                }
            )

    def _run(self) -> None:
        start_delay = self.workload.integer("publisher_start_delay_seconds")
        drain_seconds = self.workload.integer("publisher_drain_seconds")
        deadline = time.monotonic() + max(0, self.total_seconds - drain_seconds)
        if self._stop.wait(start_delay):
            return
        started = time.monotonic()
        expiry_probe_token = None
        expiry_probe_at = None
        try:
            expiry_probe_token = self.token_provider.get(self.publishers[0])
            expiry_probe_at = expiry_probe_token.expires_at_monotonic + self.workload.integer(
                "expired_token_probe_grace_seconds"
            )
        except Exception as exc:
            self._append(
                {
                    "record_type": "expired_token_probe_setup_failure",
                    "error_type": type(exc).__name__,
                }
            )
        next_workflow = started + 30
        publishers = cycle(self.publishers)
        while not self._stop.is_set() and time.monotonic() < deadline:
            if (
                expiry_probe_token is not None
                and expiry_probe_at is not None
                and time.monotonic() >= expiry_probe_at
            ):
                self._probe_expired_token(
                    expiry_probe_token.value,
                    expired_for_seconds=time.monotonic() - expiry_probe_token.expires_at_monotonic,
                )
                expiry_probe_token = None
                expiry_probe_at = None
            elapsed = time.monotonic() - started
            burst_interval = self.workload.integer("burst_interval_seconds")
            in_burst = elapsed % burst_interval < self.workload.integer("burst_seconds")
            per_tenant_rate = self.workload.number(
                "burst_events_per_second_per_tenant"
                if in_burst
                else "baseline_events_per_second_per_tenant"
            )
            total_rate = per_tenant_rate * len(self.publishers)
            loop_started = time.monotonic()
            self._publish_probe(next(publishers))
            now = time.monotonic()
            if now >= next_workflow:
                for credential in self.publishers:
                    self._trigger_workflow(credential)
                next_workflow = now + self.workload.integer("workflow_interval_seconds")
            delay = max(0.0, (1.0 / total_rate) - (time.monotonic() - loop_started))
            self._stop.wait(delay)

    def _write_summary(self) -> None:
        document = {
            "schema_version": "cybercontrol.gate-c-publisher-result.v1",
            "run_id": self.run_id,
            "stage": self.stage,
            "counters": self._counters,
            "last_ordinal_by_tenant": {
                tenant_id: ordinal - 1 for tenant_id, ordinal in self._ordinals.items()
            },
        }
        (self.output_dir / "publisher-result.json").write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def create_baseline() -> int:
    run_id = _required("GATE_C_RUN_ID")
    stage = _required("GATE_C_STAGE")
    output_dir = Path(_required("GATE_C_STAGE_RESULTS_DIR"))
    publisher = ProbePublisher(run_id=run_id, stage=stage, output_dir=output_dir, total_seconds=1)
    cursors = {
        credential.tenant_id: publisher.publish_marker(credential, "stage-baseline")
        for credential in publisher.publishers
    }
    document = {
        "schema_version": "cybercontrol.gate-c-baseline-cursors.v1",
        "run_id": run_id,
        "stage": stage,
        "cursors": cursors,
    }
    path = output_dir / "baseline-cursors.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"baseline_cursor_path": str(path), "tenant_count": len(cursors)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(create_baseline())
