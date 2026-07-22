from __future__ import annotations

import inspect
import json
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import sympy as sp
from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_c3 import StabilityConclusion, StabilityDomain
from liyans_contracts.topic4_common import VerificationVerdict
from sympy.core.function import AppliedUndef
from sympy.polys.polyerrors import PolynomialError

from liyans.domains.verification.execution import ModuleExecutionContext, ModuleFinding
from liyans.domains.verification.records import record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore

from .fact import ClaimFactVerifier, FactCoverageResult
from .formula import (
    DerivationChecker,
    FormulaEquivalenceEngine,
    FormulaIRBuilder,
    FormulaParseError,
    FormulaSecurityError,
    ParsedFormula,
    SafeFormulaParser,
)
from .numeric import NumericFactVerifier, NumericVerificationSummary
from .semantic import SemanticClaimVerifierV2, SemanticVerifierPolicy
from .stability import StabilityAnalyzer, StabilityModelBuilder
from .theorem import (
    EvidenceConditionResolver,
    TheoremRegistry,
    TheoremVerifier,
)

C3_HANDLER_VERSION = "c3-academic-handler-v1"
C3_HANDLER_VERSION_V2 = "c3-academic-handler-v2"
_STABILITY_SIGNAL = re.compile(
    r"(?:stable|stability|unstable|hurwitz|routh|jury|pole|"
    r"\u7a33\u5b9a|\u4e0d\u7a33\u5b9a|\u7279\u5f81\u6839|\u6781\u70b9)",
    re.IGNORECASE,
)
_UNSTABLE_SIGNAL = re.compile(r"(?:unstable|\u4e0d\u7a33\u5b9a)", re.IGNORECASE)
_MARGINAL_SIGNAL = re.compile(
    r"(?:marginal(?:ly)?\s+stable|critical(?:ly)?\s+stable|\u4e34\u754c\u7a33\u5b9a)",
    re.IGNORECASE,
)
_THEOREM_SIGNAL = re.compile(
    r"(?:theorem|lemma|corollary|criterion|condition|"
    r"\u5b9a\u7406|\u5f15\u7406|\u5224\u636e|\u6761\u4ef6)",
    re.IGNORECASE,
)


