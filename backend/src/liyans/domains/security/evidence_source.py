from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.topic3 import CandidateV1
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import EvidenceRefV1


@dataclass(frozen=True, slots=True)
class SecurityEvidenceBundle:
    """Candidate snapshot and immutable local evidence used by C9."""

    candidate: CandidateV1 | None
    evidence: tuple[EvidenceRefV1, ...]
    knowledge_base_version_id: object | None = None


class SecurityEvidenceSource(Protocol):
    async def load(self, claim: ClaimV1) -> SecurityEvidenceBundle: ...


class SecurityCandidateLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> SecurityEvidenceBundle: ...


class SecurityArtifactReader(Protocol):
    async def read_candidate_artifact(self, claim: ClaimV1) -> ArtifactObjectRefV1: ...
