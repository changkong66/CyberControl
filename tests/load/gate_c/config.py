from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _positive_float(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be positive")
    return float(value)


def _percentage(value: object, field: str) -> int:
    percentage = _positive_int(value, field)
    if percentage > 100 or 100 % percentage != 0:
        raise ValueError(f"{field} must be at most 100 and divide 100 exactly")
    return percentage


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    users: int
    spawn_rate: float
    sustain_seconds: int


@dataclass(frozen=True, slots=True)
class Thresholds:
    document: dict[str, Any]
    stages: tuple[Stage, ...]

    @classmethod
    def load(cls, path: Path) -> Thresholds:
        document = _object(path)
        if document.get("schema_version") != "cybercontrol.gate-c-thresholds.v1":
            raise ValueError("unsupported Gate C threshold schema")
        if document.get("frozen_before_execution") is not True:
            raise ValueError("Gate C thresholds must be frozen before execution")
        raw_stages = document.get("stages")
        if not isinstance(raw_stages, list) or not raw_stages:
            raise ValueError("Gate C thresholds require stages")
        stages: list[Stage] = []
        seen: set[str] = set()
        for raw in raw_stages:
            if not isinstance(raw, dict):
                raise ValueError("each Gate C stage must be an object")
            name = str(raw.get("name", "")).strip()
            if not name or name in seen:
                raise ValueError("Gate C stage names must be unique and nonempty")
            seen.add(name)
            stages.append(
                Stage(
                    name=name,
                    users=_positive_int(raw.get("users"), f"{name}.users"),
                    spawn_rate=_positive_float(raw.get("spawn_rate"), f"{name}.spawn_rate"),
                    sustain_seconds=_positive_int(
                        raw.get("sustain_seconds"), f"{name}.sustain_seconds"
                    ),
                )
            )
        target = _positive_int(document.get("target_active_connections"), "target")
        if stages[-1].users != target:
            raise ValueError("final Gate C stage must match target active connections")
        if stages[-1].sustain_seconds < _positive_int(
            document.get("minimum_sustain_seconds"), "minimum_sustain_seconds"
        ):
            raise ValueError("final Gate C stage is shorter than the frozen minimum")
        return cls(document=document, stages=tuple(stages))

    def stage(self, name: str) -> Stage:
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class Workload:
    document: dict[str, Any]
    tenant_ids: tuple[str, ...]
    principals_per_tenant: int
    worker_processes: int
    stream_path: str
    publish_path: str
    event_type: str

    @classmethod
    def load(cls, path: Path) -> Workload:
        document = _object(path)
        if document.get("schema_version") != "cybercontrol.gate-c-workload.v1":
            raise ValueError("unsupported Gate C workload schema")
        raw_tenants = document.get("tenant_ids")
        if not isinstance(raw_tenants, list) or len(raw_tenants) < 2:
            raise ValueError("Gate C workload requires at least two tenants")
        tenant_ids = tuple(str(value).strip() for value in raw_tenants)
        if any(not value for value in tenant_ids) or len(set(tenant_ids)) != len(tenant_ids):
            raise ValueError("Gate C tenant identifiers must be unique and nonempty")
        stream_path = str(document.get("stream_path", ""))
        publish_path = str(document.get("publish_path", ""))
        if not stream_path.startswith("/") or not publish_path.startswith("/"):
            raise ValueError("Gate C API paths must be absolute paths")
        event_type = str(document.get("event_type", ""))
        if not event_type.startswith("topic4."):
            raise ValueError("Gate C event type must use the Topic 4 projection prefix")
        _percentage(document.get("slow_consumer_percent"), "slow_consumer_percent")
        _percentage(document.get("duplicate_replay_percent"), "duplicate_replay_percent")
        slow_consumer_delay_ms = _positive_int(
            document.get("slow_consumer_delay_ms"), "slow_consumer_delay_ms"
        )
        burst_rate = _positive_float(
            document.get("burst_events_per_second_per_tenant"),
            "burst_events_per_second_per_tenant",
        )
        if slow_consumer_delay_ms * burst_rate >= 1000:
            raise ValueError(
                "slow consumers must retain processing headroom at the configured burst rate"
            )
        forced_disconnect_delay = _positive_int(
            document.get("forced_disconnect_after_sustain_seconds"),
            "forced_disconnect_after_sustain_seconds",
        )
        recovery_window = _positive_int(
            document.get("publisher_start_delay_seconds"),
            "publisher_start_delay_seconds",
        ) + _positive_int(document.get("publisher_drain_seconds"), "publisher_drain_seconds")
        if forced_disconnect_delay >= recovery_window:
            raise ValueError("forced disconnect must leave a post-fault observation window")
        _positive_int(
            document.get("expired_token_probe_grace_seconds"),
            "expired_token_probe_grace_seconds",
        )
        return cls(
            document=document,
            tenant_ids=tenant_ids,
            principals_per_tenant=_positive_int(
                document.get("principals_per_tenant"), "principals_per_tenant"
            ),
            worker_processes=_positive_int(document.get("worker_processes"), "worker_processes"),
            stream_path=stream_path,
            publish_path=publish_path,
            event_type=event_type,
        )

    def integer(self, field: str) -> int:
        return _positive_int(self.document.get(field), field)

    def number(self, field: str) -> float:
        return _positive_float(self.document.get(field), field)


@dataclass(frozen=True, slots=True)
class Credential:
    username: str
    password: str
    tenant_id: str
    subject_ref: str
    publisher: bool
    course_id: str
    target_kp_id: str


def credential_fingerprint(credential: Credential) -> str:
    value = "\0".join((credential.tenant_id, credential.subject_ref, credential.username)).encode(
        "utf-8"
    )
    return hashlib.sha256(value).hexdigest()


def is_deterministic_sample(global_slot: int, percent: int, *, phase: int = 0) -> bool:
    if global_slot < 0:
        raise ValueError("global_slot cannot be negative")
    _percentage(percent, "percent")
    interval = 100 // percent
    block = global_slot // interval
    return global_slot % interval == (block + phase) % interval


def is_slow_consumer(global_slot: int, percent: int) -> bool:
    return is_deterministic_sample(global_slot, percent)


def is_duplicate_replay_client(global_slot: int, percent: int) -> bool:
    return is_deterministic_sample(global_slot, percent, phase=7)


def load_credentials(path: Path) -> tuple[Credential, ...]:
    document = _object(path)
    if document.get("schema_version") != "cybercontrol.gate-c-credentials.v1":
        raise ValueError("unsupported Gate C credential schema")
    raw_credentials = document.get("credentials")
    if not isinstance(raw_credentials, list) or not raw_credentials:
        raise ValueError("Gate C credentials are empty")
    credentials: list[Credential] = []
    for raw in raw_credentials:
        if not isinstance(raw, dict):
            raise ValueError("Gate C credential entries must be objects")
        credential = Credential(
            username=str(raw.get("username", "")),
            password=str(raw.get("password", "")),
            tenant_id=str(raw.get("tenant_id", "")),
            subject_ref=str(raw.get("subject_ref", "")),
            publisher=raw.get("publisher") is True,
            course_id=str(raw.get("course_id", "")),
            target_kp_id=str(raw.get("target_kp_id", "")),
        )
        if not all(
            (
                credential.username,
                credential.password,
                credential.tenant_id,
                credential.subject_ref,
                credential.course_id,
                credential.target_kp_id,
            )
        ):
            raise ValueError("Gate C credential entry is incomplete")
        credentials.append(credential)
    return tuple(credentials)


def credentials_for_worker(
    credentials: tuple[Credential, ...],
    *,
    worker_index: int,
    worker_processes: int,
) -> tuple[Credential, ...]:
    if worker_processes <= 0:
        raise ValueError("worker_processes must be positive")
    if worker_index < 0 or worker_index >= worker_processes:
        raise ValueError("worker_index is outside the configured worker range")
    selected = credentials[worker_index::worker_processes]
    if not selected:
        raise ValueError("worker credential partition is empty")
    return selected
