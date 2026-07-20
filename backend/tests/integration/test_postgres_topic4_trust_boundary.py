from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import VerificationTrigger
from liyans_contracts.topic3 import CandidateV1
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c6 import CodeArtifactV1
from liyans_contracts.topic4_c11 import (
    ComplianceBuildProvenanceInputV1,
    ComplianceEvidenceImportCommandV1,
)
from liyans_contracts.topic4_common import VerificationModule
from test_topic4_c6_code import _candidate as code_candidate_factory
from test_topic4_c6_code import _snapshot

from liyans.core.tenant import tenant_scope
from liyans.domains.code.evidence_source import CodeEvidenceBundle
from liyans.domains.code.handler import C6CodeHandler
from liyans.domains.compliance.handler import C11ComplianceHandler
from liyans.domains.compliance.service import (
    ComplianceBuilderPolicy,
    ComplianceEvidenceError,
    ComplianceEvidenceService,
)
from liyans.domains.topic3.entities import CandidateRecord
from liyans.domains.verification.execution import BoundedModuleExecutor
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.infrastructure.database.context import current_session_context

from .test_postgres_topic4 import _NotApplicableHandler
from .topic4_runtime_support import COURSE_ID, KP_ID, build_topic4_runtime_fixture

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]


class _CodeEvidenceSource:
    def __init__(self, bundle: CodeEvidenceBundle) -> None:
        self._bundle = bundle

    async def load(self, claim: ClaimV1) -> CodeEvidenceBundle:
        return self._bundle


@pytest.mark.asyncio
async def test_c11_non_code_claims_remain_not_applicable_with_trusted_service(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="trust-boundary-c11-non-code",
    )

    with tenant_scope(fixture.context):
        request = await fixture.runtime._request_for_candidate(
            fixture.candidate,
            context=fixture.context,
            source_envelope_id=uuid4(),
            trigger=VerificationTrigger.INITIAL_GENERATION,
            parent_verification_id=None,
            verification_id=uuid4(),
            course_id=COURSE_ID,
            target_kp_id=KP_ID,
        )
        accepted = await fixture.verification_service.accept_verification(request)
        prepared = await fixture.verification_service.prepare_control_plane(
            request.verification_id,
            expected_state_version=accepted.state_version,
            idempotency_key=f"topic4:c11:non-code:{request.verification_id.hex}",
        )
        service = ComplianceEvidenceService(
            fixture.database,
            fixture.verification_repository,
            fixture.knowledge_repository,
            fixture.artifact_store,
            fixture.outbox,
            ComplianceBuilderPolicy.load(ROOT / "config" / "compliance-builders.toml"),
            instance_id="topic4-c11-non-code-test",
        )
        handlers = {module: _NotApplicableHandler() for module in VerificationModule}
        handlers[VerificationModule.C11_COMPLIANCE] = C11ComplianceHandler(
            service,
            fixture.artifact_store,
        )
        execution = await BoundedModuleExecutor(
            handlers,
            worker_instance_id="topic4-c11-non-code-worker",
            retry_backoff_ms=0,
        ).execute(
            prepared.dispatch_plan,
            prepared.claims,
            deadline_at=request.deadline_at,
        )

    c11_results = [
        item for item in execution.results if item.module == VerificationModule.C11_COMPLIANCE
    ]
    assert c11_results
    assert all(item.verdict.value == "NOT_APPLICABLE" for item in c11_results)
    assert all(item.finding_codes == ["C11_NON_CODE_CLAIM"] for item in c11_results)


