from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .common import Sha256Hex, VersionString
from .topic4_common import FindingSeverity, Topic4RecordV1


class SecurityFindingCategory(StrEnum):
    PROMPT_INJECTION = "PROMPT_INJECTION"
    EXPOSED_CREDENTIAL = "EXPOSED_CREDENTIAL"
    MALWARE = "MALWARE"
    UNSAFE_CODE = "UNSAFE_CODE"
    CONTENT_POLICY = "CONTENT_POLICY"
    CROSS_TENANT_REFERENCE = "CROSS_TENANT_REFERENCE"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"


class SecurityDisposition(StrEnum):
    ALLOW = "ALLOW"
    REDACT = "REDACT"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class SecurityFindingV1(Topic4RecordV1):
    schema_version: Literal["security-finding.v1"]
    security_finding_id: UUID
    verification_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    block_id: str | None = Field(default=None, min_length=1, max_length=128)
    category: SecurityFindingCategory
    severity: FindingSeverity
    disposition: SecurityDisposition
    detector: str = Field(min_length=1, max_length=128)
    detector_version: VersionString
    evidence_fingerprint_sha256: Sha256Hex
    reason_code: str = Field(min_length=1, max_length=128)
    non_waivable: bool

    @model_validator(mode="after")
    def validate_non_waivable(self) -> SecurityFindingV1:
        mandatory = {
            SecurityFindingCategory.CROSS_TENANT_REFERENCE,
            SecurityFindingCategory.DATA_EXFILTRATION,
            SecurityFindingCategory.MALWARE,
        }
        if self.category in mandatory and (
            not self.non_waivable or self.disposition != SecurityDisposition.BLOCK
        ):
            raise ValueError("critical security categories must be non-waivable blocks")
        return self
