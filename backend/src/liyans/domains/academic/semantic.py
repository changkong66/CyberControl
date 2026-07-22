from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import EvidenceRefV1, SourceAuthorityTier
from liyans_contracts.topic4_common import VerificationVerdict

from .fact import ClaimFactVerifier, FactCoverageResult

_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_AUTHORITY_WEIGHT = {
    SourceAuthorityTier.PRIMARY_STANDARD: 1.00,
    SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK: 0.92,
    SourceAuthorityTier.PEER_REVIEWED: 0.84,
    SourceAuthorityTier.OFFICIAL_DOCUMENTATION: 0.76,
    SourceAuthorityTier.CURATED_INTERNAL: 0.64,
}

# Longest and most specific phrases must be normalized before their components.
_PHRASE_ALIASES = (
    ("open right half-plane", "right_half_plane"),
    ("open right half plane", "right_half_plane"),
    ("first-order-plus-dead-time", "fopdt"),
    ("first order plus dead time", "fopdt"),
    ("integral squared error", "ise"),
    ("integral square error", "ise"),
    ("matrix exponential", "matrix_exponential"),
    ("scalar product", "scalar_product"),
    ("constant-amplitude", "constant_amplitude"),
    ("constant amplitude", "constant_amplitude"),
    ("performance indicators", "performance"),
    ("no dynamic distinction", "identical"),
    ("asymptotically stable", "stable"),
    ("right half-plane", "right_half_plane"),
    ("right half plane", "right_half_plane"),
    ("input-output", "input_output"),
    ("input output", "input_output"),
    ("state-space", "state_space"),
    ("state space", "state_space"),
    ("transfer-function", "transfer_function"),
    ("transfer function", "transfer_function"),
    ("negative-feedback", "negative_feedback"),
    ("negative feedback", "negative_feedback"),
    ("closed-loop", "closed_loop"),
    ("closed loop", "closed_loop"),
    ("open-loop", "open_loop"),
    ("open loop", "open_loop"),
    ("first-principles", "first_principles"),
    ("first principles", "first_principles"),
    ("model-free", "model_free"),
    ("model free", "model_free"),
    ("limit cycle", "limit_cycle"),
    ("time constant", "time_constant"),
    ("gain margin", "gain_margin"),
    ("phase margin", "phase_margin"),
    ("sampling period", "sampling_period"),
    ("sampling rate", "sampling_rate"),
    ("control quality", "control_quality"),
    ("not a valid", "invalid"),
    ("need not", "need_not"),
    ("must always", "must_always"),
    ("can never", "never"),
    ("no denominator", "no_denominator"),
    ("n equals zero", "n = 0"),
    ("n equals one", "n = 1"),
    ("n equals two", "n = 2"),
    ("equals zero", "= 0"),
    ("equals one", "= 1"),
    ("equals two", "= 2"),
    ("不一定", "need_not"),
    ("并非总是", "need_not"),
    ("必须总是", "must_always"),
    ("矩阵指数", "matrix_exponential"),
    ("标量乘积", "scalar_product"),
    ("右半平面", "right_half_plane"),
    ("负反馈", "negative_feedback"),
    ("闭环", "closed_loop"),
    ("开环", "open_loop"),
    ("极限环", "limit_cycle"),
    ("无分母", "no_denominator"),
    ("不稳定", "unstable"),
    ("稳定", "stable"),
    ("之前", "before"),
    ("之后", "after"),
    ("独立于", "independent"),
    ("无关", "independent"),
    ("远离", "away"),
    ("趋向", "toward"),
    ("朝向", "toward"),
    ("不包含", "exclude"),
    ("包含", "include"),
    ("包括", "include"),
    ("排除", "exclude"),
    ("不能", "cannot"),
    ("从不", "never"),
    ("相同", "identical"),
    ("不同", "distinct"),
    ("持续", "sustain"),
    ("衰减", "decay"),
    ("分母", "denominator"),
    ("依赖", "require"),
    ("需要", "require"),
)

