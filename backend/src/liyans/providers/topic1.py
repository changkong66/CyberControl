from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from liyans_contracts.topic1 import Topic1ImportBundleV1


@dataclass(frozen=True, slots=True)
class Topic1ParseRequest:
    request_id: UUID
    provider_alias: str
    source_document_ref: str
    source_document_sha256: str
    course_id: str
    locale: str = "zh-CN"

    def __post_init__(self) -> None:
        if self.provider_alias != "spark_text":
            raise ValueError("Topic 1 parsing only permits the spark_text provider alias")
        if len(self.source_document_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_document_sha256
        ):
            raise ValueError("source_document_sha256 must be a SHA-256 hex digest")


class Topic1KnowledgeParser(Protocol):
    async def parse(self, request: Topic1ParseRequest) -> Topic1ImportBundleV1: ...
