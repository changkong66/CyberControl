from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.hashing import canonical_json_bytes, sha256_hex

GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class AuditDraft:
    tenant_id: str
    category: str
    action: str
    outcome: str
    actor_ref: str
    target_ref: str | None
    trace_id: str | None
    envelope_id: str | None
    metadata: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AuditRecord:
    event_id: UUID
    tenant_id: str
    sequence: int
    category: str
    action: str
    outcome: str
    actor_ref: str
    target_ref: str | None
    trace_id: str | None
    envelope_id: str | None
    metadata: dict[str, Any]
    occurred_at: datetime
    previous_hash: str
    event_hash: str

    def to_document(self) -> dict[str, Any]:
        document = asdict(self)
        document["event_id"] = str(self.event_id)
        document["occurred_at"] = self.occurred_at.isoformat()
        return document


class AuditStore(Protocol):
    async def append(self, draft: AuditDraft) -> AuditRecord: ...

    async def records(self, tenant_id: str) -> list[AuditRecord]: ...


def _record_hash(document: dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(document))


def build_audit_record(draft: AuditDraft, sequence: int, previous_hash: str) -> AuditRecord:
    if draft.occurred_at.tzinfo is None:
        raise ValueError("audit occurred_at must be timezone-aware")
    draft = replace(draft, occurred_at=draft.occurred_at.astimezone(UTC))
    event_id = uuid4()
    material = {
        "event_id": str(event_id),
        "tenant_id": draft.tenant_id,
        "sequence": sequence,
        "category": draft.category,
        "action": draft.action,
        "outcome": draft.outcome,
        "actor_ref": draft.actor_ref,
        "target_ref": draft.target_ref,
        "trace_id": draft.trace_id,
        "envelope_id": draft.envelope_id,
        "metadata": draft.metadata,
        "occurred_at": draft.occurred_at.isoformat(),
        "previous_hash": previous_hash,
    }
    return AuditRecord(
        event_id=event_id,
        tenant_id=draft.tenant_id,
        sequence=sequence,
        category=draft.category,
        action=draft.action,
        outcome=draft.outcome,
        actor_ref=draft.actor_ref,
        target_ref=draft.target_ref,
        trace_id=draft.trace_id,
        envelope_id=draft.envelope_id,
        metadata=draft.metadata,
        occurred_at=draft.occurred_at,
        previous_hash=previous_hash,
        event_hash=_record_hash(material),
    )


def verify_audit_chain(records: list[AuditRecord]) -> bool:
    previous_hash = GENESIS_HASH
    for expected_sequence, record in enumerate(records):
        if record.sequence != expected_sequence or record.previous_hash != previous_hash:
            return False
        document = record.to_document()
        event_hash = document.pop("event_hash")
        if _record_hash(document) != event_hash:
            return False
        previous_hash = record.event_hash
    return True


class InMemoryAuditStore:
    def __init__(self) -> None:
        self._records: dict[str, list[AuditRecord]] = {}
        self._lock = asyncio.Lock()

    async def append(self, draft: AuditDraft) -> AuditRecord:
        async with self._lock:
            tenant_records = self._records.setdefault(draft.tenant_id, [])
            previous_hash = tenant_records[-1].event_hash if tenant_records else GENESIS_HASH
            record = build_audit_record(draft, len(tenant_records), previous_hash)
            tenant_records.append(record)
            return record

    async def records(self, tenant_id: str) -> list[AuditRecord]:
        async with self._lock:
            return list(self._records.get(tenant_id, []))


class JsonlAuditStore(InMemoryAuditStore):
    """Development durable store. Production implements AuditStore in PostgreSQL."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            record = AuditRecord(
                event_id=UUID(raw["event_id"]),
                tenant_id=raw["tenant_id"],
                sequence=int(raw["sequence"]),
                category=raw["category"],
                action=raw["action"],
                outcome=raw["outcome"],
                actor_ref=raw["actor_ref"],
                target_ref=raw.get("target_ref"),
                trace_id=raw.get("trace_id"),
                envelope_id=raw.get("envelope_id"),
                metadata=dict(raw.get("metadata", {})),
                occurred_at=datetime.fromisoformat(raw["occurred_at"]),
                previous_hash=raw["previous_hash"],
                event_hash=raw["event_hash"],
            )
            self._records.setdefault(record.tenant_id, []).append(record)
        for records in self._records.values():
            if not verify_audit_chain(records):
                raise ValueError("audit JSONL hash chain validation failed")

    async def append(self, draft: AuditDraft) -> AuditRecord:
        async with self._lock:
            tenant_records = self._records.setdefault(draft.tenant_id, [])
            previous_hash = tenant_records[-1].event_hash if tenant_records else GENESIS_HASH
            record = build_audit_record(draft, len(tenant_records), previous_hash)
            line = json.dumps(record.to_document(), ensure_ascii=False, separators=(",", ":"))
            await asyncio.to_thread(self._append_line, line)
            tenant_records.append(record)
            return record

    def _append_line(self, line: str) -> None:
        with self._path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class AuditService:
    def __init__(self, store: AuditStore) -> None:
        self._store = store

    async def record(
        self,
        *,
        tenant_id: str,
        category: str,
        action: str,
        outcome: str,
        actor_ref: str,
        target_ref: str | None = None,
        trace_id: str | None = None,
        envelope_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        critical: bool = True,
    ) -> AuditRecord | None:
        draft = AuditDraft(
            tenant_id=tenant_id,
            category=category,
            action=action,
            outcome=outcome,
            actor_ref=actor_ref,
            target_ref=target_ref,
            trace_id=trace_id,
            envelope_id=envelope_id,
            metadata=dict(metadata or {}),
            occurred_at=datetime.now(UTC),
        )
        try:
            return await self._store.append(draft)
        except Exception as exc:
            if critical:
                raise LiyanError(
                    ErrorCode.AUDIT_WRITE_FAILED,
                    "The audit evidence write failed.",
                    category=ErrorCategory.AUDIT,
                    status_code=503,
                ) from exc
            return None
