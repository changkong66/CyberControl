from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import ClaimV1, ExtractionMethod, ModuleDispatchItemV1
from liyans_contracts.topic4_c2 import EvidenceRefV1, SourceAuthorityTier
from liyans_contracts.topic4_common import ClaimKind, VerificationModule, VerificationVerdict
from prometheus_client import CollectorRegistry

from liyans.domains.academic.handler import (
    C3_HANDLER_VERSION,
    C3_HANDLER_VERSION_V2,
    C3AcademicHandler,
    C3AcademicHandlerV2,
)
from liyans.domains.academic.semantic import SemanticClaimVerifierV2, SemanticVerifierPolicy
from liyans.domains.verification.execution import ModuleExecutionContext
from liyans.domains.verification.records import build_topic4_record
from liyans.domains.verification.runtime import Topic4RuntimeMetrics, build_topic4_handlers
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 22, 12, tzinfo=UTC)
TENANT = "tenant-c3-semantic-v2"
TRACE = "d" * 32


def _claim(statement: str, *, tenant_id: str = TENANT) -> ClaimV1:
    return build_topic4_record(
        ClaimV1,
        trace_id=TRACE,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="claim.v1",
        claim_id=uuid4(),
        verification_id=uuid4(),
        candidate_id=uuid4(),
        candidate_version=1,
        candidate_sha256="b" * 64,
        block_id="c3-semantic-v2",
        claim_kind=ClaimKind.TEXT,
        claim_subtype="academic",
        statement=statement,
        normalized_statement=statement,
        json_pointer="/content/text",
        ordinal=0,
        source_span_start=0,
        source_span_end=len(statement),
        claim_sha256=canonical_sha256(statement),
        extraction_method=ExtractionMethod.DETERMINISTIC,
        dependent_claim_ids=[],
    )


