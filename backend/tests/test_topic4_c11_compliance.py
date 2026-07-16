from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c6 import CodeArtifactV1, CodeDependencyV1, CodeLanguage
from liyans_contracts.topic4_c11 import (
    BuildProvenanceV1,
    SBOMComponentV1,
    SBOMManifestV1,
    VulnerabilityRecordV1,
    VulnerabilityStatus,
)
from liyans_contracts.topic4_common import FindingSeverity, VerificationModule, VerificationVerdict
from test_topic4_c5_quiz import (
    TENANT as QUIZ_TENANT,
)
from test_topic4_c5_quiz import (
    _candidate as quiz_candidate,
)
from test_topic4_c5_quiz import (
    _claim as quiz_claim,
)
from test_topic4_c6_code import (
    NOW,
    TENANT,
    _candidate,
    _claim,
    _context,
    _evidence,
    _plan,
)

from liyans.domains.compliance.evidence_source import ComplianceEvidenceBundle
from liyans.domains.compliance.handler import C11ComplianceHandler, C11HandlerPolicy
from liyans.domains.verification.execution import BoundedModuleExecutor
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore


@dataclass
class _FakeSource:
    bundle: ComplianceEvidenceBundle

    async def load(self, claim):
        return self.bundle


def _artifact(sha: str, key: str, size: int = 64) -> ArtifactObjectRefV1:
    return ArtifactObjectRefV1(
        schema_version="artifact.object.ref.v1",
        storage_namespace="verification-artifacts",
        object_key=key,
        media_type="application/octet-stream",
        content_encoding="identity",
        byte_size=size,
        sha256=sha,
        created_at=NOW,
    )


def _compliance_bundle(
    claim, *, license_name: str = "BSD-3-Clause", open_vulnerability: bool = False
):
    source = "import math\nprint(math.sqrt(4))\n"
    source_sha = canonical_sha256(source)
    code_artifact_id = uuid4()
    component_id = uuid4()
    sbom_id = uuid4()
    sandbox_id = uuid4()
    dependency = build_topic4_record(
        CodeDependencyV1,
        trace_id=claim.trace_id,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="code-dependency.v1",
        name="numpy",
        version="2.1.0",
        package_url="pkg:pypi/numpy@2.1.0",
        declared_license=license_name,
    )
    code = build_topic4_record(
        CodeArtifactV1,
        trace_id=claim.trace_id,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="code-artifact.v1",
        code_artifact_id=code_artifact_id,
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        candidate_id=claim.candidate_id,
        candidate_version=claim.candidate_version,
        block_id=claim.block_id,
        language=CodeLanguage.PYTHON,
        source_artifact=_artifact(source_sha, "c11/source/main.py", len(source.encode())),
        source_sha256=source_sha,
        entrypoint="main.py",
        dependencies=[dependency],
        expected_outputs=[],
    )
    sbom_document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:" + str(sbom_id),
        "components": [
            {
                "type": "library",
                "name": "numpy",
                "version": "2.1.0",
                "purl": "pkg:pypi/numpy@2.1.0",
                "licenses": [{"license": {"id": license_name}}],
            }
        ],
    }
    sbom_sha = canonical_sha256(sbom_document)
    component = build_topic4_record(
        SBOMComponentV1,
        trace_id=claim.trace_id,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="sbom-component.v1",
        component_id=component_id,
        name="numpy",
        version="2.1.0",
        package_url="pkg:pypi/numpy@2.1.0",
        licenses=[license_name],
        component_sha256=None,
    )
    sbom = build_topic4_record(
        SBOMManifestV1,
        trace_id=claim.trace_id,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="sbom-manifest.v1",
        sbom_manifest_id=sbom_id,
        code_artifact_id=code_artifact_id,
        format="CYCLONEDX_JSON",
        spec_version="1.6",
        serial_number="urn:uuid:" + str(sbom_id),
        components=[component],
        sbom_artifact=_artifact(sbom_sha, "c11/sbom/manifest.json", 256),
        sbom_sha256=sbom_sha,
    )
    vulnerabilities: tuple[VulnerabilityRecordV1, ...] = ()
    if open_vulnerability:
        vulnerability = build_topic4_record(
            VulnerabilityRecordV1,
            trace_id=claim.trace_id,
            tenant_id=TENANT,
            version_cas=1,
            created_at=NOW,
            immutable=True,
            schema_version="vulnerability-record.v1",
            vulnerability_record_id=uuid4(),
            sbom_manifest_id=sbom_id,
            component_id=component_id,
            advisory_id="CVE-2099-0001",
            severity=FindingSeverity.HIGH,
            cvss_score=8.2,
            affected_range="<2.1.1",
            fixed_version="2.1.1",
            status=VulnerabilityStatus.OPEN,
            non_waivable=True,
        )
        vulnerabilities = (vulnerability,)
    build_output = "c11-reproducible-output"
    provenance = build_topic4_record(
        BuildProvenanceV1,
        trace_id=claim.trace_id,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="build-provenance.v1",
        build_provenance_id=uuid4(),
        code_artifact_id=code_artifact_id,
        builder_id="local-c11-builder",
        builder_version="1.0.0",
        toolchain_manifest_version="toolchain-v1",
        source_sha256=source_sha,
        build_output_artifact=_artifact(canonical_sha256(build_output), "c11/build/output.bin"),
        build_output_sha256=canonical_sha256(build_output),
        sbom_manifest_id=sbom_id,
        sandbox_policy_id=sandbox_id,
        reproducible=True,
        build_command_sha256=canonical_sha256("python -I main.py"),
    )
    evidence = _evidence(claim)
    return ComplianceEvidenceBundle(
        source_tenant_id=TENANT,
        code_artifact=code,
        sbom_manifest=sbom,
        sbom_document=sbom_document,
        vulnerabilities=vulnerabilities,
        provenance=provenance,
        evidence=(evidence,),
    )


