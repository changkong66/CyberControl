from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKeyConstraint,
    Index,
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

TOPIC4_COMPLIANCE_TABLES = (
    "topic4_sbom_manifests",
    "topic4_sbom_components",
    "topic4_vulnerability_records",
    "topic4_build_provenance",
)


class Topic4SBOMManifestModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_sbom_manifests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sbom_manifest_id"),
        UniqueConstraint("tenant_id", "code_artifact_id", "sbom_sha256"),
        CheckConstraint("format = 'CYCLONEDX_JSON'", name="format"),
        CheckConstraint("sbom_sha256 ~ '^[0-9a-f]{64}$'", name="sbom_sha256_format"),
        CheckConstraint("jsonb_typeof(sbom_artifact) = 'object'", name="artifact_object"),
        CheckConstraint("jsonb_typeof(manifest_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index("ix_topic4_sbom_manifests_code", "tenant_id", "code_artifact_id", "created_at"),
    )

    sbom_manifest_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    sbom_manifest_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    code_artifact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    spec_version: Mapped[str] = mapped_column(String(128), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(256), nullable=False)
    sbom_artifact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sbom_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4SBOMComponentModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_sbom_components"
    __table_args__ = (
        UniqueConstraint("tenant_id", "component_id"),
        UniqueConstraint("tenant_id", "sbom_manifest_id", "name", "version", "package_url"),
        ForeignKeyConstraint(
            ["tenant_id", "sbom_manifest_id"],
            ["topic4_sbom_manifests.tenant_id", "topic4_sbom_manifests.sbom_manifest_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "component_sha256 IS NULL OR component_sha256 ~ '^[0-9a-f]{64}$'",
            name="component_sha256_format",
        ),
        CheckConstraint("jsonb_typeof(licenses) = 'array'", name="licenses_array"),
        CheckConstraint("jsonb_typeof(component_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    component_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    component_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sbom_manifest_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[str] = mapped_column(String(256), nullable=False)
    package_url: Mapped[str | None] = mapped_column(String(2048))
    licenses: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    component_sha256: Mapped[str | None] = mapped_column(String(64))
    component_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4VulnerabilityRecordModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_vulnerability_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "vulnerability_record_id"),
        UniqueConstraint("tenant_id", "sbom_manifest_id", "component_id", "advisory_id"),
        ForeignKeyConstraint(
            ["tenant_id", "sbom_manifest_id"],
            ["topic4_sbom_manifests.tenant_id", "topic4_sbom_manifests.sbom_manifest_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "component_id"],
            ["topic4_sbom_components.tenant_id", "topic4_sbom_components.component_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="severity",
        ),
        CheckConstraint("cvss_score IS NULL OR cvss_score BETWEEN 0 AND 10", name="cvss_range"),
        CheckConstraint(
            "status IN ('OPEN', 'NOT_AFFECTED', 'MITIGATED', 'FIXED', 'ACCEPTED_RISK')",
            name="status",
        ),
        CheckConstraint(
            "NOT (non_waivable AND status = 'ACCEPTED_RISK')",
            name="non_waivable_not_accepted",
        ),
        CheckConstraint("jsonb_typeof(vulnerability_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
        Index(
            "ix_topic4_vulnerabilities_open",
            "tenant_id",
            "severity",
            "status",
            "created_at",
        ),
    )

    vulnerability_record_snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    vulnerability_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sbom_manifest_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    component_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    advisory_id: Mapped[str] = mapped_column(String(256), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    cvss_score: Mapped[float | None] = mapped_column(Float)
    affected_range: Mapped[str | None] = mapped_column(String(512))
    fixed_version: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    non_waivable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    vulnerability_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Topic4BuildProvenanceModel(Topic4ImmutableRecordMixin, Base):
    __tablename__ = "topic4_build_provenance"
    __table_args__ = (
        UniqueConstraint("tenant_id", "build_provenance_id"),
        UniqueConstraint("tenant_id", "code_artifact_id", "build_output_sha256"),
        ForeignKeyConstraint(
            ["tenant_id", "sbom_manifest_id"],
            ["topic4_sbom_manifests.tenant_id", "topic4_sbom_manifests.sbom_manifest_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="source_sha256_format"),
        CheckConstraint(
            "build_output_sha256 ~ '^[0-9a-f]{64}$'", name="build_output_sha256_format"
        ),
        CheckConstraint(
            "build_command_sha256 ~ '^[0-9a-f]{64}$'", name="build_command_sha256_format"
        ),
        CheckConstraint("jsonb_typeof(build_output_artifact) = 'object'", name="artifact_object"),
        CheckConstraint("jsonb_typeof(provenance_document) = 'object'", name="document_object"),
        *topic4_record_constraints(),
    )

    build_provenance_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    build_provenance_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    code_artifact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    builder_id: Mapped[str] = mapped_column(String(256), nullable=False)
    builder_version: Mapped[str] = mapped_column(String(128), nullable=False)
    toolchain_manifest_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    build_output_artifact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    build_output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sbom_manifest_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sandbox_policy_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reproducible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    build_command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
