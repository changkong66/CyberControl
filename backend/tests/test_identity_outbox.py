from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from liyans.domains.identity.outbox import (
    IDENTITY_OUTBOX_EVENT_TYPES,
    register_identity_outbox_handlers,
)
from liyans.infrastructure.messaging.bus import AsyncMessageBus, DispatchStatus

IDENTITY_SERVICE = (
    Path(__file__).resolve().parents[1] / "src" / "liyans" / "domains" / "identity" / "service.py"
)


def test_identity_outbox_catalog_matches_all_emitted_service_events() -> None:
    tree = ast.parse(IDENTITY_SERVICE.read_text(encoding="utf-8"))
    emitted = {
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "event_type"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
        and keyword.value.value.startswith("identity.")
    }

    assert len(IDENTITY_OUTBOX_EVENT_TYPES) == len(set(IDENTITY_OUTBOX_EVENT_TYPES))
    assert emitted == set(IDENTITY_OUTBOX_EVENT_TYPES)


@pytest.mark.asyncio
async def test_identity_outbox_registration_dispatches_every_event(make_envelope) -> None:
    bus = AsyncMessageBus()
    handler = AsyncMock()
    register_identity_outbox_handlers(bus, handler)

    for index, event_type in enumerate(IDENTITY_OUTBOX_EVENT_TYPES):
        envelope = make_envelope(
            0,
            event_type=event_type,
            idempotency_key=f"identity-test-{index:02d}-0000000000000000",
        ).model_copy(update={"partition_key": f"identity:test:{index}"})
        result = await bus.publish(envelope)
        assert result.status == DispatchStatus.PROCESSED

    assert handler.await_count == len(IDENTITY_OUTBOX_EVENT_TYPES)
