from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .common import Sha256Hex, VersionString
from .topic4_common import Topic4RecordV1, VerificationVerdict


class EquivalenceMethod(StrEnum):
    SYMBOLIC = "SYMBOLIC"
    NUMERIC = "NUMERIC"
    HYBRID = "HYBRID"


class StabilityDomain(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    DISCRETE = "DISCRETE"


class StabilityConclusion(StrEnum):
    STABLE = "STABLE"
    UNSTABLE = "UNSTABLE"
    MARGINAL = "MARGINAL"
    INDETERMINATE = "INDETERMINATE"


class FormulaIRV1(Topic4RecordV1):
    schema_version: Literal["formula-ir.v1"]
    formula_ir_id: UUID
    verification_id: UUID
    claim_id: UUID
    original_expression: str = Field(min_length=1, max_length=8192)
    canonical_expression: str = Field(min_length=1, max_length=8192)
    lhs_expression: str | None = Field(default=None, max_length=4096)
    rhs_expression: str | None = Field(default=None, max_length=4096)
    symbols: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list, max_length=256)
    units: dict[str, str] = Field(default_factory=dict)
    parser_version: VersionString
    expression_sha256: Sha256Hex


class NumericCounterexampleV1(Topic4RecordV1):
    schema_version: Literal["numeric-counterexample.v1"]
    assignments: dict[str, float]
    left_value: float
    right_value: float
    absolute_error: float = Field(ge=0.0)
    relative_error: float = Field(ge=0.0)


class FormulaEquivalenceResultV1(Topic4RecordV1):
    schema_version: Literal["formula-equivalence.result.v1"]
    formula_equivalence_result_id: UUID
    verification_id: UUID
    claim_id: UUID
    left_formula_ir_id: UUID
    right_formula_ir_id: UUID
    equivalent: bool
    method: EquivalenceMethod
    tolerance: float = Field(gt=0.0, le=0.01)
    sampled_points: int = Field(ge=0, le=100_000)
    counterexamples: list[NumericCounterexampleV1] = Field(default_factory=list, max_length=128)
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    toolchain_version: VersionString

    @model_validator(mode="after")
    def validate_equivalence(self) -> FormulaEquivalenceResultV1:
        if self.equivalent and self.counterexamples:
            raise ValueError("equivalent formulas cannot include counterexamples")
        if not self.equivalent and self.verdict == VerificationVerdict.SUPPORTED:
            raise ValueError("non-equivalent formulas cannot be supported")
        return self


class DerivationStepV1(Topic4RecordV1):
    schema_version: Literal["derivation-step.v1"]
    ordinal: int = Field(ge=0)
    formula_ir_id: UUID
    rule_name: str = Field(min_length=1, max_length=256)
    valid_from_previous: bool
    finding_code: str | None = Field(default=None, min_length=1, max_length=128)


class DerivationCheckResultV1(Topic4RecordV1):
    schema_version: Literal["derivation-check.result.v1"]
    derivation_check_result_id: UUID
    verification_id: UUID
    claim_id: UUID
    steps: list[DerivationStepV1] = Field(min_length=1, max_length=2048)
    first_invalid_ordinal: int | None = Field(default=None, ge=0)
    conclusion_formula_ir_id: UUID
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_steps(self) -> DerivationCheckResultV1:
        ordinals = [step.ordinal for step in self.steps]
        if ordinals != list(range(len(self.steps))):
            raise ValueError("derivation steps must be contiguous from zero")
        invalid = [step.ordinal for step in self.steps if not step.valid_from_previous]
        expected = invalid[0] if invalid else None
        if self.first_invalid_ordinal != expected:
            raise ValueError("first_invalid_ordinal does not match derivation steps")
        return self


class StabilityModelV1(Topic4RecordV1):
    schema_version: Literal["stability-model.v1"]
    stability_model_id: UUID
    verification_id: UUID
    claim_id: UUID
    domain: StabilityDomain
    representation: Literal["TRANSFER_FUNCTION", "STATE_SPACE", "CHARACTERISTIC_POLYNOMIAL"]
    numerator_coefficients: list[float] = Field(default_factory=list, max_length=4096)
    denominator_coefficients: list[float] = Field(default_factory=list, max_length=4096)
    state_space_matrices: dict[str, list[list[float]]] = Field(default_factory=dict)
    sample_time_seconds: float | None = Field(default=None, gt=0.0)
    assumptions: list[str] = Field(default_factory=list, max_length=256)
    model_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_model(self) -> StabilityModelV1:
        if self.domain == StabilityDomain.DISCRETE and self.sample_time_seconds is None:
            raise ValueError("discrete stability model requires sample_time_seconds")
        if self.representation == "TRANSFER_FUNCTION" and not self.denominator_coefficients:
            raise ValueError("transfer function requires denominator coefficients")
        if self.representation == "STATE_SPACE" and "A" not in self.state_space_matrices:
            raise ValueError("state-space model requires matrix A")
        return self


