from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .artifacts import ArtifactObjectRefV1
from .common import Sha256Hex, VersionString
from .topic4_common import Topic4RecordV1


class SourceAuthorityTier(StrEnum):
    PRIMARY_STANDARD = "PRIMARY_STANDARD"
    AUTHORITATIVE_TEXTBOOK = "AUTHORITATIVE_TEXTBOOK"
    PEER_REVIEWED = "PEER_REVIEWED"
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    CURATED_INTERNAL = "CURATED_INTERNAL"


class SourceLifecycle(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class IndexBuildState(StrEnum):
    BUILDING = "BUILDING"
    READY = "READY"
    FAILED = "FAILED"
    CORRUPTED = "CORRUPTED"
    RETIRED = "RETIRED"


class RetrievalStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class DocumentSectionIRV1(Topic4RecordV1):
    schema_version: Literal["document-section-ir.v1"]
    section_id: str = Field(min_length=1, max_length=256)
    parent_section_id: str | None = Field(default=None, min_length=1, max_length=256)
    ordinal: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=1024)
    json_pointer: str = Field(min_length=1, max_length=1024)
    text_artifact: ArtifactObjectRefV1
    text_sha256: Sha256Hex
    formula_signature_ids: list[UUID] = Field(default_factory=list, max_length=4096)
    topic1_knowledge_point_ids: list[str] = Field(default_factory=list, max_length=4096)


class IndexShardManifestV1(Topic4RecordV1):
    schema_version: Literal["index-shard-manifest.v1"]
    shard_id: UUID
    ordinal: int = Field(ge=0)
    first_vector_ordinal: int = Field(ge=0)
    vector_count: int = Field(ge=1)
    faiss_artifact: ArtifactObjectRefV1
    faiss_sha256: Sha256Hex
    bm25_artifact: ArtifactObjectRefV1
    bm25_sha256: Sha256Hex


class RetrievalTimingV1(Topic4RecordV1):
    schema_version: Literal["retrieval-timing.v1"]
    bm25_ms: int = Field(ge=0)
    vector_ms: int = Field(ge=0)
    graph_ms: int = Field(ge=0)
    formula_ms: int = Field(ge=0)
    fusion_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)


class SourceDocumentV1(Topic4RecordV1):
    schema_version: Literal["source.document.v1"]
    source_document_id: UUID
    title: str = Field(min_length=1, max_length=2048)
    authors: list[str] = Field(default_factory=list, max_length=128)
    publisher: str = Field(min_length=1, max_length=512)
    authority_tier: SourceAuthorityTier
    source_type: str = Field(min_length=1, max_length=128)
    canonical_citation: str = Field(min_length=1, max_length=4096)
    license_expression: str = Field(min_length=1, max_length=256)
    course_id: str = Field(min_length=1, max_length=128)
    locale: Literal["zh-CN"]
    lifecycle: SourceLifecycle


class SourceDocumentVersionV1(Topic4RecordV1):
    schema_version: Literal["source.document.version.v1"]
    source_document_version_id: UUID
    source_document_id: UUID
    version: VersionString
    content_artifact: ArtifactObjectRefV1
    content_sha256: Sha256Hex
    parser_version: VersionString
    published_on: date | None = None
    effective_from: AwareDatetime
    effective_until: AwareDatetime | None = None
    lifecycle: SourceLifecycle

    @model_validator(mode="after")
    def validate_effective_window(self) -> SourceDocumentVersionV1:
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        return self


class DocumentIRV1(Topic4RecordV1):
    schema_version: Literal["document-ir.v1"]
    document_ir_id: UUID
    source_document_version_id: UUID
    parser_version: VersionString
    sections: list[DocumentSectionIRV1] = Field(min_length=1, max_length=65_536)
    document_ir_artifact: ArtifactObjectRefV1
    document_ir_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_sections(self) -> DocumentIRV1:
        section_ids = [section.section_id for section in self.sections]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("document section ids must be unique")
        known = set(section_ids)
        if any(
            section.parent_section_id is not None and section.parent_section_id not in known
            for section in self.sections
        ):
            raise ValueError("document section parent is unknown")
        return self


