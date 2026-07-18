from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic1 import Topic1GraphSnapshotV1, Topic1ImportBundleV1
from liyans_contracts.topic3 import (
    BlockStatus,
    BlockType,
    BlockV1,
    CandidateProvenanceV1,
    CandidateStatus,
    CandidateV1,
)
from liyans_contracts.topic3 import (
    TesterContentV1 as Topic3TesterContentV1,
)
from liyans_contracts.topic4_c1 import (
    ClaimV1,
    ModuleDispatchItemV1,
    ModuleDispatchPlanV1,
)
from liyans_contracts.topic4_c2 import (
    EvidenceBundleV1,
    EvidenceRefV1,
    KnowledgeBaseVersionV1,
    RetrievalTimingV1,
    SourceAuthorityTier,
    SourceLifecycle,
)
from liyans_contracts.topic4_common import (
    ClaimKind,
    VerificationModule,
    VerificationVerdict,
)

from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.quiz.evidence_source import (
    PostgresQuizEvidenceSource,
    QuizEvidenceBundle,
)
from liyans.domains.quiz.handler import C5HandlerPolicy, C5QuizHandler
from liyans.domains.quiz.parser import FrozenQuizParser, ParsedQuizItem, QuizParseError
from liyans.domains.quiz.verifier import QuizIntegrityError, Topic1QuizVerifier
from liyans.domains.topic3.entities import CandidateRecord
from liyans.domains.verification.claim_extraction import DeterministicClaimExtractor
from liyans.domains.verification.execution import BoundedModuleExecutor, ModuleExecutionContext
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
TENANT = "tenant-c5"
TRACE = "5" * 32


def _seed_content():
    root = Path(__file__).resolve().parents[2]
    document = json.loads(
        (root / "data/topic1/automatic-control-principles.v1.json").read_text(encoding="utf-8")
    )
    return Topic1ImportBundleV1.model_validate(document).content


def _snapshot() -> Topic1GraphSnapshotV1:
    content = _seed_content()
    return Topic1GraphSnapshotV1(
        snapshot_id=uuid4(),
        course_id=content.course.course_id,
        graph_version=1,
        content=content,
        content_sha256=canonical_sha256(content.model_dump(mode="json")),
        node_count=len(content.knowledge_points),
        edge_count=len(content.prerequisites),
        created_by_subject="system:c5-test",
        frozen_at=NOW,
    )


def _question(
    *,
    answer: str = "参数为 K，稳定范围为 $0<K<6$。",
    stem: str | None = None,
    difficulty: float = 0.5,
    target_kp_ids: list[str] | None = None,
    diagnostics: list[str] | None = None,
    question_type: str = "CALCULATION",
) -> dict[str, object]:
    golden = next(
        item
        for item in _seed_content().golden_questions
        if item.question_id == "QUESTION_ATC_ROUTH_001"
    )
    return {
        "question_id": golden.question_id,
        "question_type": question_type,
        "difficulty": difficulty,
        "target_kp_ids": target_kp_ids or [golden.primary_kp_id],
        "prompt_markdown": stem or golden.stem_markdown,
        "standard_answer": answer,
        "solution_steps": [golden.solution_markdown],
        "misconception_diagnostics": diagnostics or list(golden.misconception_ids),
        "score": 10,
    }


