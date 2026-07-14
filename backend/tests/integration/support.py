from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from liyans_contracts.enums import SourceAgent
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)


def make_envelope(
    tenant_id: str,
    now: datetime,
    *,
    sequence: int = 0,
) -> Topic3EnvelopeV1:
    return Topic3EnvelopeV1(
        schema_version="topic3.envelope.v1",
        envelope_id=uuid4(),
        event_type="topic3.integration.created",
        message_kind=MessageKind.EVENT,
        tenant_id=tenant_id,
        session_id=uuid4(),
        subject_ref="subject:integration",
        correlation_id=uuid4(),
        causation_id=None,
        sequence=sequence,
        partition_key=f"{tenant_id}:integration",
        producer=ProducerMetadataV1(
            agent=SourceAgent.LECTURER,
            service="integration-suite",
            instance_id="pytest",
            build_version="test-v1",
        ),
        delivery=DeliveryMetadataV1(
            idempotency_key=f"integration:{tenant_id}:{sequence:016d}",
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
        payload={"source": "integration"},
    )