def _compliance_context(claim):
    context = _context(claim)
    dispatch = context.dispatch_item.model_copy(
        update={"module": VerificationModule.C11_COMPLIANCE, "tenant_id": claim.tenant_id}
    )
    return replace(context, dispatch_item=dispatch)


@pytest.mark.asyncio
async def test_c11_clean_local_supply_chain_is_supported(tmp_path: Path) -> None:
    candidate = _candidate("import numpy\nprint(numpy.__version__)\n")
    claim = _claim(candidate)
    finding = await C11ComplianceHandler(
        _FakeSource(_compliance_bundle(claim)),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_compliance_context(claim))

    assert finding.verdict == VerificationVerdict.SUPPORTED
    assert finding.deterministic is True


@pytest.mark.asyncio
async def test_c11_blocks_prohibited_license_and_open_high_vulnerability(tmp_path: Path) -> None:
    candidate = _candidate("import numpy\nprint(numpy.__version__)\n")
    claim = _claim(candidate)
    finding = await C11ComplianceHandler(
        _FakeSource(
            _compliance_bundle(
                claim,
                license_name="GPL-3.0-only",
                open_vulnerability=True,
            )
        ),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_compliance_context(claim))

    assert finding.verdict == VerificationVerdict.UNSAFE
    assert "C11_LICENSE_PROHIBITED" in finding.finding_codes
    assert "C11_OPEN_HIGH_VULNERABILITY" in finding.finding_codes


@pytest.mark.asyncio
async def test_c11_rejects_tenant_and_sbom_hash_mismatch(tmp_path: Path) -> None:
    candidate = _candidate("import numpy\nprint(numpy.__version__)\n")
    claim = _claim(candidate)
    valid = _compliance_bundle(claim)
    foreign = await C11ComplianceHandler(
        _FakeSource(replace(valid, source_tenant_id="tenant-other")),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_compliance_context(claim))
    tampered_document = dict(valid.sbom_document or {})
    tampered_document["serialNumber"] = "tampered"
    tampered = await C11ComplianceHandler(
        _FakeSource(replace(valid, sbom_document=tampered_document)),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_compliance_context(claim))

    assert "C11_TENANT_ISOLATION_FAILED" in foreign.finding_codes
    assert "C11_SBOM_INTEGRITY_FAILED" in tampered.finding_codes


@pytest.mark.asyncio
async def test_c11_returns_insufficient_evidence_when_local_evidence_is_missing(
    tmp_path: Path,
) -> None:
    candidate = _candidate("import numpy\nprint(numpy.__version__)\n")
    claim = _claim(candidate)
    valid = _compliance_bundle(claim)
    finding = await C11ComplianceHandler(
        _FakeSource(replace(valid, evidence=())),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_compliance_context(claim))

    assert finding.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


@pytest.mark.asyncio
async def test_c11_non_code_claim_is_not_applicable(tmp_path: Path) -> None:
    candidate = quiz_candidate()
    claim = quiz_claim(candidate)
    finding = await C11ComplianceHandler(
        _FakeSource(
            ComplianceEvidenceBundle(
                source_tenant_id=QUIZ_TENANT,
                code_artifact=None,
                sbom_manifest=None,
                sbom_document=None,
            )
        ),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_compliance_context(claim))

    assert finding.verdict == VerificationVerdict.NOT_APPLICABLE


