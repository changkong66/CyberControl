from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .topic4_common import Topic4RecordV1, VerificationVerdict


class GraphRelation(StrEnum):
    PREREQUISITE = "PREREQUISITE"
    CONTAINS = "CONTAINS"
    DERIVES = "DERIVES"
    CONTRASTS = "CONTRASTS"
    APPLIES_TO = "APPLIES_TO"


class VerifierGraphNodeV1(Topic4RecordV1):
    schema_version: Literal["verifier-graph-node.v1"]
    node_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=512)
    topic1_knowledge_point_id: UUID | None = None
    node_type: str = Field(min_length=1, max_length=128)


class VerifierGraphEdgeV1(Topic4RecordV1):
    schema_version: Literal["verifier-graph-edge.v1"]
    edge_id: str = Field(min_length=1, max_length=128)
    source_node_id: str = Field(min_length=1, max_length=128)
    target_node_id: str = Field(min_length=1, max_length=128)
    relation: GraphRelation
    directed: bool


class VerifierGraphIRV1(Topic4RecordV1):
    schema_version: Literal["verifier.graph-ir.v1"]
    verifier_graph_ir_id: UUID
    verification_id: UUID
    claim_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    block_id: str = Field(min_length=1, max_length=128)
    mermaid_version: str = Field(min_length=1, max_length=64)
    direction: Literal["TB", "TD", "BT", "RL", "LR"]
    nodes: list[VerifierGraphNodeV1] = Field(min_length=1, max_length=4096)
    edges: list[VerifierGraphEdgeV1] = Field(default_factory=list, max_length=16_384)

    @model_validator(mode="after")
    def validate_graph(self) -> VerifierGraphIRV1:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("graph node ids must be unique")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("graph edge ids must be unique")
        known = set(node_ids)
        if any(
            edge.source_node_id not in known or edge.target_node_id not in known
            for edge in self.edges
        ):
            raise ValueError("graph edge references an unknown node")
        return self


class GraphVerificationResultV1(Topic4RecordV1):
    schema_version: Literal["graph-verification.result.v1"]
    graph_verification_result_id: UUID
    verification_id: UUID
    claim_id: UUID
    verifier_graph_ir_id: UUID
    syntax_valid: bool
    node_ids_unique: bool
    edge_endpoints_valid: bool
    prerequisite_subgraph_acyclic: bool
    unknown_topic1_node_ids: list[str] = Field(default_factory=list, max_length=4096)
    invalid_edge_ids: list[str] = Field(default_factory=list, max_length=16_384)
    topology_mismatch_codes: list[str] = Field(default_factory=list, max_length=4096)
    evidence_ref_ids: list[UUID] = Field(default_factory=list, max_length=512)
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
