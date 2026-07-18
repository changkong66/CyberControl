from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import (
    CourseStatus,
    KnowledgePointStatus,
    PrerequisiteType,
    Topic1CourseV1,
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1KnowledgePointV1,
    Topic1PrerequisiteV1,
)
from liyans_contracts.topic4_c1 import (
    ClaimV1,
    ExtractionMethod,
    ModuleDispatchItemV1,
)
from liyans_contracts.topic4_c2 import (
    EvidenceBundleV1,
    EvidenceRefV1,
    KnowledgeBaseVersionV1,
    RetrievalTimingV1,
    SourceAuthorityTier,
    SourceLifecycle,
)
from liyans_contracts.topic4_common import ClaimKind, VerificationModule, VerificationVerdict

from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.graph.evidence_source import GraphEvidenceBundle, PostgresGraphEvidenceSource
from liyans.domains.graph.handler import C4GraphHandler, C4HandlerPolicy
from liyans.domains.graph.mermaid import (
    BoundedMermaidParser,
    MermaidPolicy,
    MermaidSecurityError,
    MermaidSyntaxError,
)
from liyans.domains.graph.verifier import GraphIntegrityError, Topic1GraphVerifier
from liyans.domains.verification.execution import BoundedModuleExecutor, ModuleExecutionContext
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
TENANT = "tenant-c4"
TRACE = "a" * 32
COURSE_ID = "CRS_ATC_001"


def _point(kp_id: str, title: str, *, aliases: list[str] | None = None) -> Topic1KnowledgePointV1:
    return Topic1KnowledgePointV1(
        kp_id=kp_id,
        course_id=COURSE_ID,
        revision=1,
        title=title,
        aliases=aliases or [],
        summary=f"Summary for {title}",
        learning_objectives=[f"Understand {title}"],
        category="CONTROL",
        difficulty_level=2,
        difficulty_score=0.4,
        topology_level=1,
        topology_weight=0.5,
        estimated_minutes=30,
        status=KnowledgePointStatus.ACTIVE,
        formula_signatures=[],
        tags=["control"],
        authority_sources=[],
        created_at=NOW,
        updated_at=NOW,
    )


