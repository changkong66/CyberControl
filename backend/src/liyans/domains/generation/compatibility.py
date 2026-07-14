from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    ErrorReceiptV1,
    MessageKind,
    ProducerMetadataV1,
    ResourceMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic3 import (
    BlockStatus,
    BlockType,
    BlockV1,
    CandidateProvenanceV1,
    CandidateStatus,
    CandidateV1,
)
from pydantic import ValidationError

from liyans.core.hashing import sha256_hex

LEGACY_NAMESPACE = UUID("b2bbb3f4-a3fb-462a-ad61-17ab4aaf7bbc")


class CompatibilityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CompatibilityWarning:
    code: str
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class EnvelopeAdaptationResult:
    envelope: Topic3EnvelopeV1
    warnings: tuple[CompatibilityWarning, ...]


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise CompatibilityError("legacy timestamp is missing or invalid")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _normalize_event_type(value: Any) -> str:
    raw = str(value or "legacy.message").strip()
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1.\2", raw).lower()
    normalized = re.sub(r"[^a-z0-9_.-]+", ".", raw).strip(".")
    if not normalized or not normalized[0].isalpha():
        normalized = "legacy." + normalized
    return normalized[:128]


def _source_agent(value: Any) -> SourceAgent | None:
    if value is None:
        return None
    normalized = str(value).replace("-", "").replace("_", "").lower()
    mapping = {
        "lecturer": SourceAgent.LECTURER,
        "mindmap": SourceAgent.MIND_MAP,
        "tester": SourceAgent.TESTER,
        "codesandbox": SourceAgent.CODE_SANDBOX,
        "extension": SourceAgent.EXTENSION,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise CompatibilityError(f"unsupported legacy agent type: {value}") from exc


def _resource_type(value: Any, agent: SourceAgent | None) -> ResourceType | None:
    if value is not None:
        normalized = str(value).replace("-", "").replace("_", "").lower()
        mapping = {
            "lecturerdoc": ResourceType.LECTURER_DOC,
            "mindmap": ResourceType.MIND_MAP,
            "gradientquiz": ResourceType.GRADIENT_QUIZ,
            "simulationcode": ResourceType.SIMULATION_CODE,
            "extensionmaterial": ResourceType.EXTENSION_MATERIAL,
        }
        try:
            return mapping[normalized]
        except KeyError as exc:
            raise CompatibilityError(f"unsupported legacy resource type: {value}") from exc
    if agent is None:
        return None
    return {
        SourceAgent.LECTURER: ResourceType.LECTURER_DOC,
        SourceAgent.MIND_MAP: ResourceType.MIND_MAP,
        SourceAgent.TESTER: ResourceType.GRADIENT_QUIZ,
        SourceAgent.CODE_SANDBOX: ResourceType.SIMULATION_CODE,
        SourceAgent.EXTENSION: ResourceType.EXTENSION_MATERIAL,
    }[agent]


def _legacy_error_code(value: Any) -> str:
    normalized = re.sub(r"[^A-Z0-9_-]+", "_", str(value or "LEGACY_ERROR").upper())
    normalized = normalized.strip("_-")
    if not normalized or not normalized[0].isalpha():
        normalized = "LEGACY_" + normalized
    return normalized[:128]


def _stable_uuid(prefix: str, value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return uuid5(LEGACY_NAMESPACE, f"{prefix}:{value}")


class Topic3EnvelopeAdapter:
    def adapt(self, raw: dict[str, Any]) -> EnvelopeAdaptationResult:
        if raw.get("schema_version") == "topic3.envelope.v1":
            try:
                return EnvelopeAdaptationResult(
                    envelope=Topic3EnvelopeV1.model_validate(raw),
                    warnings=(),
                )
            except ValidationError as exc:
                raise CompatibilityError(str(exc)) from exc
        return self._adapt_legacy_v0(raw)

    def _adapt_legacy_v0(self, raw: dict[str, Any]) -> EnvelopeAdaptationResult:
        warnings: list[CompatibilityWarning] = []
        payload = raw.get("payload", raw.get("data", {}))
        if not isinstance(payload, dict):
            payload = {"value": payload}
            warnings.append(
                CompatibilityWarning(
                    "LEGACY_PAYLOAD_WRAPPED",
                    "payload",
                    "Non-object legacy payload was wrapped under value.",
                )
            )

        tenant_id = raw.get("tenant_id")
        session_value = raw.get("session_id")
        if not tenant_id or not session_value:
            raise CompatibilityError("legacy messages require tenant_id and session_id")

        created_at = _parse_datetime(raw.get("created_at", raw.get("timestamp")))
        event_type = _normalize_event_type(raw.get("event_type", raw.get("type")))
        sequence = int(raw.get("sequence", raw.get("seq", 0)))
        agent = _source_agent(raw.get("agent", raw.get("agent_type")))
        resource_type = _resource_type(raw.get("resource_type"), agent)

        raw_subject = raw.get("subject_ref", raw.get("user_ref", raw.get("user_id")))
        if raw_subject is None:
            raise CompatibilityError("legacy messages require subject_ref/user_ref/user_id")
        if "subject_ref" not in raw:
            raw_subject = "legacy-subject:" + sha256_hex(str(raw_subject))[:24]
            warnings.append(
                CompatibilityWarning(
                    "LEGACY_SUBJECT_TOKENIZED",
                    "subject_ref",
                    "Legacy user identity was converted to an opaque subject reference.",
                )
            )

        identity_material = {
            "tenant_id": tenant_id,
            "session_id": str(session_value),
            "event_type": event_type,
            "sequence": sequence,
            "payload": payload,
        }
        envelope_id = _stable_uuid(
            "envelope",
            raw.get("envelope_id", raw.get("message_id", sha256_hex(identity_material))),
        )
        correlation_id = _stable_uuid(
            "correlation",
            raw.get("correlation_id", session_value),
        )

        error_raw = raw.get("error")
        message_kind = MessageKind.ERROR if error_raw else MessageKind.EVENT
        error = None
        if error_raw:
            if not isinstance(error_raw, dict):
                error_raw = {"message": str(error_raw)}
            error = ErrorReceiptV1(
                schema_version="topic3.error-receipt.v1",
                error_code=_legacy_error_code(error_raw.get("code", "LEGACY_ERROR")),
                category=str(error_raw.get("category", "LEGACY")),
                severity=str(error_raw.get("severity", "ERROR")).upper(),
                retriable=bool(error_raw.get("retriable", False)),
                safe_message=str(error_raw.get("safe_message", error_raw.get("message", "error"))),
                details_ref=None,
                occurred_at=created_at,
            )

        resource = None
        blueprint_value = raw.get("blueprint_id")
        if resource_type is not None and blueprint_value is not None:
            candidate_value = raw.get("candidate_id")
            candidate_version = raw.get("candidate_version")
            if (candidate_value is None) != (candidate_version is None):
                raise CompatibilityError(
                    "legacy candidate_id and candidate_version must be provided together"
                )
            resource = ResourceMetadataV1(
                resource_type=resource_type,
                blueprint_id=_stable_uuid("blueprint", blueprint_value),
                blueprint_version=str(raw.get("blueprint_version", "legacy-v0")),
                candidate_id=(
                    _stable_uuid("candidate", candidate_value)
                    if candidate_value is not None
                    else None
                ),
                candidate_version=(
                    int(candidate_version) if candidate_version is not None else None
                ),
                block_id=raw.get("block_id"),
            )

        trace_value = str(raw.get("trace_id", sha256_hex(str(envelope_id))[:32]))
        trace_value = re.sub(r"[^a-fA-F0-9]", "", trace_value)[:64]
        if len(trace_value) < 16:
            trace_value = sha256_hex(trace_value or str(envelope_id))[:32]

        envelope = Topic3EnvelopeV1(
            schema_version="topic3.envelope.v1",
            envelope_id=envelope_id,
            event_type=event_type,
            message_kind=message_kind,
            tenant_id=str(tenant_id),
            session_id=_stable_uuid("session", session_value),
            subject_ref=str(raw_subject),
            correlation_id=correlation_id,
            causation_id=(
                _stable_uuid("causation", raw["causation_id"])
                if raw.get("causation_id") is not None
                else None
            ),
            sequence=sequence,
            partition_key=str(raw.get("partition_key", f"{tenant_id}:{session_value}")),
            producer=ProducerMetadataV1(
                agent=agent,
                service=str(raw.get("producer_service", "legacy-topic3-adapter")),
                instance_id=str(raw.get("producer_instance_id", "legacy")),
                build_version=str(raw.get("producer_version", "legacy-v0")),
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=str(
                    raw.get("idempotency_key", f"legacy:{sha256_hex(identity_material)}")
                ),
                attempt=int(raw.get("attempt", 1)),
                max_attempts=int(raw.get("max_attempts", 3)),
                priority=str(raw.get("priority", "NORMAL")).upper(),
                available_at=created_at,
                expires_at=(
                    _parse_datetime(raw["expires_at"])
                    if raw.get("expires_at") is not None
                    else None
                ),
            ),
            resource=resource,
            trace_id=trace_value,
            span_id=None,
            created_at=created_at,
            error=error,
            payload=payload,
        )
        warnings.append(
            CompatibilityWarning(
                "LEGACY_V0_ADAPTED",
                "schema_version",
                "Legacy message was adapted to strict Topic 3 Envelope v1.",
            )
        )
        return EnvelopeAdaptationResult(envelope=envelope, warnings=tuple(warnings))


class LegacyCandidateAdapter:
    def adapt(self, raw: dict[str, Any]) -> CandidateV1:
        blocks_raw = raw.get("blocks")
        if not isinstance(blocks_raw, list) or not blocks_raw:
            raise CompatibilityError("legacy candidate requires non-empty blocks")

        blocks: list[BlockV1] = []
        for ordinal, block_raw in enumerate(blocks_raw):
            if not isinstance(block_raw, dict):
                raise CompatibilityError("legacy block must be an object")
            content = block_raw.get("content", block_raw.get("data", {}))
            if not isinstance(content, dict):
                content = {"value": content}
            block_type = str(block_raw.get("block_type", block_raw.get("type", "METADATA")))
            block_type = block_type.replace("-", "_").upper()
            blocks.append(
                BlockV1(
                    schema_version="topic3.block.v1",
                    block_id=str(block_raw.get("block_id", f"block-{ordinal}")),
                    block_type=BlockType(block_type),
                    ordinal=int(block_raw.get("ordinal", ordinal)),
                    title=block_raw.get("title"),
                    content_schema_version=str(
                        block_raw.get("content_schema_version", "legacy.block-content.v0")
                    ),
                    content=content,
                    content_sha256=sha256_hex(content),
                    dependency_block_ids=list(block_raw.get("dependency_block_ids", [])),
                    status=BlockStatus(str(block_raw.get("status", "COMPLETE")).upper()),
                    created_at=_parse_datetime(block_raw.get("created_at", raw.get("created_at"))),
                )
            )

        agent = _source_agent(raw.get("agent", raw.get("agent_type")))
        if agent is None:
            raise CompatibilityError("legacy candidate requires agent type")
        resource_type = _resource_type(raw.get("resource_type"), agent)
        if resource_type is None:
            raise CompatibilityError("legacy candidate resource type cannot be resolved")

        provenance = CandidateProvenanceV1(
            agent=agent,
            agent_build_version=str(raw.get("agent_version", "legacy-v0")),
            prompt_bundle_version=str(raw.get("prompt_bundle_version", "legacy-v0")),
            provider_alias=str(raw.get("provider_alias", "local")),
            provider_request_ids=list(raw.get("provider_request_ids", [])),
        )
        candidate_data = {
            "schema_version": "topic3.candidate.v1",
            "candidate_id": _stable_uuid("candidate", raw.get("candidate_id")),
            "candidate_version": int(raw.get("candidate_version", 1)),
            "parent_candidate_version": raw.get("parent_candidate_version"),
            "blueprint_id": _stable_uuid("blueprint", raw.get("blueprint_id")),
            "blueprint_version": str(raw.get("blueprint_version", "legacy-v0")),
            "blueprint_sha256": str(
                raw.get("blueprint_sha256", sha256_hex(raw.get("blueprint_id")))
            ),
            "resource_type": resource_type,
            "status": CandidateStatus(str(raw.get("status", "COMPLETE")).upper()),
            "blocks": blocks,
            "provenance": provenance,
            "personalization_policy_digest": str(
                raw.get("personalization_policy_digest", sha256_hex("legacy-personalization"))
            ),
            "created_at": _parse_datetime(raw.get("created_at")),
        }
        canonical_candidate = {
            key: (
                value.model_dump(mode="json")
                if hasattr(value, "model_dump")
                else [item.model_dump(mode="json") for item in value]
                if isinstance(value, list)
                else value.isoformat().replace("+00:00", "Z")
                if isinstance(value, datetime)
                else str(value)
                if isinstance(value, UUID)
                else value.value
                if hasattr(value, "value")
                else value
            )
            for key, value in candidate_data.items()
        }
        candidate_data["candidate_sha256"] = str(
            raw.get("candidate_sha256", sha256_hex(canonical_candidate))
        )
        return CandidateV1(**candidate_data)


PayloadConverter = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class AgentPayloadAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[tuple[SourceAgent, SourceAgent, str], PayloadConverter] = {}

    def register(
        self,
        source: SourceAgent,
        target: SourceAgent,
        payload_schema_version: str,
        converter: PayloadConverter,
    ) -> None:
        key = (source, target, payload_schema_version)
        if key in self._adapters:
            raise CompatibilityError(f"payload adapter already registered: {key}")
        self._adapters[key] = converter

    async def convert(
        self,
        source: SourceAgent,
        target: SourceAgent,
        payload_schema_version: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if source == target:
            return dict(payload)
        key = (source, target, payload_schema_version)
        try:
            converter = self._adapters[key]
        except KeyError as exc:
            raise CompatibilityError(f"no explicit cross-agent adapter: {key}") from exc
        converted = converter(dict(payload))
        if inspect.isawaitable(converted):
            converted = await converted
        if not isinstance(converted, dict):
            raise CompatibilityError("cross-agent adapter must return an object payload")
        return converted
