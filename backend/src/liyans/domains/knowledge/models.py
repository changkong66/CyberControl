from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from liyans.infrastructure.database.models import Base
from liyans.infrastructure.database.topic4 import (
    Topic4ImmutableRecordMixin,
    topic4_record_constraints,
)

TOPIC4_KNOWLEDGE_TABLES = (
    "topic4_source_documents",
    "topic4_source_document_versions",
    "topic4_embedding_profiles",
    "topic4_knowledge_base_versions",
    "topic4_knowledge_chunks",
    "topic4_formula_signatures",
    "topic4_index_build_manifests",
    "topic4_knowledge_base_activations",
    "topic4_query_plans",
    "topic4_retrieval_runs",
    "topic4_evidence_refs",
    "topic4_evidence_bundles",
)


class Topic4SourceDocumentModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_source_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_document_id"),
        UniqueConstraint("tenant_id", "course_id", "canonical_citation_sha256"),
        CheckConstraint(
            "authority_tier IN ('PRIMARY_STANDARD', 'AUTHORITATIVE_TEXTBOOK', "
            "'PEER_REVIEWED', 'OFFICIAL_DOCUMENTATION', 'CURATED_INTERNAL')",
            name="authority_tier",
        ),
        CheckConstraint(
            "lifecycle IN ('DRAFT', 'APPROVED', 'ACTIVE', 'SUPERSEDED', 'REVOKED')",
            name="lifecycle",
        ),
        CheckConstraint(
            "canonical_citation_sha256 ~ '^[0-9a-f]{64}$'",
            name="citation_sha256_format",
        ),
        CheckConstraint("jsonb_typeof(document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_source_documents_course_authority",
            "tenant_id",
            "course_id",
            "authority_tier",
        ),
    )

    source_document_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_document_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(2048), nullable=False)
    publisher: Mapped[str] = mapped_column(String(512), nullable=False)
    authority_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(24), nullable=False)
    license_expression: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_citation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4SourceDocumentVersionModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_source_document_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_document_version_id"),
        UniqueConstraint("tenant_id", "source_document_id", "version"),
        ForeignKeyConstraint(
            ["tenant_id", "source_document_id"],
            ["topic4_source_documents.tenant_id", "topic4_source_documents.source_document_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint(
            "lifecycle IN ('DRAFT', 'APPROVED', 'ACTIVE', 'SUPERSEDED', 'REVOKED')",
            name="lifecycle",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="effective_window",
        ),
        CheckConstraint("jsonb_typeof(version_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_source_versions_document_effective",
            "tenant_id",
            "source_document_id",
            "effective_from",
        ),
    )

    source_document_version_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    source_document_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(128), nullable=False)
    published_on: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifecycle: Mapped[str] = mapped_column(String(24), nullable=False)
    version_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4EmbeddingProfileModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_embedding_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "embedding_profile_id"),
        UniqueConstraint("tenant_id", "algorithm", "tokenizer_version", "hash_seed_version"),
        CheckConstraint("algorithm = 'HASHED_LEXICAL_2048'", name="local_algorithm"),
        CheckConstraint("dimension = 2048", name="fixed_dimension"),
        CheckConstraint("network_access = false", name="network_disabled"),
        CheckConstraint("signed_hashing", name="signed_hashing_required"),
        CheckConstraint("jsonb_typeof(profile_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    embedding_profile_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    embedding_profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    tokenizer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    hash_seed_version: Mapped[str] = mapped_column(String(128), nullable=False)
    signed_hashing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    network_access: Mapped[bool] = mapped_column(Boolean, nullable=False)
    profile_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4KnowledgeBaseVersionModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_knowledge_base_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "knowledge_base_version_id"),
        UniqueConstraint("tenant_id", "course_id", "version"),
        ForeignKeyConstraint(
            ["tenant_id", "graph_snapshot_id"],
            ["topic1_graph_snapshots.tenant_id", "topic1_graph_snapshots.snapshot_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "embedding_profile_id"],
            [
                "topic4_embedding_profiles.tenant_id",
                "topic4_embedding_profiles.embedding_profile_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("graph_snapshot_version >= 1", name="positive_graph_version"),
        CheckConstraint(
            "lifecycle IN ('DRAFT', 'APPROVED', 'ACTIVE', 'SUPERSEDED', 'REVOKED')",
            name="lifecycle",
        ),
        CheckConstraint(
            "jsonb_typeof(source_document_version_ids) = 'array'", name="source_versions_array"
        ),
        CheckConstraint("jsonb_typeof(version_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_kb_versions_course_created",
            "tenant_id",
            "course_id",
            "created_at",
        ),
    )

    knowledge_base_version_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    knowledge_base_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(24), nullable=False)
    source_document_version_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    graph_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    graph_snapshot_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embedding_profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    version_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4KnowledgeChunkModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "knowledge_chunk_id"),
        UniqueConstraint("tenant_id", "knowledge_base_version_id", "vector_ordinal"),
        UniqueConstraint(
            "tenant_id",
            "knowledge_base_version_id",
            "source_document_version_id",
            "section_id",
            "chunk_ordinal",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_version_id"],
            [
                "topic4_knowledge_base_versions.tenant_id",
                "topic4_knowledge_base_versions.knowledge_base_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_document_version_id"],
            [
                "topic4_source_document_versions.tenant_id",
                "topic4_source_document_versions.source_document_version_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("chunk_ordinal >= 0", name="nonnegative_chunk_ordinal"),
        CheckConstraint("vector_ordinal >= 0", name="nonnegative_vector_ordinal"),
        CheckConstraint("token_count BETWEEN 1 AND 16384", name="token_count_range"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint("octet_length(normalized_text) <= 131072", name="text_size"),
        CheckConstraint(
            "jsonb_typeof(topic1_knowledge_point_ids) = 'array'", name="knowledge_points_array"
        ),
        CheckConstraint(
            "jsonb_typeof(formula_signature_ids) = 'array'", name="formula_signatures_array"
        ),
        CheckConstraint("jsonb_typeof(chunk_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_chunks_kb_source",
            "tenant_id",
            "knowledge_base_version_id",
            "source_document_version_id",
        ),
        Index(
            "ix_topic4_chunks_kb_vector",
            "tenant_id",
            "knowledge_base_version_id",
            "vector_ordinal",
        ),
    )

    knowledge_chunk_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    knowledge_chunk_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    knowledge_base_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_document_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    section_id: Mapped[str] = mapped_column(String(256), nullable=False)
    chunk_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(131072), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic1_knowledge_point_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    formula_signature_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    chunk_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4FormulaSignatureModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_formula_signatures"
    __table_args__ = (
        UniqueConstraint("tenant_id", "formula_signature_id"),
        UniqueConstraint("tenant_id", "source_document_version_id", "signature_sha256"),
        ForeignKeyConstraint(
            ["tenant_id", "source_document_version_id"],
            [
                "topic4_source_document_versions.tenant_id",
                "topic4_source_document_versions.source_document_version_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("signature_sha256 ~ '^[0-9a-f]{64}$'", name="signature_sha256_format"),
        CheckConstraint("jsonb_typeof(signature_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_formula_signatures_source",
            "tenant_id",
            "source_document_version_id",
            "section_id",
        ),
    )

    formula_signature_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    formula_signature_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_document_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    section_id: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_expression: Mapped[str] = mapped_column(String(8192), nullable=False)
    signature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4IndexBuildManifestModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_index_build_manifests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "manifest_snapshot_id"),
        UniqueConstraint("tenant_id", "index_build_manifest_id", "manifest_version"),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_version_id"],
            [
                "topic4_knowledge_base_versions.tenant_id",
                "topic4_knowledge_base_versions.knowledge_base_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "embedding_profile_id"],
            [
                "topic4_embedding_profiles.tenant_id",
                "topic4_embedding_profiles.embedding_profile_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("manifest_version >= 1", name="positive_manifest_version"),
        CheckConstraint("version_cas = manifest_version", name="cas_matches_manifest_version"),
        CheckConstraint(
            "state IN ('BUILDING', 'READY', 'FAILED', 'CORRUPTED', 'RETIRED')", name="state"
        ),
        CheckConstraint("chunk_count >= 0", name="nonnegative_chunk_count"),
        CheckConstraint("shard_count >= 0", name="nonnegative_shard_count"),
        CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="manifest_sha256_format"),
        CheckConstraint("jsonb_typeof(manifest_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_index_manifests_kb_state",
            "tenant_id",
            "knowledge_base_version_id",
            "state",
            "manifest_version",
        ),
    )

    manifest_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    index_build_manifest_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    manifest_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    knowledge_base_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    embedding_profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    chunk_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shard_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Topic4KnowledgeBaseActivationModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_knowledge_base_activations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "activation_id"),
        UniqueConstraint("tenant_id", "course_id", "activation_version"),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_version_id"],
            [
                "topic4_knowledge_base_versions.tenant_id",
                "topic4_knowledge_base_versions.knowledge_base_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "replaces_activation_id"],
            [
                "topic4_knowledge_base_activations.tenant_id",
                "topic4_knowledge_base_activations.activation_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("activation_version >= 1", name="positive_activation_version"),
        CheckConstraint("version_cas = activation_version", name="cas_matches_activation_version"),
        CheckConstraint("jsonb_typeof(activation_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_kb_activations_course",
            "tenant_id",
            "course_id",
            "activation_version",
        ),
    )

    activation_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    activation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    activation_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    knowledge_base_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    replaces_activation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activation_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4QueryPlanModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_query_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "query_plan_id"),
        UniqueConstraint("tenant_id", "verification_id", "claim_id", "version_cas"),
        ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["topic4_claims.tenant_id", "topic4_claims.claim_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_version_id"],
            [
                "topic4_knowledge_base_versions.tenant_id",
                "topic4_knowledge_base_versions.knowledge_base_version_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("timeout_ms BETWEEN 10 AND 10000", name="timeout_range"),
        CheckConstraint("plan_sha256 ~ '^[0-9a-f]{64}$'", name="plan_sha256_format"),
        CheckConstraint("jsonb_typeof(plan_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_query_plans_claim", "tenant_id", "claim_id", "version_cas"),
    )

    query_plan_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    query_plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    knowledge_base_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4RetrievalRunModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_retrieval_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "retrieval_run_snapshot_id"),
        UniqueConstraint("tenant_id", "retrieval_request_id", "run_version"),
        ForeignKeyConstraint(
            ["tenant_id", "query_plan_id"],
            ["topic4_query_plans.tenant_id", "topic4_query_plans.query_plan_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("run_version >= 1", name="positive_run_version"),
        CheckConstraint("version_cas = run_version", name="cas_matches_run_version"),
        CheckConstraint("status IN ('SUCCEEDED', 'DEGRADED', 'FAILED')", name="status"),
        CheckConstraint("elapsed_ms >= 0", name="nonnegative_elapsed_ms"),
        CheckConstraint("jsonb_typeof(run_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_retrieval_runs_claim",
            "tenant_id",
            "claim_id",
            "run_version",
        ),
    )

    retrieval_run_snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    retrieval_request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    query_plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    index_build_manifest_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    run_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Topic4EvidenceRefModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_evidence_refs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "evidence_ref_id"),
        UniqueConstraint("tenant_id", "claim_id", "knowledge_chunk_id", "excerpt_sha256"),
        ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["topic4_claims.tenant_id", "topic4_claims.claim_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_chunk_id"],
            ["topic4_knowledge_chunks.tenant_id", "topic4_knowledge_chunks.knowledge_chunk_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("excerpt_sha256 ~ '^[0-9a-f]{64}$'", name="excerpt_sha256_format"),
        CheckConstraint("fused_score >= 0", name="nonnegative_fused_score"),
        CheckConstraint("jsonb_typeof(evidence_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_evidence_claim_score",
            "tenant_id",
            "claim_id",
            "fused_score",
        ),
    )

    evidence_ref_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    evidence_ref_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    knowledge_base_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    knowledge_chunk_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_document_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    excerpt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fused_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4EvidenceBundleModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_evidence_bundles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "evidence_bundle_id"),
        UniqueConstraint("tenant_id", "verification_id", "claim_id", "version_cas"),
        ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["topic4_claims.tenant_id", "topic4_claims.claim_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "query_plan_id"],
            ["topic4_query_plans.tenant_id", "topic4_query_plans.query_plan_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("coverage_score BETWEEN 0 AND 1", name="coverage_range"),
        CheckConstraint("total_ms >= 0", name="nonnegative_total_ms"),
        CheckConstraint("jsonb_typeof(evidence_ref_ids) = 'array'", name="evidence_refs_array"),
        CheckConstraint("jsonb_typeof(bundle_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_evidence_bundles_claim",
            "tenant_id",
            "claim_id",
            "version_cas",
        ),
    )

    evidence_bundle_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    evidence_bundle_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    query_plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    knowledge_base_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    evidence_ref_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    coverage_score: Mapped[float] = mapped_column(Float, nullable=False)
    conflicting_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False)
    total_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    bundle_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
