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
    ExtensionContentV1,
    ExtensionResourceV1,
)
from liyans_contracts.topic4_c1 import ClaimV1, ModuleDispatchItemV1, ModuleDispatchPlanV1
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
from liyans.domains.extension.evidence_source import (
    ExtensionEvidenceBundle,
    PostgresExtensionEvidenceSource,
)
from liyans.domains.extension.handler import C7ExtensionHandler, C7HandlerPolicy
from liyans.domains.extension.parser import ExtensionParseError, FrozenExtensionParser
from liyans.domains.extension.verifier import Topic1ExtensionVerifier
from liyans.domains.topic3.entities import CandidateRecord
from liyans.domains.verification.claim_extraction import DeterministicClaimExtractor
from liyans.domains.verification.execution import BoundedModuleExecutor, ModuleExecutionContext
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
TENANT = "tenant-c7"
TRACE = "7" * 32


def _snapshot() -> Topic1GraphSnapshotV1:
    root = Path(__file__).resolve().parents[2]
    document = json.loads(
        (root / "data/topic1/automatic-control-principles.v1.json").read_text(encoding="utf-8")
    )
    content = Topic1ImportBundleV1.model_validate(document).content
    return Topic1GraphSnapshotV1(
        snapshot_id=uuid4(),
        course_id=content.course.course_id,
        graph_version=1,
        content=content,
        content_sha256=canonical_sha256(content.model_dump(mode="json")),
        node_count=len(content.knowledge_points),
        edge_count=len(content.prerequisites),
        created_by_subject="system:c7-test",
        frozen_at=NOW,
    )


def _candidate(
    snapshot: Topic1GraphSnapshotV1 | None = None,
    *,
    citation: str | None = None,
) -> CandidateV1:
    snapshot = snapshot or _snapshot()
    point = snapshot.content.knowledge_points[0]
    citation_value = citation or f"{point.title} authority study 2024 CC BY-4.0"
    resource = ExtensionResourceV1(
        resource_id="extension-1",
        resource_kind="PAPER",
        title=point.title,
        summary=point.summary,
        relevance_to_kp_ids=[point.kp_id],
        citation_text=citation_value,
        source_url="https://authority.example/paper-1",
    )
    content = ExtensionContentV1(
        schema_version="topic3.extension-content.v1",
        title="Automatic control extension resources",
        resources=[resource],
        recommended_sequence=[resource.resource_id],
    ).model_dump(mode="json")
    block = BlockV1(
        schema_version="topic3.block.v1",
        block_id="extension-block",
        block_type=BlockType.EXTENSION,
        ordinal=0,
        title="Extension resources",
        content_schema_version="topic3.extension-content.v1",
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
        resource_type=ResourceType.EXTENSION_MATERIAL,
        status=CandidateStatus.COMPLETE,
        blocks=[block],
        provenance=CandidateProvenanceV1(
            agent=SourceAgent.EXTENSION,
            agent_build_version="topic3.extension.accepted.v1",
            prompt_bundle_version="prompt.extension.v1",
            provider_alias="local",
            provider_request_ids=[],
        ),
        personalization_policy_digest="c" * 64,
        candidate_sha256="0" * 64,
        created_at=NOW,
    )
    document = draft.model_dump(mode="json", exclude={"candidate_sha256"})
    return CandidateV1(**document, candidate_sha256=canonical_sha256(document))


def _claim(candidate: CandidateV1) -> ClaimV1:
    claims = DeterministicClaimExtractor().extract(
        candidate,
        verification_id=uuid4(),
        trace_id=TRACE,
        tenant_id=TENANT,
        created_at=NOW,
    )
    return next(claim for claim in claims if claim.json_pointer.endswith("/citation_text"))


def _evidence(
    claim: ClaimV1,
    *,
    citation: str | None = None,
    excerpt: str | None = None,
) -> EvidenceRefV1:
    citation_value = citation or "Automatic control authority study 2024 CC BY-4.0"
    excerpt_value = excerpt or citation_value
    return build_topic4_record(
        EvidenceRefV1,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
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
        section_id="c7-test",
        citation=citation_value,
        excerpt=excerpt_value,
        excerpt_sha256=canonical_sha256(excerpt_value),
        bm25_score=1.0,
        vector_score=1.0,
        graph_score=1.0,
        formula_score=1.0,
        fused_score=1.0,
        source_authority_tier=SourceAuthorityTier.PRIMARY_STANDARD,
    )


