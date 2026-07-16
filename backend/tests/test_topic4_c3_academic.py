from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import (
    ClaimV1,
    ExtractionMethod,
    ModuleDispatchItemV1,
    ModuleDispatchPlanV1,
)
from liyans_contracts.topic4_c2 import EvidenceRefV1, SourceAuthorityTier
from liyans_contracts.topic4_c3 import StabilityConclusion, StabilityDomain
from liyans_contracts.topic4_common import ClaimKind, VerificationModule, VerificationVerdict

from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.academic.evidence_source import PostgresAcademicEvidenceSource
from liyans.domains.academic.fact import ClaimFactVerifier
from liyans.domains.academic.formula import (
    DerivationChecker,
    FormulaEquivalenceEngine,
    FormulaIRBuilder,
    FormulaSecurityError,
    SafeFormulaParser,
)
from liyans.domains.academic.handler import C3AcademicHandler
from liyans.domains.academic.numeric import NumericFactVerifier
from liyans.domains.academic.stability import StabilityAnalyzer, StabilityModelBuilder
from liyans.domains.academic.theorem import (
    EvidenceConditionResolver,
    TheoremRegistryBuilder,
    TheoremVerifier,
)
from liyans.domains.verification.execution import BoundedModuleExecutor, ModuleExecutionContext
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
TENANT = "tenant-a"
TRACE = "a" * 32


def _claim(
    statement: str,
    *,
    tenant_id: str = TENANT,
    claim_kind: ClaimKind = ClaimKind.FORMULA,
) -> ClaimV1:
    verification_id = uuid4()
    claim_id = uuid4()
    return build_topic4_record(
        ClaimV1,
        trace_id=TRACE,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="claim.v1",
        claim_id=claim_id,
        verification_id=verification_id,
        candidate_id=uuid4(),
        candidate_version=1,
        candidate_sha256="b" * 64,
        block_id="block-1",
        claim_kind=claim_kind,
        claim_subtype="academic",
        statement=statement,
        normalized_statement=statement,
        json_pointer="/content",
        ordinal=0,
        source_span_start=0,
        source_span_end=len(statement),
        claim_sha256=canonical_sha256(statement),
        extraction_method=ExtractionMethod.DETERMINISTIC,
        dependent_claim_ids=[],
    )


def _evidence(claim: ClaimV1, excerpt: str, *, tenant_id: str | None = None) -> EvidenceRefV1:
    owner = tenant_id or claim.tenant_id
    return build_topic4_record(
        EvidenceRefV1,
        trace_id=claim.trace_id,
        tenant_id=owner,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="evidence.ref.v1",
        evidence_ref_id=uuid4(),
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        knowledge_base_version_id=uuid4(),
        knowledge_chunk_id=uuid4(),
        source_document_id=uuid4(),
        source_document_version_id=uuid4(),
        section_id="section-1",
        citation="Authoritative automatic control textbook",
        excerpt=excerpt,
        excerpt_sha256=canonical_sha256(excerpt),
        bm25_score=1.0,
        vector_score=1.0,
        graph_score=1.0,
        formula_score=1.0,
        fused_score=1.0,
        source_authority_tier=SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK,
    )


def _context(claim: ClaimV1) -> ModuleExecutionContext:
    item = build_topic4_record(
        ModuleDispatchItemV1,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="module-dispatch-item.v1",
        dispatch_item_id=uuid4(),
        claim_id=claim.claim_id,
        module=VerificationModule.C3_ACADEMIC,
        required=True,
        priority=1,
        dependency_item_ids=[],
        timeout_ms=8000,
        max_attempts=1,
    )
    return ModuleExecutionContext(
        verification_id=claim.verification_id,
        dispatch_plan_id=uuid4(),
        dispatch_item=item,
        claim=claim,
        module_run_id=uuid4(),
        attempt=1,
        deadline_at=NOW.replace(hour=13),
    )


def test_formula_parser_extracts_prose_and_rejects_code_execution_tokens() -> None:
    parser = SafeFormulaParser()
    assert parser.extract("The equation is x^2 + 2*x + 1 = 0 when x is real.") == (
        "x^2 + 2*x + 1 = 0",
    )
    assert parser.extract("The characteristic polynomial s^2 + 3*s + 2 has stable poles.") == (
        "s^2 + 3*s + 2",
    )
    with pytest.raises(FormulaSecurityError):
        parser.parse("__import__(open(x))")
    with pytest.raises(FormulaSecurityError):
        parser.parse("x^129")