class StabilityCheckResultV1(Topic4RecordV1):
    schema_version: Literal["stability-check.result.v1"]
    stability_check_result_id: UUID
    verification_id: UUID
    claim_id: UUID
    stability_model_id: UUID
    conclusion: StabilityConclusion
    method: Literal["ROUTH_HURWITZ", "JURY", "ROOTS", "EIGENVALUES", "HYBRID"]
    poles: list[str] = Field(default_factory=list, max_length=4096)
    criterion_values: dict[str, float] = Field(default_factory=dict)
    counterexample: dict[str, Any] | None = None
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)


class TheoremConditionV1(Topic4RecordV1):
    schema_version: Literal["theorem-condition.v1"]
    condition_id: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=4096)
    mandatory: bool


class TheoremRegistryEntryV1(Topic4RecordV1):
    schema_version: Literal["theorem-registry.entry.v1"]
    theorem_registry_entry_id: UUID
    theorem_key: str = Field(pattern=r"^[A-Z0-9_.-]+$", min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=512)
    domain: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=16_384)
    conditions: list[TheoremConditionV1] = Field(min_length=1, max_length=256)
    conclusion: str = Field(min_length=1, max_length=8192)
    source_evidence_ref_ids: list[UUID] = Field(min_length=1, max_length=128)
    registry_version: VersionString


class TheoremConditionResultV1(Topic4RecordV1):
    schema_version: Literal["theorem-condition-result.v1"]
    condition_id: str = Field(min_length=1, max_length=128)
    satisfied: bool | None
    evidence_ref_ids: list[UUID] = Field(default_factory=list, max_length=128)
    reason: str = Field(min_length=1, max_length=4096)


class TheoremCheckResultV1(Topic4RecordV1):
    schema_version: Literal["theorem-check.result.v1"]
    theorem_check_result_id: UUID
    verification_id: UUID
    claim_id: UUID
    theorem_registry_entry_id: UUID
    condition_results: list[TheoremConditionResultV1] = Field(min_length=1, max_length=256)
    conclusion_supported: bool
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_theorem_result(self) -> TheoremCheckResultV1:
        if self.conclusion_supported and any(
            condition.satisfied is not True for condition in self.condition_results
        ):
            raise ValueError("supported theorem conclusion requires all conditions")
        return self


class FactSynthesisRequestV1(Topic4RecordV1):
    schema_version: Literal["fact-synthesis.request.v1"]
    fact_synthesis_request_id: UUID
    verification_id: UUID
    claim_id: UUID
    evidence_bundle_id: UUID
    deterministic_result_ids: list[UUID] = Field(default_factory=list, max_length=128)
    provider_alias: Literal["spark_text"]
    prompt_bundle_version: VersionString
    response_schema_version: Literal["fact-synthesis.result.v1"]
    deadline_at: AwareDatetime

    @model_validator(mode="after")
    def validate_deadline(self) -> FactSynthesisRequestV1:
        if self.deadline_at <= self.created_at:
            raise ValueError("fact synthesis deadline must be after creation")
        return self


class FactSynthesisResultV1(Topic4RecordV1):
    schema_version: Literal["fact-synthesis.result.v1"]
    fact_synthesis_result_id: UUID
    fact_synthesis_request_id: UUID
    verification_id: UUID
    claim_id: UUID
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    supported_statement: str | None = Field(default=None, max_length=32_768)
    contradiction_summary: str | None = Field(default=None, max_length=16_384)
    evidence_ref_ids: list[UUID] = Field(default_factory=list, max_length=512)
    provider_request_id: str = Field(min_length=1, max_length=256)
    provider_response_sha256: Sha256Hex
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def require_authoritative_evidence(self) -> FactSynthesisResultV1:
        if (
            self.verdict
            in {
                VerificationVerdict.SUPPORTED,
                VerificationVerdict.PARTIALLY_SUPPORTED,
            }
            and not self.evidence_ref_ids
        ):
            raise ValueError("positive fact synthesis requires authoritative evidence")
        return self