def _context(claim: ClaimV1, *, tenant_id: str = TENANT) -> ModuleExecutionContext:
    item = build_topic4_record(
        ModuleDispatchItemV1,
        trace_id=claim.trace_id,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="module-dispatch-item.v1",
        dispatch_item_id=uuid4(),
        claim_id=claim.claim_id,
        module=VerificationModule.C7_EXTENSION,
        required=True,
        priority=1,
        dependency_item_ids=[],
        timeout_ms=30_000,
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


def _bundle(candidate: CandidateV1, claim: ClaimV1) -> ExtensionEvidenceBundle:
    citation = candidate.blocks[0].content["resources"][0]["citation_text"]
    evidence = _evidence(claim, citation=citation)
    return ExtensionEvidenceBundle(
        candidate=candidate,
        snapshot=_snapshot(),
        evidence=(evidence,),
        knowledge_base_version_id=evidence.knowledge_base_version_id,
    )


class _FakeSource:
    def __init__(self, bundle: ExtensionEvidenceBundle) -> None:
        self.bundle = bundle

    async def load(self, claim: ClaimV1) -> ExtensionEvidenceBundle:
        del claim
        return self.bundle


def test_c7_parser_reconstructs_exact_resource_and_rejects_tampering() -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    parsed = FrozenExtensionParser().parse(claim, candidate)
    assert parsed.resource.resource_id == "extension-1"
    assert parsed.candidate_block_ordinal == 0
    assert parsed.resource_ordinal == 0

    with pytest.raises(ExtensionParseError):
        FrozenExtensionParser().parse(
            claim.model_copy(update={"json_pointer": "/invalid"}), candidate
        )
    with pytest.raises(ExtensionParseError):
        FrozenExtensionParser().parse(claim.model_copy(update={"block_id": "other"}), candidate)
    with pytest.raises(ExtensionParseError):
        FrozenExtensionParser().parse(
            claim.model_copy(update={"candidate_sha256": "f" * 64}), candidate
        )
    block = candidate.blocks[0].model_copy(update={"content_sha256": "f" * 64})
    broken = candidate.model_copy(update={"blocks": [block]})
    with pytest.raises(ExtensionParseError):
        FrozenExtensionParser().parse(claim, broken)


def test_c7_verifier_accepts_local_supported_source_and_rejects_unknown_targets() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    claim = _claim(candidate)
    citation = candidate.blocks[0].content["resources"][0]["citation_text"]
    evidence = _evidence(claim, citation=citation)
    analysis = Topic1ExtensionVerifier().analyze(
        ExtensionResourceV1.model_validate(candidate.blocks[0].content["resources"][0]),
        snapshot,
        (evidence,),
    )
    assert analysis.verdict == VerificationVerdict.SUPPORTED
    assert analysis.source_present_in_approved_corpus is True
    assert analysis.license_compatible is True
    assert analysis.knowledge_relevance >= 0.5

    resource = ExtensionResourceV1.model_validate(candidate.blocks[0].content["resources"][0])
    unknown = resource.model_copy(update={"relevance_to_kp_ids": ["KP-UNKNOWN"]})
    rejected = Topic1ExtensionVerifier().analyze(unknown, snapshot, (evidence,))
    assert rejected.verdict == VerificationVerdict.CONTRADICTED
    assert "C7_UNKNOWN_KNOWLEDGE_POINT" in rejected.finding_codes


@pytest.mark.parametrize(
    ("citation", "expected"),
    [
        ("citation needed", "C7_CITATION_INVALID"),
        ("Control paper 2099 CC BY-4.0", "C7_PUBLICATION_DATE_INVALID"),
        ("Control paper 2024 GPL-3.0", "C7_LICENSE_INCOMPATIBLE"),
    ],
)
def test_c7_verifier_fails_closed_for_citation_temporal_and_license_risks(
    citation: str, expected: str
) -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot, citation=citation)
    claim = _claim(candidate)
    evidence = _evidence(claim, citation=citation)
    resource = ExtensionResourceV1.model_validate(candidate.blocks[0].content["resources"][0])
    analysis = Topic1ExtensionVerifier().analyze(resource, snapshot, (evidence,))
    assert expected in analysis.finding_codes
    assert analysis.verdict in {
        VerificationVerdict.CONTRADICTED,
        VerificationVerdict.INSUFFICIENT_EVIDENCE,
        VerificationVerdict.UNSAFE,
    }


