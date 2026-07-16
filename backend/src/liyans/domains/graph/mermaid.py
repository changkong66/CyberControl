from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from liyans_contracts.topic4_c4 import GraphRelation

MERMAID_PARSER_VERSION = "c4-mermaid-parser-v1"
_IDENTIFIER = r"[A-Za-z][A-Za-z0-9_-]{0,127}"
_HEADER = re.compile(r"^(?:graph|flowchart)\s+(TB|TD|BT|RL|LR)$", re.IGNORECASE)
_EDGE = re.compile(
    rf"^(?P<source>{_IDENTIFIER})\s*"
    rf"(?P<operator>==>|-\.->|-->|---)\s*"
    rf"(?:\|(?P<label>[^|\r\n]{{0,128}})\|\s*)?"
    rf"(?P<target>{_IDENTIFIER})$"
)
_NODE = re.compile(
    rf"^(?P<node>{_IDENTIFIER})"
    rf"(?P<shape>\[\[.*\]\]|\[.*\]|\(\(.*\)\)|\(.*\)|\{{\{{.*\}}\}}|\{{.*\}})?$"
)
_CLASS = re.compile(
    rf"^class\s+(?P<nodes>{_IDENTIFIER}(?:,{_IDENTIFIER})*)\s+(?P<name>{_IDENTIFIER})$"
)
_CLASS_DEF = re.compile(rf"^classDef\s+(?P<name>{_IDENTIFIER})\s+(?P<style>.+)$")
_STYLE = re.compile(rf"^style\s+(?P<node>{_IDENTIFIER})\s+(?P<style>.+)$")
_LINK_STYLE = re.compile(r"^linkStyle\s+(?P<ordinal>\d+)\s+(?P<style>.+)$")
_SAFE_STYLE = re.compile(r"^[A-Za-z0-9_#.,:;%()\-+\s]+$")
_FORBIDDEN_TOKENS = (
    "<script",
    "javascript:",
    "href=",
    "click ",
    "%%{",
    "init:",
    "callback",
    "call ",
    "data:",
)


class MermaidSyntaxError(ValueError):
    """Raised when a Mermaid graph is outside the supported grammar."""


class MermaidSecurityError(MermaidSyntaxError):
    """Raised when a graph contains an executable or unsafe Mermaid directive."""


@dataclass(frozen=True, slots=True)
class MermaidPolicy:
    max_chars: int = 65_536
    max_lines: int = 4_096
    max_nodes: int = 4_096
    max_edges: int = 16_384
    max_label_chars: int = 512
    max_subgraph_depth: int = 16

    def __post_init__(self) -> None:
        if not 1 <= self.max_chars <= 65_536:
            raise ValueError("max_chars must be between 1 and 65536")
        if not 1 <= self.max_lines <= 16_384:
            raise ValueError("max_lines must be between 1 and 16384")
        if not 1 <= self.max_nodes <= 4_096:
            raise ValueError("max_nodes must be between 1 and 4096")
        if not 1 <= self.max_edges <= 16_384:
            raise ValueError("max_edges must be between 1 and 16384")
        if not 1 <= self.max_label_chars <= 4_096:
            raise ValueError("max_label_chars must be between 1 and 4096")
        if not 1 <= self.max_subgraph_depth <= 64:
            raise ValueError("max_subgraph_depth must be between 1 and 64")


@dataclass(frozen=True, slots=True)
class MermaidNodeDraft:
    node_id: str
    label: str
    node_type: str
    explicit: bool


@dataclass(frozen=True, slots=True)
class MermaidEdgeDraft:
    source_node_id: str
    target_node_id: str
    relation: GraphRelation
    directed: bool
    operator: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class ParsedMermaidGraph:
    direction: str
    nodes: tuple[MermaidNodeDraft, ...]
    edges: tuple[MermaidEdgeDraft, ...]
    normalized_source: str
    parser_version: str


