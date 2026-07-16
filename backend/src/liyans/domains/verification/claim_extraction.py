from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic3 import BlockType, CandidateV1
from liyans_contracts.topic4_c1 import ClaimV1, ExtractionMethod
from liyans_contracts.topic4_common import ClaimKind

from .records import build_topic4_record

_SENTENCE_PATTERN = re.compile(
    r".+?(?:[\n\u3002\uff01\uff1f!?\uff1b;]+|(?<!\d)\.(?=\s|$)|$)",
    re.DOTALL,
)
_FORMULA_PATTERN = re.compile(
    r"(?:\\(?:frac|sum|prod|lim|dot|mathbf|begin)|\$[^$]+\$|"
    r"\b(?:det|rank|trace|sin|cos|tan|exp|log)\s*\(|"
    r"[A-Za-z][A-Za-z0-9_]*(?:\([^\n]{0,64}\))?\s*(?:=|<=|>=|<|>)\s*[^\n]+)"
)
_THEOREM_PATTERN = re.compile(
    r"(?:theorem|lemma|corollary|criterion|\u5b9a\u7406|\u5f15\u7406|"
    r"\u5224\u636e|\u5fc5\u8981\u6761\u4ef6|\u5145\u5206\u6761\u4ef6)",
    re.IGNORECASE,
)
_STABILITY_PATTERN = re.compile(
    r"(?:stable|stability|unstable|hurwitz|routh|nyquist|bode|"
    r"\u7a33\u5b9a|\u4e0d\u7a33\u5b9a|\u9c81\u68d2)",
    re.IGNORECASE,
)
_NUMERIC_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?(?:%|ms|s|Hz|dB)?")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class ClaimExtractionError(ValueError):
    """Raised when a candidate cannot be converted into a bounded claim set."""


@dataclass(frozen=True, slots=True)
class ClaimExtractionPolicy:
    max_claims: int = 4096
    max_claims_per_block: int = 512
    max_statement_chars: int = 32_768
    max_content_depth: int = 16
    max_content_nodes: int = 100_000

    def __post_init__(self) -> None:
        values = (
            self.max_claims,
            self.max_claims_per_block,
            self.max_statement_chars,
            self.max_content_depth,
            self.max_content_nodes,
        )
        if any(value < 1 for value in values):
            raise ValueError("claim extraction limits must be positive")
        if self.max_claims > 4096:
            raise ValueError("max_claims cannot exceed the frozen contract limit")
        if self.max_statement_chars > 32_768:
            raise ValueError("max_statement_chars cannot exceed the frozen contract limit")


@dataclass(frozen=True, slots=True)
class _LeafText:
    json_pointer: str
    key_hint: str
    value: str


@dataclass(frozen=True, slots=True)
class _ClaimDraft:
    claim_id: UUID
    block_id: str
    block_dependencies: tuple[str, ...]
    claim_kind: ClaimKind
    claim_subtype: str
    statement: str
    normalized_statement: str
    json_pointer: str
    ordinal: int
    source_span_start: int
    source_span_end: int
    claim_sha256: str


