from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic4_c2 import (
    FormulaSignatureV1,
    SourceAuthorityTier,
    SourceLifecycle,
)

from liyans.core.hashing import canonical_json_bytes
from liyans.domains.verification.records import build_topic4_record

from .retrieval import DeterministicTokenizer

MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_SECTIONS = 65_536
MAX_SECTION_TEXT_BYTES = 4 * 1024 * 1024
SUPPORTED_SOURCE_MEDIA_TYPES = frozenset({"text/markdown", "text/plain", "application/json"})
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？.!?；;])\s+|\n{2,}")
INLINE_FORMULA_PATTERNS = (
    re.compile(r"\$\$(.+?)\$\$", re.DOTALL),
    re.compile(r"(?<!\$)\$([^$\n]{1,8192})\$(?!\$)"),
    re.compile(r"\\\[(.+?)\\\]", re.DOTALL),
    re.compile(r"\\\((.+?)\\\)", re.DOTALL),
)
EQUATION_FRAGMENT = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9_]*(?:\([^\n()]{1,128}\))?|[0-9]+(?:\.[0-9]+)?)"
    r"(?:\s*[+\-*/^]\s*[^，。；;\n=<>]{1,128})?"
    r"\s*(?:=|<=|>=|<|>)\s*[^，。；;\n]{1,512}"
)
FORMULA_OPERATOR = re.compile(r"<=|>=|!=|==|[+\-*/^=<>]")
FORMULA_SYMBOL = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
SECTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


@dataclass(frozen=True, slots=True)
class SourceImportCommand:
    course_id: str
    title: str
    authors: tuple[str, ...]
    publisher: str
    authority_tier: SourceAuthorityTier
    source_type: str
    canonical_citation: str
    license_expression: str
    version: str
    content: bytes
    media_type: Literal["text/markdown", "text/plain", "application/json"]
    effective_from: datetime
    published_on: date | None = None
    effective_until: datetime | None = None
    lifecycle: SourceLifecycle = SourceLifecycle.ACTIVE
    parser_version: str = "c2-parser-v1"
    source_document_id: UUID | None = None
    source_document_version_id: UUID | None = None

    def __post_init__(self) -> None:
        bounded = (
            self.course_id,
            self.title,
            self.publisher,
            self.source_type,
            self.canonical_citation,
            self.license_expression,
            self.version,
            self.parser_version,
        )
        if any(not value.strip() for value in bounded):
            raise ValueError("source import metadata cannot be blank")
        if len(self.content) < 1 or len(self.content) > MAX_SOURCE_BYTES:
            raise ValueError("source content is outside the accepted size range")
        if self.media_type not in SUPPORTED_SOURCE_MEDIA_TYPES:
            raise ValueError("source media type is not supported")
        if self.effective_from.tzinfo is None:
            raise ValueError("effective_from must be timezone-aware")
        if self.effective_until is not None:
            if self.effective_until.tzinfo is None:
                raise ValueError("effective_until must be timezone-aware")
            if self.effective_until <= self.effective_from:
                raise ValueError("effective_until must be after effective_from")
        if len(self.authors) > 128 or any(not author.strip() for author in self.authors):
            raise ValueError("source authors are invalid")

    def resolved_document_id(self, tenant_id: str) -> UUID:
        if self.source_document_id is not None:
            return self.source_document_id
        citation_digest = canonical_sha256(self.canonical_citation)
        return uuid5(
            NAMESPACE_URL,
            f"liyans://{tenant_id}/topic4/c2/{self.course_id}/{citation_digest}",
        )

    def resolved_version_id(self, tenant_id: str) -> UUID:
        if self.source_document_version_id is not None:
            return self.source_document_version_id
        return uuid5(self.resolved_document_id(tenant_id), f"source-version:{self.version}")