def _evidence(claim: ClaimV1, excerpt: str, *, tenant_id: str | None = None) -> EvidenceRefV1:
    return build_topic4_record(
        EvidenceRefV1,
        trace_id=claim.trace_id,
        tenant_id=tenant_id or claim.tenant_id,
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
        section_id="semantic-v2",
        citation="Reviewed automatic-control source",
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


@pytest.mark.parametrize(
    ("premise", "hypothesis", "finding_code"),
    [
        (
            "Controller structure selection occurs before coefficient tuning.",
            "Coefficient tuning occurs before controller structure selection.",
            "C3_SEMANTIC_ORDER_REVERSED",
        ),
        (
            "The result requires the measured input.",
            "The result is independent of the measured input.",
            "C3_SEMANTIC_DEPENDENCY_REVERSED",
        ),
        (
            "Measurement noise can make derivative action undesirable and disabled.",
            "Derivative action removes measurement noise.",
            "C3_SEMANTIC_CAUSAL_EFFECT_REVERSED",
        ),
        (
            "The response must remain within the tolerance band.",
            "The first crossing counts even when the response leaves the tolerance band.",
            "C3_SEMANTIC_TEMPORAL_CONDITION_REVERSED",
        ),
        (
            "Responses are classified as underdamped, overdamped, or critically damped.",
            "Underdamped and overdamped responses are identical.",
            "C3_SEMANTIC_CLASS_DISTINCTION_DENIED",
        ),
        (
            "A model-free method uses measured plant characteristics.",
            "Every model-free method requires a complete first-principles model.",
            "C3_SEMANTIC_MODEL_REQUIREMENT_REVERSED",
        ),
        (
            "Sustained constant-amplitude oscillation identifies the critical gain.",
            "The gain is defined after the oscillation has decayed to zero.",
            "C3_SEMANTIC_PERSISTENCE_REVERSED",
        ),
        (
            "In the criterion family, n equals 0 for ISE and 2 for IST2E.",
            "Integral squared error uses n equals 2.",
            "C3_SEMANTIC_NUMERIC_ASSOCIATION_CONFLICT",
        ),
        (
            "The crossover point moves away from the critical point.",
            "The crossover point moves toward the critical point.",
            "C3_SEMANTIC_DIRECTION_REVERSED",
        ),
        (
            "Exact discretization uses the matrix exponential.",
            "Exact discretization uses a scalar product.",
            "C3_SEMANTIC_MATHEMATICAL_FORM_REPLACED",
        ),
        (
            "The transform is divided by a denominator term.",
            "The transform has no denominator term.",
            "C3_SEMANTIC_DENOMINATOR_DENIED",
        ),
        (
            "A high sampling rate can increase burden and produce poor numerical results.",
            "A high sampling rate is computationally free and numerically ideal.",
            "C3_SEMANTIC_COST_QUALITY_REVERSED",
        ),
        (
            "A right-half-plane pole makes the system unstable.",
            "A right-half-plane pole guarantees that the system is stable.",
            "C3_SEMANTIC_STABILITY_POLARITY_REVERSED",
        ),
        (
            "An eigenvalue need not appear as a transfer-function pole.",
            "Every eigenvalue must always appear as a transfer-function pole.",
            "C3_SEMANTIC_QUANTIFIER_SCOPE_REVERSED",
        ),
    ],
)
def test_semantic_v2_detects_generic_contradiction_relations(
    premise: str,
    hypothesis: str,
    finding_code: str,
) -> None:
    relation = SemanticClaimVerifierV2()._assess(premise, hypothesis)

    assert relation.verdict == VerificationVerdict.CONTRADICTED
    assert relation.finding_code == finding_code


@pytest.mark.parametrize(
    ("premise", "hypothesis"),
    [
        (
            "A thermal process may use a first-order-plus-dead-time model.",
            "A thermal process can never use a first-order-plus-dead-time model.",
        ),
        (
            "The design process includes stability analysis and controller tuning.",
            "Stability analysis is excluded from the design process.",
        ),
        (
            "System identification builds a model from measured input-output data.",
            "System identification forbids measured input-output data.",
        ),
        (
            "A negative-feedback loop may include a state estimator.",
            "A state estimator can never be part of a negative-feedback loop.",
        ),
    ],
)
def test_semantic_v2_detects_scope_bound_predicate_denial(
    premise: str,
    hypothesis: str,
) -> None:
    relation = SemanticClaimVerifierV2()._assess(premise, hypothesis)

    assert relation.verdict == VerificationVerdict.CONTRADICTED
    assert relation.finding_code == "C3_SEMANTIC_PREDICATE_DENIED"


@pytest.mark.parametrize(
    ("premise", "hypothesis"),
    [
        (
            "A model-free method may use a small set of measured characteristics.",
            "Exact coefficients can be computed without any measured characteristics.",
        ),
        (
            "Relay oscillation can provide process information.",
            "Process parameters can be recovered from relay amplitude alone.",
        ),
        (
            "PI control may be applied to temperature loops.",
            "PI control is always optimal for every temperature loop.",
        ),
    ],
)
def test_semantic_v2_abstains_on_unsupported_extrapolation(
    premise: str,
    hypothesis: str,
) -> None:
    relation = SemanticClaimVerifierV2()._assess(premise, hypothesis)

    assert relation.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_semantic_v2_supports_exact_and_conservative_paraphrase() -> None:
    verifier = SemanticClaimVerifierV2()

    exact = verifier._assess(
        "A controller structure is selected before its coefficients are tuned.",
        "A controller structure is selected before its coefficients are tuned.",
    )
    paraphrase = verifier._assess(
        "A controller structure is selected before its coefficients are tuned.",
        "The controller structure is selected before coefficient tuning.",
    )

    assert exact.verdict == VerificationVerdict.SUPPORTED
    assert paraphrase.verdict == VerificationVerdict.SUPPORTED


def test_semantic_v2_ignores_unrelated_contradiction_cues() -> None:
    verifier = SemanticClaimVerifierV2()

    persistence_noise = verifier._assess(
        "Sustained oscillation under increasing gain identifies a critical gain.",
        "Increasing gain margin moves the crossover point away from minus one plus zero j.",
    )
    stability_noise = verifier._assess(
        "A right-half-plane pole makes an unrelated plant unstable.",
        "The largest stable sampling period cannot be selected without an experiment.",
    )

    assert persistence_noise.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert stability_noise.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_semantic_v2_rejects_cross_tenant_evidence_and_conflicting_sources() -> None:
    claim = _claim("A thermal process may use a FOPDT model.")
    verifier = SemanticClaimVerifierV2()

    with pytest.raises(ValueError, match="tenant"):
        verifier.verify(claim, (_evidence(claim, claim.statement, tenant_id="tenant-b"),))

    support = _evidence(claim, claim.statement)
    contradiction = _evidence(claim, "A thermal process can never use a FOPDT model.")
    result = verifier.verify(claim, (support, contradiction))

    assert result.verdict == VerificationVerdict.PARTIALLY_SUPPORTED
    assert result.supporting_evidence_ref_ids == (support.evidence_ref_id,)
    assert result.contradicting_evidence_ref_ids == (contradiction.evidence_ref_id,)
    assert "C3_SEMANTIC_EVIDENCE_CONFLICT" in result.finding_codes


def test_semantic_v2_policy_bounds_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="thresholds"):
        SemanticVerifierPolicy(minimum_support_jaccard=0.0)
    with pytest.raises(ValueError, match="statement limit"):
        SemanticVerifierPolicy(max_statement_characters=0)


