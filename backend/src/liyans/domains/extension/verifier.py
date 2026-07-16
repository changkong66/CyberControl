from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic3 import ExtensionResourceV1
from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_common import VerificationVerdict

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]*|[\u4e00-\u9fff]")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_PLACEHOLDER = re.compile(
    r"(?:citation\s+needed|unknown|tbd|todo|待补充|未知|未找到|虚构|fake)", re.IGNORECASE
)
_LICENSE_PATTERNS = (
    ("CC-BY-4.0", re.compile(r"cc\s*by(?:\s*[- ]?4(?:\.0)?)?", re.IGNORECASE)),
    ("CC0-1.0", re.compile(r"cc0(?:\s*[- ]?1(?:\.0)?)?", re.IGNORECASE)),
    ("MIT", re.compile(r"\bmit\b", re.IGNORECASE)),
    ("Apache-2.0", re.compile(r"apache(?:\s*[- ]?2(?:\.0)?)?", re.IGNORECASE)),
    ("BSD-3-Clause", re.compile(r"bsd(?:\s*[- ]?3(?:[- ]?clause)?)?", re.IGNORECASE)),
    ("GPL-3.0", re.compile(r"gpl(?:\s*[- ]?3(?:\.0)?)?", re.IGNORECASE)),
    ("AGPL-3.0", re.compile(r"agpl(?:\s*[- ]?3(?:\.0)?)?", re.IGNORECASE)),
    ("CC-BY-NC", re.compile(r"cc\s*by\s*[- ]?nc", re.IGNORECASE)),
)
_INCOMPATIBLE_LICENSES = frozenset({"GPL-3.0", "AGPL-3.0", "CC-BY-NC"})


@dataclass(frozen=True, slots=True)
class ExtensionAnalysis:
    source_present_in_approved_corpus: bool
    citation_valid: bool
    license_compatible: bool
    license_expression: str
    knowledge_relevance: float
    temporal_validity: bool | None
    finding_codes: tuple[str, ...]
    verdict: VerificationVerdict
    confidence: float


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN.findall(value)}


def _overlap(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set)


class Topic1ExtensionVerifier:
    """Deterministic local-corpus provenance verifier for Topic3 extensions."""

    def analyze(
        self,
        resource: ExtensionResourceV1,
        snapshot: Topic1GraphSnapshotV1,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> ExtensionAnalysis:
        codes: set[str] = set()
        source_text = " ".join((resource.title, resource.summary, resource.citation_text))
        source_tokens = _tokens(source_text)
        knowledge_points = {kp.kp_id: kp for kp in snapshot.content.knowledge_points}
        unknown_ids = set(resource.relevance_to_kp_ids) - set(knowledge_points)
        if unknown_ids:
            codes.add("C7_UNKNOWN_KNOWLEDGE_POINT")

        matched_points = 0
        for kp_id in resource.relevance_to_kp_ids:
            point = knowledge_points.get(kp_id)
            if point is None:
                continue
            authority_text = " ".join(
                [
                    point.title,
                    *point.aliases,
                    point.summary,
                    *point.learning_objectives,
                    point.category,
                    *point.tags,
                ]
            )
            if _overlap(_tokens(authority_text), source_tokens) >= 0.20:
                matched_points += 1
        target_coverage = 1.0 - len(unknown_ids) / len(resource.relevance_to_kp_ids)
        semantic_coverage = matched_points / len(resource.relevance_to_kp_ids)
        knowledge_relevance = round(0.60 * target_coverage + 0.40 * semantic_coverage, 6)
        if knowledge_relevance < 0.50:
            codes.add("C7_KNOWLEDGE_RELEVANCE_LOW")

        citation = resource.citation_text.strip()
        citation_tokens = _tokens(citation)
        citation_valid = (
            len(citation) >= 10
            and not _PLACEHOLDER.search(citation)
            and bool(_YEAR.search(citation) or resource.source_url)
        )
        if not citation_valid:
            codes.add("C7_CITATION_INVALID")

        source_present = False
        corpus_text = " ".join(f"{ref.citation} {ref.excerpt}" for ref in evidence)
        corpus_tokens = _tokens(corpus_text)
        if citation_tokens and (
            citation.casefold() in corpus_text.casefold()
            or _overlap(citation_tokens, corpus_tokens) >= 0.70
        ):
            source_present = True
        if not source_present:
            codes.add("C7_SOURCE_NOT_IN_APPROVED_CORPUS")

        license_expression = self._license_expression(corpus_text, citation)
        license_compatible = license_expression not in {"UNKNOWN", *_INCOMPATIBLE_LICENSES}
        if license_expression == "UNKNOWN":
            codes.add("C7_LICENSE_UNVERIFIED")
        elif not license_compatible:
            codes.add("C7_LICENSE_INCOMPATIBLE")

        temporal_validity = self._temporal_validity(citation)
        if temporal_validity is False:
            codes.add("C7_PUBLICATION_DATE_INVALID")

        if not evidence:
            codes.add("C7_EVIDENCE_REQUIRED")
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
            confidence = 0.25
        elif "C7_LICENSE_INCOMPATIBLE" in codes:
            verdict = VerificationVerdict.UNSAFE
            confidence = 0.98
        elif not source_present or not citation_valid or unknown_ids:
            verdict = VerificationVerdict.CONTRADICTED
            confidence = 0.95
        elif "C7_LICENSE_UNVERIFIED" in codes or temporal_validity is False:
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
            confidence = 0.45
        elif "C7_KNOWLEDGE_RELEVANCE_LOW" in codes:
            verdict = VerificationVerdict.CONTRADICTED
            confidence = 0.90
        else:
            verdict = VerificationVerdict.SUPPORTED
            confidence = 0.94

        return ExtensionAnalysis(
            source_present_in_approved_corpus=source_present,
            citation_valid=citation_valid,
            license_compatible=license_compatible,
            license_expression=license_expression,
            knowledge_relevance=knowledge_relevance,
            temporal_validity=temporal_validity,
            finding_codes=tuple(sorted(codes)),
            verdict=verdict,
            confidence=confidence,
        )

    @staticmethod
    def _license_expression(corpus_text: str, citation: str) -> str:
        text = f"{citation} {corpus_text}"
        for expression, pattern in _LICENSE_PATTERNS:
            if pattern.search(text):
                return expression
        return "UNKNOWN"

    @staticmethod
    def _temporal_validity(citation: str) -> bool | None:
        years = [int(match) for match in _YEAR.findall(citation)]
        if not years:
            return None
        return all(1900 <= year <= date.today().year for year in years)