class BoundedMermaidParser:
    """Parses the safe Mermaid subset emitted by Topic3 MindMapAgent."""

    def __init__(self, policy: MermaidPolicy | None = None) -> None:
        self.policy = policy or MermaidPolicy()

    def parse(self, source: str) -> ParsedMermaidGraph:
        if not isinstance(source, str):
            raise MermaidSyntaxError("Mermaid source must be a string")
        normalized = unicodedata.normalize("NFKC", source).strip()
        if not normalized:
            raise MermaidSyntaxError("Mermaid source cannot be blank")
        if len(normalized) > self.policy.max_chars:
            raise MermaidSecurityError("Mermaid source exceeds the character limit")
        lowered = normalized.casefold()
        for token in _FORBIDDEN_TOKENS:
            if token in lowered:
                raise MermaidSecurityError(f"forbidden Mermaid directive: {token}")

        lines = self._prepare_lines(normalized)
        if len(lines) > self.policy.max_lines:
            raise MermaidSecurityError("Mermaid source exceeds the line limit")
        header_index, direction = self._find_header(lines)
        nodes: dict[str, MermaidNodeDraft] = {}
        declared: set[str] = set()
        edges: list[MermaidEdgeDraft] = []
        edge_keys: set[tuple[str, str, GraphRelation, bool]] = set()
        subgraph_depth = 0

        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip().rstrip(";").strip()
            if not line or line_number - 1 == header_index:
                continue
            if line.startswith("%%"):
                continue
            if line.casefold().startswith("subgraph "):
                subgraph_depth += 1
                if subgraph_depth > self.policy.max_subgraph_depth:
                    raise MermaidSecurityError("Mermaid subgraph nesting exceeds the limit")
                continue
            if line.casefold() == "end":
                if subgraph_depth == 0:
                    raise MermaidSyntaxError(f"unexpected subgraph end on line {line_number}")
                subgraph_depth -= 1
                continue
            if line.casefold().startswith("direction "):
                if not re.fullmatch(r"direction\s+(TB|TD|BT|RL|LR)", line, re.IGNORECASE):
                    raise MermaidSyntaxError(f"invalid direction on line {line_number}")
                continue
            lowered_line = line.casefold()
            if (
                lowered_line.startswith("acctitle ")
                or lowered_line.startswith("acctitle:")
                or lowered_line.startswith("accdescr ")
                or lowered_line.startswith("accdescr:")
            ):
                self._validate_plain_text(line, line_number)
                continue
            if _CLASS_DEF.fullmatch(line):
                self._validate_style(_CLASS_DEF.fullmatch(line).group("style"), line_number)
                continue
            if _CLASS.fullmatch(line):
                match = _CLASS.fullmatch(line)
                self._validate_identifiers(match.group("nodes").split(","), line_number)
                continue
            if _STYLE.fullmatch(line):
                match = _STYLE.fullmatch(line)
                self._validate_identifier(match.group("node"), line_number)
                self._validate_style(match.group("style"), line_number)
                continue
            if _LINK_STYLE.fullmatch(line):
                match = _LINK_STYLE.fullmatch(line)
                self._validate_style(match.group("style"), line_number)
                continue
            if (
                lowered_line.startswith("classdef ")
                or lowered_line.startswith("style ")
                or lowered_line.startswith("linkstyle ")
            ):
                raise MermaidSecurityError(f"unsafe Mermaid style directive on line {line_number}")

            edge_match = _EDGE.fullmatch(line)
            if edge_match:
                source_id = edge_match.group("source")
                target_id = edge_match.group("target")
                if source_id == target_id:
                    raise MermaidSyntaxError(f"graph self edge on line {line_number}")
                operator = edge_match.group("operator")
                relation = self._relation(operator, edge_match.group("label"))
                directed = operator != "---"
                key = (source_id, target_id, relation, directed)
                if key in edge_keys:
                    raise MermaidSyntaxError(f"duplicate graph edge on line {line_number}")
                edge_keys.add(key)
                edges.append(
                    MermaidEdgeDraft(
                        source_node_id=source_id,
                        target_node_id=target_id,
                        relation=relation,
                        directed=directed,
                        operator=operator,
                        ordinal=len(edges),
                    )
                )
                if len(edges) > self.policy.max_edges:
                    raise MermaidSecurityError("Mermaid edge count exceeds the limit")
                self._ensure_implicit_node(nodes, source_id)
                self._ensure_implicit_node(nodes, target_id)
                continue

            node_match = _NODE.fullmatch(line)
            if node_match:
                node_id = node_match.group("node")
                if node_id in declared:
                    raise MermaidSyntaxError(f"duplicate node declaration on line {line_number}")
                label, node_type = self._node_label(node_match.group("shape"), node_id, line_number)
                existing = nodes.get(node_id)
                if existing is not None and existing.explicit:
                    raise MermaidSyntaxError(f"duplicate node declaration on line {line_number}")
                nodes[node_id] = MermaidNodeDraft(node_id, label, node_type, True)
                declared.add(node_id)
                if len(nodes) > self.policy.max_nodes:
                    raise MermaidSecurityError("Mermaid node count exceeds the limit")
                continue

            raise MermaidSyntaxError(f"unsupported Mermaid syntax on line {line_number}")

        if subgraph_depth:
            raise MermaidSyntaxError("Mermaid subgraph is not closed")
        if not nodes:
            raise MermaidSyntaxError("Mermaid graph contains no nodes")
        if len(nodes) > self.policy.max_nodes:
            raise MermaidSecurityError("Mermaid node count exceeds the limit")
        return ParsedMermaidGraph(
            direction=direction,
            nodes=tuple(nodes.values()),
            edges=tuple(edges),
            normalized_source="\n".join(lines),
            parser_version=MERMAID_PARSER_VERSION,
        )

    @staticmethod
    def _prepare_lines(source: str) -> list[str]:
        lines = [unicodedata.normalize("NFKC", line).strip() for line in source.splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        if lines and lines[0].casefold() in {"```mermaid", "```"}:
            lines.pop(0)
            if lines and lines[-1] == "```":
                lines.pop()
        if any("```" in line for line in lines):
            raise MermaidSyntaxError("unclosed or nested Mermaid code fence")
        return lines

    @staticmethod
    def _find_header(lines: list[str]) -> tuple[int, str]:
        for index, line in enumerate(lines):
            match = _HEADER.fullmatch(line)
            if match:
                return index, match.group(1).upper()
            if line:
                raise MermaidSyntaxError("Mermaid graph must start with graph/flowchart header")
        raise MermaidSyntaxError("Mermaid graph header is missing")

    @staticmethod
    def _validate_identifier(value: str, line_number: int) -> None:
        if re.fullmatch(_IDENTIFIER, value) is None:
            raise MermaidSyntaxError(f"invalid Mermaid identifier on line {line_number}")

    @classmethod
    def _validate_identifiers(cls, values: list[str], line_number: int) -> None:
        for value in values:
            cls._validate_identifier(value, line_number)

    @staticmethod
    def _validate_style(value: str, line_number: int) -> None:
        lowered = value.casefold()
        if (
            len(value) > 1024
            or _SAFE_STYLE.fullmatch(value.strip()) is None
            or any(token in lowered for token in ("url(", "javascript:", "expression("))
        ):
            raise MermaidSecurityError(f"unsafe Mermaid style on line {line_number}")

    @staticmethod
    def _validate_plain_text(value: str, line_number: int) -> None:
        if len(value) > 4096 or any(ord(char) < 32 and char not in "\t" for char in value):
            raise MermaidSyntaxError(f"invalid Mermaid accessibility text on line {line_number}")

    @staticmethod
    def _ensure_implicit_node(nodes: dict[str, MermaidNodeDraft], node_id: str) -> None:
        if node_id not in nodes:
            nodes[node_id] = MermaidNodeDraft(node_id, node_id, "IMPLICIT", False)

    def _node_label(self, shape: str | None, node_id: str, line_number: int) -> tuple[str, str]:
        if shape is None:
            return node_id, "IMPLICIT"
        pairs = (
            ("[[", "]]", "SUBROUTINE"),
            ("((", "))", "CIRCLE"),
            ("{{", "}}", "HEXAGON"),
            ("[", "]", "RECTANGLE"),
            ("(", ")", "ROUND"),
            ("{", "}", "DIAMOND"),
        )
        for opening, closing, node_type in pairs:
            if shape.startswith(opening) and shape.endswith(closing):
                value = shape[len(opening) : -len(closing)].strip()
                if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                    value = value[1:-1].replace(r"\"", '"').replace(r"\\", "\\")
                if not value:
                    raise MermaidSyntaxError(f"empty node label on line {line_number}")
                if len(value) > self.policy.max_label_chars or "<" in value or ">" in value:
                    raise MermaidSecurityError(f"unsafe Mermaid node label on line {line_number}")
                return value, node_type
        raise MermaidSyntaxError(f"unsupported Mermaid node shape on line {line_number}")

    @staticmethod
    def _relation(operator: str, label: str | None) -> GraphRelation:
        if label is not None and label.strip():
            normalized = re.sub(r"[^A-Za-z0-9]+", "_", label.strip()).strip("_").upper()
            try:
                return GraphRelation(normalized)
            except ValueError as exc:
                raise MermaidSyntaxError(f"unknown graph relation label: {label}") from exc
        if operator == "---":
            return GraphRelation.CONTRASTS
        if operator == "==>":
            return GraphRelation.DERIVES
        return GraphRelation.PREREQUISITE
