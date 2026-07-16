from __future__ import annotations

import ast
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from liyans_contracts.artifacts import ArtifactObjectRefV1
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
    CodeFileV1,
    CodeSandboxContentV1,
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
from liyans_contracts.topic4_common import ClaimKind, VerificationModule, VerificationVerdict

from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.code.analysis import (
    CodeAnalysis,
    CodeStaticAnalyzer,
    MatlabStaticAnalyzer,
    PythonStaticAnalyzer,
    claims_stability,
)
from liyans.domains.code.evidence_source import (
    CodeEvidenceBundle,
    PostgresCodeEvidenceSource,
)
from liyans.domains.code.handler import C6CodeHandler, C6HandlerPolicy
from liyans.domains.code.parser import CodeParseError, FrozenCodeBundleParser
from liyans.domains.topic3.entities import CandidateRecord
from liyans.domains.verification.claim_extraction import DeterministicClaimExtractor
from liyans.domains.verification.execution import BoundedModuleExecutor, ModuleExecutionContext
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
TENANT = "tenant-c6"
TRACE = "6" * 32


def _content(
    source: str,
    *,
    language: str = "python",
    path: str = "main.py",
    objective: str = "Verify a stable step response.",
    result_analysis: str = "The stable response converges to a bounded value.",
) -> dict[str, object]:
    return CodeSandboxContentV1(
        schema_version="topic3.code-sandbox-content.v1",
        title="Stable control simulation",
        objective=objective,
        files=[
            {
                "path": path,
                "language": language,
                "content": source,
                "entrypoint": True,
            }
        ],
        parameters={"horizon": "10 s"},
        expected_observations=["The response converges."],
        result_analysis=result_analysis,
        safety_notes=["No network, filesystem, or process operations."],
    ).model_dump(mode="json")


def _candidate(
    source: str,
    *,
    language: str = "python",
    path: str = "main.py",
    objective: str = "Verify a stable step response.",
    result_analysis: str = "The stable response converges to a bounded value.",
) -> CandidateV1:
    content = _content(
        source,
        language=language,
        path=path,
        objective=objective,
        result_analysis=result_analysis,
    )
    block = BlockV1(
        schema_version="topic3.block.v1",
        block_id="code-stable",
        block_type=BlockType.CODE,
        ordinal=0,
        title="Control simulation",
        content_schema_version="topic3.code-sandbox-content.v1",
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
        resource_type=ResourceType.SIMULATION_CODE,
        status=CandidateStatus.COMPLETE,
        blocks=[block],
        provenance=CandidateProvenanceV1(
            agent=SourceAgent.CODE_SANDBOX,
            agent_build_version="topic3.code.accepted.v1",
            prompt_bundle_version="prompt.code.v1",
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
    return next(claim for claim in claims if claim.json_pointer.endswith("/content"))


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
        created_by_subject="system:c6-test",
        frozen_at=NOW,
    )


def _evidence(claim: ClaimV1, *, tenant_id: str = TENANT) -> EvidenceRefV1:
    excerpt = "The closed-loop control model is stable and its response converges."
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
        section_id="c6-test",
        citation="Topic1 control authority",
        excerpt=excerpt,
        excerpt_sha256=canonical_sha256(excerpt),
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
        module=VerificationModule.C6_CODE,
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


def _plan(claim: ClaimV1) -> ModuleDispatchPlanV1:
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
        items=[_context(claim).dispatch_item],
        max_parallelism=1,
        policy_version="c6-test-v1",
        plan_sha256="d" * 64,
    )


def _bundle(candidate: CandidateV1, claim: ClaimV1) -> CodeEvidenceBundle:
    evidence = _evidence(claim)
    return CodeEvidenceBundle(
        candidate=candidate,
        snapshot=_snapshot(),
        evidence=(evidence,),
        knowledge_base_version_id=evidence.knowledge_base_version_id,
    )


@dataclass
class _FakeSource:
    bundle: CodeEvidenceBundle

    async def load(self, claim: ClaimV1) -> CodeEvidenceBundle:
        assert claim.tenant_id == TENANT
        return self.bundle


def _code_file(source: str, *, language: str = "python", path: str = "main.py") -> CodeFileV1:
    return CodeFileV1(path=path, language=language, content=source, entrypoint=True)


