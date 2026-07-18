from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .artifacts import ArtifactObjectRefV1
from .common import FROZEN_MODEL_CONFIG, Sha256Hex, VersionString
from .topic4_c2 import EvidenceRefV1
from .topic4_c6 import CodeArtifactV1
from .topic4_common import FindingSeverity, Topic4RecordV1


class VulnerabilityStatus(StrEnum):
    OPEN = "OPEN"
    NOT_AFFECTED = "NOT_AFFECTED"
    MITIGATED = "MITIGATED"
    FIXED = "FIXED"
    ACCEPTED_RISK = "ACCEPTED_RISK"


class SBOMComponentV1(Topic4RecordV1):
    schema_version: Literal["sbom-component.v1"]
    component_id: UUID
    name: str = Field(min_length=1, max_length=512)
    version: str = Field(min_length=1, max_length=256)
    package_url: str | None = Field(default=None, max_length=2048)
    licenses: list[str] = Field(default_factory=list, max_length=64)
    component_sha256: Sha256Hex | None = None


class SBOMManifestV1(Topic4RecordV1):
    schema_version: Literal["sbom-manifest.v1"]
    sbom_manifest_id: UUID
    code_artifact_id: UUID
    format: Literal["CYCLONEDX_JSON"]
    spec_version: VersionString
    serial_number: str = Field(min_length=1, max_length=256)
    components: list[SBOMComponentV1] = Field(default_factory=list, max_length=65_536)
    sbom_artifact: ArtifactObjectRefV1
    sbom_sha256: Sha256Hex


class VulnerabilityRecordV1(Topic4RecordV1):
    schema_version: Literal["vulnerability-record.v1"]
    vulnerability_record_id: UUID
    sbom_manifest_id: UUID
    component_id: UUID
    advisory_id: str = Field(min_length=1, max_length=256)
    severity: FindingSeverity
    cvss_score: float | None = Field(default=None, ge=0.0, le=10.0)
    affected_range: str | None = Field(default=None, max_length=512)
    fixed_version: str | None = Field(default=None, max_length=256)
    status: VulnerabilityStatus
    non_waivable: bool


class BuildProvenanceV1(Topic4RecordV1):
    schema_version: Literal["build-provenance.v1"]
    build_provenance_id: UUID
    code_artifact_id: UUID
    builder_id: str = Field(min_length=1, max_length=256)
    builder_version: VersionString
    toolchain_manifest_version: VersionString
    source_sha256: Sha256Hex
    build_output_artifact: ArtifactObjectRefV1
    build_output_sha256: Sha256Hex
    sbom_manifest_id: UUID
    sandbox_policy_id: UUID
    reproducible: bool
    build_command_sha256: Sha256Hex


class ComplianceVulnerabilityInputV1(BaseModel):
    """Untrusted scanner observation normalized by the C11 import service."""

    model_config = FROZEN_MODEL_CONFIG

    component_bom_ref: str = Field(min_length=1, max_length=512)
    advisory_id: str = Field(min_length=1, max_length=256)
    severity: FindingSeverity
    cvss_score: float | None = Field(default=None, ge=0.0, le=10.0)
    affected_range: str | None = Field(default=None, max_length=512)
    fixed_version: str | None = Field(default=None, max_length=256)
    status: VulnerabilityStatus
    non_waivable: bool = False


class ComplianceBuildProvenanceInputV1(BaseModel):
    """Untrusted provenance accepted only from an allowlisted local builder."""

    model_config = FROZEN_MODEL_CONFIG

    builder_id: str = Field(min_length=1, max_length=256)
    builder_version: VersionString
    toolchain_manifest_version: VersionString
    source_sha256: Sha256Hex
    build_output_document: dict[str, Any]
    sandbox_policy_id: UUID
    reproducible: bool
    build_command_sha256: Sha256Hex


class ComplianceEvidenceImportCommandV1(Topic4RecordV1):
    schema_version: Literal["compliance-evidence-import.command.v1"]
    import_command_id: UUID
    verification_id: UUID
    claim_id: UUID
    sbom_document: dict[str, Any]
    vulnerability_records: list[ComplianceVulnerabilityInputV1] = Field(
        default_factory=list,
        max_length=65_536,
    )
    provenance_document: ComplianceBuildProvenanceInputV1
    idempotency_key_sha256: Sha256Hex


class ComplianceEvidencePackageV1(Topic4RecordV1):
    schema_version: Literal["compliance-evidence.package.v1"]
    compliance_evidence_package_id: UUID
    import_command_id: UUID
    verification_id: UUID
    claim_id: UUID
    code_artifact: CodeArtifactV1
    sbom_manifest: SBOMManifestV1
    vulnerabilities: list[VulnerabilityRecordV1] = Field(default_factory=list, max_length=65_536)
    provenance: BuildProvenanceV1
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list, max_length=512)
    policy_version: VersionString
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_package_expiry(self) -> ComplianceEvidencePackageV1:
        if self.expires_at <= self.created_at:
            raise ValueError("compliance evidence package expiry must follow creation")
        if (
            self.code_artifact.verification_id != self.verification_id
            or self.code_artifact.claim_id != self.claim_id
            or self.sbom_manifest.code_artifact_id != self.code_artifact.code_artifact_id
            or self.provenance.code_artifact_id != self.code_artifact.code_artifact_id
            or self.provenance.sbom_manifest_id != self.sbom_manifest.sbom_manifest_id
        ):
            raise ValueError("compliance evidence package records are not consistently bound")
        return self
