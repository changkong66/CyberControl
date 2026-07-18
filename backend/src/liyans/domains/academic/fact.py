from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import EvidenceRefV1, SourceAuthorityTier
from liyans_contracts.topic4_common import VerificationVerdict

_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_NEGATION = frozenset(
    {
        "cannot",
        "false",
        "not",
        "never",
        "no",
        "without",
        "\u4e0d",
        "\u5426",
        "\u65e0",
        "\u672a",
        "\u9519\u8bef",
        "\u4e0d\u80fd",
    }
)
_STOP = frozenset(
    {
        "a",
        "all",
        "an",
        "and",
        "are",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)
_AUTHORITY_WEIGHT = {
    SourceAuthorityTier.PRIMARY_STANDARD: 1.00,
    SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK: 0.92,
    SourceAuthorityTier.PEER_REVIEWED: 0.84,
    SourceAuthorityTier.OFFICIAL_DOCUMENTATION: 0.76,
    SourceAuthorityTier.CURATED_INTERNAL: 0.64,
}


@dataclass(frozen=True, slots=True)
class FactCoverageResult:
    verdict: VerificationVerdict
    confidence: float
    evidence_ref_ids: tuple[UUID, ...]
    supporting_evidence_ref_ids: tuple[UUID, ...]
    contradicting_evidence_ref_ids: tuple[UUID, ...]
    coverage_score: float
    finding_codes: tuple[str, ...]


class ClaimFactVerifier:
    def __init__(self, *, minimum_overlap: float = 0.45) -> None:
        if not 0.0 < minimum_overlap <= 1.0:
            raise ValueError("minimum_overlap must be between zero and one")
        self._minimum_overlap = minimum_overlap

    def verify(
        self,
        claim: ClaimV1,
        evidence: tuple[EvidenceRefV1, ...],
        *,
        tenant_id: str | None = None,
    ) -> FactCoverageResult:
        expected_tenant = tenant_id or claim.tenant_id
        self._validate_evidence(claim, evidence, expected_tenant)
        claim_tokens = self._meaningful_tokens(claim.normalized_statement)
        if not evidence:
            return FactCoverageResult(
                verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                confidence=0.15,
                evidence_ref_ids=(),
                supporting_evidence_ref_ids=(),
                contradicting_evidence_ref_ids=(),
                coverage_score=0.0,
                finding_codes=("C3_FACT_EVIDENCE_MISSING",),
            )

        supporting: list[tuple[EvidenceRefV1, float]] = []
        contradicting: list[tuple[EvidenceRefV1, float]] = []
        for ref in evidence:
            overlap = self._overlap(claim_tokens, self._meaningful_tokens(ref.excerpt))
            if overlap < self._minimum_overlap:
                continue
            weighted = overlap * _AUTHORITY_WEIGHT[ref.source_authority_tier]
            if self._is_negated(ref.excerpt):
                contradicting.append((ref, weighted))
            else:
                supporting.append((ref, weighted))

        supporting_ids = tuple(item.evidence_ref_id for item, _ in supporting)
        contradicting_ids = tuple(item.evidence_ref_id for item, _ in contradicting)
        all_ids = tuple(ref.evidence_ref_id for ref in evidence)
        if supporting and contradicting:
            verdict = VerificationVerdict.PARTIALLY_SUPPORTED
            confidence = 0.55
            codes = ("C3_FACT_EVIDENCE_CONFLICT",)
        elif contradicting:
            verdict = VerificationVerdict.CONTRADICTED
            confidence = min(0.97, 0.70 + max(score for _, score in contradicting) * 0.25)
            codes = ("C3_FACT_CONTRADICTED",)
        elif supporting:
            best_score = max(score for _, score in supporting)
            verdict = VerificationVerdict.SUPPORTED
            confidence = min(0.98, 0.65 + best_score * 0.33)
            codes = ()
        else:
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
            confidence = 0.25
            codes = ("C3_FACT_COVERAGE_INSUFFICIENT",)
        coverage = min(
            1.0,
            self._overlap(
                claim_tokens, self._meaningful_tokens(" ".join(ref.excerpt for ref in evidence))
            ),
        )
        return FactCoverageResult(
            verdict=verdict,
            confidence=confidence,
            evidence_ref_ids=all_ids,
            supporting_evidence_ref_ids=supporting_ids,
            contradicting_evidence_ref_ids=contradicting_ids,
            coverage_score=coverage,
            finding_codes=codes,
        )

    @staticmethod
    def _validate_evidence(
        claim: ClaimV1,
        evidence: tuple[EvidenceRefV1, ...],
        tenant_id: str,
    ) -> None:
        if claim.tenant_id != tenant_id:
            raise ValueError("claim fact verification tenant does not match claim")
        seen: set[UUID] = set()
        for ref in evidence:
            if ref.tenant_id != tenant_id:
                raise ValueError("claim fact evidence cannot cross tenant boundaries")
            if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
                raise ValueError("claim fact evidence must belong to the verified claim")
            if ref.evidence_ref_id in seen:
                raise ValueError("claim fact evidence references must be unique")
            seen.add(ref.evidence_ref_id)

    @staticmethod
    def _meaningful_tokens(value: str) -> set[str]:
        return {
            token.casefold() for token in _TOKEN.findall(value) if token.casefold() not in _STOP
        }

    @staticmethod
    def _overlap(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left)

    @staticmethod
    def _is_negated(value: str) -> bool:
        return bool(
            _TOKEN.findall(value)
            and _NEGATION.intersection(token.casefold() for token in _TOKEN.findall(value))
        )
