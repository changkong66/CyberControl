from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import uuid5

from liyans_contracts.topic3 import CandidateV1, SSEChunkV1

from liyans.infrastructure.streaming.sse import SSEBroker, make_text_chunks


class Topic3StreamCoordinator:
    """Persist-first staged stream adapter built on the frozen SSE runtime."""

    def __init__(self, broker: SSEBroker, *, max_chunk_bytes: int = 16_384) -> None:
        if not 256 <= max_chunk_bytes <= 65_536:
            raise ValueError("max_chunk_bytes must be between 256 and 65536")
        self._broker = broker
        self._max_chunk_bytes = max_chunk_bytes

    def candidate_chunks(self, candidate: CandidateV1) -> list[SSEChunkV1]:
        stream_id = uuid5(candidate.candidate_id, f"stream:{candidate.candidate_version}")
        chunks: list[SSEChunkV1] = []
        for block in candidate.blocks:
            payload = json.dumps(
                {
                    "candidate_id": str(candidate.candidate_id),
                    "candidate_version": candidate.candidate_version,
                    "resource_type": candidate.resource_type.value,
                    "block": block.model_dump(mode="json"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            generated = make_text_chunks(
                payload,
                stream_id=stream_id,
                candidate_id=candidate.candidate_id,
                candidate_version=candidate.candidate_version,
                block_id=block.block_id,
                max_bytes=self._max_chunk_bytes,
            )
            for chunk in generated:
                deterministic_id = uuid5(
                    candidate.candidate_id,
                    f"fragment:{candidate.candidate_version}:{block.block_id}:{chunk.chunk_index}",
                )
                chunks.append(chunk.model_copy(update={"fragment_id": deterministic_id}))
        return chunks

    async def publish_chunks(self, tenant_id: str, chunks: Sequence[SSEChunkV1]) -> None:
        for chunk in chunks:
            await self._broker.publish(
                tenant_id,
                "topic3.stream.chunk.staged",
                {"chunk": chunk.model_dump(mode="json")},
            )

    async def publish_progress(
        self,
        tenant_id: str,
        *,
        generation_session_id: str,
        task_id: str,
        agent: str,
        state: str,
        attempt: int,
    ) -> None:
        await self._broker.publish(
            tenant_id,
            "topic3.generation.progress",
            {
                "schema_version": "topic3.generation-progress.v1",
                "generation_session_id": generation_session_id,
                "task_id": task_id,
                "agent": agent,
                "state": state,
                "attempt": attempt,
            },
        )