def test_python_static_analyzer_accepts_bounded_control_simulation() -> None:
    source = """import numpy as np
from scipy import signal
system = signal.TransferFunction([1.0], [1.0, 2.0, 1.0])
t = np.linspace(0.0, 10.0, 1001)
t, y = signal.step(system, T=t)
"""
    result = PythonStaticAnalyzer().analyze(_code_file(source))
    assert result.syntax_valid is True
    assert result.static_analysis_passed is True
    assert result.model_detected is True
    assert result.simulation_detected is True
    assert result.time_grid_size == 1001
    assert all(pole.real < 0 for pole in result.poles)
    assert result.dependencies == ("numpy", "scipy")


@pytest.mark.parametrize(
    ("source", "finding"),
    [
        ("import os\nos.system('whoami')", "C6_DANGEROUS_IMPORT"),
        ("while True:\n    pass", "C6_UNBOUNDED_WHILE_LOOP"),
        ("for i in range(10000001):\n    pass", "C6_LOOP_LIMIT"),
        ("import numpy as np\nnp.random.rand(2)", "C6_NONDETERMINISTIC_RANDOM"),
        ("def f(:\n    pass", "C6_PYTHON_SYNTAX_INVALID"),
        ("import pathlib\nopen('x', 'w')", "C6_DANGEROUS_CALL"),
    ],
)
def test_python_static_analyzer_blocks_unsafe_or_invalid_code(
    source: str,
    finding: str,
) -> None:
    result = PythonStaticAnalyzer().analyze(_code_file(source))
    assert finding in result.finding_codes


def test_python_static_analyzer_supports_literals_and_rejects_dynamic_bounds() -> None:
    source = """from scipy import signal
den = [1.0, 3.0, 2.0]
system = signal.TransferFunction([1.0], den)
for i in range(10):
    value = i
"""
    result = PythonStaticAnalyzer().analyze(_code_file(source))
    assert len(result.poles) == 2
    assert "C6_UNBOUNDED_FOR_LOOP" not in result.finding_codes
    dynamic = PythonStaticAnalyzer().analyze(
        _code_file("limit = 10\nfor i in range(limit):\n    pass")
    )
    assert "C6_UNBOUNDED_FOR_LOOP" in dynamic.finding_codes
    seeded = PythonStaticAnalyzer().analyze(
        _code_file("import numpy as np\nrng=np.random.default_rng(42)")
    )
    assert "C6_NONDETERMINISTIC_RANDOM" not in seeded.finding_codes


def test_python_static_analyzer_covers_limits_numeric_and_loop_forms() -> None:
    with pytest.raises(ValueError):
        PythonStaticAnalyzer(max_nodes=0)
    with pytest.raises(ValueError):
        PythonStaticAnalyzer(max_loop_iterations=0)
    assert (
        "C6_AST_NODE_LIMIT"
        in PythonStaticAnalyzer(max_nodes=1).analyze(_code_file("x = 1")).finding_codes
    )
    assert (
        "C6_NUMERIC_BOUND_EXCEEDED"
        in PythonStaticAnalyzer().analyze(_code_file("x = 1e200")).finding_codes
    )
    assert (
        "C6_DUNDER_ACCESS_BLOCKED"
        in PythonStaticAnalyzer().analyze(_code_file("x = object().__class__")).finding_codes
    )
    assert (
        "C6_UNAPPROVED_IMPORT"
        in PythonStaticAnalyzer().analyze(_code_file("import symengine")).finding_codes
    )
    assert (
        "C6_UNBOUNDED_FOR_LOOP"
        in PythonStaticAnalyzer()
        .analyze(_code_file("for value in [1, 2]:\n    pass"))
        .finding_codes
    )
    assert (
        "C6_UNBOUNDED_FOR_LOOP"
        in PythonStaticAnalyzer()
        .analyze(_code_file("for value in range(1, 5, 0):\n    pass"))
        .finding_codes
    )
    assert (
        "C6_UNBOUNDED_FOR_LOOP"
        not in PythonStaticAnalyzer()
        .analyze(_code_file("for value in range(5, 0, -1):\n    pass"))
        .finding_codes
    )
    assert (
        "C6_TIME_GRID_LIMIT"
        not in CodeStaticAnalyzer()
        .analyze(
            (_code_file("import numpy as np\nx=np.linspace(0,1,n)\n"),),
            stable_claimed=False,
            unstable_claimed=False,
        )
        .finding_codes
    )