class AcademicEvidenceSource(Protocol):
    async def load(
        self,
        *,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> Sequence[EvidenceRefV1]: ...


class AcademicFactVerifier(Protocol):
    def verify(
        self,
        claim: ClaimV1,
        evidence: tuple[EvidenceRefV1, ...],
        *,
        tenant_id: str | None = None,
    ) -> FactCoverageResult: ...


EvidenceLoader = Callable[
    [str, UUID, UUID],
    Awaitable[Sequence[EvidenceRefV1]] | Sequence[EvidenceRefV1],
]


@dataclass(frozen=True, slots=True)
class C3HandlerPolicy:
    max_formula_count: int = 128
    max_evidence_count: int = 512
    max_artifact_bytes: int = 33_554_432

    def __post_init__(self) -> None:
        if not 1 <= self.max_formula_count <= 2048:
            raise ValueError("max_formula_count must be between 1 and 2048")
        if not 1 <= self.max_evidence_count <= 4096:
            raise ValueError("max_evidence_count must be between 1 and 4096")
        if not 1 <= self.max_artifact_bytes <= 33_554_432:
            raise ValueError("max_artifact_bytes must be between 1 and 33554432")


@dataclass(frozen=True, slots=True)
class _FormulaAnalysis:
    records: tuple[dict[str, object], ...]
    verdict: VerificationVerdict
    confidence: float
    finding_codes: tuple[str, ...]


class C3AcademicHandler:
    """Deterministic C3 handler compatible with the frozen C1 executor."""

    def __init__(
        self,
        evidence_source: AcademicEvidenceSource | EvidenceLoader,
        artifact_store: ArtifactObjectStore,
        *,
        policy: C3HandlerPolicy | None = None,
        theorem_registry: TheoremRegistry | None = None,
        fact_verifier: AcademicFactVerifier | None = None,
        handler_version: str = C3_HANDLER_VERSION,
    ) -> None:
        if not handler_version or len(handler_version) > 128:
            raise ValueError("C3 handler version must contain 1 to 128 characters")
        self._evidence_source = evidence_source
        self._artifact_store = artifact_store
        self._policy = policy or C3HandlerPolicy()
        self._parser = SafeFormulaParser()
        self._formula_builder = FormulaIRBuilder(self._parser)
        self._equivalence = FormulaEquivalenceEngine(self._parser)
        self._derivation = DerivationChecker(self._equivalence)
        self._stability_builder = StabilityModelBuilder()
        self._stability = StabilityAnalyzer()
        self._numeric = NumericFactVerifier()
        self._facts = fact_verifier or ClaimFactVerifier()
        self._handler_version = handler_version
        self._theorem_registry = theorem_registry or TheoremRegistry()
        self._theorem_resolver = EvidenceConditionResolver()
        self._theorem_verifier = TheoremVerifier()

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        claim = context.claim
        if claim.tenant_id != self._claim_tenant(context):
            return await self._error_finding(
                context,
                VerificationVerdict.UNSAFE,
                "C3_TENANT_CONTEXT_MISMATCH",
            )
        try:
            evidence = await self._load_evidence(claim)
            self._validate_evidence(claim, evidence)
            formula_analysis = self._analyze_formulas(claim, context, evidence)
            fact_result = self._facts.verify(claim, evidence)
            numeric_result = self._numeric.verify(claim.normalized_statement, evidence)
            stability_records, stability_verdict, stability_confidence, stability_codes = (
                self._analyze_stability(claim, context)
            )
            theorem_records, theorem_verdict, theorem_confidence, theorem_codes = (
                self._analyze_theorem(claim, context, evidence)
            )
            verdict, confidence, finding_codes = self._aggregate(
                formula_analysis,
                fact_result,
                numeric_result,
                stability_verdict,
                stability_confidence,
                stability_codes,
                theorem_verdict,
                theorem_confidence,
                theorem_codes,
            )
            document = self._document(
                context,
                evidence,
                formula_analysis,
                fact_result,
                numeric_result,
                stability_records,
                theorem_records,
                verdict,
                confidence,
                finding_codes,
            )
            artifact = await self._write_artifact(context, document)
            evidence_ids = tuple(ref.evidence_ref_id for ref in evidence)
            if verdict == VerificationVerdict.SUPPORTED and not evidence_ids:
                verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
                finding_codes = tuple(sorted(set(finding_codes) | {"C3_EVIDENCE_REQUIRED"}))
            return ModuleFinding(
                verdict=verdict,
                confidence=confidence,
                evidence_ref_ids=evidence_ids,
                finding_codes=finding_codes,
                result_artifact=artifact,
                result_sha256=artifact.sha256,
                deterministic=True,
            )
        except (FormulaParseError, FormulaSecurityError, ValueError) as exc:
            code = self._error_code(exc)
            return await self._error_finding(context, VerificationVerdict.UNSAFE, code)
        except Exception:
            return await self._error_finding(
                context,
                VerificationVerdict.ERROR,
                "C3_HANDLER_UNEXPECTED_ERROR",
            )

    @staticmethod
    def _claim_tenant(context: ModuleExecutionContext) -> str:
        if context.claim.tenant_id != context.dispatch_item.tenant_id:
            return ""
        return context.dispatch_item.tenant_id

    async def _load_evidence(self, claim: ClaimV1) -> tuple[EvidenceRefV1, ...]:
        source = self._evidence_source
        if hasattr(source, "load"):
            result = source.load(
                tenant_id=claim.tenant_id,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )
        else:
            result = source(
                tenant_id=claim.tenant_id,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )
        if inspect.isawaitable(result):
            result = await result
        evidence = tuple(result)
        if len(evidence) > self._policy.max_evidence_count:
            raise ValueError("C3 evidence count exceeds the safety limit")
        return evidence

    @staticmethod
    def _validate_evidence(claim: ClaimV1, evidence: tuple[EvidenceRefV1, ...]) -> None:
        seen: set[UUID] = set()
        for ref in evidence:
            if ref.tenant_id != claim.tenant_id:
                raise ValueError("C3 evidence crosses tenant boundaries")
            if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
                raise ValueError("C3 evidence is not bound to the claim")
            if ref.trace_id != claim.trace_id or not record_integrity_valid(ref):
                raise ValueError("C3 evidence record integrity check failed")
            if ref.evidence_ref_id in seen:
                raise ValueError("C3 evidence contains duplicate references")
            if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
                raise ValueError("C3 evidence excerpt integrity check failed")
            seen.add(ref.evidence_ref_id)

    def _analyze_formulas(
        self,
        claim: ClaimV1,
        context: ModuleExecutionContext,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> _FormulaAnalysis:
        expressions = self._parser.extract(claim.normalized_statement)
        if len(expressions) > self._policy.max_formula_count:
            raise ValueError("C3 formula count exceeds the safety limit")
        if not expressions:
            return _FormulaAnalysis((), VerificationVerdict.NOT_APPLICABLE, 1.0, ())
        formulas = tuple(
            self._formula_builder.build(
                expression,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
                trace_id=context.claim.trace_id,
                tenant_id=claim.tenant_id,
                created_at=claim.created_at,
            )
            for expression in expressions
        )
        records: list[dict[str, object]] = {
            "formula_ir": [record.model_dump(mode="json") for record in formulas]
        }
        verdict = VerificationVerdict.SUPPORTED
        confidence = 0.92
        codes: set[str] = set()
        if len(formulas) >= 2:
            derivation = self._derivation.check(
                formulas,
                rule_names=None,
                trace_id=claim.trace_id,
                tenant_id=claim.tenant_id,
                created_at=claim.created_at,
            )
            records["derivation"] = derivation.model_dump(mode="json")
            verdict = derivation.verdict
            confidence = derivation.confidence
            if derivation.first_invalid_ordinal is not None:
                codes.add("C3_DERIVATION_INVALID")
        if not evidence:
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
            confidence = min(confidence, 0.35)
            codes.add("C3_FORMULA_EVIDENCE_MISSING")
        return _FormulaAnalysis(tuple(records.items()), verdict, confidence, tuple(sorted(codes)))

    def _analyze_stability(
        self,
        claim: ClaimV1,
        context: ModuleExecutionContext,
    ) -> tuple[tuple[dict[str, object], ...], VerificationVerdict, float, tuple[str, ...]]:
        if not _STABILITY_SIGNAL.search(claim.normalized_statement):
            return (), VerificationVerdict.NOT_APPLICABLE, 1.0, ()
        expressions = self._parser.extract(claim.normalized_statement)
        models = []
        for expression in expressions:
            parsed = self._parser.parse(expression)
            symbol_name = "z" if "z" in parsed.symbols else "s" if "s" in parsed.symbols else None
            if symbol_name is None:
                continue
            symbol = next(
                (item for item in parsed.residual.free_symbols if str(item) == symbol_name), None
            )
            if symbol is None:
                continue
            coefficients = self._stability_coefficients(parsed, symbol)
            if coefficients is None:
                continue
            representation, numerator, denominator = coefficients
            models.append(
                self._stability_builder.build(
                    verification_id=claim.verification_id,
                    claim_id=claim.claim_id,
                    trace_id=claim.trace_id,
                    tenant_id=claim.tenant_id,
                    created_at=claim.created_at,
                    domain=(
                        StabilityDomain.DISCRETE
                        if symbol_name == "z"
                        else StabilityDomain.CONTINUOUS
                    ),
                    representation=representation,
                    numerator_coefficients=numerator,
                    denominator_coefficients=denominator,
                    sample_time_seconds=1.0 if symbol_name == "z" else None,
                    assumptions=["NORMALIZED_SAMPLE_PERIOD"] if symbol_name == "z" else [],
                )
            )
        if not models:
            return (
                (),
                VerificationVerdict.INSUFFICIENT_EVIDENCE,
                0.25,
                ("C3_STABILITY_MODEL_UNRESOLVED",),
            )
        records: list[dict[str, object]] = []
        verdicts: list[VerificationVerdict] = []
        confidences: list[float] = []
        for model in models[: self._policy.max_formula_count]:
            result = self._stability.analyze(
                model,
                trace_id=context.claim.trace_id,
                tenant_id=claim.tenant_id,
                created_at=claim.created_at,
                expected_conclusion=self._expected_stability(claim.normalized_statement),
            )
            records.append(
                {
                    "model": model.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                }
            )
            verdicts.append(result.verdict)
            confidences.append(result.confidence)
        verdict = self._strictest_verdict(tuple(verdicts))
        codes = {
            "C3_STABILITY_CONTRADICTED"
            if verdict == VerificationVerdict.CONTRADICTED
            else "C3_STABILITY_INDETERMINATE"
            if verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
            else "C3_STABILITY_MARGINAL"
            if verdict == VerificationVerdict.PARTIALLY_SUPPORTED
            else ""
        }
        codes.discard("")
        return tuple(records), verdict, min(confidences), tuple(sorted(codes))

    @classmethod
    def _stability_coefficients(
        cls,
        parsed: ParsedFormula,
        symbol: sp.Symbol,
    ) -> tuple[str, list[float], list[float]] | None:
        transfer_expression: sp.Expr | None = None
        parsed_lhs = getattr(parsed, "lhs", None)
        parsed_rhs = getattr(parsed, "rhs", None)
        parsed_expression = getattr(parsed, "expression", None)
        parsed_relation = getattr(parsed, "relation", None)

        if parsed_rhs is None and isinstance(parsed_expression, sp.Expr):
            try:
                numerator_expression, denominator_expression = sp.fraction(
                    sp.cancel(parsed_expression)
                )
            except (PolynomialError, TypeError, ValueError):
                return None
            if symbol in denominator_expression.free_symbols:
                transfer_expression = numerator_expression / denominator_expression
        elif (
            parsed_relation == "="
            and isinstance(parsed_lhs, sp.Expr)
            and isinstance(parsed_rhs, sp.Expr)
        ):
            left_is_function = bool(parsed_lhs.atoms(AppliedUndef))
            right_is_function = bool(parsed_rhs.atoms(AppliedUndef))
            if left_is_function and not right_is_function:
                transfer_expression = parsed_rhs
            elif right_is_function and not left_is_function:
                transfer_expression = parsed_lhs

        if transfer_expression is not None:
            numerator_expression, denominator_expression = sp.fraction(
                sp.cancel(transfer_expression)
            )
            try:
                numerator_polynomial = sp.Poly(numerator_expression, symbol)
                denominator_polynomial = sp.Poly(denominator_expression, symbol)
            except (PolynomialError, TypeError, ValueError):
                return None
            if denominator_polynomial.degree() < 1:
                return None
            numerator = cls._real_coefficients(numerator_polynomial)
            denominator = cls._real_coefficients(denominator_polynomial)
            if numerator is None or denominator is None:
                return None
            return "TRANSFER_FUNCTION", numerator, denominator

        parsed_residual = getattr(parsed, "residual", None)
        if not isinstance(parsed_residual, sp.Expr):
            return None
        try:
            characteristic = sp.Poly(parsed_residual, symbol)
        except (PolynomialError, TypeError, ValueError):
            return None
        denominator = cls._real_coefficients(characteristic)
        if denominator is None:
            return None
        return "CHARACTERISTIC_POLYNOMIAL", [], denominator

    @staticmethod
    def _real_coefficients(polynomial: sp.Poly) -> list[float] | None:
        coefficients = polynomial.all_coeffs()
        if not coefficients or not all(coefficient.is_number for coefficient in coefficients):
            return None
        try:
            values = [float(coefficient) for coefficient in coefficients]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in values):
            return None
        return values

    @staticmethod
    def _expected_stability(statement: str) -> StabilityConclusion:
        if _UNSTABLE_SIGNAL.search(statement):
            return StabilityConclusion.UNSTABLE
        if _MARGINAL_SIGNAL.search(statement):
            return StabilityConclusion.MARGINAL
        return StabilityConclusion.STABLE

    def _analyze_theorem(
        self,
        claim: ClaimV1,
        context: ModuleExecutionContext,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> tuple[tuple[dict[str, object], ...], VerificationVerdict, float, tuple[str, ...]]:
        if not _THEOREM_SIGNAL.search(claim.normalized_statement):
            return (), VerificationVerdict.NOT_APPLICABLE, 1.0, ()
        matches = [
            entry
            for entry in self._theorem_registry.list_for_tenant(claim.tenant_id)
            if entry.theorem_key.casefold() in claim.normalized_statement.casefold()
            or entry.name.casefold() in claim.normalized_statement.casefold()
        ]
        if not matches:
            return (), VerificationVerdict.INSUFFICIENT_EVIDENCE, 0.25, ("C3_THEOREM_UNREGISTERED",)
        records: list[dict[str, object]] = []
        verdicts: list[VerificationVerdict] = []
        confidences: list[float] = []
        for entry in matches[:8]:
            assessments = self._theorem_resolver.resolve(
                entry,
                evidence,
                tenant_id=claim.tenant_id,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )
            result = self._theorem_verifier.check(
                entry,
                assessments,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
                trace_id=context.claim.trace_id,
                tenant_id=claim.tenant_id,
                created_at=claim.created_at,
            )
            records.append(
                {
                    "entry": entry.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                }
            )
            verdicts.append(result.verdict)
            confidences.append(result.confidence)
        return tuple(records), self._strictest_verdict(tuple(verdicts)), min(confidences), ()

    def _aggregate(
        self,
        formula: _FormulaAnalysis,
        facts: FactCoverageResult,
        numeric: NumericVerificationSummary,
        stability_verdict: VerificationVerdict,
        stability_confidence: float,
        stability_codes: tuple[str, ...],
        theorem_verdict: VerificationVerdict,
        theorem_confidence: float,
        theorem_codes: tuple[str, ...],
    ) -> tuple[VerificationVerdict, float, tuple[str, ...]]:
        verdicts = [
            formula.verdict,
            facts.verdict,
            numeric.verdict,
            stability_verdict,
            theorem_verdict,
        ]
        relevant = [
            verdict for verdict in verdicts if verdict != VerificationVerdict.NOT_APPLICABLE
        ]
        if VerificationVerdict.UNSAFE in relevant:
            verdict = VerificationVerdict.UNSAFE
        elif VerificationVerdict.CONTRADICTED in relevant:
            verdict = VerificationVerdict.CONTRADICTED
        elif VerificationVerdict.ERROR in relevant:
            verdict = VerificationVerdict.ERROR
        elif VerificationVerdict.INSUFFICIENT_EVIDENCE in relevant:
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
        elif VerificationVerdict.PARTIALLY_SUPPORTED in relevant:
            verdict = VerificationVerdict.PARTIALLY_SUPPORTED
        else:
            verdict = (
                VerificationVerdict.SUPPORTED if relevant else VerificationVerdict.NOT_APPLICABLE
            )
        confidences = [formula.confidence, facts.confidence, numeric.confidence]
        if stability_verdict != VerificationVerdict.NOT_APPLICABLE:
            confidences.append(stability_confidence)
        if theorem_verdict != VerificationVerdict.NOT_APPLICABLE:
            confidences.append(theorem_confidence)
        codes = set(formula.finding_codes) | set(facts.finding_codes) | set(numeric.finding_codes)
        codes.update(stability_codes)
        codes.update(theorem_codes)
        return verdict, min(confidences, default=0.0), tuple(sorted(codes))

    @staticmethod
    def _strictest_verdict(verdicts: tuple[VerificationVerdict, ...]) -> VerificationVerdict:
        priority = {
            VerificationVerdict.UNSAFE: 6,
            VerificationVerdict.CONTRADICTED: 5,
            VerificationVerdict.ERROR: 4,
            VerificationVerdict.INSUFFICIENT_EVIDENCE: 3,
            VerificationVerdict.PARTIALLY_SUPPORTED: 2,
            VerificationVerdict.SUPPORTED: 1,
            VerificationVerdict.NOT_APPLICABLE: 0,
        }
        return max(
            verdicts,
            key=lambda verdict: priority[verdict],
            default=VerificationVerdict.NOT_APPLICABLE,
        )

    def _document(
        self,
        context: ModuleExecutionContext,
        evidence: tuple[EvidenceRefV1, ...],
        formula: _FormulaAnalysis,
        facts: FactCoverageResult,
        numeric: NumericVerificationSummary,
        stability: tuple[dict[str, object], ...],
        theorem: tuple[dict[str, object], ...],
        verdict: VerificationVerdict,
        confidence: float,
        finding_codes: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "schema_version": "c3-academic-finding.v1",
            "handler_version": self._handler_version,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "evidence_ref_ids": [str(ref.evidence_ref_id) for ref in evidence],
            "formula_analysis": dict(formula.records),
            "fact_coverage": {
                "verdict": facts.verdict.value,
                "confidence": facts.confidence,
                "coverage_score": facts.coverage_score,
                "supporting_evidence_ref_ids": [
                    str(item) for item in facts.supporting_evidence_ref_ids
                ],
                "contradicting_evidence_ref_ids": [
                    str(item) for item in facts.contradicting_evidence_ref_ids
                ],
            },
            "numeric_analysis": {
                "verdict": numeric.verdict.value,
                "confidence": numeric.confidence,
                "finding_codes": list(numeric.finding_codes),
                "comparisons": [
                    {
                        "asserted": {
                            "source_text": comparison.asserted.source_text,
                            "operator": comparison.asserted.operator,
                            "value": comparison.asserted.value,
                            "unit": comparison.asserted.unit,
                            "canonical_value": comparison.asserted.canonical_value,
                            "canonical_unit": comparison.asserted.canonical_unit,
                            "span_start": comparison.asserted.span_start,
                            "span_end": comparison.asserted.span_end,
                        },
                        "authoritative": (
                            None
                            if comparison.authoritative is None
                            else {
                                "source_text": comparison.authoritative.source_text,
                                "operator": comparison.authoritative.operator,
                                "value": comparison.authoritative.value,
                                "unit": comparison.authoritative.unit,
                                "canonical_value": comparison.authoritative.canonical_value,
                                "canonical_unit": comparison.authoritative.canonical_unit,
                                "span_start": comparison.authoritative.span_start,
                                "span_end": comparison.authoritative.span_end,
                            }
                        ),
                        "verdict": comparison.verdict.value,
                        "confidence": comparison.confidence,
                        "absolute_error": comparison.absolute_error,
                        "relative_error": comparison.relative_error,
                        "finding_code": comparison.finding_code,
                        "evidence_ref_id": comparison.evidence_ref_id,
                    }
                    for comparison in numeric.comparisons
                ],
            },
            "stability_analysis": list(stability),
            "theorem_analysis": list(theorem),
            "verdict": verdict.value,
            "confidence": confidence,
            "finding_codes": list(finding_codes),
        }

    async def _write_artifact(
        self,
        context: ModuleExecutionContext,
        document: dict[str, object],
    ) -> ArtifactObjectRefV1:
        content = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest = canonical_sha256(document)
        if len(content) > self._policy.max_artifact_bytes:
            raise ValueError("C3 result artifact exceeds the safety limit")
        object_key = f"c3/{context.claim.verification_id}/{context.claim.claim_id}/{digest}.json"
        stored = await self._artifact_store.put(
            tenant_id=context.claim.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise ValueError("C3 result artifact metadata failed integrity validation")
        return ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=object_key,
            media_type="application/json",
            content_encoding="identity",
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=context.claim.created_at,
        )

    async def _error_finding(
        self,
        context: ModuleExecutionContext,
        verdict: VerificationVerdict,
        finding_code: str,
    ) -> ModuleFinding:
        document = {
            "schema_version": "c3-academic-finding.v1",
            "handler_version": self._handler_version,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "verdict": verdict.value,
            "confidence": 0.0,
            "finding_codes": [finding_code],
        }
        artifact = await self._write_artifact(context, document)
        return ModuleFinding(
            verdict=verdict,
            confidence=0.0,
            evidence_ref_ids=(),
            finding_codes=(finding_code,),
            result_artifact=artifact,
            result_sha256=artifact.sha256,
            deterministic=True,
        )

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, FormulaSecurityError):
            return "C3_FORMULA_SECURITY_POLICY"
        if isinstance(error, FormulaParseError):
            return "C3_FORMULA_PARSE_FAILED"
        message = str(error).casefold()
        if "tenant" in message:
            return "C3_TENANT_ISOLATION_FAILED"
        if "evidence" in message:
            return "C3_EVIDENCE_INTEGRITY_FAILED"
        return "C3_HANDLER_VALIDATION_FAILED"


class C3AcademicHandlerV2(C3AcademicHandler):
    """Versioned semantic extension; direct C3AcademicHandler callers remain on v1."""

    def __init__(
        self,
        evidence_source: AcademicEvidenceSource | EvidenceLoader,
        artifact_store: ArtifactObjectStore,
        *,
        policy: C3HandlerPolicy | None = None,
        theorem_registry: TheoremRegistry | None = None,
        semantic_policy: SemanticVerifierPolicy | None = None,
    ) -> None:
        super().__init__(
            evidence_source,
            artifact_store,
            policy=policy,
            theorem_registry=theorem_registry,
            fact_verifier=SemanticClaimVerifierV2(semantic_policy),
            handler_version=C3_HANDLER_VERSION_V2,
        )

    def _analyze_stability(
        self,
        claim: ClaimV1,
        context: ModuleExecutionContext,
    ) -> tuple[tuple[dict[str, object], ...], VerificationVerdict, float, tuple[str, ...]]:
        if not _STABILITY_SIGNAL.search(claim.normalized_statement):
            return (), VerificationVerdict.NOT_APPLICABLE, 1.0, ()
        if not self._has_resolvable_stability_model(claim.normalized_statement):
            return (), VerificationVerdict.NOT_APPLICABLE, 1.0, ()
        return super()._analyze_stability(claim, context)

    def _has_resolvable_stability_model(self, statement: str) -> bool:
        for expression in self._parser.extract(statement):
            parsed = self._parser.parse(expression)
            symbol_name = "z" if "z" in parsed.symbols else "s" if "s" in parsed.symbols else None
            if symbol_name is None:
                continue
            symbol = next(
                (item for item in parsed.residual.free_symbols if str(item) == symbol_name), None
            )
            if symbol is not None and self._stability_coefficients(parsed, symbol) is not None:
                return True
        return False

    def _analyze_theorem(
        self,
        claim: ClaimV1,
        context: ModuleExecutionContext,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> tuple[tuple[dict[str, object], ...], VerificationVerdict, float, tuple[str, ...]]:
        if not _THEOREM_SIGNAL.search(claim.normalized_statement):
            return (), VerificationVerdict.NOT_APPLICABLE, 1.0, ()
        matches = [
            entry
            for entry in self._theorem_registry.list_for_tenant(claim.tenant_id)
            if entry.theorem_key.casefold() in claim.normalized_statement.casefold()
            or entry.name.casefold() in claim.normalized_statement.casefold()
        ]
        if not matches:
            return (), VerificationVerdict.NOT_APPLICABLE, 1.0, ()
        return super()._analyze_theorem(claim, context, evidence)
