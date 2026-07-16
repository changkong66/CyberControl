from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .topic4_common import Topic4RecordV1, VerificationVerdict


class QuizItemType(StrEnum):
    CONCEPT = "CONCEPT"
    TRUE_FALSE = "TRUE_FALSE"
    CALCULATION = "CALCULATION"
    ENGINEERING_APPLICATION = "ENGINEERING_APPLICATION"
    MISCONCEPTION = "MISCONCEPTION"


class QuizOptionV1(Topic4RecordV1):
    schema_version: Literal["quiz-option.v1"]
    option_id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=4096)


class QuizSolutionStepV1(Topic4RecordV1):
    schema_version: Literal["quiz-solution-step.v1"]
    ordinal: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=8192)
    formula_claim_id: UUID | None = None


class QuizItemVerifierIRV1(Topic4RecordV1):
    schema_version: Literal["quiz-item.verifier-ir.v1"]
    quiz_item_verifier_ir_id: UUID
    verification_id: UUID
    claim_id: UUID
    question_id: str = Field(min_length=1, max_length=128)
    item_type: QuizItemType
    stem: str = Field(min_length=1, max_length=16_384)
    options: list[QuizOptionV1] = Field(default_factory=list, max_length=32)
    expected_answer: str = Field(min_length=1, max_length=8192)
    solution_steps: list[QuizSolutionStepV1] = Field(min_length=1, max_length=256)
    misconception_codes: list[str] = Field(default_factory=list, max_length=128)
    topic1_knowledge_point_ids: list[str] = Field(min_length=1, max_length=128)
    difficulty: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_item(self) -> QuizItemVerifierIRV1:
        option_ids = [option.option_id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("quiz option ids must be unique")
        ordinals = [step.ordinal for step in self.solution_steps]
        if ordinals != list(range(len(self.solution_steps))):
            raise ValueError("solution step ordinals must be contiguous")
        return self


class QuizVerificationResultV1(Topic4RecordV1):
    schema_version: Literal["quiz-verification.result.v1"]
    quiz_verification_result_id: UUID
    verification_id: UUID
    claim_id: UUID
    quiz_item_verifier_ir_id: UUID
    stem_unambiguous: bool
    answer_correct: bool | None
    solution_coherent: bool
    distractors_valid: bool | None
    diagnosis_mapping_valid: bool
    computed_answer: str | None = Field(default=None, max_length=8192)
    finding_codes: list[str] = Field(default_factory=list, max_length=256)
    evidence_ref_ids: list[UUID] = Field(default_factory=list, max_length=512)
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
