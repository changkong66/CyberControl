from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from liyans_contracts.providers import ResponsesLiteRequestV1
from liyans_contracts.verification import ReleaseAuthorizationPayloadV1
from pydantic import ValidationError


def test_responses_lite_requires_tools() -> None:
    with pytest.raises(ValidationError):
        ResponsesLiteRequestV1(
            schema_version="responses.lite.request.v1",
            request_id=uuid4(),
            provider_alias="spark_text",
            model_alias="spark-default",
            instructions=[{"role": "system", "content": "verify"}],
            tools=[],
            input_segments=[{"text": "claim"}],
            response_schema={"type": "object"},
            temperature=0.0,
            max_output_tokens=256,
            timeout_ms=5000,
        )


def test_release_authorization_rejects_invalid_expiry() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        ReleaseAuthorizationPayloadV1(
            trace_id="a" * 32,
            tenant_id="tenant-a",
            version_cas=1,
            record_sha256="b" * 64,
            created_at=now,
            immutable=True,
            schema_version="release.authorization.v1",
            authorization_id=uuid4(),
            verification_id=uuid4(),
            report_id=uuid4(),
            candidate_id=uuid4(),
            candidate_version=1,
            candidate_sha256="c" * 64,
            release_mode="FULL",
            allowed_block_ids=["block-1"],
            disclosure_codes=[],
            report_sha256="d" * 64,
            issued_at=now,
            expires_at=now - timedelta(seconds=1),
            one_time_use=True,
        )
