from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .artifacts import ArtifactObjectRefV1
from .common import Sha256Hex, VersionString
from .topic4_common import FindingSeverity, Topic4RecordV1, VerificationVerdict


class PIIType(StrEnum):
    NAME = "NAME"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    NATIONAL_ID = "NATIONAL_ID"
    STUDENT_ID = "STUDENT_ID"
    ADDRESS = "ADDRESS"
    BIOMETRIC = "BIOMETRIC"
    CREDENTIAL = "CREDENTIAL"
    OTHER = "OTHER"


class PrivacyAction(StrEnum):
    ALLOW = "ALLOW"
    TOKENIZE = "TOKENIZE"
    REDACT = "REDACT"
    BLOCK = "BLOCK"


class PIIFindingV1(Topic4RecordV1):
    schema_version: Literal["pii-finding.v1"]
    pii_finding_id: UUID
    verification_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    block_id: str = Field(min_length=1, max_length=128)
    json_pointer: str = Field(min_length=1, max_length=1024)
    pii_type: PIIType
    severity: FindingSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    action: PrivacyAction
    original_value_sha256: Sha256Hex
    non_waivable: bool

    @model_validator(mode="after")
    def validate_sensitive_pii(self) -> PIIFindingV1:
        critical = {PIIType.NATIONAL_ID, PIIType.BIOMETRIC, PIIType.CREDENTIAL}
        if self.pii_type in critical and self.action == PrivacyAction.ALLOW:
            raise ValueError("critical PII cannot be allowed unchanged")
        return self


class TokenizedValueV1(Topic4RecordV1):
    schema_version: Literal["tokenized-value.v1"]
    tokenized_value_id: UUID
    pii_finding_id: UUID
    token: str = Field(pattern=r"^tok_[A-Za-z0-9_-]{16,128}$")
    original_value_sha256: Sha256Hex
    vault_reference: str = Field(min_length=1, max_length=512)
    key_version: VersionString
    reversible: bool


class PrivacyTenantResultV1(Topic4RecordV1):
    schema_version: Literal["privacy-tenant.result.v1"]
    privacy_tenant_result_id: UUID
    verification_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    candidate_sha256: Sha256Hex
    tenant_boundary_valid: bool
    pii_finding_ids: list[UUID] = Field(default_factory=list, max_length=4096)
    tokenized_value_ids: list[UUID] = Field(default_factory=list, max_length=4096)
    redacted_candidate_artifact: ArtifactObjectRefV1 | None = None
    redacted_candidate_sha256: Sha256Hex | None = None
    policy_version: VersionString
    verdict: VerificationVerdict

    @model_validator(mode="after")
    def validate_boundary(self) -> PrivacyTenantResultV1:
        if not self.tenant_boundary_valid and self.verdict != VerificationVerdict.UNSAFE:
            raise ValueError("cross-tenant result must be unsafe")
        if (self.redacted_candidate_artifact is None) != (self.redacted_candidate_sha256 is None):
            raise ValueError("redacted candidate artifact and hash must be provided together")
        return self
