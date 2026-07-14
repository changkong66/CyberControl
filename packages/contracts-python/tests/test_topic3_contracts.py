from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    ErrorReceiptV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic3 import (
    BlockStatus,
    BlockType,
    BlockV1,
    CandidateProvenanceV1,
    CandidateStatus,
    CandidateV1,
    SSEChunkV1,
)
from pydantic import ValidationError


def _envelope(**updates) -> dict:
    now = datetime.now(UTC)
    document = {
        "schema_version": "topic3.envelope.v1",
        "envelope_id": uuid4(),
        "event_type": "topic3.contract.test",
        "message_kind": MessageKind.EVENT,
        "tenant_id": "tenant-a",
        "session_id": uuid4(),
        "subject_ref": "subject:test",
        "correlation_id": uuid4(),
        "causation_id": None,
        "sequence": 0,
        "partition_key": "tenant-a:session",
        "producer": ProducerMetadataV1(
            agent=SourceAgent.LECTURER,
            service="test",
            instance_id="pytest",
            build_version="test-v1",
        ),
        "delivery": DeliveryMetadataV1(
            idempotency_key="contract:test:000000000000",
            available_at=now,
        ),
        "resource": None,
        "trace_id": "a" * 32,
        "span_id": None,
        "created_at": now,
        "error": None,
        "payload": {},
    }
    document.update(updates)
    return document


def test_error_envelope_requires_error_receipt() -> None:
    with pytest.raises(ValidationError):
        Topic3EnvelopeV1.model_validate(_envelope(message_kind=MessageKind.ERROR))

    now = datetime.now(UTC)
    envelope = Topic3EnvelopeV1.model_validate(
        _envelope(
            message_kind=MessageKind.ERROR,
            error=ErrorReceiptV1(
                schema_version="topic3.error-receipt.v1",
                error_code="TEST_ERROR",
                category="CONTRACT",
                severity="ERROR",
                retriable=False,
                safe_message="test",
                occurred_at=now,
            ),
        )
    )
    assert envelope.error is not None


def test_candidate_rejects_agent_resource_mismatch_and_noncontiguous_blocks() -> None:
    now = datetime.now(UTC)
    block = BlockV1(
        schema_version="topic3.block.v1",
        block_id="block-1",
        block_type=BlockType.MARKDOWN,
        ordinal=1,
        content_schema_version="lecturer.block.v1",
        content={"text": "x"},
        content_sha256=canonical_sha256({"text": "x"}),
        status=BlockStatus.COMPLETE,
        created_at=now,
    )
    with pytest.raises(ValidationError):
        CandidateV1(
            schema_version="topic3.candidate.v1",
            candidate_id=uuid4(),
            candidate_version=1,
            blueprint_id=uuid4(),
            blueprint_version="blueprint-v1",
            blueprint_sha256="b" * 64,
            resource_type=ResourceType.GRADIENT_QUIZ,
            status=CandidateStatus.COMPLETE,
            blocks=[block],
            provenance=CandidateProvenanceV1(
                agent=SourceAgent.LECTURER,
                agent_build_version="agent-v1",
                prompt_bundle_version="prompt-v1",
                provider_alias="spark_text",
            ),
            personalization_policy_digest="c" * 64,
            candidate_sha256="d" * 64,
            created_at=now,
        )

    ordinal_zero = block.model_copy(update={"ordinal": 0})
    with pytest.raises(ValidationError):
        CandidateV1(
            schema_version="topic3.candidate.v1",
            candidate_id=uuid4(),
            candidate_version=1,
            blueprint_id=uuid4(),
            blueprint_version="blueprint-v1",
            blueprint_sha256="b" * 64,
            resource_type=ResourceType.GRADIENT_QUIZ,
            status=CandidateStatus.COMPLETE,
            blocks=[ordinal_zero],
            provenance=CandidateProvenanceV1(
                agent=SourceAgent.LECTURER,
                agent_build_version="agent-v1",
                prompt_bundle_version="prompt-v1",
                provider_alias="spark_text",
            ),
            personalization_policy_digest="c" * 64,
            candidate_sha256="d" * 64,
            created_at=now,
        )


def test_candidate_accepts_exact_canonical_hash() -> None:
    now = datetime.now(UTC)
    block = BlockV1(
        schema_version="topic3.block.v1",
        block_id="block-1",
        block_type=BlockType.MARKDOWN,
        ordinal=0,
        content_schema_version="lecturer.block.v1",
        content={"text": "x"},
        content_sha256=canonical_sha256({"text": "x"}),
        status=BlockStatus.COMPLETE,
        created_at=now,
    )
    data = {
        "schema_version": "topic3.candidate.v1",
        "candidate_id": uuid4(),
        "candidate_version": 1,
        "parent_candidate_version": None,
        "blueprint_id": uuid4(),
        "blueprint_version": "blueprint-v1",
        "blueprint_sha256": "b" * 64,
        "resource_type": ResourceType.LECTURER_DOC,
        "status": CandidateStatus.COMPLETE,
        "blocks": [block],
        "provenance": CandidateProvenanceV1(
            agent=SourceAgent.LECTURER,
            agent_build_version="agent-v1",
            prompt_bundle_version="prompt-v1",
            provider_alias="spark_text",
        ),
        "personalization_policy_digest": "c" * 64,
        "created_at": now,
    }
    unvalidated = CandidateV1.model_construct(candidate_sha256="0" * 64, **data)
    digest = canonical_sha256(unvalidated.model_dump(mode="json", exclude={"candidate_sha256"}))
    candidate = CandidateV1(candidate_sha256=digest, **data)
    assert candidate.candidate_sha256 == digest


def test_sse_chunk_rejects_incorrect_hash() -> None:
    with pytest.raises(ValidationError):
        SSEChunkV1(
            schema_version="topic3.sse-chunk.v1",
            stream_id=uuid4(),
            fragment_id=uuid4(),
            candidate_id=uuid4(),
            candidate_version=1,
            fragment_type="SNAPSHOT",
            chunk_index=0,
            is_final=True,
            data_encoding="utf-8-text",
            data="content",
            data_sha256="0" * 64,
            emitted_at=datetime.now(UTC),
        )
