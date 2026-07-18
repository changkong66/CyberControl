from __future__ import annotations

import math
import re
from dataclasses import dataclass

from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_common import VerificationVerdict

_NUMERIC = re.compile(
    r"(?P<operator><=|>=|!=|=|<|>)?\s*"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*"
    r"(?P<unit>%|kHz|Hz|ms|us|ns|s|rad/s|deg/s|dB|mV|V|mA|A|ohm|rpm)?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NumericPolicy:
    absolute_tolerance: float = 1e-9
    relative_tolerance: float = 1e-6
    max_assertions: int = 256
    max_absolute_value: float = 1e100

    def __post_init__(self) -> None:
        if not math.isfinite(self.absolute_tolerance) or self.absolute_tolerance < 0:
            raise ValueError("absolute_tolerance must be finite and nonnegative")
        if not math.isfinite(self.relative_tolerance) or self.relative_tolerance < 0:
            raise ValueError("relative_tolerance must be finite and nonnegative")
        if not 1 <= self.max_assertions <= 4096:
            raise ValueError("max_assertions must be between 1 and 4096")
        if not math.isfinite(self.max_absolute_value) or self.max_absolute_value <= 0:
            raise ValueError("max_absolute_value must be finite and positive")


@dataclass(frozen=True, slots=True)
class NumericAssertion:
    source_text: str
    operator: str
    value: float
    unit: str | None
    canonical_value: float
    canonical_unit: str | None
    span_start: int
    span_end: int


@dataclass(frozen=True, slots=True)
class NumericComparison:
    asserted: NumericAssertion
    authoritative: NumericAssertion | None
    verdict: VerificationVerdict
    confidence: float
    absolute_error: float | None
    relative_error: float | None
    finding_code: str
    evidence_ref_id: str | None


@dataclass(frozen=True, slots=True)
class NumericVerificationSummary:
    comparisons: tuple[NumericComparison, ...]
    verdict: VerificationVerdict
    confidence: float
    finding_codes: tuple[str, ...]


class UnitNormalizer:
    _UNITS: dict[str, tuple[str, float]] = {
        "%": ("ratio", 0.01),
        "a": ("A", 1.0),
        "db": ("dB", 1.0),
        "deg/s": ("deg/s", 1.0),
        "hz": ("Hz", 1.0),
        "khz": ("Hz", 1000.0),
        "ma": ("A", 0.001),
        "ms": ("s", 0.001),
        "mv": ("V", 0.001),
        "ns": ("s", 1e-9),
        "ohm": ("ohm", 1.0),
        "rad/s": ("rad/s", 1.0),
        "rpm": ("rpm", 1.0),
        "s": ("s", 1.0),
        "us": ("s", 1e-6),
        "v": ("V", 1.0),
    }

    def normalize(self, value: float, unit: str | None) -> tuple[float, str | None]:
        if unit is None:
            return value, None
        normalized = self._UNITS.get(unit.casefold())
        if normalized is None:
            raise ValueError(f"unsupported numeric unit: {unit}")
        canonical_unit, multiplier = normalized
        return value * multiplier, canonical_unit


class NumericAssertionExtractor:
    def __init__(
        self,
        policy: NumericPolicy | None = None,
        normalizer: UnitNormalizer | None = None,
    ) -> None:
        self.policy = policy or NumericPolicy()
        self.normalizer = normalizer or UnitNormalizer()

    def extract(self, value: str) -> tuple[NumericAssertion, ...]:
        assertions: list[NumericAssertion] = []
        for match in _NUMERIC.finditer(value):
            numeric_value = float(match.group("value"))
            if (
                not math.isfinite(numeric_value)
                or abs(numeric_value) > self.policy.max_absolute_value
            ):
                raise ValueError("numeric assertion exceeds the bounded numeric range")
            unit = match.group("unit")
            canonical_value, canonical_unit = self.normalizer.normalize(numeric_value, unit)
            assertions.append(
                NumericAssertion(
                    source_text=match.group(0).strip(),
                    operator=match.group("operator") or "=",
                    value=numeric_value,
                    unit=unit,
                    canonical_value=canonical_value,
                    canonical_unit=canonical_unit,
                    span_start=match.start(),
                    span_end=match.end(),
                )
            )
            if len(assertions) > self.policy.max_assertions:
                raise ValueError("numeric assertion count exceeds the safety limit")
        return tuple(assertions)


class NumericFactVerifier:
    def __init__(
        self,
        policy: NumericPolicy | None = None,
        extractor: NumericAssertionExtractor | None = None,
    ) -> None:
        self.policy = policy or NumericPolicy()
        self.extractor = extractor or NumericAssertionExtractor(self.policy)

    def verify(
        self,
        statement: str,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> NumericVerificationSummary:
        asserted = self.extractor.extract(statement)
        if not asserted:
            return NumericVerificationSummary(
                comparisons=(),
                verdict=VerificationVerdict.NOT_APPLICABLE,
                confidence=1.0,
                finding_codes=(),
            )
        evidence_values = [
            (ref, item) for ref in evidence for item in self.extractor.extract(ref.excerpt)
        ]
        comparisons = tuple(self._match(item, evidence_values) for item in asserted)
        verdict = self._aggregate(comparisons)
        confidence = min((comparison.confidence for comparison in comparisons), default=0.0)
        finding_codes = tuple(
            sorted(
                {
                    comparison.finding_code
                    for comparison in comparisons
                    if comparison.finding_code != "C3_NUMERIC_SUPPORTED"
                }
            )
        )
        return NumericVerificationSummary(
            comparisons=comparisons,
            verdict=verdict,
            confidence=confidence,
            finding_codes=finding_codes,
        )

    def _match(
        self,
        asserted: NumericAssertion,
        evidence_values: list[tuple[EvidenceRefV1, NumericAssertion]],
    ) -> NumericComparison:
        compatible = [
            (ref, item)
            for ref, item in evidence_values
            if item.canonical_unit == asserted.canonical_unit
        ]
        if not compatible:
            return NumericComparison(
                asserted=asserted,
                authoritative=None,
                verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                confidence=0.25,
                absolute_error=None,
                relative_error=None,
                finding_code="C3_NUMERIC_EVIDENCE_MISSING",
                evidence_ref_id=None,
            )
        ref, authoritative = min(
            compatible,
            key=lambda pair: abs(pair[1].canonical_value - asserted.canonical_value),
        )
        absolute_error = abs(authoritative.canonical_value - asserted.canonical_value)
        scale = max(1.0, abs(authoritative.canonical_value), abs(asserted.canonical_value))
        relative_error = absolute_error / scale
        supported = self._satisfies(asserted, authoritative.canonical_value)
        return NumericComparison(
            asserted=asserted,
            authoritative=authoritative,
            verdict=(
                VerificationVerdict.SUPPORTED if supported else VerificationVerdict.CONTRADICTED
            ),
            confidence=0.98 if supported else 0.99,
            absolute_error=absolute_error,
            relative_error=relative_error,
            finding_code="C3_NUMERIC_SUPPORTED" if supported else "C3_NUMERIC_CONTRADICTED",
            evidence_ref_id=str(ref.evidence_ref_id),
        )

    def _satisfies(self, asserted: NumericAssertion, observed: float) -> bool:
        tolerance = max(
            self.policy.absolute_tolerance,
            self.policy.relative_tolerance * max(1.0, abs(asserted.canonical_value), abs(observed)),
        )
        difference = observed - asserted.canonical_value
        if asserted.operator == "=":
            return abs(difference) <= tolerance
        if asserted.operator == "!=":
            return abs(difference) > tolerance
        if asserted.operator == "<":
            return observed < asserted.canonical_value - tolerance
        if asserted.operator == "<=":
            return observed <= asserted.canonical_value + tolerance
        if asserted.operator == ">":
            return observed > asserted.canonical_value + tolerance
        if asserted.operator == ">=":
            return observed >= asserted.canonical_value - tolerance
        raise ValueError("unsupported numeric assertion operator")

    @staticmethod
    def _aggregate(comparisons: tuple[NumericComparison, ...]) -> VerificationVerdict:
        verdicts = {comparison.verdict for comparison in comparisons}
        if VerificationVerdict.CONTRADICTED in verdicts:
            return VerificationVerdict.CONTRADICTED
        if VerificationVerdict.INSUFFICIENT_EVIDENCE in verdicts:
            if VerificationVerdict.SUPPORTED in verdicts:
                return VerificationVerdict.PARTIALLY_SUPPORTED
            return VerificationVerdict.INSUFFICIENT_EVIDENCE
        return VerificationVerdict.SUPPORTED