_WORD_ALIASES = {
    "applied": "apply",
    "applies": "apply",
    "builds": "build",
    "calculated": "calculate",
    "classified": "classify",
    "classes": "class",
    "coefficients": "coefficient",
    "computed": "compute",
    "crosses": "cross",
    "crossing": "cross",
    "decayed": "decay",
    "derived": "derive",
    "derives": "derive",
    "determined": "determine",
    "determines": "determine",
    "disabled": "disable",
    "excludes": "exclude",
    "excluded": "exclude",
    "forbidden": "forbid",
    "forbids": "forbid",
    "identified": "determine",
    "identifies": "determine",
    "included": "include",
    "includes": "include",
    "including": "include",
    "increasing": "increase",
    "indicators": "indicator",
    "inferred": "infer",
    "leaves": "leave",
    "measured": "measure",
    "measurements": "measure",
    "models": "model",
    "moves": "move",
    "moving": "move",
    "operations": "operation",
    "oscillates": "oscillation",
    "oscillations": "oscillation",
    "parameters": "parameter",
    "performs": "perform",
    "performed": "perform",
    "poles": "pole",
    "processes": "process",
    "recognized": "recognize",
    "recognises": "recognize",
    "regulation": "control",
    "remains": "remain",
    "removed": "remove",
    "removes": "remove",
    "required": "require",
    "requires": "require",
    "requiring": "require",
    "responses": "response",
    "selected": "select",
    "selecting": "select",
    "selection": "select",
    "selects": "select",
    "sustained": "sustain",
    "tuned": "tune",
    "tuning": "tune",
    "used": "use",
    "uses": "use",
    "using": "use",
    "variables": "variable",
    "eigenvalues": "eigenvalue",
}

_STOP_WORDS = frozenset(
    {
        "a",
        "all",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "both",
        "by",
        "can",
        "cited",
        "could",
        "every",
        "for",
        "from",
        "if",
        "in",
        "is",
        "its",
        "may",
        "of",
        "on",
        "one",
        "only",
        "or",
        "should",
        "such",
        "that",
        "the",
        "this",
        "to",
        "under",
        "was",
        "were",
        "will",
        "with",
        "would",
    }
)
_WEAK_MODAL = frozenset({"can", "commonly", "may", "often", "sometimes"})
_STRONG_MODAL = frozenset(
    {"always", "cannot", "every", "exact", "guaranteed", "must", "necessarily", "never"}
)
_GENERIC_ANCHORS = frozenset(
    {
        "claim",
        "complete",
        "control",
        "fact",
        "gain",
        "increase",
        "initial",
        "method",
        "model",
        "process",
        "procedure",
        "system",
    }
)