class DeterministicClaimExtractor:
    """Extracts replay-stable claims without invoking an external model."""

    def __init__(self, policy: ClaimExtractionPolicy | None = None) -> None:
        self._policy = policy or ClaimExtractionPolicy()

    def extract(
        self,
        candidate: CandidateV1,
        *,
        verification_id: UUID,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> list[ClaimV1]:
        drafts: list[_ClaimDraft] = []
        for block in sorted(candidate.blocks, key=lambda item: item.ordinal):
            block_drafts = self._extract_block(
                candidate,
                verification_id=verification_id,
                tenant_id=tenant_id,
                block=block,
            )
            if len(block_drafts) > self._policy.max_claims_per_block:
                raise ClaimExtractionError(
                    f"block {block.block_id!r} exceeds the per-block claim limit"
                )
            drafts.extend(block_drafts)
            if len(drafts) > self._policy.max_claims:
                raise ClaimExtractionError("candidate exceeds the frozen claim limit")

        if not drafts:
            raise ClaimExtractionError("candidate contains no verifiable claims")

        claims_by_block: dict[str, list[UUID]] = {}
        for draft in drafts:
            claims_by_block.setdefault(draft.block_id, []).append(draft.claim_id)

        return [
            self._build_claim(
                candidate,
                verification_id=verification_id,
                trace_id=trace_id,
                tenant_id=tenant_id,
                created_at=created_at,
                draft=draft,
                dependent_claim_ids=self._dependency_claim_ids(draft, claims_by_block),
            )
            for draft in drafts
        ]

    def _extract_block(
        self,
        candidate: CandidateV1,
        *,
        verification_id: UUID,
        tenant_id: str,
        block: Any,
    ) -> list[_ClaimDraft]:
        if block.block_type == BlockType.METADATA:
            return []

        drafts: list[_ClaimDraft] = []
        seen: set[tuple[ClaimKind, str, str, int, int]] = set()
        for leaf in self._walk_strings(block.content):
            if self._is_metadata_leaf(block.block_type, leaf.key_hint):
                continue
            for start, end, statement in self._segments(block.block_type, leaf.value):
                normalized = self._normalize(statement)
                if not self._is_verifiable(normalized, block.block_type):
                    continue
                kind = self._claim_kind(block.block_type, normalized)
                deduplication_key = (kind, normalized, leaf.json_pointer, start, end)
                if deduplication_key in seen:
                    continue
                seen.add(deduplication_key)
                ordinal = len(drafts)
                subtype = self._claim_subtype(kind, leaf.key_hint, normalized)
                digest = canonical_sha256(
                    {
                        "candidate_id": str(candidate.candidate_id),
                        "candidate_version": candidate.candidate_version,
                        "block_id": block.block_id,
                        "kind": kind.value,
                        "subtype": subtype,
                        "statement": normalized,
                        "json_pointer": leaf.json_pointer,
                        "source_span": [start, end],
                    }
                )
                claim_id = uuid5(
                    NAMESPACE_URL,
                    f"liyans:topic4:claim:{tenant_id}:{verification_id}:{digest}",
                )
                drafts.append(
                    _ClaimDraft(
                        claim_id=claim_id,
                        block_id=block.block_id,
                        block_dependencies=tuple(block.dependency_block_ids),
                        claim_kind=kind,
                        claim_subtype=subtype,
                        statement=statement,
                        normalized_statement=normalized,
                        json_pointer=f"/blocks/{block.ordinal}/content{leaf.json_pointer}",
                        ordinal=ordinal,
                        source_span_start=start,
                        source_span_end=end,
                        claim_sha256=digest,
                    )
                )
        return drafts

    def _walk_strings(self, content: dict[str, Any]) -> Iterator[_LeafText]:
        visited = 0
        stack: list[tuple[str, str, Any, int]] = [("", "content", content, 0)]
        while stack:
            pointer, key_hint, value, depth = stack.pop()
            visited += 1
            if visited > self._policy.max_content_nodes:
                raise ClaimExtractionError("candidate content exceeds the node safety limit")
            if depth > self._policy.max_content_depth:
                raise ClaimExtractionError("candidate content exceeds the nesting safety limit")
            if isinstance(value, str):
                if value.strip():
                    yield _LeafText(pointer or "/", key_hint, value)
                continue
            if isinstance(value, dict):
                for key in sorted(value, reverse=True):
                    escaped = self._escape_pointer(str(key))
                    stack.append((f"{pointer}/{escaped}", str(key), value[key], depth + 1))
                continue
            if isinstance(value, list):
                for index in range(len(value) - 1, -1, -1):
                    stack.append((f"{pointer}/{index}", key_hint, value[index], depth + 1))

    def _segments(self, block_type: BlockType, value: str) -> Iterator[tuple[int, int, str]]:
        if block_type in {BlockType.CODE, BlockType.MERMAID}:
            yield from self._bounded_segments(value)
            return
        for match in _SENTENCE_PATTERN.finditer(value):
            start, end = self._trim_span(value, match.start(), match.end())
            if end <= start:
                continue
            yield from self._bounded_segments(value, start=start, end=end)

    def _bounded_segments(
        self,
        value: str,
        *,
        start: int = 0,
        end: int | None = None,
    ) -> Iterator[tuple[int, int, str]]:
        final = len(value) if end is None else end
        cursor = start
        while cursor < final:
            boundary = min(cursor + self._policy.max_statement_chars, final)
            segment_start, segment_end = self._trim_span(value, cursor, boundary)
            if segment_end > segment_start:
                yield segment_start, segment_end, value[segment_start:segment_end]
            cursor = boundary

    @staticmethod
    def _trim_span(value: str, start: int, end: int) -> tuple[int, int]:
        while start < end and value[start].isspace():
            start += 1
        while end > start and value[end - 1].isspace():
            end -= 1
        return start, end

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value)
        return _WHITESPACE_PATTERN.sub(" ", normalized).strip()

    @staticmethod
    def _is_verifiable(value: str, block_type: BlockType) -> bool:
        if not value:
            return False
        if block_type in {BlockType.CODE, BlockType.MERMAID, BlockType.QUIZ}:
            return True
        return any(character.isalnum() or "\u4e00" <= character <= "\u9fff" for character in value)

    @staticmethod
    def _is_metadata_leaf(block_type: BlockType, key_hint: str) -> bool:
        normalized = key_hint.casefold().replace("-", "_")
        common_metadata = {"id", "schema_version", "content_schema_version", "mime_type"}
        if normalized in common_metadata:
            return True
        return block_type == BlockType.CODE and normalized in {
            "language",
            "runtime",
            "filename",
            "entrypoint",
        }

    @staticmethod
    def _claim_kind(block_type: BlockType, statement: str) -> ClaimKind:
        mapping = {
            BlockType.MERMAID: ClaimKind.GRAPH,
            BlockType.QUIZ: ClaimKind.QUIZ,
            BlockType.CODE: ClaimKind.CODE,
            BlockType.EXTENSION: ClaimKind.EXTENSION,
        }
        if block_type in mapping:
            return mapping[block_type]
        return ClaimKind.FORMULA if _FORMULA_PATTERN.search(statement) else ClaimKind.TEXT

    @staticmethod
    def _claim_subtype(kind: ClaimKind, key_hint: str, statement: str) -> str:
        hint = re.sub(r"[^a-z0-9_.-]+", "_", key_hint.casefold()).strip("_")[:64]
        if kind == ClaimKind.FORMULA:
            if _STABILITY_PATTERN.search(statement):
                return "stability_conclusion"
            if _THEOREM_PATTERN.search(statement):
                return "theorem_statement"
            if _NUMERIC_PATTERN.search(statement):
                return "numeric_formula"
            return "formula_statement"
        if kind == ClaimKind.GRAPH:
            return "mermaid_graph"
        if kind == ClaimKind.QUIZ:
            return f"quiz_{hint or 'content'}"
        if kind == ClaimKind.CODE:
            return f"code_{hint or 'source'}"
        if kind == ClaimKind.EXTENSION:
            if any(token in hint for token in ("citation", "doi", "reference", "source")):
                return "extension_citation"
            return f"extension_{hint or 'content'}"
        if _THEOREM_PATTERN.search(statement):
            return "theorem_statement"
        if _STABILITY_PATTERN.search(statement):
            return "stability_conclusion"
        if _NUMERIC_PATTERN.search(statement):
            return "numeric_statement"
        return f"text_{hint or 'statement'}"

    @staticmethod
    def _dependency_claim_ids(
        draft: _ClaimDraft,
        claims_by_block: dict[str, list[UUID]],
    ) -> list[UUID]:
        dependencies: list[UUID] = []
        for block_id in draft.block_dependencies:
            dependencies.extend(claims_by_block.get(block_id, []))
            if len(dependencies) >= 128:
                break
        return dependencies[:128]

    @staticmethod
    def _escape_pointer(value: str) -> str:
        return value.replace("~", "~0").replace("/", "~1")

    @staticmethod
    def _build_claim(
        candidate: CandidateV1,
        *,
        verification_id: UUID,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
        draft: _ClaimDraft,
        dependent_claim_ids: list[UUID],
    ) -> ClaimV1:
        return build_topic4_record(
            ClaimV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="claim.v1",
            claim_id=draft.claim_id,
            verification_id=verification_id,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            candidate_sha256=candidate.candidate_sha256,
            block_id=draft.block_id,
            claim_kind=draft.claim_kind,
            claim_subtype=draft.claim_subtype,
            statement=draft.statement,
            normalized_statement=draft.normalized_statement,
            json_pointer=draft.json_pointer,
            ordinal=draft.ordinal,
            source_span_start=draft.source_span_start,
            source_span_end=draft.source_span_end,
            claim_sha256=draft.claim_sha256,
            extraction_method=ExtractionMethod.DETERMINISTIC,
            dependent_claim_ids=dependent_claim_ids,
        )
