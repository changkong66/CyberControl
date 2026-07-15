from uuid import uuid4

import pytest

from liyans.domains.topic1.repository import Topic1Repository
from liyans.providers.topic1 import Topic1KnowledgeParser, Topic1ParseRequest


def test_topic1_provider_request_accepts_only_spark_text() -> None:
    request = Topic1ParseRequest(
        request_id=uuid4(),
        provider_alias="spark_text",
        source_document_ref="artifact:control-textbook",
        source_document_sha256="a" * 64,
        course_id="CRS_ATC_001",
    )
    assert request.locale == "zh-CN"
    assert Topic1KnowledgeParser.__name__ == "Topic1KnowledgeParser"
    assert hasattr(Topic1Repository, "replace_graph_content")


def test_topic1_provider_request_rejects_non_allowlisted_provider() -> None:
    with pytest.raises(ValueError, match="spark_text"):
        Topic1ParseRequest(
            request_id=uuid4(),
            provider_alias="external_llm",
            source_document_ref="artifact:control-textbook",
            source_document_sha256="a" * 64,
            course_id="CRS_ATC_001",
        )


def test_topic1_provider_request_rejects_invalid_digest() -> None:
    for invalid_digest in ("short", "z" * 64, "A" * 64):
        with pytest.raises(ValueError, match="SHA-256"):
            Topic1ParseRequest(
                request_id=uuid4(),
                provider_alias="spark_text",
                source_document_ref="artifact:control-textbook",
                source_document_sha256=invalid_digest,
                course_id="CRS_ATC_001",
            )