def _snapshot(*, cycle: bool = False, ambiguous: bool = False) -> Topic1GraphSnapshotV1:
    course = Topic1CourseV1(
        course_id=COURSE_ID,
        revision=1,
        course_code="ATC101",
        title="Automatic Control",
        description="Authoritative control course",
        credit_hours=3,
        status=CourseStatus.ACTIVE,
        authority_sources=[],
        created_at=NOW,
        updated_at=NOW,
    )
    points = [
        _point("KP_ATC_A", "Plant", aliases=["对象"]),
        _point("KP_ATC_B", "Stability", aliases=["稳定性"]),
        _point("KP_ATC_C", "Controller", aliases=["稳定性"] if ambiguous else []),
    ]
    edges = [
        Topic1PrerequisiteV1(
            edge_id="EDGE_ATC_A_B",
            course_id=COURSE_ID,
            prerequisite_kp_id="KP_ATC_A",
            dependent_kp_id="KP_ATC_B",
            relation_type=PrerequisiteType.REQUIRED,
            strength=1.0,
            rationale="Plant precedes stability",
            revision=1,
            created_at=NOW,
            updated_at=NOW,
        )
    ]
    if cycle:
        edges.append(
            Topic1PrerequisiteV1(
                edge_id="EDGE_ATC_B_A",
                course_id=COURSE_ID,
                prerequisite_kp_id="KP_ATC_B",
                dependent_kp_id="KP_ATC_A",
                relation_type=PrerequisiteType.REQUIRED,
                strength=1.0,
                rationale="Injected cycle",
                revision=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    content = Topic1GraphContentV1(
        course=course,
        knowledge_points=points,
        prerequisites=edges,
        misconceptions=[],
        textbooks=[],
        textbook_sections=[],
        textbook_mappings=[],
        golden_questions=[],
    )
    return Topic1GraphSnapshotV1(
        snapshot_id=uuid4(),
        course_id=COURSE_ID,
        graph_version=1,
        content=content,
        content_sha256=canonical_sha256(content.model_dump(mode="json")),
        node_count=len(points),
        edge_count=len(edges),
        created_by_subject="system:c4-test",
        frozen_at=NOW,
    )


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
        block_id="mindmap-graph",
        claim_kind=ClaimKind.GRAPH,
        claim_subtype="mermaid_graph",
        statement=statement,
        normalized_statement=statement,
        json_pointer="/blocks/0/content/mermaid",
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
        section_id="c4-test",
        citation="Topic1 authoritative graph snapshot",
        excerpt=excerpt,
        excerpt_sha256=canonical_sha256(excerpt),
        bm25_score=1.0,
        vector_score=1.0,
        graph_score=1.0,
        formula_score=0.0,
        fused_score=1.0,
        source_authority_tier=SourceAuthorityTier.PRIMARY_STANDARD,
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
        module=VerificationModule.C4_GRAPH,
        required=True,
        priority=1,
        dependency_item_ids=[],
        timeout_ms=3000,
        max_attempts=1,
    )
    return ModuleExecutionContext(
        verification_id=claim.verification_id,
        dispatch_plan_id=uuid4(),
        dispatch_item=item,
        claim=claim,
        module_run_id=uuid4(),
        attempt=1,
        deadline_at=NOW + timedelta(minutes=1),
    )


def _mermaid(*, edge: str = "K0 --> K1", include_third: bool = False) -> str:
    lines = [
        "graph TD",
        '    K0["Plant"]',
        '    K1["Stability"]',
    ]
    if include_third:
        lines.append('    K2["Controller"]')
    lines.append(f"    {edge}")
    lines.extend(
        [
            "    classDef current fill:#fff3bf,stroke:#b7791f,color:#1a202c",
            "    class K1 current",
        ]
    )
    return "\n".join(lines)


def test_bounded_mermaid_parser_accepts_topic3_output_and_code_fences() -> None:
    parser = BoundedMermaidParser()
    parsed = parser.parse(f"```mermaid\n{_mermaid()}\n```")
    assert parsed.direction == "TD"
    assert [node.node_id for node in parsed.nodes] == ["K0", "K1"]
    assert parsed.edges[0].relation.value == "PREREQUISITE"
    assert parsed.edges[0].directed is True


def test_bounded_mermaid_parser_supports_relations_and_implicit_nodes() -> None:
    parsed = BoundedMermaidParser().parse("flowchart LR\nA ==> B\nB --- C\nC -->|CONTAINS| D")
    assert parsed.direction == "LR"
    assert {node.node_id for node in parsed.nodes} == {"A", "B", "C", "D"}
    assert [edge.relation.value for edge in parsed.edges] == [
        "DERIVES",
        "CONTRASTS",
        "CONTAINS",
    ]
    assert parsed.edges[1].directed is False


@pytest.mark.parametrize(
    "source",
    [
        "graph TD\nA --> A",
        'graph TD\nA["x"]\nA["y"]',
        'graph TD\nA["x"]\nA --> B\nA --> B',
        'graph TD\nclick A "https://evil.test"',
        'graph TD\nA["<script>alert(1)</script>"]',
        'graph XX\nA["x"]',
        'graph TD\nsubgraph X\nA["x"]',
    ],
)
def test_bounded_mermaid_parser_rejects_malformed_or_unsafe_graphs(source: str) -> None:
    with pytest.raises((MermaidSyntaxError, MermaidSecurityError)):
        BoundedMermaidParser().parse(source)


def test_mermaid_policy_rejects_unbounded_limits() -> None:
    for kwargs in (
        {"max_chars": 0},
        {"max_lines": 0},
        {"max_nodes": 0},
        {"max_edges": 0},
        {"max_label_chars": 0},
        {"max_subgraph_depth": 0},
    ):
        with pytest.raises(ValueError):
            MermaidPolicy(**kwargs)
    with pytest.raises(MermaidSecurityError):
        BoundedMermaidParser(MermaidPolicy(max_chars=8)).parse('graph TD\nA["x"]')


def test_bounded_mermaid_parser_covers_shapes_directives_and_limits() -> None:
    source = "\n".join(
        [
            "graph TD",
            "%% safe comment",
            "direction LR",
            "accTitle: Control graph",
            "accDescr: bounded graph",
            "A[[subroutine]]",
            "B((circle))",
            "C{{hexagon}}",
            "D(round)",
            "E{diamond}",
            "A --> B",
            "B --> C",
            "C --> D",
            "D --> E",
            "classDef focus fill:#fff,stroke:#000",
            "class A,B focus",
            "style C fill:#fff",
            "linkStyle 0 stroke:#000",
        ]
    )
    parsed = BoundedMermaidParser().parse(source)
    assert parsed.direction == "TD"
    assert {node.node_type for node in parsed.nodes} >= {
        "SUBROUTINE",
        "CIRCLE",
        "HEXAGON",
        "ROUND",
        "DIAMOND",
    }
    with pytest.raises(MermaidSyntaxError):
        BoundedMermaidParser().parse('not-a-header\nA["x"]')
    with pytest.raises(MermaidSyntaxError):
        BoundedMermaidParser().parse("graph TD\nend")
    with pytest.raises(MermaidSyntaxError):
        BoundedMermaidParser().parse('graph TD\ndirection XX\nA["x"]')
    with pytest.raises(MermaidSyntaxError):
        BoundedMermaidParser().parse("graph TD\naccDescr: \x01")
    with pytest.raises(MermaidSecurityError):
        BoundedMermaidParser().parse("graph TD\nclassDef focus fill:url(x)")
    with pytest.raises(MermaidSyntaxError):
        BoundedMermaidParser().parse("graph TD\nA[]")
    with pytest.raises(MermaidSyntaxError):
        BoundedMermaidParser().parse('graph TD\nA["x"]\nA -->|UNKNOWN| B')
    with pytest.raises(MermaidSecurityError):
        BoundedMermaidParser(MermaidPolicy(max_lines=1)).parse('graph TD\nA["x"]')
    with pytest.raises(MermaidSecurityError):
        BoundedMermaidParser(MermaidPolicy(max_nodes=1)).parse('graph TD\nA["x"]\nB["y"]')
    with pytest.raises(MermaidSecurityError):
        BoundedMermaidParser(MermaidPolicy(max_edges=1)).parse("graph TD\nA --> B\nB --> C")


def test_topic1_verifier_supports_labels_and_binds_deterministic_node_ids() -> None:
    claim = _claim(_mermaid())
    parsed = BoundedMermaidParser().parse(claim.normalized_statement)
    evidence = _evidence(claim, "Topic1 prerequisite Plant -> Stability")
    analysis = Topic1GraphVerifier().verify(
        parsed,
        _snapshot(),
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        candidate_id=claim.candidate_id,
        candidate_version=claim.candidate_version,
        block_id=claim.block_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        evidence_ref_ids=(evidence.evidence_ref_id,),
    )
    assert analysis.result.verdict == VerificationVerdict.SUPPORTED
    assert analysis.result.unknown_topic1_node_ids == []
    assert analysis.result.topology_mismatch_codes == []
    assert analysis.graph_ir.nodes[0].topic1_knowledge_point_id is not None
    assert analysis.graph_ir.nodes[0].record_sha256


def test_topic1_verifier_fails_closed_for_unverifiable_relations_and_id_label_mismatch() -> None:
    relation_claim = _claim('graph TD\nA["Plant"]\nC["Controller"]\nA -->|CONTAINS| C')
    relation_evidence = _evidence(relation_claim, "graph relation")
    relation_result = Topic1GraphVerifier().verify(
        BoundedMermaidParser().parse(relation_claim.normalized_statement),
        _snapshot(),
        verification_id=relation_claim.verification_id,
        claim_id=relation_claim.claim_id,
        candidate_id=relation_claim.candidate_id,
        candidate_version=1,
        block_id=relation_claim.block_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        evidence_ref_ids=(relation_evidence.evidence_ref_id,),
    )
    assert relation_result.result.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert "RELATION_NOT_VERIFIABLE_FROM_TOPIC1" in (relation_result.result.topology_mismatch_codes)

    mismatch_claim = _claim('graph TD\nKP_ATC_A["Stability"]')
    mismatch_evidence = _evidence(mismatch_claim, "graph node")
    mismatch_result = Topic1GraphVerifier().verify(
        BoundedMermaidParser().parse(mismatch_claim.normalized_statement),
        _snapshot(),
        verification_id=mismatch_claim.verification_id,
        claim_id=mismatch_claim.claim_id,
        candidate_id=mismatch_claim.candidate_id,
        candidate_version=1,
        block_id=mismatch_claim.block_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        evidence_ref_ids=(mismatch_evidence.evidence_ref_id,),
    )
    assert mismatch_result.result.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert "TOPIC1_NODE_ID_LABEL_MISMATCH" in (mismatch_result.result.topology_mismatch_codes)


def test_topic1_verifier_detects_unknown_omitted_reverse_and_cycles() -> None:
    parser = BoundedMermaidParser()
    claim = _claim(_mermaid(edge="K1 --> K0", include_third=True))
    evidence = _evidence(claim, "Topic1 graph evidence")
    reversed_result = Topic1GraphVerifier().verify(
        parser.parse(claim.normalized_statement),
        _snapshot(),
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        candidate_id=claim.candidate_id,
        candidate_version=1,
        block_id=claim.block_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        evidence_ref_ids=(evidence.evidence_ref_id,),
    )
    assert reversed_result.result.verdict == VerificationVerdict.CONTRADICTED
    assert "PREREQUISITE_EDGE_NOT_IN_TOPIC1" in reversed_result.result.topology_mismatch_codes

    omitted_claim = _claim(_mermaid(edge="K0 --- K1"))
    omitted_result = Topic1GraphVerifier().verify(
        parser.parse(omitted_claim.normalized_statement),
        _snapshot(),
        verification_id=omitted_claim.verification_id,
        claim_id=omitted_claim.claim_id,
        candidate_id=omitted_claim.candidate_id,
        candidate_version=1,
        block_id=omitted_claim.block_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        evidence_ref_ids=(_evidence(omitted_claim, "graph").evidence_ref_id,),
    )
    assert omitted_result.result.verdict == VerificationVerdict.CONTRADICTED
    assert "TOPIC1_PREREQUISITE_OMITTED" in omitted_result.result.topology_mismatch_codes

    cycle_claim = _claim('graph TD\nA["Plant"]\nB["Stability"]\nA --> B\nB --> A')
    cycle_result = Topic1GraphVerifier().verify(
        parser.parse(cycle_claim.normalized_statement),
        _snapshot(cycle=True),
        verification_id=cycle_claim.verification_id,
        claim_id=cycle_claim.claim_id,
        candidate_id=cycle_claim.candidate_id,
        candidate_version=1,
        block_id=cycle_claim.block_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        evidence_ref_ids=(_evidence(cycle_claim, "cycle").evidence_ref_id,),
    )
    assert cycle_result.result.prerequisite_subgraph_acyclic is False
    assert cycle_result.result.verdict == VerificationVerdict.CONTRADICTED


def test_topic1_verifier_fails_closed_on_ambiguous_or_tampered_snapshot() -> None:
    claim = _claim('graph TD\nK0["Plant"]\nK1["稳定性"]\nK0 --> K1')
    evidence = _evidence(claim, "graph")
    result = Topic1GraphVerifier().verify(
        BoundedMermaidParser().parse(claim.normalized_statement),
        _snapshot(ambiguous=True),
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        candidate_id=claim.candidate_id,
        candidate_version=1,
        block_id=claim.block_id,
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
        evidence_ref_ids=(evidence.evidence_ref_id,),
    )
    assert result.result.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert "AMBIGUOUS_TOPIC1_LABEL" in result.result.topology_mismatch_codes
    with pytest.raises(GraphIntegrityError):
        Topic1GraphVerifier().verify(
            BoundedMermaidParser().parse(claim.normalized_statement),
            _snapshot().model_copy(update={"content_sha256": "f" * 64}),
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            candidate_id=claim.candidate_id,
            candidate_version=1,
            block_id=claim.block_id,
            trace_id=TRACE,
            tenant_id=TENANT,
            created_at=NOW,
            evidence_ref_ids=(evidence.evidence_ref_id,),
        )


@dataclass
class _FakeGraphSource:
    bundle: GraphEvidenceBundle

    async def load(
        self,
        *,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> GraphEvidenceBundle:
        assert tenant_id == TENANT
        if self.bundle.evidence:
            assert verification_id == self.bundle.evidence[0].verification_id
            assert claim_id == self.bundle.evidence[0].claim_id
        return self.bundle


@pytest.mark.asyncio
async def test_c4_handler_writes_replayable_artifact_and_works_with_c1_executor(
    tmp_path: Path,
) -> None:
    statement = _mermaid()
    claim = _claim(statement)
    evidence = _evidence(claim, "Topic1 prerequisite Plant -> Stability")
    store = FileSystemArtifactObjectStore(tmp_path)
    source = _FakeGraphSource(
        GraphEvidenceBundle(
            snapshot=_snapshot(),
            evidence=(evidence,),
            knowledge_base_version_id=evidence.knowledge_base_version_id,
        )
    )
    handler = C4GraphHandler(source, store)
    finding = await handler.verify(_context(claim))
    assert finding.verdict == VerificationVerdict.SUPPORTED
    assert finding.result_artifact.object_key.endswith(f"{finding.result_sha256}.json")
    content = await store.read(
        tenant_id=TENANT,
        storage_namespace=finding.result_artifact.storage_namespace,
        object_key=finding.result_artifact.object_key,
        expected_byte_size=finding.result_artifact.byte_size,
        expected_sha256=finding.result_artifact.sha256,
    )
    document = json.loads(content)
    assert document["verification_result"]["verdict"] == "SUPPORTED"
    assert document["topic1_snapshot"]["graph_version"] == 1

    bundle = await BoundedModuleExecutor(
        {VerificationModule.C4_GRAPH: handler},
        worker_instance_id="c4-test-worker",
        retry_backoff_ms=0,
    ).execute(
        _plan_for_claim(claim),
        [claim],
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert len(bundle.results) == 1
    assert bundle.results[0].verdict == VerificationVerdict.SUPPORTED


def _plan_for_claim(claim: ClaimV1):
    from liyans_contracts.topic4_c1 import ModuleDispatchPlanV1

    item = _context(claim).dispatch_item
    return build_topic4_record(
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
        policy_version="c4-test-v1",
        plan_sha256="c" * 64,
    )


@pytest.mark.asyncio
async def test_c4_handler_rejects_cross_tenant_and_unsafe_inputs(tmp_path: Path) -> None:
    claim = _claim(_mermaid())
    foreign = _evidence(claim, "graph", tenant_id="tenant-foreign")
    foreign_source = _FakeGraphSource(
        GraphEvidenceBundle(_snapshot(), (foreign,), foreign.knowledge_base_version_id)
    )
    foreign_finding = await C4GraphHandler(
        foreign_source, FileSystemArtifactObjectStore(tmp_path / "foreign")
    ).verify(_context(claim))
    assert foreign_finding.verdict == VerificationVerdict.UNSAFE
    assert "C4_TENANT_ISOLATION_FAILED" in foreign_finding.finding_codes

    unsafe_claim = _claim('graph TD\nclick K0 "javascript:alert(1)"')
    safe_evidence = _evidence(unsafe_claim, "graph")
    unsafe_source = _FakeGraphSource(
        GraphEvidenceBundle(
            _snapshot(),
            (safe_evidence,),
            safe_evidence.knowledge_base_version_id,
        )
    )
    unsafe_finding = await C4GraphHandler(
        unsafe_source, FileSystemArtifactObjectStore(tmp_path / "unsafe")
    ).verify(_context(unsafe_claim))
    assert unsafe_finding.verdict == VerificationVerdict.UNSAFE
    assert "C4_MERMAID_SECURITY_POLICY" in unsafe_finding.finding_codes


@pytest.mark.asyncio
async def test_c4_handler_downgrades_missing_authoritative_evidence(tmp_path: Path) -> None:
    claim = _claim(_mermaid())
    source = _FakeGraphSource(GraphEvidenceBundle(_snapshot(), (), uuid4()))
    finding = await C4GraphHandler(source, FileSystemArtifactObjectStore(tmp_path)).verify(
        _context(claim)
    )
    assert finding.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert "C4_TOPIC1_SNAPSHOT_MISSING" not in finding.finding_codes


@pytest.mark.asyncio
async def test_c4_handler_fail_closed_boundaries_and_callable_loader(tmp_path: Path) -> None:
    claim = _claim(_mermaid())
    evidence = _evidence(claim, "graph")
    bundle = GraphEvidenceBundle(
        _snapshot(),
        (evidence,),
        evidence.knowledge_base_version_id,
    )

    async def loader(**kwargs: object) -> GraphEvidenceBundle:
        assert kwargs["tenant_id"] == TENANT
        return bundle

    finding = await C4GraphHandler(
        loader, FileSystemArtifactObjectStore(tmp_path / "callable")
    ).verify(_context(claim))
    assert finding.verdict == VerificationVerdict.SUPPORTED

    with pytest.raises(ValueError):
        C4HandlerPolicy(max_artifact_bytes=0)

    wrong_kind = claim.model_copy(update={"claim_kind": ClaimKind.TEXT})
    wrong_kind_finding = await C4GraphHandler(
        _FakeGraphSource(bundle), FileSystemArtifactObjectStore(tmp_path / "kind")
    ).verify(_context(wrong_kind))
    assert "C4_CLAIM_KIND_MISMATCH" in wrong_kind_finding.finding_codes

    mismatched_context = _context(claim)
    mismatched_item = mismatched_context.dispatch_item.model_copy(update={"tenant_id": "other"})
    mismatched_context = mismatched_context.__class__(
        verification_id=mismatched_context.verification_id,
        dispatch_plan_id=mismatched_context.dispatch_plan_id,
        dispatch_item=mismatched_item,
        claim=mismatched_context.claim,
        module_run_id=mismatched_context.module_run_id,
        attempt=mismatched_context.attempt,
        deadline_at=mismatched_context.deadline_at,
    )
    tenant_finding = await C4GraphHandler(
        _FakeGraphSource(bundle), FileSystemArtifactObjectStore(tmp_path / "tenant")
    ).verify(mismatched_context)
    assert "C4_TENANT_CONTEXT_MISMATCH" in tenant_finding.finding_codes

    knowledge_base_mismatch = await C4GraphHandler(
        _FakeGraphSource(GraphEvidenceBundle(_snapshot(), (evidence,), uuid4())),
        FileSystemArtifactObjectStore(tmp_path / "knowledge-base"),
    ).verify(_context(claim))
    assert "C4_KNOWLEDGE_BASE_BINDING_FAILED" in knowledge_base_mismatch.finding_codes

    missing_snapshot = await C4GraphHandler(
        _FakeGraphSource(
            GraphEvidenceBundle(None, (evidence,), evidence.knowledge_base_version_id)
        ),
        FileSystemArtifactObjectStore(tmp_path / "missing"),
    ).verify(_context(claim))
    assert missing_snapshot.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE

    malformed = _claim('graph TD\nA["Plant"]\nA --> A')
    malformed_evidence = _evidence(malformed, "graph")
    malformed_finding = await C4GraphHandler(
        _FakeGraphSource(
            GraphEvidenceBundle(
                _snapshot(),
                (malformed_evidence,),
                malformed_evidence.knowledge_base_version_id,
            )
        ),
        FileSystemArtifactObjectStore(tmp_path / "malformed"),
    ).verify(_context(malformed))
    assert "C4_MERMAID_SYNTAX_INVALID" in malformed_finding.finding_codes

    tampered = await C4GraphHandler(
        _FakeGraphSource(
            GraphEvidenceBundle(
                _snapshot().model_copy(update={"content_sha256": "f" * 64}),
                (evidence,),
                evidence.knowledge_base_version_id,
            )
        ),
        FileSystemArtifactObjectStore(tmp_path / "tampered"),
    ).verify(_context(claim))
    assert "C4_TOPIC1_SNAPSHOT_INTEGRITY" in tampered.finding_codes

    invalid_source = await C4GraphHandler(
        lambda **kwargs: {"not": "a bundle"},
        FileSystemArtifactObjectStore(tmp_path / "invalid"),
    ).verify(_context(claim))
    assert "C4_HANDLER_VALIDATION_FAILED" in invalid_source.finding_codes


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


@dataclass
class _FakeTopic1Repository:
    snapshot: Topic1GraphSnapshotV1 | None

    async def get_snapshot(self, *args: object) -> Topic1GraphSnapshotV1 | None:
        return self.snapshot


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
        formula_ms=0,
        fusion_ms=1,
        total_ms=4,
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
        retrieval_pipeline_version="c4-test-rag-v1",
        degraded_reason_codes=[],
    )


def _knowledge_base(claim: ClaimV1, snapshot: Topic1GraphSnapshotV1, bundle: EvidenceBundleV1):
    return build_topic4_record(
        KnowledgeBaseVersionV1,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="knowledge-base.version.v1",
        knowledge_base_version_id=bundle.knowledge_base_version_id,
        version="kb-c4-test-1",
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
async def test_postgres_graph_evidence_source_scopes_bundle_snapshot_and_evidence() -> None:
    claim = _claim(_mermaid())
    evidence = _evidence(claim, "graph")
    snapshot = _snapshot()
    bundle = _evidence_bundle(claim, evidence)
    database = _FakeDatabase()
    repository = _FakeKnowledgeRepository(
        bundle, _knowledge_base(claim, snapshot, bundle), [evidence]
    )
    topic1 = _FakeTopic1Repository(snapshot)
    adapter = PostgresGraphEvidenceSource(database, repository, topic1)
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c4-test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )
    with tenant_scope(context):
        loaded = await adapter.load(
            tenant_id=TENANT,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
        )
    assert loaded.snapshot == snapshot
    assert loaded.evidence == (evidence,)
    assert loaded.knowledge_base_version_id == bundle.knowledge_base_version_id


@pytest.mark.asyncio
async def test_postgres_graph_evidence_source_fail_closed_repository_boundaries() -> None:
    claim = _claim(_mermaid())
    evidence = _evidence(claim, "graph")
    snapshot = _snapshot()
    bundle = _evidence_bundle(claim, evidence)
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c4-test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )

    async def load(repository: _FakeKnowledgeRepository, topic1: _FakeTopic1Repository):
        adapter = PostgresGraphEvidenceSource(_FakeDatabase(), repository, topic1)
        with tenant_scope(context):
            return await adapter.load(
                tenant_id=TENANT,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )

    assert (
        await load(_FakeKnowledgeRepository(None, None, []), _FakeTopic1Repository(None))
    ).snapshot is None
    with pytest.raises(ValueError, match="knowledge base"):
        await load(
            _FakeKnowledgeRepository(bundle, None, [evidence]), _FakeTopic1Repository(snapshot)
        )
    with pytest.raises(ValueError, match="integrity"):
        await load(
            _FakeKnowledgeRepository(
                bundle.model_copy(update={"record_sha256": "f" * 64}),
                _knowledge_base(claim, snapshot, bundle),
                [evidence],
            ),
            _FakeTopic1Repository(snapshot),
        )
    with pytest.raises(ValueError, match="snapshot"):
        await load(
            _FakeKnowledgeRepository(bundle, _knowledge_base(claim, snapshot, bundle), [evidence]),
            _FakeTopic1Repository(None),
        )
    with pytest.raises(ValueError, match="integrity"):
        await load(
            _FakeKnowledgeRepository(
                bundle,
                _knowledge_base(claim, snapshot, bundle).model_copy(
                    update={"record_sha256": "f" * 64}
                ),
                [evidence],
            ),
            _FakeTopic1Repository(snapshot),
        )
    wrong_version_values = _knowledge_base(claim, snapshot, bundle).model_dump(
        mode="python",
        exclude={"record_sha256"},
    )
    wrong_version_values["graph_snapshot_version"] = 99
    wrong_version = build_topic4_record(KnowledgeBaseVersionV1, **wrong_version_values)
    with pytest.raises(ValueError, match="version"):
        await load(
            _FakeKnowledgeRepository(bundle, wrong_version, [evidence]),
            _FakeTopic1Repository(snapshot),
        )
    wrong_binding_values = _knowledge_base(claim, snapshot, bundle).model_dump(
        mode="python",
        exclude={"record_sha256"},
    )
    wrong_binding_values["knowledge_base_version_id"] = uuid4()
    wrong_binding = build_topic4_record(KnowledgeBaseVersionV1, **wrong_binding_values)
    with pytest.raises(ValueError, match="evidence bundle"):
        await load(
            _FakeKnowledgeRepository(bundle, wrong_binding, [evidence]),
            _FakeTopic1Repository(snapshot),
        )
    with pytest.raises(ValueError, match="bound to the knowledge base"):
        await load(
            _FakeKnowledgeRepository(
                bundle,
                _knowledge_base(claim, snapshot, bundle),
                [evidence],
            ),
            _FakeTopic1Repository(snapshot.model_copy(update={"snapshot_id": uuid4()})),
        )
    with pytest.raises(ValueError, match="unavailable evidence"):
        await load(
            _FakeKnowledgeRepository(bundle, _knowledge_base(claim, snapshot, bundle), []),
            _FakeTopic1Repository(snapshot),
        )
    with pytest.raises(ValueError, match="duplicate"):
        await load(
            _FakeKnowledgeRepository(
                bundle,
                _knowledge_base(claim, snapshot, bundle),
                [evidence, evidence],
            ),
            _FakeTopic1Repository(snapshot),
        )


def test_postgres_graph_evidence_source_validates_evidence_integrity() -> None:
    claim = _claim(_mermaid())
    evidence = _evidence(claim, "graph")
    with pytest.raises(ValueError, match="tenant"):
        PostgresGraphEvidenceSource._validate_evidence(
            (evidence.model_copy(update={"tenant_id": "other"}),),
            TENANT,
            claim.verification_id,
            claim.claim_id,
        )
    with pytest.raises(ValueError, match="integrity"):
        PostgresGraphEvidenceSource._validate_evidence(
            (evidence.model_copy(update={"record_sha256": "f" * 64}),),
            TENANT,
            claim.verification_id,
            claim.claim_id,
        )
    with pytest.raises(ValueError, match="claim"):
        PostgresGraphEvidenceSource._validate_evidence(
            (evidence,),
            TENANT,
            uuid4(),
            claim.claim_id,
        )
    with pytest.raises(ValueError, match="trace"):
        PostgresGraphEvidenceSource._validate_evidence(
            (evidence,),
            TENANT,
            claim.verification_id,
            claim.claim_id,
            trace_id="b" * 32,
        )
    with pytest.raises(ValueError, match="knowledge base version"):
        PostgresGraphEvidenceSource._validate_evidence(
            (evidence,),
            TENANT,
            claim.verification_id,
            claim.claim_id,
            knowledge_base_version_id=uuid4(),
        )
    with pytest.raises(ValueError, match="excerpt"):
        values = evidence.model_dump(mode="python", exclude={"record_sha256"})
        values["excerpt_sha256"] = "f" * 64
        tampered_excerpt = build_topic4_record(EvidenceRefV1, **values)
        PostgresGraphEvidenceSource._validate_evidence(
            (tampered_excerpt,),
            TENANT,
            claim.verification_id,
            claim.claim_id,
        )
    with pytest.raises(ValueError, match="duplicate"):
        PostgresGraphEvidenceSource._validate_evidence(
            (evidence, evidence),
            TENANT,
            claim.verification_id,
            claim.claim_id,
        )
