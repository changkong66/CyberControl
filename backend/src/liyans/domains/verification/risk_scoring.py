from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from liyans_contracts.enums import VerificationProfile
from liyans_contracts.topic4_c1 import ClaimRiskV1, ClaimV1
from liyans_contracts.topic4_common import ClaimKind, RiskLevel, VerificationModule

from .records import build_topic4_record

_ABSOLUTE_ASSERTION = re.compile(
    r"(?:always|never|guaranteed|must|if and only if|"
    r"\u5fc5\u7136|\u7edd\u5bf9|\u4e00\u5b9a|\u5f53\u4e14\u4ec5\u5f53|\u5145\u8981)",
    re.IGNORECASE,
)
_STABILITY_ASSERTION = re.compile(
    r"(?:stable|unstable|stability|hurwitz|routh|nyquist|"
    r"\u7a33\u5b9a|\u4e0d\u7a33\u5b9a|\u9c81\u68d2)",
    re.IGNORECASE,
)
_CITATION_SIGNAL = re.compile(
    r"(?:doi\s*:|https?://|et\s+al\.|journal|proceedings|"
    r"\u53c2\u8003\u6587\u732e|\u8bba\u6587|\u671f\u520a)",
    re.IGNORECASE,
)
_NUMERIC_SIGNAL = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?(?:%|ms|s|Hz|dB)?")
_INJECTION_SIGNAL = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous|system\s+prompt|developer\s+message|"
    r"jailbreak|prompt\s+injection|\u5ffd\u7565\u4e4b\u524d|\u7cfb\u7edf\u63d0\u793a\u8bcd)",
    re.IGNORECASE,
)
_DESTRUCTIVE_CODE = re.compile(
    r"(?:rm\s+-rf|format\s+[a-z]:|drop\s+(?:database|table)|"
    r"os\.system|subprocess\.|shell\s*=\s*true|eval\s*\(|exec\s*\()",
    re.IGNORECASE,
)
_PII_SIGNAL = re.compile(
    r"(?:\b1[3-9]\d{9}\b|\b\d{17}[0-9Xx]\b|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)

_BASE_DIMENSIONS: dict[ClaimKind, tuple[float, float, float, float, float]] = {
    ClaimKind.TEXT: (0.42, 0.38, 0.34, 0.22, 0.08),
    ClaimKind.FORMULA: (0.76, 0.68, 0.42, 0.34, 0.08),
    ClaimKind.GRAPH: (0.58, 0.52, 0.38, 0.30, 0.08),
    ClaimKind.QUIZ: (0.72, 0.76, 0.42, 0.42, 0.10),
    ClaimKind.CODE: (0.78, 0.80, 0.46, 0.64, 0.76),
    ClaimKind.EXTENSION: (0.60, 0.44, 0.66, 0.28, 0.24),
}

_VERTICAL_MODULE: dict[ClaimKind, VerificationModule] = {
    ClaimKind.TEXT: VerificationModule.C3_ACADEMIC,
    ClaimKind.FORMULA: VerificationModule.C3_ACADEMIC,
    ClaimKind.GRAPH: VerificationModule.C4_GRAPH,
    ClaimKind.QUIZ: VerificationModule.C5_QUIZ,
    ClaimKind.CODE: VerificationModule.C6_CODE,
    ClaimKind.EXTENSION: VerificationModule.C7_EXTENSION,
}


@dataclass(frozen=True, slots=True)
class RiskScoringPolicy:
    policy_version: str
    low_ceiling: float = 0.35
    medium_ceiling: float = 0.60
    high_ceiling: float = 0.78

    def __post_init__(self) -> None:
        if not self.policy_version or len(self.policy_version) > 128:
            raise ValueError("risk policy version must contain 1 to 128 characters")
        if not 0.0 < self.low_ceiling < self.medium_ceiling < self.high_ceiling <= 1.0:
            raise ValueError("risk thresholds must be strictly increasing")


class ClaimRiskScorer:
    """Calculates replayable risk dimensions and mandatory module coverage."""

    def __init__(self, policy: RiskScoringPolicy) -> None:
        self._policy = policy

    def score_all(
        self,
        claims: list[ClaimV1],
        *,
        profile: VerificationProfile,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> list[ClaimRiskV1]:
        return [
            self.score(
                claim,
                profile=profile,
                trace_id=trace_id,
                tenant_id=tenant_id,
                created_at=created_at,
            )
            for claim in claims
        ]

    def score(
        self,
        claim: ClaimV1,
        *,
        profile: VerificationProfile,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> ClaimRiskV1:
        dimensions = list(_BASE_DIMENSIONS[claim.claim_kind])
        reasons = [f"CLAIM_KIND_{claim.claim_kind.value}"]
        statement = claim.normalized_statement

        if _ABSOLUTE_ASSERTION.search(statement):
            self._raise_dimensions(dimensions, academic=0.12, learner=0.10, uncertainty=0.14)
            reasons.append("ABSOLUTE_ASSERTION")
        if _STABILITY_ASSERTION.search(statement):
            self._raise_dimensions(dimensions, academic=0.10, learner=0.10, irreversibility=0.08)
            reasons.append("STABILITY_ASSERTION")
        if _NUMERIC_SIGNAL.search(statement):
            self._raise_dimensions(dimensions, academic=0.08, learner=0.06, uncertainty=0.08)
            reasons.append("NUMERIC_ASSERTION")
        if _CITATION_SIGNAL.search(statement) or claim.claim_subtype == "extension_citation":
            self._raise_dimensions(dimensions, academic=0.08, uncertainty=0.16)
            reasons.append("EXTERNAL_CITATION")
        if claim.claim_kind == ClaimKind.CODE:
            reasons.append("EXECUTABLE_CONTENT")
        if _DESTRUCTIVE_CODE.search(statement):
            self._raise_dimensions(
                dimensions,
                learner=0.18,
                uncertainty=0.12,
                irreversibility=0.30,
                external_action=0.24,
            )
            reasons.append("DESTRUCTIVE_CODE_SIGNAL")
        if _INJECTION_SIGNAL.search(statement):
            self._raise_dimensions(
                dimensions,
                uncertainty=0.34,
                irreversibility=0.24,
                external_action=0.24,
            )
            reasons.append("PROMPT_INJECTION_SIGNAL")
        if _PII_SIGNAL.search(statement):
            self._raise_dimensions(
                dimensions,
                learner=0.18,
                irreversibility=0.32,
                external_action=0.20,
            )
            reasons.append("PII_SIGNAL")

        profile_factor = {
            VerificationProfile.STANDARD: 1.0,
            VerificationProfile.STRICT: 1.08,
            VerificationProfile.CODE_STRICT: 1.12 if claim.claim_kind == ClaimKind.CODE else 1.05,
        }[profile]
        dimensions = [min(1.0, value * profile_factor) for value in dimensions]
        weighted_score = self._weighted_score(dimensions)
        if any(
            reason in reasons
            for reason in ("PROMPT_INJECTION_SIGNAL", "DESTRUCTIVE_CODE_SIGNAL", "PII_SIGNAL")
        ):
            weighted_score = max(weighted_score, 0.82)
        level = self._level(weighted_score)
        risk_id = uuid5(
            NAMESPACE_URL,
            (
                f"liyans:topic4:risk:{tenant_id}:{claim.verification_id}:"
                f"{claim.claim_id}:{self._policy.policy_version}"
            ),
        )
        return build_topic4_record(
            ClaimRiskV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="claim.risk.v1",
            risk_id=risk_id,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            level=level,
            score=round(weighted_score, 6),
            academic_impact=round(dimensions[0], 6),
            learner_harm=round(dimensions[1], 6),
            uncertainty=round(dimensions[2], 6),
            irreversibility=round(dimensions[3], 6),
            external_action=round(dimensions[4], 6),
            mandatory_modules=self._mandatory_modules(claim.claim_kind),
            reason_codes=reasons,
            policy_version=self._policy.policy_version,
        )

    @staticmethod
    def _raise_dimensions(
        dimensions: list[float],
        *,
        academic: float = 0.0,
        learner: float = 0.0,
        uncertainty: float = 0.0,
        irreversibility: float = 0.0,
        external_action: float = 0.0,
    ) -> None:
        increments = (academic, learner, uncertainty, irreversibility, external_action)
        for index, increment in enumerate(increments):
            dimensions[index] = min(1.0, dimensions[index] + increment)

    @staticmethod
    def _weighted_score(dimensions: list[float]) -> float:
        weights = (0.30, 0.25, 0.20, 0.15, 0.10)
        return sum(value * weight for value, weight in zip(dimensions, weights, strict=True))

    def _level(self, score: float) -> RiskLevel:
        if score < self._policy.low_ceiling:
            return RiskLevel.LOW
        if score < self._policy.medium_ceiling:
            return RiskLevel.MEDIUM
        if score < self._policy.high_ceiling:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    @staticmethod
    def _mandatory_modules(kind: ClaimKind) -> list[VerificationModule]:
        return [
            VerificationModule.C2_RAG,
            _VERTICAL_MODULE[kind],
            VerificationModule.C9_SECURITY,
            VerificationModule.C10_PRIVACY,
            VerificationModule.C11_COMPLIANCE,
        ]