def test_python_static_analyzer_covers_literal_pole_failures_and_unresolved_stability() -> None:
    analyzer = PythonStaticAnalyzer()
    assert analyzer._call_name(ast.Constant(value=1)) == ""
    assert analyzer._range_iterations(ast.Name(id="range")) is None
    assert (
        analyzer._literal_denominator_poles(
            ast.Call(args=[ast.Constant(value=1)]),
            {},
        )
        == []
    )
    invalid = CodeStaticAnalyzer().analyze(
        (_code_file("from scipy import signal\nsys=signal.TransferFunction(num)"),),
        stable_claimed=True,
        unstable_claimed=False,
    )
    assert "C6_STABILITY_UNRESOLVED" in invalid.finding_codes
    contradiction = CodeStaticAnalyzer().analyze(
        (
            _code_file(
                "from scipy import signal\n"
                "sys=signal.TransferFunction([1],[1,2,1])\n"
                "t=range(3)\n"
                "y=step(sys,t)"
            ),
        ),
        stable_claimed=False,
        unstable_claimed=True,
    )
    assert "C6_UNSTABLE_CLAIM_CONTRADICTION" in contradiction.finding_codes


def test_matlab_static_analyzer_accepts_model_and_rejects_unsafe_operations() -> None:
    safe = """sys = tf([1], [1 2 1]);
t = linspace(0, 10, 1001);
y = step(sys, t);
"""
    result = MatlabStaticAnalyzer().analyze(_code_file(safe, language="matlab", path="main.m"))
    assert result.syntax_valid is True
    assert result.static_analysis_passed is True
    assert result.model_detected is True
    assert result.simulation_detected is True
    assert result.time_grid_size == 1001
    assert all(pole.real < 0 for pole in result.poles)

    unsafe = MatlabStaticAnalyzer().analyze(
        _code_file(
            "system('whoami');\nwhile true\nend",
            language="matlab",
            path="main.m",
        )
    )
    assert "C6_MATLAB_DANGEROUS_OPERATION" in unsafe.finding_codes
    assert "C6_UNBOUNDED_WHILE_LOOP" in unsafe.finding_codes


def test_matlab_static_analyzer_covers_syntax_loop_and_grid_boundaries() -> None:
    malformed = MatlabStaticAnalyzer().analyze(
        _code_file("x = [1 2;", language="matlab", path="main.m")
    )
    assert "C6_MATLAB_DELIMITER_INVALID" in malformed.finding_codes
    dynamic = MatlabStaticAnalyzer().analyze(
        _code_file("for k = values\nend", language="matlab", path="main.m")
    )
    assert "C6_UNBOUNDED_FOR_LOOP" in dynamic.finding_codes
    bounded = MatlabStaticAnalyzer().analyze(
        _code_file("for k = 1:1:10\nend", language="matlab", path="main.m")
    )
    assert "C6_UNBOUNDED_FOR_LOOP" not in bounded.finding_codes
    mismatch = MatlabStaticAnalyzer().analyze(
        _code_file("function f()\nend\nend", language="matlab", path="main.m")
    )
    assert "C6_MATLAB_BLOCK_TERMINATOR_MISMATCH" in mismatch.finding_codes
    step_zero = MatlabStaticAnalyzer().analyze(
        _code_file("for k = 1:0:10\nend", language="matlab", path="main.m")
    )
    assert "C6_UNBOUNDED_FOR_LOOP" in step_zero.finding_codes
    assert MatlabStaticAnalyzer._balanced("x=[1)") is False
    assert MatlabStaticAnalyzer._for_iterations("for k=1:0:10") is None
    assert MatlabStaticAnalyzer._literal_poles("tf([1],[x])") == []
    with pytest.raises(ValueError):
        CodeStaticAnalyzer(max_time_grid=0)


def test_code_static_analyzer_detects_stability_and_resource_boundaries() -> None:
    safe_file = _code_file("import numpy as np\nx=np.linspace(0,1,10)\n")
    result = CodeStaticAnalyzer(max_time_grid=5).analyze(
        (safe_file,),
        stable_claimed=True,
        unstable_claimed=False,
    )
    assert "C6_TIME_GRID_LIMIT" in result.finding_codes
    assert "C6_CONTROL_MODEL_MISSING" in result.finding_codes
    assert "C6_SIMULATION_FLOW_MISSING" in result.finding_codes
    assert claims_stability("unstable response") == (False, True)
    assert claims_stability("stable response") == (True, False)

    unstable = """import numpy as np
from scipy import signal
system = signal.TransferFunction([1.0], [1.0, -1.0])
t = np.linspace(0.0, 2.0, 10)
y = signal.step(system, T=t)
"""
    unstable_result = CodeStaticAnalyzer().analyze(
        (_code_file(unstable),),
        stable_claimed=True,
        unstable_claimed=False,
    )
    assert "C6_STABILITY_CONTRADICTION" in unstable_result.finding_codes


