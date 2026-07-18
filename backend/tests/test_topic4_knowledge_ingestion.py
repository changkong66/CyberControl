from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from liyans_contracts.topic4_c2 import SourceAuthorityTier
from topic3_support import COURSE_ID, graph_snapshot

from liyans.domains.knowledge.ingestion import (
    BoundedKnowledgeChunker,
    DeterministicDocumentParser,
    FormulaSignatureExtractor,
    KnowledgePointMatcher,
    SourceImportCommand,
)
from liyans.domains.knowledge.retrieval import DeterministicTokenizer
from liyans.domains.verification.records import record_integrity_valid

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)


def _command(content: str, *, media_type: str = "text/markdown") -> SourceImportCommand:
    return SourceImportCommand(
        course_id=COURSE_ID,
        title="Automatic Control Theory",
        authors=("Author A",),
        publisher="Authoritative Press",
        authority_tier=SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK,
        source_type="TEXTBOOK",
        canonical_citation="Author A. Automatic Control Theory. 2026.",
        license_expression="LicenseRef-Educational-Authorized",
        version="2026.1",
        content=content.encode(),
        media_type=media_type,
        effective_from=NOW,
    )


def test_markdown_parser_formula_signatures_and_topic1_matching_are_deterministic() -> None:
    parser = DeterministicDocumentParser()
    command = _command(
        """# Transfer function
The transfer function is defined under zero initial conditions: $G(s)=Y(s)/U(s)$.

## Closed-loop stability
Closed-loop stability follows from the characteristic equation $1+G(s)H(s)=0$.
"""
    )
    first = parser.parse(command)
    second = parser.parse(command)
    assert first == second
    assert len(first.sections) == 2
    assert first.sections[1].parent_section_id == first.sections[0].section_id

    matcher = KnowledgePointMatcher(graph_snapshot())
    matched = {section.title: matcher.match(section) for section in first.sections}
    assert "KP_ATC_B" in matched["Transfer function"]
    assert "KP_ATC_C" in matched["Closed-loop stability"]

    signatures = FormulaSignatureExtractor().extract(
        first.sections,
        source_document_version_id=command.resolved_version_id("tenant-a"),
        trace_id="a" * 32,
        tenant_id="tenant-a",
        created_at=NOW,
    )
    assert len(signatures) == 2
    assert all(record_integrity_valid(signature) for signature in signatures)
    assert any(signature.canonical_expression == "1+G(s)H(s)=0" for signature in signatures)


def test_structured_parser_rejects_unknown_parent_and_unknown_topic1_id() -> None:
    parser = DeterministicDocumentParser()
    invalid_parent = json.dumps(
        {
            "sections": [
                {
                    "section_id": "child",
                    "parent_section_id": "missing",
                    "title": "Child",
                    "text": "Closed-loop stability.",
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="unknown parent"):
        parser.parse(_command(invalid_parent, media_type="application/json"))

    explicit_unknown = json.dumps(
        {
            "sections": [
                {
                    "section_id": "root",
                    "title": "Root",
                    "text": "Closed-loop stability.",
                    "topic1_knowledge_point_ids": ["KP_UNKNOWN"],
                }
            ]
        }
    )
    parsed = parser.parse(_command(explicit_unknown, media_type="application/json"))
    with pytest.raises(ValueError, match="unknown Topic 1"):
        KnowledgePointMatcher(graph_snapshot()).match(parsed.sections[0])


def test_section_artifact_digest_tampering_is_rejected() -> None:
    parser = DeterministicDocumentParser()
    parsed = parser.parse(_command("# Stability\nClosed-loop stability is pole-location based."))
    payload = json.loads(parser.sections_payload(parsed))
    payload["sections"][0]["text"] = "tampered"
    with pytest.raises(ValueError, match="digest"):
        parser.read_sections_payload(json.dumps(payload).encode())


def test_bounded_chunker_enforces_token_limit_and_forward_progress() -> None:
    parser = DeterministicDocumentParser()
    paragraph = "Closed-loop stability requires all poles in the open left half-plane. " * 500
    section = parser.parse(_command(paragraph, media_type="text/plain")).sections[0]
    chunker = BoundedKnowledgeChunker(
        DeterministicTokenizer(),
        max_tokens=128,
        overlap_tokens=16,
    )
    chunks = chunker.chunk(
        section,
        knowledge_point_ids=("KP_ATC_C",),
        formula_signature_ids=(),
    )
    assert len(chunks) > 5
    assert all(1 <= chunk.token_count <= 128 for chunk in chunks)
    assert len({chunk.content_sha256 for chunk in chunks}) > 1


def test_source_import_command_ids_are_stable_and_content_sensitive() -> None:
    first = _command("# Stability\nStable content")
    replay = replace(first)
    assert first.resolved_document_id("tenant-a") == replay.resolved_document_id("tenant-a")
    assert first.resolved_version_id("tenant-a") == replay.resolved_version_id("tenant-a")
    assert first.resolved_document_id("tenant-a") != first.resolved_document_id("tenant-b")
