from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from .common import Sha256Hex
from .topic4_common import Topic4RecordV1, VerificationVerdict


class ExtensionResourceType(StrEnum):
    PAPER = "PAPER"
    STANDARD = "STANDARD"
    ENGINEERING_CASE = "ENGINEERING_CASE"
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    DATASET = "DATASET"


class VerifierExtensionResourceV1(Topic4RecordV1):
    schema_version: Literal["extension-resource.v1"]
    extension_resource_id: UUID
    verification_id: UUID
    claim_id: UUID
    resource_type: ExtensionResourceType
    title: str = Field(min_length=1, max_length=2048)
    authors: list[str] = Field(default_factory=list, max_length=128)
    publisher: str = Field(min_length=1, max_length=512)
    publication_date: date | None = None
    identifier: str | None = Field(default=None, max_length=512)
    canonical_uri: str | None = Field(default=None, max_length=2048)
    canonical_citation: str = Field(min_length=1, max_length=4096)
    citation_sha256: Sha256Hex
    license_expression: str = Field(min_length=1, max_length=256)
    topic1_knowledge_point_ids: list[str] = Field(min_length=1, max_length=256)
    source_evidence_ref_ids: list[UUID] = Field(min_length=1, max_length=128)


class ExtensionVerificationResultV1(Topic4RecordV1):
    schema_version: Literal["extension-verification.result.v1"]
    extension_verification_result_id: UUID
    verification_id: UUID
    claim_id: UUID
    extension_resource_id: UUID
    source_present_in_approved_corpus: bool
    citation_valid: bool
    license_compatible: bool
    knowledge_relevance: float = Field(ge=0.0, le=1.0)
    temporal_validity: bool | None
    finding_codes: list[str] = Field(default_factory=list, max_length=256)
    evidence_ref_ids: list[UUID] = Field(default_factory=list, max_length=512)
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