def test_formula_equivalence_and_derivation_are_deterministic() -> None:
    claim = _claim("x^2 + 2*x + 1 = 0")
    builder = FormulaIRBuilder()
    first = builder.build(
        "x^2 + 2*x + 1",
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    second = builder.build(
        "(x+1)^2",
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    result = FormulaEquivalenceEngine().compare(
        first,
        second,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert result.equivalent is True
    assert result.verdict == VerificationVerdict.SUPPORTED
    derivation = DerivationChecker().check(
        (first, second),
        rule_names=("EXPAND", "FACTOR"),
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert derivation.first_invalid_ordinal is None


@pytest.mark.parametrize(
    ("coefficients", "expected"),
    [([1, 3, 2], "STABLE"), ([1, -1], "UNSTABLE"), ([1, 0, 1], "MARGINAL")],
)
def test_stability_analyzer_classifies_continuous_poles(
    coefficients: list[float], expected: str
) -> None:
    claim = _claim("stability")
    model = StabilityModelBuilder().build(
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        domain=StabilityDomain.CONTINUOUS,
        representation="CHARACTERISTIC_POLYNOMIAL",
        denominator_coefficients=coefficients,
    )
    result = StabilityAnalyzer().analyze(
        model,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert result.conclusion.value == expected


def test_stability_analyzer_classifies_discrete_and_state_space_models() -> None:
    claim = _claim("discrete stability")
    builder = StabilityModelBuilder()
    discrete = builder.build(
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        domain=StabilityDomain.DISCRETE,
        representation="CHARACTERISTIC_POLYNOMIAL",
        denominator_coefficients=[1, -0.5],
        sample_time_seconds=0.1,
    )
    state_space = builder.build(
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        domain=StabilityDomain.CONTINUOUS,
        representation="STATE_SPACE",
        state_space_matrices={"A": [[-1.0, 0.0], [0.0, -2.0]]},
    )
    analyzer = StabilityAnalyzer()
    assert (
        analyzer.analyze(
            discrete, trace_id=TRACE, tenant_id=TENANT, created_at=NOW
        ).conclusion.value
        == "STABLE"
    )
    assert (
        analyzer.analyze(
            state_space, trace_id=TRACE, tenant_id=TENANT, created_at=NOW
        ).conclusion.value
        == "STABLE"
    )


def test_numeric_fact_verifier_normalizes_units() -> None:
    claim = _claim("response time = 50ms", claim_kind=ClaimKind.TEXT)
    evidence = (_evidence(claim, "The measured response time = 0.05s."),)
    result = NumericFactVerifier().verify(claim.normalized_statement, evidence)
    assert result.verdict == VerificationVerdict.SUPPORTED
    assert result.comparisons[0].absolute_error == pytest.approx(0.0)


def test_claim_fact_verifier_rejects_cross_tenant_evidence() -> None:
    claim = _claim("closed loop stability is supported")
    foreign = _evidence(claim, "closed loop stability is supported", tenant_id="tenant-b")
    with pytest.raises(ValueError, match="tenant"):
        ClaimFactVerifier().verify(claim, (foreign,))


def test_theorem_registry_resolves_conditions_and_produces_supported_result() -> None:
    claim = _claim("Routh theorem: all poles are in the left half plane")
    evidence = _evidence(claim, "Routh theorem requires all poles in the left half plane.")
    entry = TheoremRegistryBuilder().build(
        theorem_key="ROUTH_HURWITZ",
        name="Routh theorem",
        domain="CONTROL",
        statement="A polynomial is Hurwitz when all poles are in the left half plane.",
        conditions=(("POLES_LEFT", "all poles in the left half plane", True),),
        conclusion="The polynomial is Hurwitz.",
        source_evidence_ref_ids=(evidence.evidence_ref_id,),
        registry_version="c3-test-1",
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assessments = EvidenceConditionResolver().resolve(
        entry,
        (evidence,),
        tenant_id=TENANT,
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
    )
    result = TheoremVerifier().check(
        entry,
        assessments,
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert result.conclusion_supported is True
    assert result.verdict == VerificationVerdict.SUPPORTED


@pytest.mark.asyncio
async def test_c3_handler_writes_hashed_artifact_and_returns_supported_finding(
    tmp_path: Path,
) -> None:
    statement = (
        "The characteristic polynomial s^2 + 3*s + 2 has all poles in the "
        "left half-plane and is stable."
    )
    claim = _claim(statement)
    evidence = (
        _evidence(claim, "The characteristic polynomial s^2 + 3*s + 2 has roots -1 and -2."),
    )

    async def load(
        *, tenant_id: str, verification_id: UUID, claim_id: UUID
    ) -> tuple[EvidenceRefV1, ...]:
        assert tenant_id == TENANT
        assert verification_id == claim.verification_id
        assert claim_id == claim.claim_id
        return evidence

    store = FileSystemArtifactObjectStore(tmp_path)
    handler = C3AcademicHandler(load, store)
    finding = await handler.verify(_context(claim))
    assert finding.verdict == VerificationVerdict.SUPPORTED
    assert finding.deterministic is True
    assert finding.result_artifact.sha256 == finding.result_sha256
    assert finding.result_artifact.object_key.startswith("c3/")
    assert finding.result_artifact.object_key.endswith(f"{finding.result_sha256}.json")


@pytest.mark.asyncio
async def test_c3_handler_extracts_transfer_function_and_preserves_numeric_evidence(
    tmp_path: Path,
) -> None:
    statement = "The transfer function G(s) = 1/(s+1) is stable with response time = 50ms."
    claim = _claim(statement)
    evidence = (
        _evidence(
            claim,
            "The transfer function G(s) = 1/(s+1) is stable with response time = 0.05s.",
        ),
    )

    async def load(
        *, tenant_id: str, verification_id: UUID, claim_id: UUID
    ) -> tuple[EvidenceRefV1, ...]:
        assert tenant_id == claim.tenant_id
        assert verification_id == claim.verification_id
        assert claim_id == claim.claim_id
        return evidence

    store = FileSystemArtifactObjectStore(tmp_path)
    finding = await C3AcademicHandler(load, store).verify(_context(claim))
    assert finding.verdict == VerificationVerdict.SUPPORTED
    content = await store.read(
        tenant_id=claim.tenant_id,
        storage_namespace=finding.result_artifact.storage_namespace,
        object_key=finding.result_artifact.object_key,
        expected_byte_size=finding.result_artifact.byte_size,
        expected_sha256=finding.result_artifact.sha256,
    )
    document = json.loads(content)
    model = document["stability_analysis"][0]["model"]
    assert model["representation"] == "TRANSFER_FUNCTION"
    assert model["numerator_coefficients"] == [1.0]
    assert model["denominator_coefficients"] == [1.0, 1.0]
    comparisons = document["numeric_analysis"]["comparisons"]
    assert comparisons
    assert any(item["absolute_error"] == pytest.approx(0.0) for item in comparisons)


def test_c3_stability_parser_handles_bare_and_reverse_transfer_functions() -> None:
    from liyans.domains.academic.handler import C3AcademicHandler

    parser = SafeFormulaParser()
    bare = parser.parse("1/(s+1)")
    symbol = next(item for item in bare.residual.free_symbols if str(item) == "s")
    bare_result = C3AcademicHandler._stability_coefficients(bare, symbol)
    assert bare_result == ("TRANSFER_FUNCTION", [1.0], [1.0, 1.0])

    reverse = parser.parse("1/(s+1) = G(s)")
    reverse_symbol = next(item for item in reverse.residual.free_symbols if str(item) == "s")
    reverse_result = C3AcademicHandler._stability_coefficients(reverse, reverse_symbol)
    assert reverse_result == ("TRANSFER_FUNCTION", [1.0], [1.0, 1.0])

    non_polynomial = parser.parse("exp(s)")
    non_polynomial_symbol = next(
        item for item in non_polynomial.residual.free_symbols if str(item) == "s"
    )
    assert C3AcademicHandler._stability_coefficients(non_polynomial, non_polynomial_symbol) is None


@pytest.mark.asyncio
async def test_c3_handler_fails_closed_on_foreign_evidence(tmp_path: Path) -> None:
    claim = _claim("The equation is x = 1.")
    foreign = _evidence(claim, "x = 1", tenant_id="tenant-b")

    async def load(*args: object, **kwargs: object) -> tuple[EvidenceRefV1, ...]:
        return (foreign,)

    finding = await C3AcademicHandler(load, FileSystemArtifactObjectStore(tmp_path)).verify(
        _context(claim)
    )
    assert finding.verdict == VerificationVerdict.UNSAFE
    assert "C3_TENANT_ISOLATION_FAILED" in finding.finding_codes


@pytest.mark.asyncio
async def test_c3_handler_is_compatible_with_frozen_bounded_executor(tmp_path: Path) -> None:
    claim = _claim("The equation is x = 1.")
    evidence = (_evidence(claim, "The equation is x = 1."),)

    async def load(
        *, tenant_id: str, verification_id: UUID, claim_id: UUID
    ) -> tuple[EvidenceRefV1, ...]:
        assert tenant_id == claim.tenant_id
        assert verification_id == claim.verification_id
        assert claim_id == claim.claim_id
        return evidence

    item = build_topic4_record(
        ModuleDispatchItemV1,
        trace_id=TRACE,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="module-dispatch-item.v1",
        dispatch_item_id=uuid4(),
        claim_id=claim.claim_id,
        module=VerificationModule.C3_ACADEMIC,
        required=True,
        priority=1,
        dependency_item_ids=[],
        timeout_ms=8000,
        max_attempts=1,
    )
    plan = build_topic4_record(
        ModuleDispatchPlanV1,
        trace_id=TRACE,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="module-dispatch-plan.v1",
        dispatch_plan_id=uuid4(),
        verification_id=claim.verification_id,
        claim_ids=[claim.claim_id],
        items=[item],
        max_parallelism=1,
        policy_version="c3-test-1",
        plan_sha256="c" * 64,
    )
    handler = C3AcademicHandler(load, FileSystemArtifactObjectStore(tmp_path))
    bundle = await BoundedModuleExecutor(
        {VerificationModule.C3_ACADEMIC: handler},
        worker_instance_id="c3-test-worker",
    ).execute(plan, [claim], deadline_at=datetime.now(UTC) + timedelta(seconds=10))
    assert len(bundle.results) == 1
    assert bundle.results[0].verdict == VerificationVerdict.SUPPORTED


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_expression_chars": 0},
        {"max_identifiers": 0},
        {"max_operations": 0},
        {"max_parenthesis_depth": 0},
        {"max_absolute_exponent": 0},
        {"numeric_samples": 0},
        {"tolerance": 0.0},
    ],
)
def test_formula_policy_rejects_invalid_limits(kwargs: dict[str, object]) -> None:
    from liyans.domains.academic.formula import FormulaPolicy

    with pytest.raises(ValueError):
        FormulaPolicy(**kwargs)


def test_formula_parser_security_and_parse_error_boundaries() -> None:
    from liyans.domains.academic.formula import FormulaParseError, FormulaPolicy

    parser = SafeFormulaParser()
    with pytest.raises(FormulaParseError):
        parser.parse(None)  # type: ignore[arg-type]
    with pytest.raises(FormulaParseError):
        parser.parse("")
    with pytest.raises(FormulaParseError):
        parser.parse("x + * 1")
    with pytest.raises(FormulaParseError):
        parser.parse("x = 1 = 2")
    with pytest.raises(FormulaParseError):
        parser.parse("= 1")
    with pytest.raises(FormulaSecurityError):
        parser.parse("x@1")
    with pytest.raises(FormulaSecurityError):
        parser.parse("1" * 65)
    with pytest.raises(FormulaParseError):
        parser.parse("(x]")
    with pytest.raises(FormulaParseError):
        parser.parse("(x")
    with pytest.raises(FormulaSecurityError):
        SafeFormulaParser(FormulaPolicy(max_expression_chars=2)).parse("x+1")
    with pytest.raises(FormulaSecurityError):
        SafeFormulaParser(FormulaPolicy(max_parenthesis_depth=1)).parse("((x))")
    with pytest.raises(FormulaSecurityError):
        SafeFormulaParser(FormulaPolicy(max_identifiers=1)).parse("x+y")
    with pytest.raises(FormulaSecurityError):
        SafeFormulaParser(FormulaPolicy(max_operations=1)).parse("(x+y)*(z+1)")
    with pytest.raises(FormulaParseError):
        parser.parse("1/0")
    with pytest.raises(FormulaParseError):
        parser._parse_expression("[1, 2]", {})


def test_formula_parser_normalizes_latex_functions_and_relations() -> None:
    parser = SafeFormulaParser()
    assert "sqrt" in parser.parse(r"\sqrt{x^2}").canonical_expression
    assert parser.parse(r"\frac{1}{s+1}").canonical_expression == "1/(s + 1)"
    assert parser.parse("sin(x) + F(x) + pi").symbols["F"] == "FUNCTION"
    assert parser.parse("x <= 1").relation == "<="
    assert parser.parse("x != 1").relation == "!="
    assert parser.extract("$x=1$ and $y=2$") == ("x=1", "y=2")
    assert parser.extract("plain prose without mathematics") == ()


def _formula_record(claim: ClaimV1, expression: str):
    return FormulaIRBuilder().build(
        expression,
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
        created_at=NOW,
    )


def test_formula_equivalence_covers_numeric_counterexamples_and_unknowns() -> None:
    claim = _claim("formula")
    engine = FormulaEquivalenceEngine()
    different = engine.compare(
        _formula_record(claim, "x"),
        _formula_record(claim, "x+1"),
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert different.verdict == VerificationVerdict.CONTRADICTED
    assert different.counterexamples
    sampled_identity = engine.compare(
        _formula_record(claim, "sin(x)^2 + cos(x)^2"),
        _formula_record(claim, "1"),
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert sampled_identity.equivalent is True
    unknown = engine.compare(
        _formula_record(claim, "F(x)"),
        _formula_record(claim, "G(x)"),
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert unknown.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    relation_unknown = engine.compare(
        _formula_record(claim, "x > 0"),
        _formula_record(claim, "x >= 0"),
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert relation_unknown.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_formula_equivalence_rejects_cross_binding_and_derivation_errors() -> None:
    claim = _claim("formula")
    other_claim = _claim("other")
    left = _formula_record(claim, "x")
    right = _formula_record(claim, "x+1")
    with pytest.raises(ValueError, match="tenant"):
        FormulaEquivalenceEngine().compare(
            left,
            left.model_copy(update={"tenant_id": "tenant-b"}),
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
        )
    with pytest.raises(ValueError, match="claim"):
        FormulaEquivalenceEngine().compare(
            left,
            _formula_record(other_claim, "x"),
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
        )
    with pytest.raises(ValueError, match="rule count"):
        DerivationChecker().check(
            (left, right),
            rule_names=("ONLY_ONE",),
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
        )
    invalid = DerivationChecker().check(
        (left, right),
        rule_names=("START", "BAD_STEP"),
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert invalid.first_invalid_ordinal == 1
    with pytest.raises(ValueError, match="rule names"):
        DerivationChecker().check(
            (left,),
            rule_names=("",),
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
        )


def test_stability_boundary_failures_and_expected_claim_polarity() -> None:
    from liyans.domains.academic.stability import StabilityPolicy

    with pytest.raises(ValueError):
        StabilityPolicy(tolerance=0.0)
    with pytest.raises(ValueError):
        StabilityPolicy(max_polynomial_degree=0)
    with pytest.raises(ValueError):
        StabilityPolicy(max_matrix_dimension=0)
    claim = _claim("stability")
    builder = StabilityModelBuilder()
    analyzer = StabilityAnalyzer()
    unstable = builder.build(
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        domain=StabilityDomain.CONTINUOUS,
        representation="CHARACTERISTIC_POLYNOMIAL",
        denominator_coefficients=[1, -1],
    )
    assert (
        analyzer.analyze(
            unstable,
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
            expected_conclusion=StabilityConclusion.UNSTABLE,
        ).verdict
        == VerificationVerdict.SUPPORTED
    )
    with pytest.raises(ValueError, match="SHA256"):
        analyzer.analyze(
            unstable.model_copy(update={"model_sha256": "f" * 64}),
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
        )
    with pytest.raises(ValueError, match="tenant"):
        analyzer.analyze(unstable, trace_id="b" * 32, tenant_id="tenant-b", created_at=NOW)
    with pytest.raises(ValueError, match="identically"):
        zero = builder.build(
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
            domain=StabilityDomain.CONTINUOUS,
            representation="CHARACTERISTIC_POLYNOMIAL",
            denominator_coefficients=[0, 0],
        )
        analyzer.analyze(zero, trace_id=TRACE, tenant_id=TENANT, created_at=NOW)


def test_stability_discrete_marginal_unstable_and_bad_state_space_paths() -> None:
    claim = _claim("stability")
    builder = StabilityModelBuilder()
    analyzer = StabilityAnalyzer()
    marginal = builder.build(
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        domain=StabilityDomain.DISCRETE,
        representation="CHARACTERISTIC_POLYNOMIAL",
        denominator_coefficients=[1, -1],
        sample_time_seconds=1.0,
    )
    outside = builder.build(
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        domain=StabilityDomain.DISCRETE,
        representation="CHARACTERISTIC_POLYNOMIAL",
        denominator_coefficients=[1, -2],
        sample_time_seconds=1.0,
    )
    assert (
        analyzer.analyze(
            marginal, trace_id=TRACE, tenant_id=TENANT, created_at=NOW
        ).conclusion.value
        == "MARGINAL"
    )
    assert (
        analyzer.analyze(outside, trace_id=TRACE, tenant_id=TENANT, created_at=NOW).conclusion.value
        == "UNSTABLE"
    )
    bad_matrix = builder.build(
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        domain=StabilityDomain.CONTINUOUS,
        representation="STATE_SPACE",
        state_space_matrices={"A": [[-1.0, 0.0]]},
    )
    with pytest.raises(ValueError, match="square"):
        analyzer.analyze(bad_matrix, trace_id=TRACE, tenant_id=TENANT, created_at=NOW)


def test_numeric_policy_units_operators_and_missing_evidence() -> None:
    from liyans.domains.academic.numeric import (
        NumericAssertionExtractor,
        NumericPolicy,
        UnitNormalizer,
    )

    for kwargs in (
        {"absolute_tolerance": -1.0},
        {"relative_tolerance": -1.0},
        {"max_assertions": 0},
        {"max_absolute_value": 0.0},
    ):
        with pytest.raises(ValueError):
            NumericPolicy(**kwargs)
    with pytest.raises(ValueError, match="unsupported"):
        UnitNormalizer().normalize(1.0, "unknown")
    with pytest.raises(ValueError, match="count"):
        NumericAssertionExtractor(NumericPolicy(max_assertions=1)).extract("1 2")
    assert (
        NumericFactVerifier().verify("no numeric assertion", ()).verdict
        == VerificationVerdict.NOT_APPLICABLE
    )
    claim = _claim("value = 10ms", claim_kind=ClaimKind.TEXT)
    missing = NumericFactVerifier().verify(
        claim.normalized_statement, (_evidence(claim, "value = 2V"),)
    )
    assert missing.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    contradictory = NumericFactVerifier().verify(
        claim.normalized_statement, (_evidence(claim, "value = 20ms"),)
    )
    assert contradictory.verdict == VerificationVerdict.CONTRADICTED
    partial = NumericFactVerifier().verify(
        "first = 10ms and second = 20Hz",
        (_evidence(claim, "first = 10ms"),),
    )
    assert partial.verdict == VerificationVerdict.PARTIALLY_SUPPORTED


def test_numeric_all_comparison_operators() -> None:
    from liyans.domains.academic.numeric import NumericAssertionExtractor, NumericFactVerifier

    verifier = NumericFactVerifier()
    extractor = NumericAssertionExtractor()
    for expression, observed, expected in (
        ("x != 5", "x = 4", True),
        ("x < 5", "x = 4", True),
        ("x <= 5", "x = 5", True),
        ("x > 5", "x = 6", True),
        ("x >= 5", "x = 5", True),
    ):
        claim = _claim(expression, claim_kind=ClaimKind.TEXT)
        result = verifier.verify(expression, (_evidence(claim, observed),))
        assert (result.verdict == VerificationVerdict.SUPPORTED) is expected
    with pytest.raises(ValueError, match="unsupported"):
        verifier._satisfies(
            extractor.extract("x = 1")[0].__class__(
                source_text="",
                operator="?",
                value=1.0,
                unit=None,
                canonical_value=1.0,
                canonical_unit=None,
                span_start=0,
                span_end=1,
            ),
            1.0,
        )


def test_fact_verifier_supports_conflict_and_insufficient_evidence_paths() -> None:
    from liyans.domains.academic.fact import ClaimFactVerifier

    with pytest.raises(ValueError):
        ClaimFactVerifier(minimum_overlap=0.0)
    claim = _claim("closed loop stability requires poles in the left half plane")
    verifier = ClaimFactVerifier()
    assert verifier.verify(claim, ()).verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    unrelated = _evidence(claim, "frequency response uses a Bode plot")
    assert verifier.verify(claim, (unrelated,)).verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    supporting = _evidence(claim, "closed loop stability requires poles in the left half plane")
    assert verifier.verify(claim, (supporting,)).verdict == VerificationVerdict.SUPPORTED
    contradicting = _evidence(
        claim, "closed loop stability does not require poles in the left half plane"
    )
    assert verifier.verify(claim, (contradicting,)).verdict == VerificationVerdict.CONTRADICTED
    with pytest.raises(ValueError, match="unique"):
        verifier.verify(claim, (supporting, supporting))
    with pytest.raises(ValueError, match="claim"):
        verifier.verify(claim, (supporting.model_copy(update={"claim_id": uuid4()}),))
    assert (
        verifier.verify(claim, (supporting, contradicting)).verdict
        == VerificationVerdict.PARTIALLY_SUPPORTED
    )


def test_theorem_registry_and_verifier_cover_missing_optional_and_conflicting_conditions() -> None:
    claim = _claim("ROUTH_HURWITZ theorem conditions")
    positive = _evidence(claim, "all poles are in the left half plane")
    negative = _evidence(claim, "not all poles are in the left half plane")
    builder = TheoremRegistryBuilder()
    entry = builder.build(
        theorem_key="ROUTH_HURWITZ",
        name="Routh Hurwitz theorem",
        domain="CONTROL",
        statement="A polynomial is Hurwitz under the stated conditions.",
        conditions=(
            ("POSITIVE", "all poles in the left half plane", True),
            ("OPTIONAL", "gain margin is positive", False),
        ),
        conclusion="The polynomial is Hurwitz.",
        source_evidence_ref_ids=(positive.evidence_ref_id,),
        registry_version="test-1",
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="unique"):
        builder.build(
            theorem_key="DUPLICATE",
            name="Duplicate",
            domain="CONTROL",
            statement="statement",
            conditions=(("X", "same", True), ("X", "same", False)),
            conclusion="conclusion",
            source_evidence_ref_ids=(positive.evidence_ref_id,),
            registry_version="test-1",
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
        )
    from liyans.domains.academic.theorem import TheoremConditionAssessment, TheoremRegistry

    registry = TheoremRegistry((entry,))
    assert registry.get(TENANT, "ROUTH_HURWITZ") == entry
    assert registry.get(TENANT, "MISSING") is None
    assert len(registry.list_for_tenant(TENANT)) == 1
    with pytest.raises(ValueError):
        registry.get("", "ROUTH_HURWITZ")
    resolver = EvidenceConditionResolver()
    resolved = resolver.resolve(
        entry,
        (positive, negative),
        tenant_id=TENANT,
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
    )
    assert resolved["POSITIVE"].satisfied is None
    result = TheoremVerifier().check(
        entry,
        resolved,
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert result.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    optional_failure = TheoremVerifier().check(
        entry,
        {
            "POSITIVE": TheoremConditionAssessment(True, (positive.evidence_ref_id,), "ok"),
            "OPTIONAL": TheoremConditionAssessment(False, (), "optional failed"),
        },
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    assert optional_failure.verdict == VerificationVerdict.PARTIALLY_SUPPORTED
    with pytest.raises(ValueError, match="tenant"):
        resolver.resolve(
            entry,
            (positive,),
            tenant_id="tenant-b",
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
        )


class _FakeAcademicDatabase:
    @asynccontextmanager
    async def transaction(self, **kwargs: object):
        yield object()


class _FakeAcademicRepository:
    def __init__(self, bundle: object | None, refs: tuple[EvidenceRefV1, ...]) -> None:
        self.bundle = bundle
        self.refs = refs

    async def latest_evidence_bundle(self, *args: object) -> object | None:
        return self.bundle

    async def list_evidence_refs(self, *args: object) -> list[EvidenceRefV1]:
        return list(self.refs)


@pytest.mark.asyncio
async def test_postgres_academic_evidence_source_binds_latest_bundle() -> None:
    claim = _claim("x = 1")
    first = _evidence(claim, "x = 1")
    second = _evidence(claim, "x equals one")
    bundle = SimpleNamespace(
        tenant_id=TENANT,
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        evidence_ref_ids=[second.evidence_ref_id, first.evidence_ref_id],
    )
    source = PostgresAcademicEvidenceSource(
        _FakeAcademicDatabase(),  # type: ignore[arg-type]
        _FakeAcademicRepository(bundle, (first, second)),  # type: ignore[arg-type]
    )
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="subject:test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )
    with tenant_scope(context):
        loaded = await source.load(
            tenant_id=TENANT,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
        )
    assert loaded == (second, first)


@pytest.mark.asyncio
async def test_postgres_academic_evidence_source_handles_none_and_integrity_failures() -> None:
    claim = _claim("x = 1")
    ref = _evidence(claim, "x = 1")
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="subject:test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )
    with tenant_scope(context):
        empty = PostgresAcademicEvidenceSource(
            _FakeAcademicDatabase(),  # type: ignore[arg-type]
            _FakeAcademicRepository(None, ()),  # type: ignore[arg-type]
        )
        assert (
            await empty.load(
                tenant_id=TENANT,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )
            == ()
        )
        missing_bundle = SimpleNamespace(
            tenant_id=TENANT,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            evidence_ref_ids=[uuid4()],
        )
        missing = PostgresAcademicEvidenceSource(
            _FakeAcademicDatabase(),  # type: ignore[arg-type]
            _FakeAcademicRepository(missing_bundle, (ref,)),  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="unavailable"):
            await missing.load(
                tenant_id=TENANT,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )
        duplicate_bundle = SimpleNamespace(
            tenant_id=TENANT,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            evidence_ref_ids=[ref.evidence_ref_id],
        )
        duplicate = PostgresAcademicEvidenceSource(
            _FakeAcademicDatabase(),  # type: ignore[arg-type]
            _FakeAcademicRepository(duplicate_bundle, (ref, ref)),  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="duplicate"):
            await duplicate.load(
                tenant_id=TENANT,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )


@pytest.mark.asyncio
async def test_c3_handler_insufficient_unregistered_and_tenant_dispatch_paths(
    tmp_path: Path,
) -> None:
    async def empty_load(**kwargs: object) -> tuple[EvidenceRefV1, ...]:
        return ()

    formula_claim = _claim("The equation is x = 1.")
    handler = C3AcademicHandler(empty_load, FileSystemArtifactObjectStore(tmp_path / "empty"))
    assert (
        await handler.verify(_context(formula_claim))
    ).verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE

    theorem_claim = _claim("The Routh theorem condition is satisfied.", claim_kind=ClaimKind.TEXT)
    theorem_finding = await C3AcademicHandler(
        empty_load,
        FileSystemArtifactObjectStore(tmp_path / "theorem"),
    ).verify(_context(theorem_claim))
    assert "C3_THEOREM_UNREGISTERED" in theorem_finding.finding_codes

    context = _context(formula_claim)
    foreign_item = context.dispatch_item.model_copy(update={"tenant_id": "tenant-b"})
    foreign_context = ModuleExecutionContext(
        verification_id=context.verification_id,
        dispatch_plan_id=context.dispatch_plan_id,
        dispatch_item=foreign_item,
        claim=context.claim,
        module_run_id=context.module_run_id,
        attempt=context.attempt,
        deadline_at=context.deadline_at,
    )
    unsafe = await C3AcademicHandler(
        empty_load,
        FileSystemArtifactObjectStore(tmp_path / "tenant"),
    ).verify(foreign_context)
    assert unsafe.verdict == VerificationVerdict.UNSAFE


@pytest.mark.asyncio
async def test_c3_handler_validates_unstable_claim_against_actual_poles(tmp_path: Path) -> None:
    statement = "The characteristic polynomial s - 1 is unstable."
    claim = _claim(statement)
    evidence = (_evidence(claim, "The characteristic polynomial s - 1 has a pole at +1."),)

    async def load(**kwargs: object) -> tuple[EvidenceRefV1, ...]:
        return evidence

    finding = await C3AcademicHandler(
        load,
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_context(claim))
    assert finding.verdict == VerificationVerdict.SUPPORTED