async def _prepare_code_authority(fixture, now: datetime):
    candidate = code_candidate_factory(
        "import numpy as np\n"
        "from scipy import signal\n"
        "system = signal.TransferFunction([1.0], [1.0, 2.0, 1.0])\n"
        "t = np.linspace(0.0, 10.0, 101)\n"
        "t, y = signal.step(system, T=t)\n"
    )
    candidate_values = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    candidate_values["blueprint_id"] = str(fixture.candidate.blueprint_id)
    candidate_values["blueprint_version"] = fixture.candidate.blueprint_version
    candidate = CandidateV1(
        **candidate_values,
        candidate_sha256=canonical_sha256(candidate_values),
    )
    context = fixture.context
    with tenant_scope(context):
        async with fixture.database.transaction(context=current_session_context()) as session:
            audit = await fixture.runtime._append_audit(
                session,
                context,
                action="TEST_C6_AUTHORITY_CREATED",
                target_ref=str(candidate.candidate_id),
                metadata={"candidate_sha256": candidate.candidate_sha256},
            )
            await fixture.topic3_repository.append_candidate(
                session,
                context.tenant_id,
                CandidateRecord(
                    candidate_record_id=uuid5(candidate.candidate_id, "candidate-record-v1"),
                    candidate=candidate,
                    frozen_at=now,
                ),
                audit,
            )
        request = await fixture.runtime._request_for_candidate(
            candidate,
            context=context,
            source_envelope_id=uuid4(),
            trigger=VerificationTrigger.INITIAL_GENERATION,
            parent_verification_id=None,
            verification_id=uuid4(),
            course_id=COURSE_ID,
            target_kp_id=KP_ID,
        )
        accepted = await fixture.verification_service.accept_verification(request)
        prepared = await fixture.verification_service.prepare_control_plane(
            request.verification_id,
            expected_state_version=accepted.state_version,
            idempotency_key=f"topic4:c11:prepare:{request.verification_id.hex}",
        )
        bundle = CodeEvidenceBundle(
            candidate=candidate,
            snapshot=_snapshot(),
            evidence=(),
            knowledge_base_version_id=uuid4(),
        )
        handlers = {module: _NotApplicableHandler() for module in VerificationModule}
        handlers[VerificationModule.C6_CODE] = C6CodeHandler(
            _CodeEvidenceSource(bundle),
            fixture.artifact_store,
        )
        execution = await BoundedModuleExecutor(
            handlers,
            worker_instance_id="topic4-c11-code-worker",
            retry_backoff_ms=0,
        ).execute(
            prepared.dispatch_plan,
            prepared.claims,
            deadline_at=request.deadline_at,
        )
        async with fixture.database.transaction(context=current_session_context()) as session:
            audit_id = await fixture.runtime._append_audit(
                session,
                context,
                action="TEST_C6_MODULE_RESULT_RECORDED",
                target_ref=str(request.verification_id),
                metadata={"module_result_count": len(execution.results)},
            )
            await fixture.verification_repository.append_module_runs(
                session,
                context.tenant_id,
                list(execution.run_snapshots),
                audit_id,
            )
            await fixture.verification_repository.append_module_results(
                session,
                context.tenant_id,
                list(execution.results),
                audit_id,
            )
        claim = next(item for item in prepared.claims if item.claim_kind.value == "CODE")
        result = next(
            item
            for item in execution.results
            if item.module == VerificationModule.C6_CODE and item.claim_id == claim.claim_id
        )
        raw = await fixture.artifact_store.read(
            tenant_id=context.tenant_id,
            storage_namespace=result.result_artifact.storage_namespace,
            object_key=result.result_artifact.object_key,
            expected_byte_size=result.result_artifact.byte_size,
            expected_sha256=result.result_artifact.sha256,
        )
    code_artifact = CodeArtifactV1.model_validate(json.loads(raw)["code_artifact"])
    assert record_integrity_valid(code_artifact)
    return claim, code_artifact