@dataclass(frozen=True, slots=True)
class ParsedSection:
    section_id: str
    parent_section_id: str | None
    ordinal: int
    title: str
    json_pointer: str
    text: str
    text_sha256: str
    explicit_knowledge_point_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    sections: tuple[ParsedSection, ...]
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    section_id: str
    chunk_ordinal: int
    normalized_text: str
    content_sha256: str
    token_count: int
    topic1_knowledge_point_ids: tuple[str, ...]
    formula_signature_ids: tuple[UUID, ...]
    lexical_terms: tuple[str, ...]


class DeterministicDocumentParser:
    def parse(self, command: SourceImportCommand) -> ParsedDocument:
        try:
            decoded = command.content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("source content must be valid UTF-8") from exc
        if "\x00" in decoded:
            raise ValueError("source content cannot contain NUL characters")
        normalized = self._normalize_text(decoded)
        if command.media_type == "text/markdown":
            sections = self._parse_markdown(normalized)
        elif command.media_type == "application/json":
            sections = self._parse_json(normalized)
        else:
            sections = self._parse_plain_text(normalized)
        if not sections:
            raise ValueError("source content produced no non-empty sections")
        if len(sections) > MAX_SECTIONS:
            raise ValueError("source document exceeds the section limit")
        if len({section.section_id for section in sections}) != len(sections):
            raise ValueError("source document contains duplicate section identifiers")
        return ParsedDocument(
            sections=tuple(sections),
            content_sha256=sha256(command.content).hexdigest(),
        )

    def sections_payload(self, parsed: ParsedDocument) -> bytes:
        return canonical_json_bytes(
            {
                "schema_version": "document-sections.v1",
                "content_sha256": parsed.content_sha256,
                "sections": [
                    {
                        "section_id": section.section_id,
                        "parent_section_id": section.parent_section_id,
                        "ordinal": section.ordinal,
                        "title": section.title,
                        "json_pointer": section.json_pointer,
                        "text": section.text,
                        "text_sha256": section.text_sha256,
                        "topic1_knowledge_point_ids": list(section.explicit_knowledge_point_ids),
                    }
                    for section in parsed.sections
                ],
            }
        )

    @classmethod
    def read_sections_payload(cls, payload: bytes) -> tuple[ParsedSection, ...]:
        try:
            document = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("document section artifact is not valid JSON") from exc
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != "document-sections.v1"
        ):
            raise ValueError("document section artifact schema is unsupported")
        raw_sections = document.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ValueError("document section artifact has no sections")
        sections: list[ParsedSection] = []
        for raw in raw_sections:
            if not isinstance(raw, dict):
                raise ValueError("document section artifact contains an invalid section")
            text = str(raw.get("text", ""))
            digest = sha256(text.encode("utf-8")).hexdigest()
            if digest != raw.get("text_sha256"):
                raise ValueError("document section artifact failed its text digest check")
            explicit = raw.get("topic1_knowledge_point_ids", [])
            if not isinstance(explicit, list):
                raise ValueError("document section knowledge-point ids must be an array")
            sections.append(
                ParsedSection(
                    section_id=str(raw["section_id"]),
                    parent_section_id=(
                        None
                        if raw.get("parent_section_id") is None
                        else str(raw["parent_section_id"])
                    ),
                    ordinal=int(raw["ordinal"]),
                    title=str(raw["title"]),
                    json_pointer=str(raw["json_pointer"]),
                    text=text,
                    text_sha256=digest,
                    explicit_knowledge_point_ids=tuple(str(item) for item in explicit),
                )
            )
        return tuple(sorted(sections, key=lambda item: item.ordinal))

    def _parse_markdown(self, value: str) -> list[ParsedSection]:
        sections: list[ParsedSection] = []
        stack: dict[int, str] = {}
        title = "Document"
        parent_id: str | None = None
        body: list[str] = []

        def flush() -> None:
            nonlocal body
            text = self._normalize_section_text("\n".join(body))
            if text or not sections:
                sections.append(self._section(len(sections), title, parent_id, text or title))
            body = []

        seen_heading = False
        for line in value.splitlines():
            heading = MARKDOWN_HEADING.match(line)
            if heading is None:
                body.append(line)
                continue
            if body or seen_heading:
                flush()
            level = len(heading.group(1))
            title = heading.group(2).strip()[:1024]
            parent_id = next(
                (
                    stack[parent_level]
                    for parent_level in range(level - 1, 0, -1)
                    if parent_level in stack
                ),
                None,
            )
            predicted_id = self._section_id(len(sections), title)
            stack = {depth: identifier for depth, identifier in stack.items() if depth < level}
            stack[level] = predicted_id
            seen_heading = True
        if body or seen_heading or not sections:
            flush()
        return sections

    def _parse_plain_text(self, value: str) -> list[ParsedSection]:
        paragraphs = [self._normalize_section_text(item) for item in re.split(r"\n{2,}", value)]
        paragraphs = [item for item in paragraphs if item]
        return [
            self._section(
                ordinal,
                self._plain_title(paragraph, ordinal),
                None,
                paragraph,
            )
            for ordinal, paragraph in enumerate(paragraphs)
        ]

    def _parse_json(self, value: str) -> list[ParsedSection]:
        try:
            document = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("structured source content is not valid JSON") from exc
        raw_sections = document.get("sections") if isinstance(document, dict) else None
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ValueError("structured source content requires a non-empty sections array")
        sections: list[ParsedSection] = []
        for ordinal, raw in enumerate(raw_sections):
            if not isinstance(raw, dict):
                raise ValueError("structured source section must be an object")
            title = str(raw.get("title", "")).strip()
            text = self._normalize_section_text(str(raw.get("text", "")))
            if not title or not text:
                raise ValueError("structured source section requires title and text")
            requested_id = str(raw.get("section_id", "")).strip()
            section_id = (
                requested_id
                if SECTION_ID_PATTERN.fullmatch(requested_id)
                else self._section_id(ordinal, title)
            )
            parent = raw.get("parent_section_id")
            explicit = raw.get("topic1_knowledge_point_ids", [])
            if not isinstance(explicit, list) or any(
                not isinstance(item, str) for item in explicit
            ):
                raise ValueError("structured section knowledge-point ids must be strings")
            sections.append(
                ParsedSection(
                    section_id=section_id,
                    parent_section_id=None if parent is None else str(parent),
                    ordinal=ordinal,
                    title=title[:1024],
                    json_pointer=f"/sections/{ordinal}",
                    text=text,
                    text_sha256=sha256(text.encode("utf-8")).hexdigest(),
                    explicit_knowledge_point_ids=tuple(dict.fromkeys(explicit)),
                )
            )
        known = {section.section_id for section in sections}
        if any(
            section.parent_section_id is not None and section.parent_section_id not in known
            for section in sections
        ):
            raise ValueError("structured source section references an unknown parent")
        return sections

    def _section(
        self,
        ordinal: int,
        title: str,
        parent_section_id: str | None,
        text: str,
    ) -> ParsedSection:
        if len(text.encode("utf-8")) > MAX_SECTION_TEXT_BYTES:
            raise ValueError("source section exceeds the accepted size limit")
        section_id = self._section_id(ordinal, title)
        return ParsedSection(
            section_id=section_id,
            parent_section_id=parent_section_id,
            ordinal=ordinal,
            title=title[:1024],
            json_pointer=f"/sections/{ordinal}",
            text=text,
            text_sha256=sha256(text.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _section_id(ordinal: int, title: str) -> str:
        digest = sha256(f"{ordinal}:{title}".encode()).hexdigest()[:16]
        return f"section-{ordinal:05d}-{digest}"

    @staticmethod
    def _plain_title(paragraph: str, ordinal: int) -> str:
        first = SENTENCE_BOUNDARY.split(paragraph, maxsplit=1)[0].strip()
        return (first[:120] or f"Section {ordinal + 1}")[:1024]

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
        return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()

    @staticmethod
    def _normalize_section_text(value: str) -> str:
        lines = [re.sub(r"[\t ]+", " ", line).strip() for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()


class FormulaSignatureExtractor:
    def extract(
        self,
        sections: tuple[ParsedSection, ...],
        *,
        source_document_version_id: UUID,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> tuple[FormulaSignatureV1, ...]:
        signatures: dict[str, FormulaSignatureV1] = {}
        for section in sections:
            for expression in self._candidates(section.text):
                canonical = self.canonicalize(expression)
                if not canonical or len(canonical) > 8192:
                    continue
                operators = self.operator_multiset(canonical)
                if not operators:
                    continue
                material = {
                    "canonical_expression": canonical,
                    "operator_multiset": operators,
                    "dimensional_signature": None,
                }
                signature_sha256 = canonical_sha256(material)
                if signature_sha256 in signatures:
                    continue
                signatures[signature_sha256] = build_topic4_record(
                    FormulaSignatureV1,
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    version_cas=1,
                    created_at=created_at,
                    immutable=True,
                    schema_version="formula-signature.v1",
                    formula_signature_id=uuid5(
                        source_document_version_id,
                        f"formula-signature:{signature_sha256}",
                    ),
                    source_document_version_id=source_document_version_id,
                    section_id=section.section_id,
                    canonical_expression=canonical,
                    symbol_arity=len(set(FORMULA_SYMBOL.findall(canonical))),
                    operator_multiset=operators,
                    dimensional_signature=None,
                    signature_sha256=signature_sha256,
                )
        return tuple(signatures[key] for key in sorted(signatures))

    def match_ids(
        self,
        value: str,
        signatures: tuple[FormulaSignatureV1, ...],
    ) -> tuple[UUID, ...]:
        by_digest = {item.signature_sha256: item.formula_signature_id for item in signatures}
        matched: list[UUID] = []
        for expression in self._candidates(value):
            canonical = self.canonicalize(expression)
            if not canonical:
                continue
            digest = canonical_sha256(
                {
                    "canonical_expression": canonical,
                    "operator_multiset": self.operator_multiset(canonical),
                    "dimensional_signature": None,
                }
            )
            identifier = by_digest.get(digest)
            if identifier is not None and identifier not in matched:
                matched.append(identifier)
        return tuple(matched)

    @staticmethod
    def canonicalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value)
        replacements = {
            "−": "-",
            "×": "*",
            "÷": "/",
            "≤": "<=",
            "≥": ">=",
            "≠": "!=",
            "\\cdot": "*",
            "\\times": "*",
            "\\left": "",
            "\\right": "",
        }
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return re.sub(r"\s+", "", normalized).strip("$`")

    @staticmethod
    def operator_multiset(value: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for operator in FORMULA_OPERATOR.findall(value):
            counts[operator] = counts.get(operator, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _candidates(value: str) -> tuple[str, ...]:
        candidates: list[str] = []
        residual = value
        for pattern in INLINE_FORMULA_PATTERNS:
            candidates.extend(match.group(1) for match in pattern.finditer(residual))
            residual = pattern.sub(" ", residual)
        candidates.extend(match.group(0) for match in EQUATION_FRAGMENT.finditer(residual))
        return tuple(dict.fromkeys(item.strip() for item in candidates if item.strip()))


class KnowledgePointMatcher:
    def __init__(self, graph: Topic1GraphSnapshotV1) -> None:
        self._tokenizer = DeterministicTokenizer()
        self._known = {point.kp_id: point for point in graph.content.knowledge_points}

    def match(self, section: ParsedSection) -> tuple[str, ...]:
        unknown = set(section.explicit_knowledge_point_ids) - set(self._known)
        if unknown:
            raise ValueError(
                "source section references unknown Topic 1 knowledge points: "
                + ", ".join(sorted(unknown))
            )
        if section.explicit_knowledge_point_ids:
            return tuple(dict.fromkeys(section.explicit_knowledge_point_ids))

        normalized = unicodedata.normalize("NFKC", f"{section.title}\n{section.text}").lower()
        section_tokens = set(self._tokenizer.tokenize(normalized))
        scored: list[tuple[float, str]] = []
        for point in self._known.values():
            names = [point.title, *getattr(point, "aliases", [])]
            exact = any(
                len(name.strip()) >= 2 and unicodedata.normalize("NFKC", name).lower() in normalized
                for name in names
            )
            point_text = " ".join(
                [
                    point.title,
                    point.summary,
                    *getattr(point, "aliases", []),
                    *point.tags,
                    *point.formula_signatures,
                ]
            )
            point_tokens = set(self._tokenizer.tokenize(point_text))
            overlap = len(section_tokens & point_tokens) / max(1, len(point_tokens))
            score = max(1.0 if exact else 0.0, overlap)
            if score >= 0.35:
                scored.append((score, point.kp_id))
        return tuple(
            identifier
            for _, identifier in sorted(scored, key=lambda item: (-item[0], item[1]))[:32]
        )


class BoundedKnowledgeChunker:
    def __init__(
        self,
        tokenizer: DeterministicTokenizer,
        *,
        max_tokens: int = 384,
        overlap_tokens: int = 48,
    ) -> None:
        if not 64 <= max_tokens <= 16_384:
            raise ValueError("chunk max_tokens must be between 64 and 16384")
        if not 0 <= overlap_tokens < max_tokens:
            raise ValueError("chunk overlap must be smaller than max_tokens")
        self._tokenizer = tokenizer
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    def chunk(
        self,
        section: ParsedSection,
        *,
        knowledge_point_ids: tuple[str, ...],
        formula_signature_ids: tuple[UUID, ...],
    ) -> tuple[ChunkDraft, ...]:
        value = self._normalize_chunk_text(f"{section.title}\n{section.text}")
        pieces = self._windows(value)
        drafts: list[ChunkDraft] = []
        for ordinal, piece in enumerate(pieces):
            tokens = self._tokenizer.tokenize(piece)
            if not tokens or len(tokens) > self._max_tokens:
                raise ValueError("chunker produced an invalid token count")
            lexical_terms = tuple(dict.fromkeys(tokens))[:8192]
            drafts.append(
                ChunkDraft(
                    section_id=section.section_id,
                    chunk_ordinal=ordinal,
                    normalized_text=piece,
                    content_sha256=canonical_sha256(piece),
                    token_count=len(tokens),
                    topic1_knowledge_point_ids=knowledge_point_ids,
                    formula_signature_ids=formula_signature_ids,
                    lexical_terms=lexical_terms,
                )
            )
        return tuple(drafts)

    def _windows(self, value: str) -> tuple[str, ...]:
        if len(self._tokenizer.tokenize(value)) <= self._max_tokens:
            return (value,)
        windows: list[str] = []
        start = 0
        while start < len(value):
            end = self._max_end(value, start)
            end = self._prefer_boundary(value, start, end)
            piece = value[start:end].strip()
            if not piece:
                raise ValueError("chunker could not make forward progress")
            windows.append(piece)
            if end >= len(value):
                break
            next_start = self._overlap_start(value, start, end)
            start = max(start + 1, next_start)
        return tuple(windows)

    def _max_end(self, value: str, start: int) -> int:
        low = start + 1
        high = len(value)
        best = low
        while low <= high:
            middle = (low + high) // 2
            count = len(self._tokenizer.tokenize(value[start:middle]))
            if count <= self._max_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return best

    @staticmethod
    def _prefer_boundary(value: str, start: int, end: int) -> int:
        if end >= len(value):
            return end
        minimum = start + max(1, (end - start) // 2)
        for position in range(end, minimum, -1):
            if value[position - 1] in "\n。！？.!?；; ":
                return position
        return end

    def _overlap_start(self, value: str, start: int, end: int) -> int:
        if self._overlap_tokens == 0:
            return end
        low = start
        high = end - 1
        best = end
        while low <= high:
            middle = (low + high) // 2
            count = len(self._tokenizer.tokenize(value[middle:end]))
            if count <= self._overlap_tokens:
                best = middle
                high = middle - 1
            else:
                low = middle + 1
        return best

    @staticmethod
    def _normalize_chunk_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value)
        normalized = re.sub(r"[\t ]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()
