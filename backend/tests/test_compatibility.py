from __future__ import annotations

from datetime import UTC, datetime

import pytest
from liyans.domains.generation.compatibility import (
    AgentPayloadAdapterRegistry,
    CompatibilityError,
    LegacyCandidateAdapter,
    Topic3EnvelopeAdapter,
)
from liyans_contracts.enums import SourceAgent


def test_legacy_envelope_is_tokenized_and_error_code_is_sanitized() -> None:
    result = Topic3EnvelopeAdapter().adapt(
        {
            "tenant_id": "tenant-a",
            "session_id": "legacy-session",
            "user_id": "student@example.edu",
            "timestamp": datetime.now(UTC).isoformat(),
            "type": "GenerationFailed",
            "seq": 0,
            "agent": "Lecturer",
            "error": {"code": "legacy bad/code", "message": "failed"},
            "data": {"reason": "test"},
        }
    )
    assert result.envelope.subject_ref.startswith("legacy-subject:")
    assert result.envelope.error is not None
    assert result.envelope.error.error_code == "LEGACY_BAD_CODE"
    assert {warning.code for warning in result.warnings} >= {
        "LEGACY_SUBJECT_TOKENIZED",
        "LEGACY_V0_ADAPTED",
    }


def test_legacy_candidate_adapter_emits_verified_hashes() -> None:
    now = datetime.now(UTC).isoformat()
    candidate = LegacyCandidateAdapter().adapt(
        {
            "candidate_id": "legacy-candidate",
            "blueprint_id": "legacy-blueprint",
            "agent": "Lecturer",
            "created_at": now,
            "blocks": [
                {
                    "block_id": "block-1",
                    "type": "MARKDOWN",
                    "content": {"text": "transfer function"},
                    "created_at": now,
                }
            ],
        }
    )
    assert candidate.resource_type.value == "Lecturer_Doc"
    assert len(candidate.candidate_sha256) == 64


@pytest.mark.asyncio
async def test_cross_agent_conversion_requires_explicit_adapter() -> None:
    registry = AgentPayloadAdapterRegistry()
    with pytest.raises(CompatibilityError):
        await registry.convert(
            SourceAgent.LECTURER,
            SourceAgent.TESTER,
            "lecturer.output.v1",
            {"content": "x"},
        )

    async def converter(payload: dict) -> dict:
        return {"source": payload["content"]}

    registry.register(
        SourceAgent.LECTURER,
        SourceAgent.TESTER,
        "lecturer.output.v1",
        converter,
    )
    assert await registry.convert(
        SourceAgent.LECTURER,
        SourceAgent.TESTER,
        "lecturer.output.v1",
        {"content": "x"},
    ) == {"source": "x"}