def _import_command(
    claim: ClaimV1,
    code_artifact: CodeArtifactV1,
    *,
    key: str,
    created_at: datetime,
    builder_id: str = "liyans-local-python-evidence",
) -> ComplianceEvidenceImportCommandV1:
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid4()}",
        "components": [
            {
                "bom-ref": "pkg:pypi/numpy@1.0.0",
                "name": "numpy",
                "version": "1.0.0",
                "purl": "pkg:pypi/numpy@1.0.0",
                "licenses": [{"license": {"id": "BSD-3-Clause"}}],
            }
        ],
    }
    provenance = ComplianceBuildProvenanceInputV1(
        builder_id=builder_id,
        builder_version="1.0.0",
        toolchain_manifest_version="topic4-toolchain-v1",
        source_sha256=code_artifact.source_sha256,
        build_output_document={"status": "verified", "exit_code": 0},
        sandbox_policy_id=uuid4(),
        reproducible=True,
        build_command_sha256="a" * 64,
    )
    return build_topic4_record(
        ComplianceEvidenceImportCommandV1,
        trace_id=claim.trace_id,
        tenant_id=claim.tenant_id,
        version_cas=1,
        created_at=created_at,
        immutable=True,
        schema_version="compliance-evidence-import.command.v1",
        import_command_id=uuid5(NAMESPACE_URL, f"c11-import:{key}"),
        verification_id=claim.verification_id,
        claim_id=claim.claim_id,
        sbom_document=sbom,
        vulnerability_records=[],
        provenance_document=provenance,
        idempotency_key_sha256=canonical_sha256({"idempotency_key": key}),
    )


@pytest.mark.asyncio
async def test_c11_trusted_import_is_idempotent_and_reloadable(
    postgres_runtime, tmp_path: Path
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="trust-boundary-c11",
    )
    now = datetime.now(UTC)
    claim, code_artifact = await _prepare_code_authority(fixture, now)
    policy = ComplianceBuilderPolicy.load(ROOT / "config" / "compliance-builders.toml")
    service = ComplianceEvidenceService(
        fixture.database,
        fixture.verification_repository,
        fixture.knowledge_repository,
        fixture.artifact_store,
        fixture.outbox,
        policy,
        instance_id="topic4-c11-test",
    )
    key = "topic4-c11-import-00000000000000000001"
    command = _import_command(claim, code_artifact, key=key, created_at=now)

    with tenant_scope(fixture.context):
        package = await service.import_package(command)
        replay_values = command.model_dump(mode="python", exclude={"record_sha256"})
        replay_values["created_at"] = now + timedelta(seconds=5)
        replay_values["vulnerability_records"] = command.vulnerability_records
        replay_values["provenance_document"] = command.provenance_document
        replay = await service.import_package(
            build_topic4_record(ComplianceEvidenceImportCommandV1, **replay_values)
        )
        loaded = await service.load(claim)

    assert package == replay
    assert record_integrity_valid(package)
    assert loaded.code_artifact == code_artifact
    assert loaded.sbom_manifest is not None
    assert loaded.provenance is not None
    assert loaded.sbom_document is not None
    assert loaded.sbom_document["bomFormat"] == "CycloneDX"

    with tenant_scope(fixture.context):
        with pytest.raises(ComplianceEvidenceError, match="different content"):
            changed_values = command.model_dump(mode="python", exclude={"record_sha256"})
            changed_values["sbom_document"] = {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "serialNumber": "urn:uuid:changed",
                "components": [],
            }
            changed_values["vulnerability_records"] = command.vulnerability_records
            changed_values["provenance_document"] = command.provenance_document
            await service.import_package(
                build_topic4_record(ComplianceEvidenceImportCommandV1, **changed_values)
            )
        with pytest.raises(ComplianceEvidenceError, match="allowlisted"):
            await service.import_package(
                _import_command(
                    claim,
                    code_artifact,
                    key="topic4-c11-import-00000000000000000002",
                    created_at=now,
                    builder_id="untrusted-builder",
                )
            )

    foreign = fixture.context.__class__(
        tenant_id="foreign-tenant",
        subject_ref=fixture.context.subject_ref,
        roles=fixture.context.roles,
        scopes=fixture.context.scopes,
        trace_id=fixture.context.trace_id,
    )
    with tenant_scope(foreign):
        with pytest.raises(ComplianceEvidenceError, match="Claim was not found"):
            await service.package_for_claim_id(claim.claim_id)
