from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_c6 import CodeArtifactV1
from liyans_contracts.topic4_c11 import (
    BuildProvenanceV1,
    SBOMManifestV1,
    VulnerabilityRecordV1,
)


@dataclass(frozen=True, slots=True)
class ComplianceEvidenceBundle:
    """Local, tenant-bound supply-chain evidence for a code Claim."""

    source_tenant_id: str | None
    code_artifact: CodeArtifactV1 | None
    sbom_manifest: SBOMManifestV1 | None
    sbom_document: dict[str, Any] | None
    vulnerabilities: tuple[VulnerabilityRecordV1, ...] = field(default_factory=tuple)
    provenance: BuildProvenanceV1 | None = None
    evidence: tuple[EvidenceRefV1, ...] = field(default_factory=tuple)


class ComplianceEvidenceSource(Protocol):
    async def load(self, claim: ClaimV1) -> ComplianceEvidenceBundle: ...


class ComplianceEvidenceLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> ComplianceEvidenceBundle: ...