def test_c7_verifier_requires_evidence() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    resource = ExtensionResourceV1.model_validate(candidate.blocks[0].content["resources"][0])
    analysis = Topic1ExtensionVerifier().analyze(resource, snapshot, ())
    assert analysis.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert "C7_EVIDENCE_REQUIRED" in analysis.finding_codes


def test_c7_private_binding_and_policy_boundaries() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    claim = _claim(candidate)
    evidence = _evidence(
        claim,
        citation=candidate.blocks[0].content["resources"][0]["citation_text"],
    )
    bundle = _bundle(candidate, claim)
    handler = C7ExtensionHandler(
        _FakeSource(bundle),
        FileSystemArtifactObjectStore(Path.cwd() / "var"),
        policy=C7HandlerPolicy(max_evidence_count=1),
    )

    with pytest.raises(ValueError, match="Candidate"):
        PostgresExtensionEvidenceSource._validate_candidate(
            candidate.model_copy(update={"candidate_version": 2}), claim
        )
    with pytest.raises(ValueError, match="integrity"):
        PostgresExtensionEvidenceSource._validate_candidate(
            candidate.model_copy(update={"blocks": []}), claim
        )
    PostgresExtensionEvidenceSource._validate_candidate(None, claim)

    with pytest.raises(ValueError, match="Claim"):
        PostgresExtensionEvidenceSource._validate_evidence(
            (evidence.model_copy(update={"claim_id": uuid4()}),),
            claim,
            evidence.knowledge_base_version_id,
        )
    with pytest.raises(ValueError, match="Trace"):
        PostgresExtensionEvidenceSource._validate_evidence(
            (evidence.model_copy(update={"trace_id": "8" * 32}),),
            claim,
            evidence.knowledge_base_version_id,
        )
    with pytest.raises(ValueError, match="knowledge base"):
        PostgresExtensionEvidenceSource._validate_evidence((evidence,), claim, uuid4())
    with pytest.raises(ValueError, match="integrity"):
        PostgresExtensionEvidenceSource._validate_evidence(
            (evidence.model_copy(update={"record_sha256": "f" * 64}),),
            claim,
            evidence.knowledge_base_version_id,
        )
    tampered_excerpt = evidence.model_copy(update={"excerpt_sha256": "f" * 64})
    tampered_excerpt = tampered_excerpt.model_copy(
        update={
            "record_sha256": canonical_sha256(
                tampered_excerpt.model_dump(mode="json", exclude={"record_sha256"})
            )
        }
    )
    with pytest.raises(ValueError, match="excerpt"):
        PostgresExtensionEvidenceSource._validate_evidence(
            (tampered_excerpt,),
            claim,
            evidence.knowledge_base_version_id,
        )
    with pytest.raises(ValueError, match="duplicate"):
        PostgresExtensionEvidenceSource._validate_evidence(
            (evidence, evidence), claim, evidence.knowledge_base_version_id
        )

    with pytest.raises(ValueError, match="safety"):
        handler._validate_bundle(
            claim,
            ExtensionEvidenceBundle(
                candidate=candidate,
                snapshot=snapshot,
                evidence=(evidence,) * 2,
                knowledge_base_version_id=evidence.knowledge_base_version_id,
            ),
        )
    with pytest.raises(ValueError, match="binding"):
        handler._validate_bundle(
            claim,
            ExtensionEvidenceBundle(
                candidate=candidate,
                snapshot=snapshot,
                evidence=(),
                knowledge_base_version_id=None,
            ),
        )
    with pytest.raises(ValueError, match="Candidate"):
        handler._validate_bundle(
            claim,
            ExtensionEvidenceBundle(
                candidate=candidate.model_copy(update={"candidate_version": 2}),
                snapshot=snapshot,
                evidence=(),
                knowledge_base_version_id=evidence.knowledge_base_version_id,
            ),
        )

    with pytest.raises(ValueError, match="unsupported"):
        handler._resource_type("UNKNOWN")
    assert handler._resource_type("PAPER").value == "PAPER"
    assert handler._resource_type("RESEARCH").value == "PAPER"
    assert handler._resource_type("ENGINEERING").value == "ENGINEERING_CASE"
    assert handler._resource_type("INDUSTRY").value == "ENGINEERING_CASE"
    assert handler._resource_type("COMPETITION").value == "STANDARD"
    assert handler._error_code(ValueError("tenant")) == "C7_TENANT_ISOLATION_FAILED"
    assert handler._error_code(ValueError("candidate")) == "C7_CANDIDATE_BINDING_FAILED"
    assert handler._error_code(ValueError("knowledge base")) == "C7_KNOWLEDGE_BASE_BINDING_FAILED"
    assert handler._error_code(ValueError("evidence")) == "C7_EVIDENCE_INTEGRITY_FAILED"
    assert handler._error_code(ValueError("artifact")) == "C7_ARTIFACT_INTEGRITY_FAILED"
    assert handler._error_code(ValueError("other")) == "C7_HANDLER_VALIDATION_FAILED"

    with pytest.raises(ExtensionParseError, match="identity"):
        FrozenExtensionParser().parse(claim.model_copy(update={"candidate_id": uuid4()}), candidate)
    with pytest.raises(ExtensionParseError, match="version"):
        FrozenExtensionParser().parse(claim.model_copy(update={"candidate_version": 2}), candidate)


