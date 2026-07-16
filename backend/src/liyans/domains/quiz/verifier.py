from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

import sympy as sp
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import (
    GoldenQuestionType,
    Topic1GoldenQuestionV1,
    Topic1GraphSnapshotV1,
    Topic1MisconceptionV1,
)
from liyans_contracts.topic4_c5 import QuizItemType, QuizVerificationResultV1
from liyans_contracts.topic4_common import VerificationVerdict

from liyans.domains.academic.formula import (
    FormulaParseError,
    FormulaSecurityError,
    SafeFormulaParser,
)
from liyans.domains.verification.records import build_topic4_record

from .parser import ParsedQuizItem

_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?%?")
_QUESTION_SIGNAL = re.compile(
    r"(?:[?\uff1f]|what|which|why|how|explain|determine|calculate|derive|prove|"
    r"\u6c42|\u8ba1\u7b97|\u5224\u65ad|\u8bf4\u660e|\u89e3\u91ca|"
    r"\u63a8\u5bfc|\u8bc1\u660e|\u4f30\u7b97|\u5206\u6790|\u6bd4\u8f83|"
    r"\u8bbe\u8ba1|\u7ed9\u51fa|\u5199\u51fa)",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(
    r"(?:\b(?:todo|tbd|placeholder|question|lorem ipsum)\b|"
    r"\u5f85\u8865\u5145|\u5360\u4f4d|\u793a\u4f8b\u9898\u5e72)",
    re.IGNORECASE,
)
_FALSE = re.compile(
    r"(?:\b(?:false|no|not|uncontrollable)\b|"
    r"\u9519\u8bef|\u4e0d\u6210\u7acb|\u4e0d\u53ef\u63a7|\u5426)",
    re.I,
)
_TRUE = re.compile(
    r"(?:\b(?:true|yes|controllable)\b|"
    r"\u6b63\u786e|\u6210\u7acb|\u53ef\u63a7|\u662f)",
    re.I,
)
_FORMULA_SIGNAL = re.compile(r"(?:[=<>^*/]|\\(?:frac|sqrt|zeta|omega)|\$)")
_TYPE_COMPATIBILITY = {
    GoldenQuestionType.CALCULATION: frozenset({QuizItemType.CALCULATION}),
    GoldenQuestionType.PROOF: frozenset(
        {QuizItemType.CONCEPT, QuizItemType.TRUE_FALSE, QuizItemType.CALCULATION}
    ),
    GoldenQuestionType.DESIGN: frozenset({QuizItemType.ENGINEERING_APPLICATION}),
    GoldenQuestionType.SIMULATION: frozenset({QuizItemType.ENGINEERING_APPLICATION}),
    GoldenQuestionType.SINGLE_CHOICE: frozenset(
        {QuizItemType.CONCEPT, QuizItemType.TRUE_FALSE, QuizItemType.MISCONCEPTION}
    ),
    GoldenQuestionType.MULTIPLE_CHOICE: frozenset(
        {QuizItemType.CONCEPT, QuizItemType.MISCONCEPTION}
    ),
}


class QuizIntegrityError(ValueError):
    """Raised when immutable Topic1 quiz authority cannot be trusted."""


@dataclass(frozen=True, slots=True)
class QuizAnalysis:
    result: QuizVerificationResultV1
    golden_question_id: str | None
    answer_coverage: float
    stem_similarity: float
    expected_difficulty: float | None


class Topic1QuizVerifier:
    """Deterministic quiz verifier over one immutable Topic1 graph snapshot."""

    def __init__(self) -> None:
        self._formula_parser = SafeFormulaParser()

    def verify(
        self,
        parsed: ParsedQuizItem,
        snapshot: Topic1GraphSnapshotV1,
        *,
        evidence_ref_ids: tuple[UUID, ...],
    ) -> QuizAnalysis:
        self._validate_snapshot(snapshot)
        item = parsed.verifier_ir
        codes: set[str] = set()
        known_kp_ids = {point.kp_id for point in snapshot.content.knowledge_points}
        if set(item.topic1_knowledge_point_ids) - known_kp_ids:
            codes.add("C5_UNKNOWN_KNOWLEDGE_POINT")

        golden, similarity = self._select_golden_question(parsed, snapshot)
        stem_unambiguous = self._stem_is_unambiguous(item.stem)
        if not stem_unambiguous:
            codes.add("C5_STEM_AMBIGUOUS_OR_INCOMPLETE")
        if golden is None:
            codes.add("C5_GOLDEN_QUESTION_NOT_FOUND")
        elif similarity < 0.18:
            codes.add("C5_STEM_TOPIC_MISMATCH")

        answer_correct: bool | None = None
        answer_coverage = 0.0
        computed_answer: str | None = None
        solution_coherent = self._solution_is_coherent(parsed, golden)
        diagnosis_valid = self._diagnosis_is_valid(parsed, golden, snapshot)
        expected_difficulty: float | None = None
        if golden is not None:
            computed_answer = json.dumps(
                golden.answer_document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if len(computed_answer) > 8192:
                raise QuizIntegrityError("Topic1 golden answer exceeds the frozen result limit")
            answer_coverage = self._answer_coverage(item.expected_answer, golden.answer_document)
            answer_correct = answer_coverage >= 0.999999
            if not answer_correct:
                codes.add("C5_ANSWER_INCORRECT_OR_INCOMPLETE")
            if not solution_coherent:
                codes.add("C5_SOLUTION_INCOHERENT")
            if not diagnosis_valid:
                codes.add("C5_DIAGNOSIS_MAPPING_INVALID")
            expected_difficulty = (golden.difficulty_level - 1) / 4
            if abs(item.difficulty - expected_difficulty) > 0.26:
                codes.add("C5_DIFFICULTY_LABEL_MISMATCH")
            if item.item_type not in _TYPE_COMPATIBILITY[golden.question_type]:
                codes.add("C5_QUESTION_TYPE_MISMATCH")

        verdict, confidence = self._verdict(
            codes=codes,
            golden=golden,
            answer_correct=answer_correct,
            evidence_ref_ids=evidence_ref_ids,
        )
        result = build_topic4_record(
            QuizVerificationResultV1,
            trace_id=item.trace_id,
            tenant_id=item.tenant_id,
            version_cas=1,
            created_at=item.created_at,
            immutable=True,
            schema_version="quiz-verification.result.v1",
            quiz_verification_result_id=uuid5(
                item.quiz_item_verifier_ir_id,
                f"quiz-verification:{canonical_sha256(sorted(codes))}",
            ),
            verification_id=item.verification_id,
            claim_id=item.claim_id,
            quiz_item_verifier_ir_id=item.quiz_item_verifier_ir_id,
            stem_unambiguous=stem_unambiguous,
            answer_correct=answer_correct,
            solution_coherent=solution_coherent,
            distractors_valid=None,
            diagnosis_mapping_valid=diagnosis_valid,
            computed_answer=computed_answer,
            finding_codes=sorted(codes),
            evidence_ref_ids=list(evidence_ref_ids),
            verdict=verdict,
            confidence=confidence,
        )
        return QuizAnalysis(
            result=result,
            golden_question_id=None if golden is None else golden.question_id,
            answer_coverage=answer_coverage,
            stem_similarity=similarity,
            expected_difficulty=expected_difficulty,
        )

    @staticmethod
    def _validate_snapshot(snapshot: Topic1GraphSnapshotV1) -> None:
        actual = canonical_sha256(snapshot.content.model_dump(mode="json"))
        if actual != snapshot.content_sha256:
            raise QuizIntegrityError("Topic1 quiz snapshot content hash failed")
        if snapshot.node_count != len(snapshot.content.knowledge_points):
            raise QuizIntegrityError("Topic1 quiz snapshot node count failed")
        if snapshot.edge_count != len(snapshot.content.prerequisites):
            raise QuizIntegrityError("Topic1 quiz snapshot edge count failed")
        question_ids = [item.question_id for item in snapshot.content.golden_questions]
        if len(question_ids) != len(set(question_ids)):
            raise QuizIntegrityError("Topic1 quiz snapshot contains duplicate questions")

    def _select_golden_question(
        self,
        parsed: ParsedQuizItem,
        snapshot: Topic1GraphSnapshotV1,
    ) -> tuple[Topic1GoldenQuestionV1 | None, float]:
        item = parsed.verifier_ir
        targets = set(item.topic1_knowledge_point_ids)
        candidates = [
            question
            for question in snapshot.content.golden_questions
            if question.primary_kp_id in targets or targets.intersection(question.related_kp_ids)
        ]
        if not candidates:
            return None, 0.0
        scored = [
            (
                self._text_similarity(item.stem, question.stem_markdown),
                question.question_id == item.question_id,
                question,
            )
            for question in candidates
        ]
        scored.sort(key=lambda value: (value[1], value[0], value[2].question_id), reverse=True)
        best_similarity, _, best = scored[0]
        if len(scored) > 1 and not scored[0][1] and abs(best_similarity - scored[1][0]) < 0.02:
            return None, best_similarity
        return best, best_similarity

    @staticmethod
    def _stem_is_unambiguous(stem: str) -> bool:
        normalized = unicodedata.normalize("NFKC", stem).strip()
        tokens = _TOKEN.findall(normalized)
        if len(normalized) < 8 or len(tokens) < 3 or _PLACEHOLDER.search(normalized):
            return False
        if normalized.count("$") % 2 or normalized.count("{") != normalized.count("}"):
            return False
        return _QUESTION_SIGNAL.search(normalized) is not None

    def _answer_coverage(self, answer: str, authority: dict[str, Any]) -> float:
        leaves = tuple(self._flatten(authority))
        if not leaves:
            return 0.0
        supported = sum(self._leaf_supported(answer, key, value) for key, value in leaves)
        return supported / len(leaves)

    def _leaf_supported(self, answer: str, key: str, value: object) -> bool:
        del key
        if isinstance(value, bool):
            return bool(_TRUE.search(answer)) if value else bool(_FALSE.search(answer))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            expected = float(value)
            for match in _NUMBER.finditer(answer):
                token = match.group(0)
                observed = float(token.rstrip("%"))
                if token.endswith("%"):
                    observed /= 100
                tolerance = max(1e-9, abs(expected) * 1e-3)
                if math.isclose(observed, expected, rel_tol=1e-3, abs_tol=tolerance):
                    return True
            return False
        if isinstance(value, str):
            if _FORMULA_SIGNAL.search(value):
                formula_match = self._formula_supported(answer, value)
                if formula_match is True:
                    return True
            value_tokens = self._meaningful_tokens(value)
            answer_tokens = self._meaningful_tokens(answer)
            if not value_tokens:
                return self._normalize_text(value) in self._normalize_text(answer)
            return len(value_tokens & answer_tokens) / len(value_tokens) >= 0.75
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return self._normalize_text(serialized) in self._normalize_text(answer)

    def _formula_supported(self, answer: str, authority: str) -> bool | None:
        try:
            expected = self._formula_parser.parse(authority)
        except (FormulaParseError, FormulaSecurityError):
            return None
        candidates = self._formula_parser.extract(answer)
        if not candidates and len(answer) <= 512:
            candidates = (answer,)
        for candidate in candidates:
            try:
                observed = self._formula_parser.parse(candidate)
                ratio = sp.cancel(observed.residual / expected.residual)
                if ratio != 0 and not ratio.free_symbols and not ratio.atoms(sp.Function):
                    numeric_ratio = complex(sp.N(ratio, 16))
                    if math.isfinite(numeric_ratio.real) and abs(numeric_ratio.imag) <= 1e-8:
                        return abs(numeric_ratio.real) > 1e-8
            except (
                FormulaParseError,
                FormulaSecurityError,
                ArithmeticError,
                TypeError,
                ValueError,
                ZeroDivisionError,
            ):
                continue
        return False

    def _solution_is_coherent(
        self,
        parsed: ParsedQuizItem,
        golden: Topic1GoldenQuestionV1 | None,
    ) -> bool:
        steps = [step.explanation.strip() for step in parsed.verifier_ir.solution_steps]
        if not steps or any(len(step) < 3 or _PLACEHOLDER.search(step) for step in steps):
            return False
        if len(set(map(self._normalize_text, steps))) != len(steps):
            return False
        combined = " ".join(steps)
        if self._text_similarity(combined, parsed.verifier_ir.expected_answer) < 0.08:
            return False
        if golden is None:
            return True
        return self._text_similarity(combined, golden.solution_markdown) >= 0.08

    @staticmethod
    def _diagnosis_is_valid(
        parsed: ParsedQuizItem,
        golden: Topic1GoldenQuestionV1 | None,
        snapshot: Topic1GraphSnapshotV1,
    ) -> bool:
        supplied = {value.casefold() for value in parsed.verifier_ir.misconception_codes}
        if golden is None:
            return not supplied
        known: dict[str, Topic1MisconceptionV1] = {
            item.misconception_id: item for item in snapshot.content.misconceptions
        }
        expected_ids = set(golden.misconception_ids)
        if any(identifier not in known for identifier in expected_ids):
            raise QuizIntegrityError("golden question references an unknown misconception")
        if not expected_ids:
            return not supplied
        accepted: set[str] = set()
        for identifier in expected_ids:
            misconception = known[identifier]
            accepted.add(identifier.casefold())
            accepted.update(tag.casefold() for tag in misconception.diagnosis_tags)
            accepted.add(misconception.title.casefold())
        return (
            bool(supplied)
            and supplied <= accepted
            and any(identifier.casefold() in supplied for identifier in expected_ids)
        )

    @staticmethod
    def _flatten(value: object, prefix: str = ""):
        if isinstance(value, dict):
            for key in sorted(value):
                next_prefix = f"{prefix}.{key}" if prefix else key
                yield from Topic1QuizVerifier._flatten(value[key], next_prefix)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                yield from Topic1QuizVerifier._flatten(item, f"{prefix}[{index}]")
            return
        yield prefix, value

    @staticmethod
    def _verdict(
        *,
        codes: set[str],
        golden: Topic1GoldenQuestionV1 | None,
        answer_correct: bool | None,
        evidence_ref_ids: tuple[UUID, ...],
    ) -> tuple[VerificationVerdict, float]:
        contradictory = {
            "C5_ANSWER_INCORRECT_OR_INCOMPLETE",
            "C5_SOLUTION_INCOHERENT",
            "C5_DIAGNOSIS_MAPPING_INVALID",
            "C5_STEM_TOPIC_MISMATCH",
            "C5_QUESTION_TYPE_MISMATCH",
        }
        if codes & contradictory:
            return VerificationVerdict.CONTRADICTED, 0.96
        if golden is None or answer_correct is None or not evidence_ref_ids:
            return VerificationVerdict.INSUFFICIENT_EVIDENCE, 0.25
        if codes:
            return VerificationVerdict.PARTIALLY_SUPPORTED, 0.72
        return VerificationVerdict.SUPPORTED, 0.98

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    @classmethod
    def _meaningful_tokens(cls, value: str) -> set[str]:
        return {token.casefold() for token in _TOKEN.findall(cls._normalize_text(value))}

    @classmethod
    def _text_similarity(cls, left: str, right: str) -> float:
        left_tokens = cls._meaningful_tokens(left)
        right_tokens = cls._meaningful_tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
