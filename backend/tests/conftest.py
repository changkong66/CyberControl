from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from liyans_contracts.enums import SourceAgent
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)


@pytest.fixture
def make_envelope():
    def factory(
        sequence: int,
        *,
        idempotency_key: str | None = None,
        payload: dict | None = None,
        event_type: str = "topic3.test.event",
        tenant_id: str = "tenant-a",
    ) -> Topic3EnvelopeV1:
        now = datetime.now(UTC)
        return Topic3EnvelopeV1(
            schema_version="topic3.envelope.v1",
            envelope_id=uuid4(),
            event_type=event_type,
            message_kind=MessageKind.EVENT,
            tenant_id=tenant_id,
            session_id=uuid4(),
            subject_ref="subject:test",
            correlation_id=uuid4(),
            causation_id=None,
            sequence=sequence,
            partition_key=f"{tenant_id}:session-1",
            producer=ProducerMetadataV1(
                agent=SourceAgent.LECTURER,
                service="test-suite",
                instance_id="pytest",
                build_version="test-v1",
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=idempotency_key or f"test:{tenant_id}:{sequence}:0000000000000000",
                attempt=1,
                max_attempts=3,
                available_at=now,
                expires_at=now + timedelta(minutes=5),
            ),
            resource=None,
            trace_id="a" * 32,
            span_id="b" * 16,
            created_at=now,
            error=None,
            payload=payload or {"sequence": sequence},
        )

    return factory