def test_c7_snapshot_integrity_boundaries() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    claim = _claim(candidate)
    handler = C7ExtensionHandler(
        _FakeSource(_bundle(candidate, claim)), FileSystemArtifactObjectStore(Path.cwd() / "var")
    )
    with pytest.raises(ValueError, match="integrity"):
        handler._validate_snapshot(
            ExtensionEvidenceBundle(
                candidate=candidate,
                snapshot=snapshot.model_copy(update={"content_sha256": "f" * 64}),
                evidence=(),
                knowledge_base_version_id=uuid4(),
            )
        )
    with pytest.raises(ValueError, match="node count"):
        handler._validate_snapshot(
            ExtensionEvidenceBundle(
                candidate=candidate,
                snapshot=snapshot.model_copy(update={"node_count": 0}),
                evidence=(),
                knowledge_base_version_id=uuid4(),
            )
        )
    with pytest.raises(ValueError, match="edge count"):
        handler._validate_snapshot(
            ExtensionEvidenceBundle(
                candidate=candidate,
                snapshot=snapshot.model_copy(update={"edge_count": 0}),
                evidence=(),
                knowledge_base_version_id=uuid4(),
            )
        )


@pytest.mark.asyncio
async def test_c7_handler_writes_immutable_artifact_and_runs_under_c1(tmp_path: Path) -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    store = FileSystemArtifactObjectStore(tmp_path)
    handler = C7ExtensionHandler(_FakeSource(_bundle(candidate, claim)), store)
    finding = await handler.verify(_context(claim))
    assert finding.verdict == VerificationVerdict.SUPPORTED
    data = await store.read(
        tenant_id=TENANT,
        storage_namespace=finding.result_artifact.storage_namespace,
        object_key=finding.result_artifact.object_key,
        expected_byte_size=finding.result_artifact.byte_size,
        expected_sha256=finding.result_artifact.sha256,
    )
    document = json.loads(data)
    assert document["verification_result"]["source_present_in_approved_corpus"] is True
    assert document["resource"]["citation_sha256"]
    execution = await BoundedModuleExecutor(
        {VerificationModule.C7_EXTENSION: handler},
        worker_instance_id="c7-worker",
        retry_backoff_ms=0,
    ).execute(
        build_topic4_record(
            ModuleDispatchPlanV1,
            trace_id=claim.trace_id,
            tenant_id=TENANT,
            version_cas=1,
            created_at=NOW,
            immutable=True,
            schema_version="module-dispatch-plan.v1",
            dispatch_plan_id=uuid4(),
            verification_id=claim.verification_id,
            claim_ids=[claim.claim_id],
            items=[_context(claim).dispatch_item],
            max_parallelism=1,
            policy_version="c7-test-v1",
            plan_sha256="d" * 64,
        ),
        [claim],
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert execution.results[0].verdict == VerificationVerdict.SUPPORTED


@pytest.mark.asyncio
async def test_c7_handler_fails_closed_for_tenant_kind_missing_and_loader_errors(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    store = FileSystemArtifactObjectStore(tmp_path)
    handler = C7ExtensionHandler(_FakeSource(_bundle(candidate, claim)), store)
    assert (
        "C7_TENANT_CONTEXT_MISMATCH"
        in (await handler.verify(_context(claim, tenant_id="other"))).finding_codes
    )
    wrong_kind = claim.model_copy(update={"claim_kind": ClaimKind.TEXT})
    assert "C7_CLAIM_KIND_MISMATCH" in (await handler.verify(_context(wrong_kind))).finding_codes
    missing = await C7ExtensionHandler(
        _FakeSource(ExtensionEvidenceBundle(None, None, ())), store
    ).verify(_context(claim))
    assert missing.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    invalid = await C7ExtensionHandler(lambda claim: {"invalid": claim}, store).verify(
        _context(claim)
    )
    assert "C7_HANDLER_VALIDATION_FAILED" in invalid.finding_codes

    async def fail(_claim: ClaimV1) -> ExtensionEvidenceBundle:
        raise RuntimeError("forced")

    unexpected = await C7ExtensionHandler(fail, store).verify(_context(claim))
    assert "C7_HANDLER_UNEXPECTED_ERROR" in unexpected.finding_codes
    with pytest.raises(ValueError):
        C7HandlerPolicy(max_evidence_count=0)
    with pytest.raises(ValueError):
        C7HandlerPolicy(max_artifact_bytes=0)


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
        return None if self.candidate is None else CandidateRecord(uuid4(), self.candidate, NOW)


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
        retrieval_pipeline_version="c7-test-rag-v1",
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
        version="kb-c7-test-v1",
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
async def test_c7_postgres_evidence_source_scopes_frozen_inputs() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    claim = _claim(candidate)
    citation = candidate.blocks[0].content["resources"][0]["citation_text"]
    evidence = _evidence(claim, citation=citation)
    bundle = _evidence_bundle(claim, evidence)
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c7-test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )
    source = PostgresExtensionEvidenceSource(
        _FakeDatabase(),
        _FakeKnowledgeRepository(bundle, _knowledge_base(claim, snapshot, bundle), [evidence]),
        _FakeTopic1Repository(snapshot),
        _FakeTopic3Repository(candidate),
    )
    with tenant_scope(context):
        loaded = await source.load(claim)
    assert loaded.candidate == candidate
    assert loaded.snapshot == snapshot
    assert loaded.evidence == (evidence,)


@pytest.mark.asyncio
async def test_c7_postgres_evidence_source_rejects_missing_authority_and_cross_tenant_data() -> (
    None
):
    snapshot = _snapshot()
    candidate = _candidate(snapshot)
    claim = _claim(candidate)
    citation = candidate.blocks[0].content["resources"][0]["citation_text"]
    evidence = _evidence(claim, citation=citation)
    bundle = _evidence_bundle(claim, evidence)
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c7-test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )

    async def load(
        repository: _FakeKnowledgeRepository,
        topic1: _FakeTopic1Repository,
        topic3: _FakeTopic3Repository,
    ) -> ExtensionEvidenceBundle:
        source = PostgresExtensionEvidenceSource(_FakeDatabase(), repository, topic1, topic3)
        with tenant_scope(context):
            return await source.load(claim)

    empty = await load(
        _FakeKnowledgeRepository(None, None, []),
        _FakeTopic1Repository(None),
        _FakeTopic3Repository(candidate),
    )
    assert empty.candidate == candidate
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
    cross_tenant = evidence.model_copy(update={"tenant_id": "other"})
    with pytest.raises(ValueError, match="tenant"):
        await load(
            _FakeKnowledgeRepository(
                bundle,
                _knowledge_base(claim, snapshot, bundle),
                [cross_tenant],
            ),
            _FakeTopic1Repository(snapshot),
            _FakeTopic3Repository(candidate),
        )