def test_phase7_semantic_benchmark_has_no_runtime_label_channel() -> None:
    source = inspect.getsource(SemanticClaimVerifierV2)
    assert re.search(r"C3-\d{3}", source) is None
    for forbidden in ("expected_outcome", "expected_outcome_rationale", "fact_id", "topic"):
        assert forbidden not in source

    facts = [
        json.loads(line)
        for line in (ROOT / "tests/golden/phase7-academic-golden-facts.v1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    premise_by_topic = {
        fact["topic"]: fact["claim"] for fact in facts if fact["expected_outcome"] == "SUPPORTED"
    }
    counts = {outcome: 0 for outcome in ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE")}
    unsafe_false_negatives: list[str] = []

    for fact in facts:
        claim = _claim(fact["claim"])
        evidence = _evidence(claim, premise_by_topic[fact["topic"]])
        runtime_input = json.dumps(
            {
                "claim": claim.model_dump(mode="json"),
                "evidence": evidence.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        assert fact["fact_id"] not in runtime_input
        assert fact["expected_outcome_rationale"] not in runtime_input
        assert "expected_outcome" not in runtime_input

        actual = SemanticClaimVerifierV2().verify(claim, (evidence,)).verdict.value
        counts[actual] += 1
        if fact["expected_outcome"] == "CONTRADICTED" and actual == "SUPPORTED":
            unsafe_false_negatives.append(fact["fact_id"])
        assert actual == fact["expected_outcome"]

    assert counts == {"SUPPORTED": 24, "CONTRADICTED": 24, "INSUFFICIENT_EVIDENCE": 24}
    assert unsafe_false_negatives == []


@pytest.mark.asyncio
async def test_v2_handler_is_explicit_and_preserves_v1_artifact_compatibility(
    tmp_path: Path,
) -> None:
    statement = "Increasing the sampling period can degrade stability."
    claim = _claim(statement)
    evidence = (_evidence(claim, statement),)

    async def load(**kwargs: object) -> tuple[EvidenceRefV1, ...]:
        assert kwargs["tenant_id"] == claim.tenant_id
        return evidence

    v1_store = FileSystemArtifactObjectStore(tmp_path / "v1")
    v2_store = FileSystemArtifactObjectStore(tmp_path / "v2")
    v1_finding = await C3AcademicHandler(load, v1_store).verify(_context(claim))
    v2_finding = await C3AcademicHandlerV2(load, v2_store).verify(_context(claim))

    assert v1_finding.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert v2_finding.verdict == VerificationVerdict.SUPPORTED
    v1_document = json.loads(
        await v1_store.read(
            tenant_id=claim.tenant_id,
            storage_namespace=v1_finding.result_artifact.storage_namespace,
            object_key=v1_finding.result_artifact.object_key,
            expected_byte_size=v1_finding.result_artifact.byte_size,
            expected_sha256=v1_finding.result_artifact.sha256,
        )
    )
    v2_document = json.loads(
        await v2_store.read(
            tenant_id=claim.tenant_id,
            storage_namespace=v2_finding.result_artifact.storage_namespace,
            object_key=v2_finding.result_artifact.object_key,
            expected_byte_size=v2_finding.result_artifact.byte_size,
            expected_sha256=v2_finding.result_artifact.sha256,
        )
    )
    assert v1_document["schema_version"] == "c3-academic-finding.v1"
    assert v2_document["schema_version"] == "c3-academic-finding.v1"
    assert v1_document["handler_version"] == C3_HANDLER_VERSION
    assert v2_document["handler_version"] == C3_HANDLER_VERSION_V2


@pytest.mark.asyncio
async def test_v2_handler_does_not_treat_prose_hyphens_as_stability_models(
    tmp_path: Path,
) -> None:
    statement = (
        "Every transfer-function pole is an eigenvalue of the state matrix, but an eigenvalue "
        "need not appear as a transfer-function pole in a nonminimal realization."
    )
    claim = _claim(statement)
    evidence = (_evidence(claim, statement),)

    async def load(**kwargs: object) -> tuple[EvidenceRefV1, ...]:
        assert kwargs["claim_id"] == claim.claim_id
        return evidence

    finding = await C3AcademicHandlerV2(
        load,
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_context(claim))

    assert finding.verdict == VerificationVerdict.SUPPORTED


def test_topic4_runtime_explicitly_assembles_c3_v2(tmp_path: Path) -> None:
    handlers = build_topic4_handlers(
        database=Mock(),
        verification_service=Mock(),
        knowledge_repository=Mock(),
        topic1_repository=Mock(),
        topic3_repository=Mock(),
        retrieval_service=Mock(),
        artifact_store=FileSystemArtifactObjectStore(tmp_path),
        metrics=Topic4RuntimeMetrics(CollectorRegistry()),
    )

    assert isinstance(handlers[VerificationModule.C3_ACADEMIC], C3AcademicHandlerV2)
