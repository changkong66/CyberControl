from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1GraphSnapshotV1, Topic1KnowledgePointV1
from liyans_contracts.topic4_c4 import (
    GraphRelation,
    GraphVerificationResultV1,
    VerifierGraphEdgeV1,
    VerifierGraphIRV1,
    VerifierGraphNodeV1,
)
from liyans_contracts.topic4_common import VerificationVerdict

from liyans.domains.verification.records import build_topic4_record

from .mermaid import MermaidNodeDraft, ParsedMermaidGraph

GRAPH_VERIFIER_VERSION = "c4-graph-verifier-v1"
_SPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


class GraphIntegrityError(ValueError):
    """Raised when the immutable Topic1 graph snapshot is invalid."""


@dataclass(frozen=True, slots=True)
class GraphVerificationPolicy:
    require_explicit_nodes: bool = True
    reject_ambiguous_labels: bool = True
    require_declared_prerequisites: bool = True


@dataclass(frozen=True, slots=True)
class GraphAnalysis:
    graph_ir: VerifierGraphIRV1
    result: GraphVerificationResultV1
    unknown_node_ids: tuple[str, ...]


class Topic1GraphVerifier:
    """Checks Mermaid graph semantics against one immutable Topic1 snapshot."""

    def __init__(self, policy: GraphVerificationPolicy | None = None) -> None:
        self.policy = policy or GraphVerificationPolicy()

    def verify(
        self,
        parsed: ParsedMermaidGraph,
        snapshot: Topic1GraphSnapshotV1,
        *,
        verification_id: UUID,
        claim_id: UUID,
        candidate_id: UUID,
        candidate_version: int,
        block_id: str,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
        evidence_ref_ids: tuple[UUID, ...] = (),
    ) -> GraphAnalysis:
        self._validate_snapshot(snapshot)
        point_by_id = {point.kp_id: point for point in snapshot.content.knowledge_points}
        label_index = self._label_index(snapshot)
        mapped: dict[str, str | None] = {}
        ambiguous: set[str] = set()
        id_label_mismatches: set[str] = set()
        unknown: set[str] = set()
        for node in parsed.nodes:
            point = point_by_id.get(node.node_id)
            if point is not None and not self._label_matches_point(node, point):
                kp_id = None
                id_label_mismatches.add(node.node_id)
            else:
                kp_id = self._resolve_node(node, point_by_id, label_index)
            if kp_id is None:
                normalized_label = self._normalize_label(node.label)
                if normalized_label in label_index and len(label_index[normalized_label]) > 1:
                    ambiguous.add(node.node_id)
                else:
                    unknown.add(node.node_id)
            mapped[node.node_id] = kp_id

        graph_nodes = tuple(
            self._node_record(
                node,
                mapped[node.node_id],
                verification_id=verification_id,
                claim_id=claim_id,
                trace_id=trace_id,
                tenant_id=tenant_id,
                created_at=created_at,
            )
            for node in parsed.nodes
        )
        graph_edges = tuple(
            build_topic4_record(
                VerifierGraphEdgeV1,
                trace_id=trace_id,
                tenant_id=tenant_id,
                version_cas=1,
                created_at=created_at,
                immutable=True,
                schema_version="verifier-graph-edge.v1",
                edge_id=f"E{edge.ordinal}",
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                relation=edge.relation,
                directed=edge.directed,
            )
            for edge in parsed.edges
        )
        source_sha256 = canonical_sha256(parsed.normalized_source)
        graph_ir = build_topic4_record(
            VerifierGraphIRV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="verifier.graph-ir.v1",
            verifier_graph_ir_id=uuid5(
                claim_id,
                f"{GRAPH_VERIFIER_VERSION}:{source_sha256}",
            ),
            verification_id=verification_id,
            claim_id=claim_id,
            candidate_id=candidate_id,
            candidate_version=candidate_version,
            block_id=block_id,
            mermaid_version=parsed.parser_version,
            direction=parsed.direction,
            nodes=list(graph_nodes),
            edges=list(graph_edges),
        )

        invalid_edge_ids: set[str] = set()
        mismatch_codes: set[str] = set()
        authoritative_edges = {
            (edge.prerequisite_kp_id, edge.dependent_kp_id)
            for edge in snapshot.content.prerequisites
        }
        declared_prerequisites: set[tuple[str, str]] = set()
        adjacency: dict[str, set[str]] = {}
        for edge_record, edge_draft in zip(graph_edges, parsed.edges, strict=True):
            source_kp = mapped.get(edge_draft.source_node_id)
            target_kp = mapped.get(edge_draft.target_node_id)
            if source_kp is None or target_kp is None:
                invalid_edge_ids.add(edge_record.edge_id)
                mismatch_codes.add("EDGE_ENDPOINT_UNRESOLVED")
                continue
            if edge_draft.relation == GraphRelation.PREREQUISITE:
                declared_prerequisites.add((source_kp, target_kp))
                adjacency.setdefault(source_kp, set()).add(target_kp)
                if (source_kp, target_kp) not in authoritative_edges:
                    invalid_edge_ids.add(edge_record.edge_id)
                    mismatch_codes.add("PREREQUISITE_EDGE_NOT_IN_TOPIC1")
            else:
                invalid_edge_ids.add(edge_record.edge_id)
                mismatch_codes.add("RELATION_NOT_VERIFIABLE_FROM_TOPIC1")

        if self.policy.require_declared_prerequisites:
            graph_kp_ids = {kp_id for kp_id in mapped.values() if kp_id is not None}
            for source_kp, target_kp in authoritative_edges:
                if {source_kp, target_kp} <= graph_kp_ids and (
                    source_kp,
                    target_kp,
                ) not in declared_prerequisites:
                    mismatch_codes.add("TOPIC1_PREREQUISITE_OMITTED")

        acyclic = not self._has_cycle(adjacency)
        if not acyclic:
            mismatch_codes.add("PREREQUISITE_SUBGRAPH_CYCLE")
        if ambiguous:
            mismatch_codes.add("AMBIGUOUS_TOPIC1_LABEL")
            unknown.update(ambiguous)
        if id_label_mismatches:
            mismatch_codes.add("TOPIC1_NODE_ID_LABEL_MISMATCH")
            unknown.update(id_label_mismatches)
        if unknown and self.policy.require_explicit_nodes:
            mismatch_codes.add("UNKNOWN_TOPIC1_NODE")
        if not evidence_ref_ids:
            mismatch_codes.add("AUTHORITATIVE_EVIDENCE_MISSING")

        verdict = self._verdict(
            unknown=unknown,
            invalid_edge_ids=invalid_edge_ids,
            mismatch_codes=mismatch_codes,
        )
        confidence = {
            VerificationVerdict.SUPPORTED: 0.98,
            VerificationVerdict.CONTRADICTED: 0.96,
            VerificationVerdict.INSUFFICIENT_EVIDENCE: 0.30,
            VerificationVerdict.UNSAFE: 0.0,
        }[verdict]
        result = build_topic4_record(
            GraphVerificationResultV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="graph-verification.result.v1",
            graph_verification_result_id=uuid5(
                graph_ir.verifier_graph_ir_id,
                f"{GRAPH_VERIFIER_VERSION}:result",
            ),
            verification_id=verification_id,
            claim_id=claim_id,
            verifier_graph_ir_id=graph_ir.verifier_graph_ir_id,
            syntax_valid=True,
            node_ids_unique=True,
            edge_endpoints_valid=not invalid_edge_ids
            or not any(code == "EDGE_ENDPOINT_UNRESOLVED" for code in mismatch_codes),
            prerequisite_subgraph_acyclic=acyclic,
            unknown_topic1_node_ids=sorted(unknown),
            invalid_edge_ids=sorted(invalid_edge_ids),
            topology_mismatch_codes=sorted(mismatch_codes),
            evidence_ref_ids=list(evidence_ref_ids),
            verdict=verdict,
            confidence=confidence,
        )
        return GraphAnalysis(
            graph_ir=graph_ir, result=result, unknown_node_ids=tuple(sorted(unknown))
        )

    @staticmethod
    def _validate_snapshot(snapshot: Topic1GraphSnapshotV1) -> None:
        content = snapshot.content
        if canonical_sha256(content.model_dump(mode="json")) != snapshot.content_sha256:
            raise GraphIntegrityError("Topic1 graph snapshot content SHA256 is invalid")
        if snapshot.node_count != len(content.knowledge_points):
            raise GraphIntegrityError("Topic1 graph snapshot node count is invalid")
        if snapshot.edge_count != len(content.prerequisites):
            raise GraphIntegrityError("Topic1 graph snapshot edge count is invalid")

    @classmethod
    def _label_index(cls, snapshot: Topic1GraphSnapshotV1) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for point in snapshot.content.knowledge_points:
            for value in (point.kp_id, point.title, *point.aliases):
                normalized = cls._normalize_label(value)
                if normalized:
                    index.setdefault(normalized, set()).add(point.kp_id)
        return index

    @classmethod
    def _resolve_node(
        cls,
        node: MermaidNodeDraft,
        point_by_id: dict[str, Topic1KnowledgePointV1],
        label_index: dict[str, set[str]],
    ) -> str | None:
        if node.node_id in point_by_id:
            return node.node_id
        candidates = label_index.get(cls._normalize_label(node.label), set())
        return next(iter(candidates)) if len(candidates) == 1 else None

    @classmethod
    def _label_matches_point(
        cls,
        node: MermaidNodeDraft,
        point: Topic1KnowledgePointV1,
    ) -> bool:
        normalized_label = cls._normalize_label(node.label)
        accepted = {
            cls._normalize_label(value)
            for value in (point.kp_id, point.title, *point.aliases)
            if cls._normalize_label(value)
        }
        return normalized_label in accepted

    @staticmethod
    def _normalize_label(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        normalized = _PUNCTUATION.sub(" ", normalized)
        return _SPACE.sub(" ", normalized).strip()

    @staticmethod
    def _node_record(
        node: MermaidNodeDraft,
        kp_id: str | None,
        *,
        verification_id: UUID,
        claim_id: UUID,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> VerifierGraphNodeV1:
        return build_topic4_record(
            VerifierGraphNodeV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="verifier-graph-node.v1",
            node_id=node.node_id,
            label=node.label,
            topic1_knowledge_point_id=(
                None
                if kp_id is None
                else uuid5(NAMESPACE_URL, f"liyans:topic1:knowledge-point:{tenant_id}:{kp_id}")
            ),
            node_type="KNOWLEDGE_POINT" if kp_id is not None else node.node_type,
        )

    @staticmethod
    def _has_cycle(adjacency: dict[str, set[str]]) -> bool:
        state: dict[str, int] = {}

        def visit(node: str) -> bool:
            current = state.get(node, 0)
            if current == 1:
                return True
            if current == 2:
                return False
            state[node] = 1
            if any(visit(child) for child in sorted(adjacency.get(node, ()))):
                return True
            state[node] = 2
            return False

        return any(visit(node) for node in sorted(adjacency))

    @staticmethod
    def _verdict(
        *,
        unknown: set[str],
        invalid_edge_ids: set[str],
        mismatch_codes: set[str],
    ) -> VerificationVerdict:
        if {
            "PREREQUISITE_SUBGRAPH_CYCLE",
            "PREREQUISITE_EDGE_NOT_IN_TOPIC1",
            "TOPIC1_PREREQUISITE_OMITTED",
        } & mismatch_codes:
            return VerificationVerdict.CONTRADICTED
        if unknown or invalid_edge_ids or mismatch_codes:
            return VerificationVerdict.INSUFFICIENT_EVIDENCE
        return VerificationVerdict.SUPPORTED