class KnowledgeChunkV1(Topic4RecordV1):
    schema_version: Literal["knowledge-chunk.v1"]
    knowledge_chunk_id: UUID
    knowledge_base_version_id: UUID
    source_document_version_id: UUID
    document_ir_id: UUID
    section_id: str = Field(min_length=1, max_length=256)
    chunk_ordinal: int = Field(ge=0)
    normalized_text: str = Field(min_length=1, max_length=32_768)
    content_sha256: Sha256Hex
    token_count: int = Field(ge=1, le=16_384)
    topic1_knowledge_point_ids: list[str] = Field(default_factory=list, max_length=4096)
    formula_signature_ids: list[UUID] = Field(default_factory=list, max_length=4096)
    lexical_terms: list[str] = Field(default_factory=list, max_length=8192)
    embedding_profile_id: UUID
    vector_ordinal: int = Field(ge=0)


class FormulaSignatureV1(Topic4RecordV1):
    schema_version: Literal["formula-signature.v1"]
    formula_signature_id: UUID
    source_document_version_id: UUID
    section_id: str = Field(min_length=1, max_length=256)
    canonical_expression: str = Field(min_length=1, max_length=8192)
    symbol_arity: int = Field(ge=0, le=1024)
    operator_multiset: dict[str, int] = Field(default_factory=dict)
    dimensional_signature: str | None = Field(default=None, max_length=2048)
    signature_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_operators(self) -> FormulaSignatureV1:
        if any(count < 1 for count in self.operator_multiset.values()):
            raise ValueError("operator counts must be positive")
        return self


class EmbeddingProfileV1(Topic4RecordV1):
    schema_version: Literal["embedding-profile.v1"]
    embedding_profile_id: UUID
    algorithm: Literal["HASHED_LEXICAL_2048"]
    dimension: Literal[2048]
    tokenizer_version: VersionString
    hash_seed_version: VersionString
    normalization: Literal["L2"]
    signed_hashing: Literal[True]
    network_access: Literal[False]


class IndexBuildManifestV1(Topic4RecordV1):
    schema_version: Literal["index-build-manifest.v1"]
    index_build_manifest_id: UUID
    knowledge_base_version_id: UUID
    embedding_profile_id: UUID
    state: IndexBuildState
    chunk_count: int = Field(ge=0)
    shard_count: int = Field(ge=0)
    shards: list[IndexShardManifestV1] = Field(default_factory=list, max_length=4096)
    graph_snapshot_id: UUID
    graph_snapshot_version: int = Field(ge=1)
    toolchain_manifest_version: VersionString
    built_at: AwareDatetime | None = None
    failure_code: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_manifest(self) -> IndexBuildManifestV1:
        if self.shard_count != len(self.shards):
            raise ValueError("shard_count must match shards")
        if self.state == IndexBuildState.READY and (not self.shards or self.built_at is None):
            raise ValueError("ready index requires shards and built_at")
        return self


class KnowledgeBaseVersionV1(Topic4RecordV1):
    schema_version: Literal["knowledge-base.version.v1"]
    knowledge_base_version_id: UUID
    version: VersionString
    lifecycle: SourceLifecycle
    source_document_version_ids: list[UUID] = Field(min_length=1, max_length=65_536)
    graph_snapshot_id: UUID
    graph_snapshot_version: int = Field(ge=1)
    index_build_manifest_id: UUID
    embedding_profile_id: UUID
    activated_at: AwareDatetime | None = None
    retired_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> KnowledgeBaseVersionV1:
        if self.lifecycle == SourceLifecycle.ACTIVE and self.activated_at is None:
            raise ValueError("active knowledge base requires activated_at")
        if self.retired_at is not None and self.activated_at is None:
            raise ValueError("retired knowledge base requires activated_at")
        if self.activated_at and self.retired_at and self.retired_at <= self.activated_at:
            raise ValueError("retired_at must be after activated_at")
        return self


