from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic3 import BlockType, CandidateV1, TesterContentV1, TesterQuestionV1
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c5 import (
    QuizItemType,
    QuizItemVerifierIRV1,
    QuizSolutionStepV1,
)

from liyans.domains.verification.records import build_topic4_record

_QUESTION_POINTER = re.compile(
    r"^/blocks/(?P<block>\d+)/content/questions/(?P<question>\d+)(?:/|$)"
)
_TYPE_MAP = {
    "CONCEPT": QuizItemType.CONCEPT,
    "DISCRIMINATION": QuizItemType.TRUE_FALSE,
    "CALCULATION": QuizItemType.CALCULATION,
    "ENGINEERING": QuizItemType.ENGINEERING_APPLICATION,
    "MISCONCEPTION": QuizItemType.MISCONCEPTION,
}


class QuizParseError(ValueError):
    """Raised when a frozen Topic3 quiz Claim cannot be reconstructed safely."""


@dataclass(frozen=True, slots=True)
class ParsedQuizItem:
    question: TesterQuestionV1
    verifier_ir: QuizItemVerifierIRV1
    candidate_block_ordinal: int
    question_ordinal: int


class FrozenQuizParser:
    def parse(self, claim: ClaimV1, candidate: CandidateV1) -> ParsedQuizItem:
        if candidate.candidate_id != claim.candidate_id:
            raise QuizParseError("quiz candidate identity does not match the Claim")
        if candidate.candidate_version != claim.candidate_version:
            raise QuizParseError("quiz candidate version does not match the Claim")
        if candidate.candidate_sha256 != claim.candidate_sha256:
            raise QuizParseError("quiz candidate SHA does not match the Claim")

        pointer = _QUESTION_POINTER.match(claim.json_pointer)
        if pointer is None:
            raise QuizParseError("quiz Claim pointer is not question-scoped")
        block_ordinal = int(pointer.group("block"))
        question_ordinal = int(pointer.group("question"))
        block = next((item for item in candidate.blocks if item.ordinal == block_ordinal), None)
        if block is None or block.block_id != claim.block_id or block.block_type != BlockType.QUIZ:
            raise QuizParseError("quiz Claim block binding is invalid")
        if canonical_sha256(block.content) != block.content_sha256:
            raise QuizParseError("quiz block content integrity check failed")
        try:
            content = TesterContentV1.model_validate(block.content)
            question = content.questions[question_ordinal]
        except (IndexError, ValueError) as exc:
            raise QuizParseError("quiz block does not satisfy the frozen Tester contract") from exc

        steps = [
            build_topic4_record(
                QuizSolutionStepV1,
                trace_id=claim.trace_id,
                tenant_id=claim.tenant_id,
                version_cas=1,
                created_at=claim.created_at,
                immutable=True,
                schema_version="quiz-solution-step.v1",
                ordinal=ordinal,
                explanation=explanation,
                formula_claim_id=None,
            )
            for ordinal, explanation in enumerate(question.solution_steps)
        ]
        digest = canonical_sha256(
            {
                "candidate_id": str(candidate.candidate_id),
                "candidate_version": candidate.candidate_version,
                "block_id": block.block_id,
                "question_ordinal": question_ordinal,
                "question": question.model_dump(mode="json"),
            }
        )
        verifier_ir = build_topic4_record(
            QuizItemVerifierIRV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=1,
            created_at=claim.created_at,
            immutable=True,
            schema_version="quiz-item.verifier-ir.v1",
            quiz_item_verifier_ir_id=uuid5(NAMESPACE_URL, f"liyans:c5:quiz-ir:{digest}"),
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            question_id=question.question_id,
            item_type=_TYPE_MAP[question.question_type],
            stem=question.prompt_markdown,
            options=[],
            expected_answer=question.standard_answer,
            solution_steps=steps,
            misconception_codes=question.misconception_diagnostics,
            topic1_knowledge_point_ids=question.target_kp_ids,
            difficulty=question.difficulty,
        )
        return ParsedQuizItem(question, verifier_ir, block_ordinal, question_ordinal)
