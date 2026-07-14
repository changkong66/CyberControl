from __future__ import annotations

from uuid import uuid4

import pytest
from liyans.core.errors import LiyanError
from liyans.infrastructure.streaming.sse import (
    InMemorySSEReplayLog,
    ReplayCursorCodec,
    SSEBroker,
    SSEChunkAssembler,
    make_text_chunks,
)
from pydantic import ValidationError


def test_utf8_chunks_reassemble_after_out_of_order_delivery() -> None:
    stream_id = uuid4()
    candidate_id = uuid4()
    chunks = make_text_chunks(
        "控制系统稳定性",
        stream_id=stream_id,
        candidate_id=candidate_id,
        candidate_version=1,
        block_id="block-1",
        max_bytes=6,
    )
    assert len(chunks) > 2
    assert all(len(chunk.data.encode("utf-8")) <= 6 for chunk in chunks)

    assembler = SSEChunkAssembler()
    assembler.add(chunks[1])
    assembler.add(chunks[0])
    for chunk in chunks[2:]:
        assembler.add(chunk)
    assert (
        assembler.assembled_text(
            stream_id=stream_id,
            candidate_id=candidate_id,
            candidate_version=1,
            block_id="block-1",
        )
        == "控制系统稳定性"
    )


def test_chunk_contract_rejects_tampered_digest() -> None:
    chunk = make_text_chunks(
        "abc",
        stream_id=uuid4(),
        candidate_id=uuid4(),
        candidate_version=1,
        block_id=None,
    )[0]
    with pytest.raises(ValidationError):
        chunk.model_copy(update={"data": "changed"}).model_validate(
            {**chunk.model_dump(), "data": "changed"}
        )


@pytest.mark.asyncio
async def test_signed_cursor_is_tenant_bound_and_replay_is_monotonic() -> None:
    codec = ReplayCursorCodec(b"x" * 32)
    log = InMemorySSEReplayLog(capacity_per_tenant=4)
    broker = SSEBroker(log)
    first = await broker.publish("tenant-a", "progress", {"value": 1})
    second = await broker.publish("tenant-a", "progress", {"value": 2})
    cursor = codec.encode("tenant-a", first.sequence)
    assert codec.decode(cursor, "tenant-a") == first.sequence
    with pytest.raises(LiyanError):
        codec.decode(cursor, "tenant-b")
    replay = await log.replay("tenant-a", first.sequence)
    assert [event.sequence for event in replay] == [second.sequence]