@pytest.mark.asyncio
async def test_c11_integrates_with_frozen_c1_executor(tmp_path: Path) -> None:
    candidate = _candidate("import numpy\nprint(numpy.__version__)\n")
    claim = _claim(candidate)
    handler = C11ComplianceHandler(
        _FakeSource(_compliance_bundle(claim)),
        FileSystemArtifactObjectStore(tmp_path),
    )
    context = _compliance_context(claim)
    execution = await BoundedModuleExecutor(
        {VerificationModule.C11_COMPLIANCE: handler},
        worker_instance_id="c11-test-worker",
        retry_backoff_ms=0,
    ).execute(
        _plan(claim).model_copy(update={"items": [context.dispatch_item]}),
        [claim],
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )

    assert execution.results[0].module == VerificationModule.C11_COMPLIANCE
    assert execution.results[0].verdict == VerificationVerdict.SUPPORTED


def test_c11_policy_rejects_unbounded_limits() -> None:
    with pytest.raises(ValueError, match="evidence"):
        C11HandlerPolicy(max_evidence_count=0)
    with pytest.raises(ValueError, match="component"):
        C11HandlerPolicy(max_components=0)
    with pytest.raises(ValueError, match="artifact"):
        C11HandlerPolicy(max_artifact_bytes=0)


def test_c11_error_codes_remain_stable() -> None:
    mapper = C11ComplianceHandler._error_code
    assert mapper(ValueError("evidence record failed")) == "C11_EVIDENCE_INTEGRITY_FAILED"
    assert mapper(ValueError("sbom component failed")) == "C11_SBOM_INTEGRITY_FAILED"
    assert mapper(ValueError("provenance is not reproducible")) == "C11_PROVENANCE_INTEGRITY_FAILED"
    assert (
        mapper(ValueError("code artifact candidate mismatch")) == "C11_CODE_ARTIFACT_BINDING_FAILED"
    )
    assert mapper(ValueError("other input")) == "C11_HANDLER_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_c11_fail_closed_tenant_source_and_loader_boundaries(tmp_path: Path) -> None:
    candidate = _candidate("import numpy\nprint(numpy.__version__)\n")
    claim = _claim(candidate)
    context = _compliance_context(claim)
    foreign_context = replace(
        context,
        dispatch_item=context.dispatch_item.model_copy(update={"tenant_id": "tenant-other"}),
    )
    store = FileSystemArtifactObjectStore(tmp_path)
    tenant_finding = await C11ComplianceHandler(
        _FakeSource(_compliance_bundle(claim)), store
    ).verify(foreign_context)
    invalid_loader_finding = await C11ComplianceHandler(
        lambda current_claim: object(), store
    ).verify(context)

    assert "C11_TENANT_CONTEXT_MISMATCH" in tenant_finding.finding_codes
    assert "C11_EVIDENCE_INTEGRITY_FAILED" in invalid_loader_finding.finding_codes


@pytest.mark.asyncio
async def test_c11_reports_license_and_empty_sbom_findings(tmp_path: Path) -> None:
    candidate = _candidate("import numpy\nprint(numpy.__version__)\n")
    claim = _claim(candidate)
    license_finding = await C11ComplianceHandler(
        _FakeSource(_compliance_bundle(claim, license_name="CC-BY-4.0")),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_compliance_context(claim))
    empty_bundle = _compliance_bundle(claim)
    empty_sbom = empty_bundle.sbom_manifest.model_copy(update={"components": []})
    empty_sbom_doc = dict(empty_bundle.sbom_document or {})
    empty_sbom_doc["components"] = []
    empty_values = empty_sbom.model_dump(mode="python", exclude={"record_sha256"})
    empty_values.update(
        {
            "sbom_sha256": canonical_sha256(empty_sbom_doc),
            "sbom_artifact": _artifact(canonical_sha256(empty_sbom_doc), "c11/sbom/empty.json"),
        }
    )
    empty_sbom = build_topic4_record(SBOMManifestV1, **empty_values)
    empty_finding = await C11ComplianceHandler(
        _FakeSource(replace(empty_bundle, sbom_manifest=empty_sbom, sbom_document=empty_sbom_doc)),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_compliance_context(claim))

    assert "C11_LICENSE_UNAPPROVED" in license_finding.finding_codes
    assert "C11_SBOM_COMPONENT_MISSING" in empty_finding.finding_codes
    assert "C11_SBOM_EMPTY" in empty_finding.finding_codes