class QueryPlanV1(Topic4RecordV1):
    schema_version: Literal["query-plan.v1"]
    query_plan_id: UUID
    verification_id: UUID
    claim_id: UUID
    knowledge_base_version_id: UUID
    lexical_queries: list[str] = Field(min_length=1, max_length=32)
    graph_seed_knowledge_point_ids: list[str] = Field(default_factory=list, max_length=256)
    formula_signature_ids: list[UUID] = Field(default_factory=list, max_length=256)
    top_k_bm25: int = Field(ge=1, le=200)
    top_k_vector: int = Field(ge=1, le=200)
    top_k_graph: int = Field(ge=0, le=200)
    top_k_formula: int = Field(ge=0, le=200)
    final_top_k: int = Field(ge=1, le=200)
    fusion_method: Literal["RRF_V1"]
    tenant_filter_required: Literal[True]
    timeout_ms: int = Field(ge=10, le=10_000)


class EvidenceRefV1(Topic4RecordV1):
    schema_version: Literal["evidence.ref.v1"]
    evidence_ref_id: UUID
    verification_id: UUID
    claim_id: UUID
    knowledge_base_version_id: UUID
    knowledge_chunk_id: UUID
    source_document_id: UUID
    source_document_version_id: UUID
    section_id: str = Field(min_length=1, max_length=256)
    citation: str = Field(min_length=1, max_length=4096)
    excerpt: str = Field(min_length=1, max_length=8192)
    excerpt_sha256: Sha256Hex
    bm25_score: float | None = Field(default=None, ge=0.0)
    vector_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    graph_score: float | None = Field(default=None, ge=0.0)
    formula_score: float | None = Field(default=None, ge=0.0, le=1.0)
    fused_score: float = Field(ge=0.0)
    source_authority_tier: SourceAuthorityTier


class EvidenceBundleV1(Topic4RecordV1):
    schema_version: Literal["evidence.bundle.v1"]
    evidence_bundle_id: UUID
    verification_id: UUID
    claim_id: UUID
    query_plan_id: UUID
    knowledge_base_version_id: UUID
    evidence_ref_ids: list[UUID] = Field(default_factory=list, max_length=512)
    coverage_score: float = Field(ge=0.0, le=1.0)
    conflicting_evidence: bool
    retrieval_timing: RetrievalTimingV1
    retrieval_pipeline_version: VersionString
    degraded_reason_codes: list[str] = Field(default_factory=list, max_length=32)


class RetrievalRequestV1(Topic4RecordV1):
    schema_version: Literal["retrieval.request.v1"]
    retrieval_request_id: UUID
    verification_id: UUID
    claim_id: UUID
    query_plan: QueryPlanV1
    deadline_at: AwareDatetime

    @model_validator(mode="after")
    def validate_deadline(self) -> RetrievalRequestV1:
        if self.deadline_at <= self.created_at:
            raise ValueError("retrieval deadline must be after creation")
        return self


class RetrievalResponseV1(Topic4RecordV1):
    schema_version: Literal["retrieval.response.v1"]
    retrieval_response_id: UUID
    retrieval_request_id: UUID
    verification_id: UUID
    claim_id: UUID
    status: RetrievalStatus
    evidence_bundle: EvidenceBundleV1 | None = None
    index_build_manifest_id: UUID
    elapsed_ms: int = Field(ge=0)
    degraded_reason_codes: list[str] = Field(default_factory=list, max_length=32)
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_response(self) -> RetrievalResponseV1:
        if self.status != RetrievalStatus.FAILED and self.evidence_bundle is None:
            raise ValueError("successful or degraded retrieval requires an evidence bundle")
        if self.status == RetrievalStatus.DEGRADED and not self.degraded_reason_codes:
            raise ValueError("degraded retrieval requires reason codes")
        return self