def _candidate(**question_overrides: object) -> CandidateV1:
    question = _question(**question_overrides)
    content = Topic3TesterContentV1(
        schema_version="topic3.tester-content.v1",
        title="Routh stability diagnostic",
        total_score=10,
        questions=[question],
        diagnostic_dimensions=["knowledge_mastery", "misconception"],
    ).model_dump(mode="json")
    block = BlockV1(
        schema_version="topic3.block.v1",
        block_id="quiz-routh",
        block_type=BlockType.QUIZ,
        ordinal=0,
        title="Routh stability quiz",
        content_schema_version="topic3.tester-content.v1",
        content=content,
        content_sha256=canonical_sha256(content),
        dependency_block_ids=[],
        status=BlockStatus.COMPLETE,
        created_at=NOW,
    )
    draft = CandidateV1.model_construct(
        schema_version="topic3.candidate.v1",
        candidate_id=uuid4(),
        candidate_version=1,
        parent_candidate_version=None,
        blueprint_id=uuid4(),
        blueprint_version="topic3.blueprint.v1",
        blueprint_sha256="b" * 64,
        resource_type=ResourceType.GRADIENT_QUIZ,
        status=CandidateStatus.COMPLETE,
        blocks=[block],
        provenance=CandidateProvenanceV1(
            agent=SourceAgent.TESTER,
            agent_build_version="topic3.tester.accepted.v1",
            prompt_bundle_version="prompt.tester.v1",
            provider_alias="local",
            provider_request_ids=[],
        ),
        personalization_policy_digest="c" * 64,
        candidate_sha256="0" * 64,
        created_at=NOW,
    )
    document = draft.model_dump(mode="json", exclude={"candidate_sha256"})
    return CandidateV1(**document, candidate_sha256=canonical_sha256(document))