def test_frozen_code_parser_reconstructs_and_rejects_boundaries() -> None:
    candidate = _candidate(
        "import numpy as np\nx=np.linspace(0,1,10)\n",
        result_analysis="A bounded response is produced.",
    )
    claim = _claim(candidate)
    parsed = FrozenCodeBundleParser().parse(claim, candidate)
    assert parsed.entrypoint.path == "main.py"
    assert parsed.source_sha256
    with pytest.raises(CodeParseError):
        FrozenCodeBundleParser().parse(
            claim.model_copy(update={"json_pointer": "/invalid"}), candidate
        )
    with pytest.raises(CodeParseError):
        FrozenCodeBundleParser().parse(claim.model_copy(update={"block_id": "other"}), candidate)
    mixed_content = CodeSandboxContentV1(
        schema_version="topic3.code-sandbox-content.v1",
        title="mixed",
        objective="mixed code",
        files=[
            {"path": "a.py", "language": "python", "content": "print(1)", "entrypoint": True},
            {"path": "b.m", "language": "matlab", "content": "x=1;", "entrypoint": False},
        ],
        expected_observations=["none"],
        result_analysis="none",
    ).model_dump(mode="json")
    block = candidate.blocks[0].model_copy(
        update={"content": mixed_content, "content_sha256": canonical_sha256(mixed_content)}
    )
    mixed_document = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    mixed_document["blocks"] = [block.model_dump(mode="json")]
    mixed_candidate = CandidateV1(
        **mixed_document,
        candidate_sha256=canonical_sha256(mixed_document),
    )
    mixed_claim = claim.model_copy(update={"candidate_sha256": mixed_candidate.candidate_sha256})
    with pytest.raises(CodeParseError, match="mixed"):
        FrozenCodeBundleParser().parse(mixed_claim, mixed_candidate)
    with pytest.raises(CodeParseError):
        FrozenCodeBundleParser().parse(
            claim.model_copy(update={"candidate_id": uuid4()}), candidate
        )
    with pytest.raises(CodeParseError):
        FrozenCodeBundleParser().parse(claim.model_copy(update={"candidate_version": 2}), candidate)
    with pytest.raises(CodeParseError):
        FrozenCodeBundleParser().parse(
            claim.model_copy(update={"candidate_sha256": "f" * 64}), candidate
        )
    broken_block = candidate.blocks[0].model_copy(update={"content_sha256": "f" * 64})
    broken_candidate = candidate.model_copy(update={"blocks": [broken_block]})
    with pytest.raises(CodeParseError):
        FrozenCodeBundleParser().parse(claim, broken_candidate)
    invalid_content = candidate.blocks[0].model_copy(
        update={
            "content": {"schema_version": "wrong"},
            "content_sha256": canonical_sha256({"schema_version": "wrong"}),
        }
    )
    invalid_candidate = candidate.model_copy(update={"blocks": [invalid_content]})
    with pytest.raises(CodeParseError):
        FrozenCodeBundleParser().parse(claim, invalid_candidate)


