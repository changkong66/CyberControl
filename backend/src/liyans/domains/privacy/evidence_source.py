from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from liyans_contracts.topic3 import CandidateV1
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import EvidenceRefV1


@dataclass(frozen=True, slots=True)
class PrivacyEvidenceBundle:
    """Candidate snapshot, trusted source tenant, and local evidence."""

    candidate: CandidateV1 | None
    evidence: tuple[EvidenceRefV1, ...]
    source_tenant_id: str | None
    knowledge_base_version_id: object | None = None


class PrivacyEvidenceSource(Protocol):
    async def load(self, claim: ClaimV1) -> PrivacyEvidenceBundle: ...


class PrivacyEvidenceLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> PrivacyEvidenceBundle: ...