def _claim(candidate: CandidateV1, field: str = "standard_answer") -> ClaimV1:
    claims = DeterministicClaimExtractor().extract(
        candidate,
        verification_id=uuid4(),
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    return next(claim for claim in claims if claim.json_pointer.endswith(f"/{field}"))


def _evidence(claim: ClaimV1, *, tenant_id: str = TENANT) -> EvidenceRefV1:
    excerpt = next(
        item.solution_markdown
        for item in _seed_content().golden_questions
        if item.question_id == "QUESTION_ATC_ROUTH_001"
    )
    return build_topic4_record(
        EvidenceRefV1,
        trace_id=claim.trace_id,
        tenant_id=tenant_id,
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
        section_id="topic1:QUESTION_ATC_ROUTH_001",
        citation="Topic1 golden question QUESTION_ATC_ROUTH_001",
        excerpt=excerpt,
        excerpt_sha256=canonical_sha256(excerpt),
        bm25_score=1.0,
        vector_score=1.0,
        graph_score=1.0,
        formula_score=1.0,
        fused_score=1.0,
        source_authority_tier=SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK,
    )


def _context(claim: ClaimV1, *, tenant_id: str = TENANT) -> ModuleExecutionContext:
    dispatch = build_topic4_record(
        ModuleDispatchItemV1,
        trace_id=claim.trace_id,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="module-dispatch-item.v1",
        dispatch_item_id=uuid4(),
        claim_id=claim.claim_id,
        module=VerificationModule.C5_QUIZ,
        required=True,
        priority=1,
        dependency_item_ids=[],
        timeout_ms=8000,
        max_attempts=1,
    )
    return ModuleExecutionContext(
        verification_id=claim.verification_id,
        dispatch_plan_id=uuid4(),
        dispatch_item=dispatch,
        claim=claim,
        module_run_id=uuid4(),
        attempt=1,
        deadline_at=NOW + timedelta(minutes=1),
    )


def _plan(claim: ClaimV1) -> ModuleDispatchPlanV1:
    item = _context(claim).dispatch_item
    return build_topic4_record(
        ModuleDispatchPlanV1,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="module-dispatch-plan.v1",
        dispatch_plan_id=uuid4(),
        verification_id=claim.verification_id,
        claim_ids=[claim.claim_id],
        items=[item],
        max_parallelism=1,
        policy_version="c5-test-v1",
        plan_sha256="d" * 64,
    )


@dataclass
class _FakeSource:
    bundle: QuizEvidenceBundle

    async def load(self, claim: ClaimV1) -> QuizEvidenceBundle:
        assert claim.tenant_id == TENANT
        return self.bundle


def test_frozen_quiz_parser_reconstructs_question_level_ir() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    parsed = FrozenQuizParser().parse(claim, candidate)
    assert parsed.question.question_id == "QUESTION_ATC_ROUTH_001"
    assert parsed.verifier_ir.item_type.value == "CALCULATION"
    assert parsed.verifier_ir.solution_steps[0].ordinal == 0
    assert parsed.verifier_ir.record_sha256


def test_frozen_quiz_parser_rejects_candidate_pointer_and_block_tampering() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    with pytest.raises(QuizParseError):
        FrozenQuizParser().parse(claim.model_copy(update={"candidate_id": uuid4()}), candidate)
    with pytest.raises(QuizParseError):
        FrozenQuizParser().parse(claim.model_copy(update={"json_pointer": "/invalid"}), candidate)
    tampered_block = candidate.blocks[0].model_copy(update={"content_sha256": "f" * 64})
    tampered_document = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    tampered_document["blocks"] = [tampered_block.model_dump(mode="json")]
    tampered = candidate.model_copy(
        update={
            "blocks": [tampered_block],
            "candidate_sha256": canonical_sha256(tampered_document),
        }
    )
    tampered_claim = claim.model_copy(update={"candidate_sha256": tampered.candidate_sha256})
    with pytest.raises(QuizParseError):
        FrozenQuizParser().parse(tampered_claim, tampered)


def test_topic1_quiz_verifier_supports_authoritative_complete_answer() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    analysis = Topic1QuizVerifier().verify(
        FrozenQuizParser().parse(claim, candidate),
        _snapshot(),
        evidence_ref_ids=(evidence.evidence_ref_id,),
    )
    assert analysis.result.verdict == VerificationVerdict.SUPPORTED
    assert analysis.result.answer_correct is True
    assert analysis.result.solution_coherent is True
    assert analysis.result.diagnosis_mapping_valid is True
    assert analysis.answer_coverage == 1.0


@pytest.mark.parametrize(
    ("overrides", "finding_code"),
    [
        ({"answer": "稳定范围为 K>10。"}, "C5_ANSWER_INCORRECT_OR_INCOMPLETE"),
        ({"stem": "TODO"}, "C5_STEM_AMBIGUOUS_OR_INCOMPLETE"),
        ({"difficulty": 1.0}, "C5_DIFFICULTY_LABEL_MISMATCH"),
        ({"diagnostics": ["unknown-diagnosis"]}, "C5_DIAGNOSIS_MAPPING_INVALID"),
        ({"question_type": "ENGINEERING"}, "C5_QUESTION_TYPE_MISMATCH"),
        ({"target_kp_ids": ["KP_UNKNOWN"]}, "C5_UNKNOWN_KNOWLEDGE_POINT"),
    ],
)
def test_topic1_quiz_verifier_detects_semantic_failures(
    overrides: dict[str, object],
    finding_code: str,
) -> None:
    candidate = _candidate(**overrides)
    claim = _claim(candidate)
    result = (
        Topic1QuizVerifier()
        .verify(
            FrozenQuizParser().parse(claim, candidate),
            _snapshot(),
            evidence_ref_ids=(_evidence(claim).evidence_ref_id,),
        )
        .result
    )
    assert finding_code in result.finding_codes
    assert result.verdict != VerificationVerdict.SUPPORTED


def test_topic1_quiz_verifier_fails_closed_without_golden_evidence() -> None:
    candidate = _candidate(target_kp_ids=["KP_ATC_101_SYSTEM_MODEL"])
    claim = _claim(candidate)
    result = (
        Topic1QuizVerifier()
        .verify(
            FrozenQuizParser().parse(claim, candidate),
            _snapshot(),
            evidence_ref_ids=(),
        )
        .result
    )
    assert result.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert "C5_GOLDEN_QUESTION_NOT_FOUND" in result.finding_codes


def test_topic1_quiz_verifier_rejects_tampered_snapshot() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    with pytest.raises(QuizIntegrityError):
        Topic1QuizVerifier().verify(
            FrozenQuizParser().parse(claim, candidate),
            _snapshot().model_copy(update={"content_sha256": "f" * 64}),
            evidence_ref_ids=(_evidence(claim).evidence_ref_id,),
        )


def test_topic1_quiz_verifier_covers_structured_answer_and_integrity_boundaries() -> None:
    verifier = Topic1QuizVerifier()
    assert verifier._answer_coverage("", {}) == 0.0
    assert verifier._leaf_supported("The system is controllable.", "flag", True)
    assert verifier._leaf_supported("The statement is false.", "flag", False)
    assert verifier._leaf_supported("The ratio is 16.3%.", "ratio", 0.163)
    assert not verifier._leaf_supported("The ratio is 10%.", "ratio", 0.163)
    assert verifier._leaf_supported("G(s)=3/(s+2)", "formula", "3/(s+2)")
    assert not verifier._leaf_supported("unrelated", "value", ["a", "b"])
    assert list(verifier._flatten({"a": [1, 2]})) == [("a[0]", 1), ("a[1]", 2)]
    assert verifier._formula_supported("x", "__import__('os')") is None
    assert verifier._formula_supported("not a formula", "s+1") is False
    assert verifier._text_similarity("", "") == 0.0
    assert not verifier._stem_is_unambiguous("Calculate $s+1")

    snapshot = _snapshot()
    with pytest.raises(QuizIntegrityError, match="node count"):
        verifier._validate_snapshot(snapshot.model_copy(update={"node_count": 0}))
    with pytest.raises(QuizIntegrityError, match="edge count"):
        verifier._validate_snapshot(snapshot.model_copy(update={"edge_count": 0}))
    duplicated = snapshot.content.model_copy(
        update={
            "golden_questions": [
                snapshot.content.golden_questions[0],
                snapshot.content.golden_questions[0],
            ]
        }
    )
    duplicated_snapshot = snapshot.model_copy(
        update={
            "content": duplicated,
            "content_sha256": canonical_sha256(duplicated.model_dump(mode="json")),
        }
    )
    with pytest.raises(QuizIntegrityError, match="duplicate questions"):
        verifier._validate_snapshot(duplicated_snapshot)


def test_topic1_quiz_verifier_covers_ambiguous_authority_and_solution_boundaries() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    parsed = FrozenQuizParser().parse(claim, candidate)
    verifier = Topic1QuizVerifier()
    golden = next(
        item
        for item in _snapshot().content.golden_questions
        if item.question_id == "QUESTION_ATC_ROUTH_001"
    )
    duplicate = golden.model_copy(update={"question_id": "QUESTION_ATC_ROUTH_DUPLICATE"})
    ambiguous_content = _snapshot().content.model_copy(
        update={"golden_questions": [golden, duplicate]}
    )
    ambiguous_snapshot = _snapshot().model_copy(
        update={
            "content": ambiguous_content,
            "content_sha256": canonical_sha256(ambiguous_content.model_dump(mode="json")),
            "node_count": len(ambiguous_content.knowledge_points),
            "edge_count": len(ambiguous_content.prerequisites),
        }
    )
    unknown_id_ir = parsed.verifier_ir.model_copy(update={"question_id": "candidate-only"})
    unknown_id_parsed = ParsedQuizItem(
        parsed.question,
        unknown_id_ir,
        parsed.candidate_block_ordinal,
        parsed.question_ordinal,
    )
    selected, _ = verifier._select_golden_question(unknown_id_parsed, ambiguous_snapshot)
    assert selected is None

    duplicate_steps = parsed.verifier_ir.model_copy(
        update={"solution_steps": [parsed.verifier_ir.solution_steps[0]] * 2}
    )
    duplicate_parsed = ParsedQuizItem(
        parsed.question,
        duplicate_steps,
        parsed.candidate_block_ordinal,
        parsed.question_ordinal,
    )
    assert not verifier._solution_is_coherent(duplicate_parsed, golden)
    assert verifier._solution_is_coherent(parsed, None)

    no_misconception = next(
        item
        for item in _snapshot().content.golden_questions
        if item.question_id == "QUESTION_ATC_CONTROLLABILITY_001"
    )
    no_diagnosis_parsed = ParsedQuizItem(
        parsed.question,
        parsed.verifier_ir.model_copy(update={"misconception_codes": []}),
        parsed.candidate_block_ordinal,
        parsed.question_ordinal,
    )
    assert verifier._diagnosis_is_valid(no_diagnosis_parsed, no_misconception, _snapshot())
    unknown_misconception = golden.model_copy(
        update={"misconception_ids": ["MISCONCEPTION_UNKNOWN"]}
    )
    with pytest.raises(QuizIntegrityError, match="unknown misconception"):
        verifier._diagnosis_is_valid(parsed, unknown_misconception, _snapshot())


@pytest.mark.asyncio
async def test_c5_handler_writes_replayable_artifact_and_executes_under_c1(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    bundle = QuizEvidenceBundle(
        candidate, _snapshot(), (evidence,), evidence.knowledge_base_version_id
    )
    store = FileSystemArtifactObjectStore(tmp_path)
    handler = C5QuizHandler(_FakeSource(bundle), store)
    finding = await handler.verify(_context(claim))
    assert finding.verdict == VerificationVerdict.SUPPORTED
    content = await store.read(
        tenant_id=TENANT,
        storage_namespace=finding.result_artifact.storage_namespace,
        object_key=finding.result_artifact.object_key,
        expected_byte_size=finding.result_artifact.byte_size,
        expected_sha256=finding.result_artifact.sha256,
    )
    artifact = json.loads(content)
    assert artifact["verification_result"]["answer_correct"] is True
    assert artifact["golden_question_id"] == "QUESTION_ATC_ROUTH_001"

    execution = await BoundedModuleExecutor(
        {VerificationModule.C5_QUIZ: handler},
        worker_instance_id="c5-test-worker",
        retry_backoff_ms=0,
    ).execute(
        _plan(claim),
        [claim],
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert execution.results[0].verdict == VerificationVerdict.SUPPORTED


@pytest.mark.asyncio
async def test_c5_handler_enforces_tenant_kind_evidence_and_authority_boundaries(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    valid = QuizEvidenceBundle(
        candidate, _snapshot(), (evidence,), evidence.knowledge_base_version_id
    )
    store = FileSystemArtifactObjectStore(tmp_path)

    tenant = await C5QuizHandler(_FakeSource(valid), store).verify(
        _context(claim, tenant_id="tenant-other")
    )
    assert "C5_TENANT_CONTEXT_MISMATCH" in tenant.finding_codes

    wrong_kind = claim.model_copy(update={"claim_kind": ClaimKind.TEXT})
    kind = await C5QuizHandler(_FakeSource(valid), store).verify(_context(wrong_kind))
    assert "C5_CLAIM_KIND_MISMATCH" in kind.finding_codes

    foreign = _evidence(claim, tenant_id="tenant-other")
    foreign_bundle = QuizEvidenceBundle(
        candidate, _snapshot(), (foreign,), foreign.knowledge_base_version_id
    )
    isolation = await C5QuizHandler(_FakeSource(foreign_bundle), store).verify(_context(claim))
    assert "C5_TENANT_ISOLATION_FAILED" in isolation.finding_codes

    tampered = await C5QuizHandler(
        _FakeSource(
            QuizEvidenceBundle(
                candidate,
                _snapshot().model_copy(update={"content_sha256": "f" * 64}),
                (evidence,),
                evidence.knowledge_base_version_id,
            )
        ),
        store,
    ).verify(_context(claim))
    assert "C5_TOPIC1_AUTHORITY_INTEGRITY_FAILED" in tampered.finding_codes


@pytest.mark.asyncio
async def test_c5_handler_missing_invalid_and_policy_boundaries(tmp_path: Path) -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    store = FileSystemArtifactObjectStore(tmp_path)
    missing_candidate = await C5QuizHandler(
        _FakeSource(QuizEvidenceBundle(None, None, ())),
        store,
    ).verify(_context(claim))
    assert missing_candidate.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE

    missing_snapshot = await C5QuizHandler(
        _FakeSource(QuizEvidenceBundle(candidate, None, ())),
        store,
    ).verify(_context(claim))
    assert "C5_TOPIC1_SNAPSHOT_MISSING" in missing_snapshot.finding_codes

    invalid = await C5QuizHandler(lambda claim: {"invalid": claim}, store).verify(_context(claim))
    assert "C5_HANDLER_VALIDATION_FAILED" in invalid.finding_codes
    with pytest.raises(ValueError):
        C5HandlerPolicy(max_evidence_count=0)
    with pytest.raises(ValueError):
        C5HandlerPolicy(max_artifact_bytes=0)

    malformed_claim = claim.model_copy(update={"json_pointer": "/invalid"})
    malformed = await C5QuizHandler(
        _FakeSource(QuizEvidenceBundle(candidate, _snapshot(), (), uuid4())),
        store,
    ).verify(_context(malformed_claim))
    assert "C5_QUIZ_CONTRACT_INVALID" in malformed.finding_codes

    async def fail(_claim: ClaimV1) -> QuizEvidenceBundle:
        raise RuntimeError("forced failure")

    unexpected = await C5QuizHandler(fail, store).verify(_context(claim))
    assert "C5_HANDLER_UNEXPECTED_ERROR" in unexpected.finding_codes


def test_c5_handler_bundle_validation_boundaries(tmp_path: Path) -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    handler = C5QuizHandler(
        _FakeSource(QuizEvidenceBundle(candidate, None, ())),
        FileSystemArtifactObjectStore(tmp_path),
        policy=C5HandlerPolicy(max_evidence_count=1),
    )
    with pytest.raises(ValueError, match="count"):
        handler._validate_bundle(
            claim,
            QuizEvidenceBundle(candidate, _snapshot(), (evidence, evidence), uuid4()),
        )
    with pytest.raises(ValueError, match="knowledge base binding"):
        handler._validate_bundle(claim, QuizEvidenceBundle(candidate, _snapshot(), ()))
    with pytest.raises(ValueError, match="candidate"):
        handler._validate_bundle(
            claim,
            QuizEvidenceBundle(_candidate(), None, ()),
        )
    duplicate_handler = C5QuizHandler(
        _FakeSource(QuizEvidenceBundle(candidate, None, ())),
        FileSystemArtifactObjectStore(tmp_path / "duplicates"),
        policy=C5HandlerPolicy(max_evidence_count=2),
    )
    with pytest.raises(ValueError, match="duplicate"):
        duplicate_handler._validate_bundle(
            claim,
            QuizEvidenceBundle(
                candidate,
                _snapshot(),
                (evidence, evidence),
                evidence.knowledge_base_version_id,
            ),
        )


@dataclass
class _FakeTransaction:
    session: object = object()

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *args: object) -> bool:
        return False


class _FakeDatabase:
    def transaction(self, *, context: object) -> _FakeTransaction:
        del context
        return _FakeTransaction()


@dataclass
class _FakeTopic3Repository:
    candidate: CandidateV1 | None

    async def get_candidate(self, *args: object) -> CandidateRecord | None:
        if self.candidate is None:
            return None
        return CandidateRecord(uuid4(), self.candidate, NOW)


@dataclass
class _FakeTopic1Repository:
    snapshot: Topic1GraphSnapshotV1 | None

    async def get_snapshot(self, *args: object) -> Topic1GraphSnapshotV1 | None:
        return self.snapshot


@dataclass
class _FakeKnowledgeRepository:
    bundle: EvidenceBundleV1 | None
    knowledge_base: KnowledgeBaseVersionV1 | None
    refs: list[EvidenceRefV1]

    async def latest_evidence_bundle(self, *args: object) -> EvidenceBundleV1 | None:
        return self.bundle

    async def get_knowledge_base_version(self, *args: object) -> KnowledgeBaseVersionV1 | None:
        return self.knowledge_base

    async def list_evidence_refs(self, *args: object) -> list[EvidenceRefV1]:
        return self.refs


def _evidence_bundle(claim: ClaimV1, evidence: EvidenceRefV1) -> EvidenceBundleV1:
    timing = build_topic4_record(
        RetrievalTimingV1,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="retrieval-timing.v1",
        bm25_ms=1,
        vector_ms=1,
        graph_ms=1,
        formula_ms=1,
        fusion_ms=1,
        total_ms=5,
    )
    return build_topic4_record(
        EvidenceBundleV1,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="evidence.bundle.v1",
        evidence_bundle_id=uuid4(),
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        query_plan_id=uuid4(),
        knowledge_base_version_id=evidence.knowledge_base_version_id,
        evidence_ref_ids=[evidence.evidence_ref_id],
        coverage_score=1.0,
        conflicting_evidence=False,
        retrieval_timing=timing,
        retrieval_pipeline_version="c5-test-rag-v1",
        degraded_reason_codes=[],
    )


def _knowledge_base(
    claim: ClaimV1,
    snapshot: Topic1GraphSnapshotV1,
    bundle: EvidenceBundleV1,
) -> KnowledgeBaseVersionV1:
    return build_topic4_record(
        KnowledgeBaseVersionV1,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="knowledge-base.version.v1",
        knowledge_base_version_id=bundle.knowledge_base_version_id,
        version="kb-c5-test-1",
        lifecycle=SourceLifecycle.ACTIVE,
        source_document_version_ids=[uuid4()],
        graph_snapshot_id=snapshot.snapshot_id,
        graph_snapshot_version=snapshot.graph_version,
        index_build_manifest_id=uuid4(),
        embedding_profile_id=uuid4(),
        activated_at=NOW,
        retired_at=None,
    )


@pytest.mark.asyncio
async def test_postgres_quiz_evidence_source_atomically_scopes_all_authorities() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    snapshot = _snapshot()
    bundle = _evidence_bundle(claim, evidence)
    source = PostgresQuizEvidenceSource(
        _FakeDatabase(),
        _FakeKnowledgeRepository(bundle, _knowledge_base(claim, snapshot, bundle), [evidence]),
        _FakeTopic1Repository(snapshot),
        _FakeTopic3Repository(candidate),
    )
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c5-test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )
    with tenant_scope(context):
        loaded = await source.load(claim)
    assert loaded.candidate == candidate
    assert loaded.snapshot == snapshot
    assert loaded.evidence == (evidence,)


@pytest.mark.asyncio
async def test_postgres_quiz_evidence_source_fails_closed_at_repository_boundaries() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    snapshot = _snapshot()
    bundle = _evidence_bundle(claim, evidence)
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c5-test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )

    async def load(
        knowledge: _FakeKnowledgeRepository,
        topic1: _FakeTopic1Repository,
        topic3: _FakeTopic3Repository,
    ) -> QuizEvidenceBundle:
        source = PostgresQuizEvidenceSource(_FakeDatabase(), knowledge, topic1, topic3)
        with tenant_scope(context):
            return await source.load(claim)

    no_bundle = await load(
        _FakeKnowledgeRepository(None, None, []),
        _FakeTopic1Repository(None),
        _FakeTopic3Repository(candidate),
    )
    assert no_bundle.snapshot is None
    assert no_bundle.candidate == candidate

    with pytest.raises(ValueError, match="knowledge base"):
        await load(
            _FakeKnowledgeRepository(bundle, None, [evidence]),
            _FakeTopic1Repository(snapshot),
            _FakeTopic3Repository(candidate),
        )
    with pytest.raises(ValueError, match="snapshot"):
        await load(
            _FakeKnowledgeRepository(bundle, _knowledge_base(claim, snapshot, bundle), [evidence]),
            _FakeTopic1Repository(None),
            _FakeTopic3Repository(candidate),
        )
    with pytest.raises(ValueError, match="unavailable evidence"):
        await load(
            _FakeKnowledgeRepository(bundle, _knowledge_base(claim, snapshot, bundle), []),
            _FakeTopic1Repository(snapshot),
            _FakeTopic3Repository(candidate),
        )
    with pytest.raises(ValueError, match="candidate"):
        await load(
            _FakeKnowledgeRepository(bundle, _knowledge_base(claim, snapshot, bundle), [evidence]),
            _FakeTopic1Repository(snapshot),
            _FakeTopic3Repository(_candidate()),
        )


def test_postgres_quiz_evidence_source_validates_candidate_and_evidence_integrity() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    PostgresQuizEvidenceSource._validate_candidate(None, claim)
    corrupt_candidate = candidate.model_copy(update={"candidate_sha256": "f" * 64})
    corrupt_claim = claim.model_copy(update={"candidate_sha256": "f" * 64})
    with pytest.raises(ValueError, match="integrity"):
        PostgresQuizEvidenceSource._validate_candidate(corrupt_candidate, corrupt_claim)

    cases = [
        (evidence.model_copy(update={"tenant_id": "other"}), "tenant"),
        (evidence.model_copy(update={"claim_id": uuid4()}), "Claim"),
        (evidence.model_copy(update={"trace_id": "e" * 32}), "Trace"),
        (
            evidence.model_copy(update={"knowledge_base_version_id": uuid4()}),
            "knowledge base",
        ),
        (evidence.model_copy(update={"record_sha256": "f" * 64}), "record integrity"),
    ]
    for invalid, message in cases:
        with pytest.raises(ValueError, match=message):
            PostgresQuizEvidenceSource._validate_evidence(
                (invalid,),
                claim,
                evidence.knowledge_base_version_id,
            )

    values = evidence.model_dump(mode="python", exclude={"record_sha256"})
    values["excerpt_sha256"] = "f" * 64
    invalid_excerpt = build_topic4_record(EvidenceRefV1, **values)
    with pytest.raises(ValueError, match="excerpt"):
        PostgresQuizEvidenceSource._validate_evidence(
            (invalid_excerpt,),
            claim,
            evidence.knowledge_base_version_id,
        )
    with pytest.raises(ValueError, match="duplicate"):
        PostgresQuizEvidenceSource._validate_evidence(
            (evidence, evidence),
            claim,
            evidence.knowledge_base_version_id,
        )


@pytest.mark.asyncio
async def test_postgres_quiz_evidence_source_rejects_bundle_and_snapshot_tampering() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    snapshot = _snapshot()
    bundle = _evidence_bundle(claim, evidence)
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c5-test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )

    async def load(
        bundle_value: EvidenceBundleV1,
        knowledge_base: KnowledgeBaseVersionV1,
        snapshot_value: Topic1GraphSnapshotV1,
        refs: list[EvidenceRefV1],
    ) -> None:
        source = PostgresQuizEvidenceSource(
            _FakeDatabase(),
            _FakeKnowledgeRepository(bundle_value, knowledge_base, refs),
            _FakeTopic1Repository(snapshot_value),
            _FakeTopic3Repository(candidate),
        )
        with tenant_scope(context):
            await source.load(claim)

    knowledge_base = _knowledge_base(claim, snapshot, bundle)
    with pytest.raises(ValueError, match="not bound"):
        await load(
            bundle.model_copy(update={"tenant_id": "other"}),
            knowledge_base,
            snapshot,
            [evidence],
        )
    with pytest.raises(ValueError, match="record integrity"):
        await load(
            bundle.model_copy(update={"record_sha256": "f" * 64}),
            knowledge_base,
            snapshot,
            [evidence],
        )
    with pytest.raises(ValueError, match="binding or integrity"):
        await load(
            bundle,
            knowledge_base.model_copy(update={"record_sha256": "f" * 64}),
            snapshot,
            [evidence],
        )
    with pytest.raises(ValueError, match="snapshot binding"):
        await load(
            bundle,
            knowledge_base,
            snapshot.model_copy(update={"graph_version": 99}),
            [evidence],
        )
    with pytest.raises(ValueError, match="duplicate references"):
        await load(bundle, knowledge_base, snapshot, [evidence, evidence])