@dataclass(frozen=True, slots=True)
class SemanticVerifierPolicy:
    minimum_support_hypothesis_coverage: float = 0.82
    minimum_support_jaccard: float = 0.58
    minimum_denial_anchor_coverage: float = 0.18
    max_statement_characters: int = 32_768

    def __post_init__(self) -> None:
        for value in (
            self.minimum_support_hypothesis_coverage,
            self.minimum_support_jaccard,
            self.minimum_denial_anchor_coverage,
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError("semantic verifier thresholds must be between zero and one")
        if not 1 <= self.max_statement_characters <= 131_072:
            raise ValueError("semantic verifier statement limit must be between 1 and 131072")


@dataclass(frozen=True, slots=True)
class _RelationAssessment:
    verdict: VerificationVerdict
    confidence: float
    finding_code: str


class SemanticClaimVerifierV2:
    """Conservative deterministic NLI over immutable academic evidence."""

    def __init__(self, policy: SemanticVerifierPolicy | None = None) -> None:
        self._policy = policy or SemanticVerifierPolicy()

    def verify(
        self,
        claim: ClaimV1,
        evidence: tuple[EvidenceRefV1, ...],
        *,
        tenant_id: str | None = None,
    ) -> FactCoverageResult:
        expected_tenant = tenant_id or claim.tenant_id
        ClaimFactVerifier._validate_evidence(claim, evidence, expected_tenant)
        self._validate_lengths(claim, evidence)
        if not evidence:
            return FactCoverageResult(
                verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                confidence=0.15,
                evidence_ref_ids=(),
                supporting_evidence_ref_ids=(),
                contradicting_evidence_ref_ids=(),
                coverage_score=0.0,
                finding_codes=("C3_SEMANTIC_EVIDENCE_MISSING",),
            )

        supporting: list[tuple[EvidenceRefV1, _RelationAssessment]] = []
        contradicting: list[tuple[EvidenceRefV1, _RelationAssessment]] = []
        codes: set[str] = set()
        for ref in evidence:
            relation = self._assess(ref.excerpt, claim.normalized_statement)
            if relation.verdict == VerificationVerdict.SUPPORTED:
                supporting.append((ref, relation))
            elif relation.verdict == VerificationVerdict.CONTRADICTED:
                contradicting.append((ref, relation))
                codes.add(relation.finding_code)

        supporting_ids = tuple(ref.evidence_ref_id for ref, _ in supporting)
        contradicting_ids = tuple(ref.evidence_ref_id for ref, _ in contradicting)
        all_ids = tuple(ref.evidence_ref_id for ref in evidence)
        if supporting and contradicting:
            verdict = VerificationVerdict.PARTIALLY_SUPPORTED
            confidence = 0.55
            codes.add("C3_SEMANTIC_EVIDENCE_CONFLICT")
        elif contradicting:
            verdict = VerificationVerdict.CONTRADICTED
            confidence = self._weighted_confidence(contradicting)
            codes.add("C3_SEMANTIC_CONTRADICTED")
        elif supporting:
            verdict = VerificationVerdict.SUPPORTED
            confidence = self._weighted_confidence(supporting)
        else:
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
            confidence = 0.30
            codes.add("C3_SEMANTIC_COVERAGE_INSUFFICIENT")

        return FactCoverageResult(
            verdict=verdict,
            confidence=confidence,
            evidence_ref_ids=all_ids,
            supporting_evidence_ref_ids=supporting_ids,
            contradicting_evidence_ref_ids=contradicting_ids,
            coverage_score=self._combined_coverage(claim.normalized_statement, evidence),
            finding_codes=tuple(sorted(codes)),
        )

    def _validate_lengths(self, claim: ClaimV1, evidence: tuple[EvidenceRefV1, ...]) -> None:
        if len(claim.normalized_statement) > self._policy.max_statement_characters:
            raise ValueError("semantic claim exceeds the bounded statement length")
        if any(len(ref.excerpt) > self._policy.max_statement_characters for ref in evidence):
            raise ValueError("semantic evidence exceeds the bounded statement length")

    @staticmethod
    def _weighted_confidence(
        relations: list[tuple[EvidenceRefV1, _RelationAssessment]],
    ) -> float:
        return min(
            0.995,
            max(
                relation.confidence * _AUTHORITY_WEIGHT[ref.source_authority_tier]
                for ref, relation in relations
            ),
        )

    def _assess(self, premise: str, hypothesis: str) -> _RelationAssessment:
        premise_normalized = self._normalize(premise)
        hypothesis_normalized = self._normalize(hypothesis)
        if premise_normalized == hypothesis_normalized:
            return _RelationAssessment(VerificationVerdict.SUPPORTED, 0.995, "")

        contradiction = self._explicit_contradiction(premise, hypothesis)
        if contradiction is not None:
            return _RelationAssessment(VerificationVerdict.CONTRADICTED, 0.99, contradiction)
        if self._epistemic_extrapolation(hypothesis):
            return _RelationAssessment(
                VerificationVerdict.INSUFFICIENT_EVIDENCE,
                0.30,
                "C3_SEMANTIC_EXTRAPOLATION_UNSUPPORTED",
            )
        if self._direct_denial(premise, hypothesis) or self._direct_denial(hypothesis, premise):
            return _RelationAssessment(
                VerificationVerdict.CONTRADICTED,
                0.97,
                "C3_SEMANTIC_PREDICATE_DENIED",
            )

        hypothesis_coverage, jaccard = self._semantic_similarity(premise, hypothesis)
        if (
            not self._stronger_hypothesis(premise, hypothesis)
            and hypothesis_coverage >= self._policy.minimum_support_hypothesis_coverage
            and jaccard >= self._policy.minimum_support_jaccard
        ):
            confidence = min(0.96, 0.72 + 0.14 * hypothesis_coverage + 0.10 * jaccard)
            return _RelationAssessment(VerificationVerdict.SUPPORTED, confidence, "")
        return _RelationAssessment(
            VerificationVerdict.INSUFFICIENT_EVIDENCE,
            0.30,
            "C3_SEMANTIC_COVERAGE_INSUFFICIENT",
        )

    def _explicit_contradiction(self, premise: str, hypothesis: str) -> str | None:
        premise_tokens = set(self._tokens(premise))
        hypothesis_tokens = set(self._tokens(hypothesis))
        hypothesis_normalized = self._normalize(hypothesis)

        if not self._contradiction_relevant(premise_tokens, hypothesis_tokens):
            return None

        if self._order_reversed(premise, hypothesis):
            return "C3_SEMANTIC_ORDER_REVERSED"
        if (
            "require" in premise_tokens
            and "independent" in hypothesis_tokens
            or "independent" in premise_tokens
            and "require" in hypothesis_tokens
        ):
            return "C3_SEMANTIC_DEPENDENCY_REVERSED"
        if (
            "noise" in premise_tokens
            and premise_tokens.intersection({"disable", "undesirable"})
            and "noise" in hypothesis_tokens
            and hypothesis_tokens.intersection({"eliminate", "remove"})
        ):
            return "C3_SEMANTIC_CAUSAL_EFFECT_REVERSED"
        if (
            "remain" in premise_tokens
            and "within" in premise_tokens
            and ("leave" in hypothesis_tokens or {"cross", "first"}.issubset(hypothesis_tokens))
        ):
            return "C3_SEMANTIC_TEMPORAL_CONDITION_REVERSED"
        if (
            "classify" in premise_tokens
            or len(
                premise_tokens.intersection({"critically", "damped", "overdamped", "underdamped"})
            )
            >= 2
        ) and "identical" in hypothesis_tokens:
            return "C3_SEMANTIC_CLASS_DISTINCTION_DENIED"
        if (
            "model_free" in premise_tokens
            and "complete" in hypothesis_tokens
            and "require" in hypothesis_tokens
            and (
                "first_principles" in hypothesis_tokens
                or {"mathematical", "model"}.issubset(hypothesis_tokens)
            )
        ):
            return "C3_SEMANTIC_MODEL_REQUIREMENT_REVERSED"
        if (
            premise_tokens.intersection({"constant_amplitude", "sustain"})
            and "oscillation" in premise_tokens
            and "oscillation" in hypothesis_tokens
            and hypothesis_tokens.intersection({"decay", "zero"})
        ):
            return "C3_SEMANTIC_PERSISTENCE_REVERSED"
        if self._numeric_association_conflict(premise, hypothesis):
            return "C3_SEMANTIC_NUMERIC_ASSOCIATION_CONFLICT"
        if (
            "away" in premise_tokens
            and "toward" in hypothesis_tokens
            or "toward" in premise_tokens
            and "away" in hypothesis_tokens
        ):
            return "C3_SEMANTIC_DIRECTION_REVERSED"
        if "matrix_exponential" in premise_tokens and "scalar_product" in hypothesis_tokens:
            return "C3_SEMANTIC_MATHEMATICAL_FORM_REPLACED"
        if (
            "divided" in premise_tokens or "denominator" in premise_tokens
        ) and "no_denominator" in hypothesis_tokens:
            return "C3_SEMANTIC_DENOMINATOR_DENIED"
        if premise_tokens.intersection({"burden", "degrade", "error", "poor"}) and (
            hypothesis_tokens.intersection({"free", "ideal"})
        ):
            return "C3_SEMANTIC_COST_QUALITY_REVERSED"
        if (
            "unstable" in premise_tokens
            and "stable" in hypothesis_tokens
            or "stable" in premise_tokens
            and "unstable" in hypothesis_tokens
        ):
            return "C3_SEMANTIC_STABILITY_POLARITY_REVERSED"
        if "need_not" in premise_tokens and (
            "must_always" in hypothesis_tokens
            or {"always", "every"}.issubset(set(hypothesis_normalized.split()))
        ):
            return "C3_SEMANTIC_QUANTIFIER_SCOPE_REVERSED"
        return None

    @staticmethod
    def _contradiction_relevant(premise_tokens: set[str], hypothesis_tokens: set[str]) -> bool:
        anchors = premise_tokens.intersection(hypothesis_tokens) - _GENERIC_ANCHORS
        return bool(anchors)

    def _order_reversed(self, premise: str, hypothesis: str) -> bool:
        premise_order = self._order_pair(premise)
        hypothesis_order = self._order_pair(hypothesis)
        if premise_order is None or hypothesis_order is None:
            return False
        premise_left, premise_right = premise_order
        hypothesis_left, hypothesis_right = hypothesis_order
        cross = (
            self._set_coverage(premise_left, hypothesis_right)
            + self._set_coverage(premise_right, hypothesis_left)
        ) / 2
        direct = (
            self._set_coverage(premise_left, hypothesis_left)
            + self._set_coverage(premise_right, hypothesis_right)
        ) / 2
        return cross >= 0.45 and cross > direct + 0.08

    def _order_pair(self, value: str) -> tuple[set[str], set[str]] | None:
        words = self._normalize(value).split()
        if "before" in words:
            ordinal = words.index("before")
            return (
                set(self._tokens(" ".join(words[:ordinal]))),
                set(self._tokens(" ".join(words[ordinal + 1 :]))),
            )
        if "after" in words:
            ordinal = words.index("after")
            return (
                set(self._tokens(" ".join(words[ordinal + 1 :]))),
                set(self._tokens(" ".join(words[:ordinal]))),
            )
        return None

    def _numeric_association_conflict(self, premise: str, hypothesis: str) -> bool:
        premise_words = self._normalize(premise).split()
        hypothesis_words = self._normalize(hypothesis).split()
        concepts = set(premise_words).intersection(hypothesis_words)
        concepts.intersection_update({"ad", "bd", "ise", "ist2e", "iste"})
        for concept in concepts:
            premise_value = self._nearest_number(premise_words, concept)
            hypothesis_value = self._nearest_number(hypothesis_words, concept)
            if (
                premise_value is not None
                and hypothesis_value is not None
                and premise_value != hypothesis_value
            ):
                return True
        return False

    @staticmethod
    def _nearest_number(words: list[str], concept: str) -> str | None:
        concept_indices = [index for index, word in enumerate(words) if word == concept]
        number_indices = [index for index, word in enumerate(words) if _NUMBER.fullmatch(word)]
        if not concept_indices or not number_indices:
            return None
        concept_index = concept_indices[0]
        number_index = min(number_indices, key=lambda index: (abs(index - concept_index), index))
        return words[number_index]

    def _direct_denial(self, premise: str, hypothesis: str) -> bool:
        hypothesis_words = self._normalize(hypothesis).split()
        hypothesis_padded = f" {' '.join(hypothesis_words)} "
        premise_tokens = set(self._tokens(premise))
        hypothesis_tokens = set(self._tokens(hypothesis))
        denial_tokens = {
            "cannot",
            "exclude",
            "forbid",
            "invalid",
            "never",
            "no",
            "no_denominator",
            "unusable",
        }
        if not hypothesis_tokens.intersection(denial_tokens) and (
            " without any " not in hypothesis_padded
        ):
            return False
        anchors = premise_tokens.intersection(hypothesis_tokens) - _GENERIC_ANCHORS
        if len(anchors) < 2:
            return False
        denominator = max(1, min(len(premise_tokens), len(hypothesis_tokens)))
        return len(anchors) / denominator >= self._policy.minimum_denial_anchor_coverage

    def _epistemic_extrapolation(self, hypothesis: str) -> bool:
        normalized = self._normalize(hypothesis)
        passive_inference = re.search(
            r"\b(?:can be|is enough to)(?:\s+\w+){0,3}\s+"
            r"(?:calculated|computed|decided|derived|determined|established|identified|"
            r"inferred|known|recovered|selected)\b",
            normalized,
        )
        bounded_request = re.search(
            r"\b(?:best|exact|largest|numerical|optimum|preferable|unique)\b",
            normalized,
        ) and re.search(r"\b(?:alone|only|solely|unspecified|without)\b", normalized)
        return bool(passive_inference or bounded_request)

    def _stronger_hypothesis(self, premise: str, hypothesis: str) -> bool:
        premise_words = set(self._normalize(premise).split())
        hypothesis_words = set(self._normalize(hypothesis).split())
        return bool(premise_words.intersection(_WEAK_MODAL)) and bool(
            hypothesis_words.intersection(_STRONG_MODAL)
        )

    def _semantic_similarity(self, premise: str, hypothesis: str) -> tuple[float, float]:
        premise_tokens = set(self._tokens(premise))
        hypothesis_tokens = set(self._tokens(hypothesis))
        if not premise_tokens or not hypothesis_tokens:
            return 0.0, 0.0
        intersection = premise_tokens.intersection(hypothesis_tokens)
        hypothesis_coverage = len(intersection) / len(hypothesis_tokens)
        jaccard = len(intersection) / len(premise_tokens.union(hypothesis_tokens))
        return hypothesis_coverage, jaccard

    def _combined_coverage(self, hypothesis: str, evidence: tuple[EvidenceRefV1, ...]) -> float:
        premise = " ".join(ref.excerpt for ref in evidence)
        hypothesis_coverage, _ = self._semantic_similarity(premise, hypothesis)
        return min(1.0, hypothesis_coverage)

    @classmethod
    def _normalize(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold().replace("'", " ")
        for source, target in _PHRASE_ALIASES:
            normalized = normalized.replace(source, target)
        return " ".join(_TOKEN.findall(normalized))

    @classmethod
    def _tokens(cls, value: str) -> tuple[str, ...]:
        return tuple(
            resolved
            for token in cls._normalize(value).split()
            if (resolved := _WORD_ALIASES.get(token, token)) not in _STOP_WORDS
        )

    @staticmethod
    def _set_coverage(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left.intersection(right)) / min(len(left), len(right))