@pytest.mark.asyncio
async def test_c6_handler_writes_immutable_artifact_and_runs_under_c1(tmp_path: Path) -> None:
    source = """import numpy as np
from scipy import signal
system = signal.TransferFunction([1.0], [1.0, 2.0, 1.0])
t = np.linspace(0.0, 10.0, 1001)
t, y = signal.step(system, T=t)
"""
    candidate = _candidate(source)
    claim = _claim(candidate)
    store = FileSystemArtifactObjectStore(tmp_path)
    handler = C6CodeHandler(_FakeSource(_bundle(candidate, claim)), store)
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
    assert document["verification_result"]["execution_state"] == "NOT_RUN"
    assert document["code_artifact"]["source_sha256"]
    assert len(document["verification_result"]["numeric_assertions"]) == 2
    execution = await BoundedModuleExecutor(
        {VerificationModule.C6_CODE: handler},
        worker_instance_id="c6-worker",
        retry_backoff_ms=0,
    ).execute(
        _plan(claim),
        [claim],
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert execution.results[0].verdict == VerificationVerdict.SUPPORTED


@pytest.mark.asyncio
async def test_c6_handler_fails_closed_for_tenant_kind_missing_and_unsafe_inputs(
    tmp_path: Path,
) -> None:
    safe_candidate = _candidate(
        "import numpy as np\nx=np.linspace(0,1,10)\n",
        result_analysis="A bounded response is produced.",
    )
    safe_claim = _claim(safe_candidate)
    store = FileSystemArtifactObjectStore(tmp_path)
    handler = C6CodeHandler(_FakeSource(_bundle(safe_candidate, safe_claim)), store)
    assert (
        "C6_TENANT_CONTEXT_MISMATCH"
        in (await handler.verify(_context(safe_claim, tenant_id="other"))).finding_codes
    )
    assert (
        "C6_CLAIM_KIND_MISMATCH"
        in (
            await handler.verify(
                _context(safe_claim.model_copy(update={"claim_kind": ClaimKind.TEXT}))
            )
        ).finding_codes
    )
    missing = await C6CodeHandler(
        _FakeSource(CodeEvidenceBundle(None, None, ())),
        store,
    ).verify(_context(safe_claim))
    assert missing.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    unsafe_candidate = _candidate("import os\nos.system('whoami')")
    unsafe_claim = _claim(unsafe_candidate)
    unsafe = await C6CodeHandler(
        _FakeSource(_bundle(unsafe_candidate, unsafe_claim)),
        store,
    ).verify(_context(unsafe_claim))
    assert unsafe.verdict == VerificationVerdict.UNSAFE
    assert "C6_DANGEROUS_IMPORT" in unsafe.finding_codes


@pytest.mark.asyncio
async def test_c6_handler_contract_snapshot_and_loader_boundaries(tmp_path: Path) -> None:
    candidate = _candidate(
        "import numpy as np\nx=np.linspace(0,1,10)\n",
        result_analysis="A bounded response is produced.",
    )
    claim = _claim(candidate)
    store = FileSystemArtifactObjectStore(tmp_path)
    invalid = await C6CodeHandler(lambda claim: {"invalid": claim}, store).verify(_context(claim))
    assert "C6_HANDLER_VALIDATION_FAILED" in invalid.finding_codes
    evidence = _evidence(claim)
    tampered = await C6CodeHandler(
        _FakeSource(
            CodeEvidenceBundle(
                candidate,
                _snapshot().model_copy(update={"content_sha256": "f" * 64}),
                (evidence,),
                evidence.knowledge_base_version_id,
            )
        ),
        store,
    ).verify(_context(claim))
    assert "C6_KNOWLEDGE_BASE_BINDING_FAILED" in tampered.finding_codes
    malformed = await C6CodeHandler(
        _FakeSource(_bundle(candidate, claim)),
        store,
    ).verify(_context(claim.model_copy(update={"json_pointer": "/invalid"})))
    assert "C6_CODE_CONTRACT_INVALID" in malformed.finding_codes

    async def fail(_claim: ClaimV1) -> CodeEvidenceBundle:
        raise RuntimeError("forced")

    unexpected = await C6CodeHandler(fail, store).verify(_context(claim))
    assert "C6_HANDLER_UNEXPECTED_ERROR" in unexpected.finding_codes
    with pytest.raises(ValueError):
        C6HandlerPolicy(max_evidence_count=0)
    with pytest.raises(ValueError):
        C6HandlerPolicy(max_artifact_bytes=0)


def test_c6_handler_private_verdict_and_error_code_boundaries(tmp_path: Path) -> None:
    candidate = _candidate(
        "import numpy as np\nx=np.linspace(0,1,10)\n",
        result_analysis="A bounded response is produced.",
    )
    claim = _claim(candidate)
    handler = C6CodeHandler(
        _FakeSource(_bundle(candidate, claim)),
        FileSystemArtifactObjectStore(tmp_path),
    )
    parsed = FrozenCodeBundleParser().parse(claim, candidate)
    source_ref = ArtifactObjectRefV1(
        schema_version="artifact.object.ref.v1",
        storage_namespace="verification-artifacts",
        object_key="source.json",
        media_type="application/json",
        content_encoding="identity",
        byte_size=2,
        sha256="a" * 64,
        created_at=NOW,
    )
    code_artifact = handler._code_artifact(
        _context(claim),
        parsed,
        source_ref,
        [],
    )
    policy = handler._sandbox_policy(_context(claim), parsed.language)
    insufficient = CodeAnalysis(
        files=(),
        finding_codes=("C6_STABILITY_UNRESOLVED",),
        dependencies=(),
        syntax_valid=True,
        static_analysis_passed=False,
        model_detected=True,
        simulation_detected=True,
        time_grid_size=10,
        poles=(),
        stable_claimed=True,
        unstable_claimed=False,
    )
    assert (
        handler._verification_result(
            _context(claim),
            code_artifact,
            policy,
            insufficient,
            evidence_ref_ids=(uuid4(),),
        ).verdict
        == VerificationVerdict.INSUFFICIENT_EVIDENCE
    )
    syntax = replace(insufficient, finding_codes=(), syntax_valid=False)
    assert (
        handler._verification_result(
            _context(claim), code_artifact, policy, syntax, evidence_ref_ids=(uuid4(),)
        ).verdict
        == VerificationVerdict.CONTRADICTED
    )
    no_evidence = handler._verification_result(
        _context(claim),
        code_artifact,
        policy,
        CodeAnalysis(
            files=(),
            finding_codes=(),
            dependencies=(),
            syntax_valid=True,
            static_analysis_passed=True,
            model_detected=True,
            simulation_detected=True,
            time_grid_size=10,
            poles=(),
            stable_claimed=False,
            unstable_claimed=False,
        ),
        evidence_ref_ids=(),
    )
    assert no_evidence.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert handler._error_code(ValueError("tenant")) == "C6_TENANT_ISOLATION_FAILED"
    assert handler._error_code(ValueError("candidate")) == "C6_CANDIDATE_BINDING_FAILED"
    assert handler._error_code(ValueError("knowledge base")) == "C6_KNOWLEDGE_BASE_BINDING_FAILED"
    assert handler._error_code(ValueError("evidence")) == "C6_EVIDENCE_INTEGRITY_FAILED"
    assert handler._error_code(ValueError("artifact")) == "C6_ARTIFACT_INTEGRITY_FAILED"
    assert handler._error_code(ValueError("other")) == "C6_HANDLER_VALIDATION_FAILED"


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
        retrieval_pipeline_version="c6-test-rag-v1",
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
        version="kb-c6-test-v1",
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
async def test_postgres_code_evidence_source_scopes_all_frozen_inputs() -> None:
    candidate = _candidate(
        "import numpy as np\nx=np.linspace(0,1,10)\n",
        result_analysis="A bounded response is produced.",
    )
    claim = _claim(candidate)
    evidence = _evidence(claim)
    bundle = _evidence_bundle(claim, evidence)
    snapshot = _snapshot()
    source = PostgresCodeEvidenceSource(
        _FakeDatabase(),
        _FakeKnowledgeRepository(bundle, _knowledge_base(claim, snapshot, bundle), [evidence]),
        _FakeTopic1Repository(snapshot),
        _FakeTopic3Repository(candidate),
    )
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c6-test",
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
async def test_postgres_code_evidence_source_rejects_missing_authority_and_integrity() -> None:
    candidate = _candidate(
        "import numpy as np\nx=np.linspace(0,1,10)\n",
        result_analysis="A bounded response is produced.",
    )
    claim = _claim(candidate)
    evidence = _evidence(claim)
    bundle = _evidence_bundle(claim, evidence)
    snapshot = _snapshot()
    context = TenantContext(
        tenant_id=TENANT,
        subject_ref="c6-test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=TRACE,
    )

    async def load(
        repository: _FakeKnowledgeRepository,
        topic1: _FakeTopic1Repository,
        topic3: _FakeTopic3Repository,
    ) -> CodeEvidenceBundle:
        source = PostgresCodeEvidenceSource(_FakeDatabase(), repository, topic1, topic3)
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
    with pytest.raises(ValueError, match="unavailable evidence"):
        await load(
            _FakeKnowledgeRepository(
                bundle,
                _knowledge_base(claim, snapshot, bundle),
                [],
            ),
            _FakeTopic1Repository(snapshot),
            _FakeTopic3Repository(candidate),
        )
