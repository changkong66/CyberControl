"""Trusted C11 evidence import and tenant-scoped evidence loading."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    MessagePriority,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic4_c1 import ClaimV1, ModuleRunResultV1
from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_c6 import CodeArtifactV1
from liyans_contracts.topic4_c11 import (
    BuildProvenanceV1,
    ComplianceBuildProvenanceInputV1,
    ComplianceEvidenceImportCommandV1,
    ComplianceEvidencePackageV1,
    SBOMComponentV1,
    SBOMManifestV1,
    VulnerabilityRecordV1,
)
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.tenant import TenantContext, current_tenant
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.domains.verification.models import Topic4ClaimModel
from liyans.domains.verification.postgres_repository import PostgresVerificationRepository
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import (
    AuditEventModel,
    IdempotencyRecordModel,
    IdempotencyStatus,
    OutboxMessageModel,
)
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    TransactionIsolation,
    TransactionRetryPolicy,
)
from liyans.infrastructure.observability.audit import (
    GENESIS_HASH,
    AuditDraft,
    AuditRecord,
    build_audit_record,
)
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore
from liyans.infrastructure.persistence.outbox import OutboxMessage
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

from .evidence_source import ComplianceEvidenceBundle
from .models import (
    Topic4BuildProvenanceModel,
    Topic4SBOMComponentModel,
    Topic4SBOMManifestModel,
    Topic4VulnerabilityRecordModel,
)

IDEMPOTENCY_RETENTION = timedelta(days=1)
COMPLIANCE_OPERATION = "topic4.compliance.import"
COMPLIANCE_EVENT = "topic4.compliance.package.imported"


class ComplianceEvidenceError(ValueError):
    """A fail-closed C11 import or loading failure."""


@dataclass(frozen=True, slots=True)
class ComplianceBuilderPolicy:
    policy_version: str
    max_evidence_age_seconds: int
    builders: frozenset[tuple[str, str, str]]

    @classmethod
    def load(cls, path: Path) -> ComplianceBuilderPolicy:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        policy_version = str(document.get("policy_version", ""))
        age = int(document.get("max_evidence_age_seconds", 0))
        raw_builders = document.get("builders")
        if not policy_version or age <= 0 or not isinstance(raw_builders, list) or not raw_builders:
            raise ValueError("compliance builder policy is incomplete")
        builders: set[tuple[str, str, str]] = set()
        for raw in raw_builders:
            if not isinstance(raw, dict):
                raise ValueError("compliance builder policy contains an invalid builder")
            identity = (
                str(raw.get("builder_id", "")),
                str(raw.get("builder_version", "")),
                str(raw.get("toolchain_manifest_version", "")),
            )
            if not all(identity):
                raise ValueError("compliance builder policy contains an incomplete builder")
            builders.add(identity)
        return cls(policy_version, age, frozenset(builders))

    def assert_builder(self, provenance: ComplianceBuildProvenanceInputV1) -> None:
        identity = (
            provenance.builder_id,
            provenance.builder_version,
            provenance.toolchain_manifest_version,
        )
        if identity not in self.builders:
            raise ComplianceEvidenceError("C11 builder is not allowlisted")


class ComplianceEvidenceService:
    """Persists and loads only server-bound, append-only C11 evidence packages."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        verification_repository: PostgresVerificationRepository,
        knowledge_repository: PostgresKnowledgeRepository,
        artifact_store: ArtifactObjectStore,
        outbox: PostgresOutboxRepository,
        policy: ComplianceBuilderPolicy,
        *,
        instance_id: str,
    ) -> None:
        self._database = database
        self._verification_repository = verification_repository
        self._knowledge_repository = knowledge_repository
        self._artifact_store = artifact_store
        self._outbox = outbox
        self._policy = policy
        self._instance_id = instance_id

    @property
    def policy_version(self) -> str:
        return self._policy.policy_version

    @staticmethod
    def _idempotency_document(
        command: ComplianceEvidenceImportCommandV1,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Return only stable request facts for retry identity.

        Envelope timestamps, record hashes, and server-generated command IDs are
        intentionally excluded so a legitimate retry can use a fresh trace and
        still resolve to the original immutable result.
        """
        return {
            "tenant_id": tenant_id,
            "verification_id": str(command.verification_id),
            "claim_id": str(command.claim_id),
            "sbom_document": command.sbom_document,
            "vulnerability_records": [
                item.model_dump(mode="json") for item in command.vulnerability_records
            ],
            "provenance_document": command.provenance_document.model_dump(mode="json"),
        }

    async def import_package(
        self,
        command: ComplianceEvidenceImportCommandV1,
    ) -> ComplianceEvidencePackageV1:
        context = current_tenant()
        if command.tenant_id != context.tenant_id or command.trace_id != context.trace_id:
            raise ComplianceEvidenceError("C11 import command does not match trusted context")
        if not record_integrity_valid(command):
            raise ComplianceEvidenceError("C11 import command integrity failed")

        claim, code_artifact, evidence = await self._load_code_authority(
            command.verification_id,
            command.claim_id,
        )
        if claim.tenant_id != context.tenant_id or claim.trace_id != context.trace_id:
            raise ComplianceEvidenceError("C11 Claim crosses the trusted tenant or trace boundary")
        package = await self._build_package(command, claim, code_artifact, evidence)
        request_document = self._idempotency_document(command, context.tenant_id)
        digest = canonical_sha256({"operation": COMPLIANCE_OPERATION, "request": request_document})

        async def transaction(session: AsyncSession) -> dict[str, Any]:
            await self._lock(session, f"audit:{context.tenant_id}")
            duplicate = await self._reserve_idempotency(
                session,
                context,
                command.idempotency_key_sha256,
                digest,
            )
            if duplicate is not None:
                return duplicate

            audit = await self._append_audit(
                session,
                context,
                action="compliance_evidence_imported",
                target_ref=str(package.compliance_evidence_package_id),
                metadata={
                    "verification_id": str(package.verification_id),
                    "claim_id": str(package.claim_id),
                    "code_artifact_id": str(package.code_artifact.code_artifact_id),
                    "package_sha256": package.record_sha256,
                },
            )
            manifest = package.sbom_manifest
            session.add(
                Topic4SBOMManifestModel(
                    sbom_manifest_record_id=uuid5(manifest.sbom_manifest_id, "record"),
                    sbom_manifest_id=manifest.sbom_manifest_id,
                    code_artifact_id=manifest.code_artifact_id,
                    format=manifest.format,
                    spec_version=manifest.spec_version,
                    serial_number=manifest.serial_number,
                    sbom_artifact=manifest.sbom_artifact.model_dump(mode="json"),
                    sbom_sha256=manifest.sbom_sha256,
                    manifest_document={
                        "record": manifest.model_dump(mode="json"),
                        "package_id": str(package.compliance_evidence_package_id),
                        "import_command_id": str(package.import_command_id),
                        "package_sha256": package.record_sha256,
                        "evidence_refs": [
                            item.model_dump(mode="json") for item in package.evidence_refs
                        ],
                        "expires_at": package.expires_at.isoformat(),
                        "policy_version": package.policy_version,
                    },
                    tenant_id=context.tenant_id,
                    trace_id=manifest.trace_id,
                    version_cas=manifest.version_cas,
                    record_sha256=manifest.record_sha256,
                    immutable=True,
                    audit_event_id=audit.event_id,
                    created_at=manifest.created_at,
                )
            )
            await session.flush()
            for component in manifest.components:
                session.add(
                    Topic4SBOMComponentModel(
                        component_record_id=uuid5(component.component_id, "record"),
                        component_id=component.component_id,
                        sbom_manifest_id=manifest.sbom_manifest_id,
                        name=component.name,
                        version=component.version,
                        package_url=component.package_url,
                        licenses=component.licenses,
                        component_sha256=component.component_sha256,
                        component_document={"record": component.model_dump(mode="json")},
                        tenant_id=context.tenant_id,
                        trace_id=component.trace_id,
                        version_cas=component.version_cas,
                        record_sha256=component.record_sha256,
                        immutable=True,
                        audit_event_id=audit.event_id,
                        created_at=component.created_at,
                    )
                )
            for vulnerability in package.vulnerabilities:
                session.add(
                    Topic4VulnerabilityRecordModel(
                        vulnerability_record_snapshot_id=uuid5(
                            vulnerability.vulnerability_record_id, "snapshot"
                        ),
                        vulnerability_record_id=vulnerability.vulnerability_record_id,
                        sbom_manifest_id=vulnerability.sbom_manifest_id,
                        component_id=vulnerability.component_id,
                        advisory_id=vulnerability.advisory_id,
                        severity=vulnerability.severity.value,
                        cvss_score=vulnerability.cvss_score,
                        affected_range=vulnerability.affected_range,
                        fixed_version=vulnerability.fixed_version,
                        status=vulnerability.status.value,
                        non_waivable=vulnerability.non_waivable,
                        vulnerability_document={"record": vulnerability.model_dump(mode="json")},
                        tenant_id=context.tenant_id,
                        trace_id=vulnerability.trace_id,
                        version_cas=vulnerability.version_cas,
                        record_sha256=vulnerability.record_sha256,
                        immutable=True,
                        audit_event_id=audit.event_id,
                        created_at=vulnerability.created_at,
                    )
                )
            provenance = package.provenance
            session.add(
                Topic4BuildProvenanceModel(
                    build_provenance_record_id=uuid5(provenance.build_provenance_id, "record"),
                    build_provenance_id=provenance.build_provenance_id,
                    code_artifact_id=provenance.code_artifact_id,
                    builder_id=provenance.builder_id,
                    builder_version=provenance.builder_version,
                    toolchain_manifest_version=provenance.toolchain_manifest_version,
                    source_sha256=provenance.source_sha256,
                    build_output_artifact=provenance.build_output_artifact.model_dump(mode="json"),
                    build_output_sha256=provenance.build_output_sha256,
                    sbom_manifest_id=provenance.sbom_manifest_id,
                    sandbox_policy_id=provenance.sandbox_policy_id,
                    reproducible=provenance.reproducible,
                    build_command_sha256=provenance.build_command_sha256,
                    provenance_document={"record": provenance.model_dump(mode="json")},
                    tenant_id=context.tenant_id,
                    trace_id=provenance.trace_id,
                    version_cas=provenance.version_cas,
                    record_sha256=provenance.record_sha256,
                    immutable=True,
                    audit_event_id=audit.event_id,
                    created_at=provenance.created_at,
                )
            )
            await session.flush()
            await self._append_outbox(session, context, package, audit.event_id)
            result = package.model_dump(mode="json")
            await self._complete_idempotency(
                session,
                context,
                command.idempotency_key_sha256,
                result,
            )
            return result

        try:
            result = await self._database.run_transaction(
                transaction,
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=5),
            )
        except IntegrityError as exc:
            raise ComplianceEvidenceError(
                "C11 evidence package conflicts with an immutable record"
            ) from exc
        return ComplianceEvidencePackageV1.model_validate(result)

    async def load(self, claim: ClaimV1) -> ComplianceEvidenceBundle:
        context = current_tenant()
        if claim.tenant_id != context.tenant_id or claim.trace_id != context.trace_id:
            raise ComplianceEvidenceError("C11 Claim does not match trusted context")
        if claim.claim_kind.value != "CODE":
            loaded_claim, evidence = await self._load_claim_authority(
                claim.verification_id,
                claim.claim_id,
            )
            if loaded_claim.model_dump(mode="json") != claim.model_dump(mode="json"):
                raise ComplianceEvidenceError(
                    "C11 Claim does not match the persisted immutable authority"
                )
            return ComplianceEvidenceBundle(
                source_tenant_id=claim.tenant_id,
                code_artifact=None,
                sbom_manifest=None,
                sbom_document=None,
                vulnerabilities=(),
                provenance=None,
                evidence=evidence,
            )
        _loaded_claim, code_artifact, evidence = await self._load_code_authority(
            claim.verification_id,
            claim.claim_id,
        )
        package = await self._latest_package(code_artifact, claim, evidence)
        if package is None:
            return ComplianceEvidenceBundle(
                source_tenant_id=claim.tenant_id,
                code_artifact=code_artifact,
                sbom_manifest=None,
                sbom_document=None,
                vulnerabilities=(),
                provenance=None,
                evidence=evidence,
            )
        if package.expires_at <= datetime.now(UTC):
            return ComplianceEvidenceBundle(
                source_tenant_id=claim.tenant_id,
                code_artifact=code_artifact,
                sbom_manifest=None,
                sbom_document=None,
                vulnerabilities=(),
                provenance=None,
                evidence=evidence,
            )
        raw = await self._artifact_store.read(
            tenant_id=claim.tenant_id,
            storage_namespace=package.sbom_manifest.sbom_artifact.storage_namespace,
            object_key=package.sbom_manifest.sbom_artifact.object_key,
            expected_byte_size=package.sbom_manifest.sbom_artifact.byte_size,
            expected_sha256=package.sbom_manifest.sbom_artifact.sha256,
        )
        try:
            sbom_document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComplianceEvidenceError("C11 persisted SBOM artifact is not valid JSON") from exc
        if not isinstance(sbom_document, dict):
            raise ComplianceEvidenceError("C11 persisted SBOM artifact is not an object")
        if canonical_sha256(sbom_document) != package.sbom_manifest.sbom_sha256:
            raise ComplianceEvidenceError("C11 persisted SBOM content hash does not match manifest")
        output_raw = await self._artifact_store.read(
            tenant_id=claim.tenant_id,
            storage_namespace=package.provenance.build_output_artifact.storage_namespace,
            object_key=package.provenance.build_output_artifact.object_key,
            expected_byte_size=package.provenance.build_output_artifact.byte_size,
            expected_sha256=package.provenance.build_output_artifact.sha256,
        )
        try:
            output_document = json.loads(output_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComplianceEvidenceError("C11 persisted build output is not valid JSON") from exc
        if (
            not isinstance(output_document, dict)
            or canonical_sha256(output_document) != package.provenance.build_output_sha256
        ):
            raise ComplianceEvidenceError(
                "C11 persisted build output hash does not match provenance"
            )
        return ComplianceEvidenceBundle(
            source_tenant_id=claim.tenant_id,
            code_artifact=package.code_artifact,
            sbom_manifest=package.sbom_manifest,
            sbom_document=sbom_document,
            vulnerabilities=tuple(package.vulnerabilities),
            provenance=package.provenance,
            evidence=tuple(package.evidence_refs),
        )

    async def package_for_claim(
        self,
        verification_id: UUID,
        claim_id: UUID,
    ) -> ComplianceEvidencePackageV1 | None:
        context = current_tenant()
        claim, code_artifact, evidence = await self._load_code_authority(verification_id, claim_id)
        if claim.tenant_id != context.tenant_id:
            raise ComplianceEvidenceError("C11 package lookup crosses the tenant boundary")
        return await self._latest_package(code_artifact, claim, evidence)

    async def package_for_claim_id(self, claim_id: UUID) -> ComplianceEvidencePackageV1 | None:
        """Resolve a Claim's verification only inside the current tenant."""
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            row = (
                await session.execute(
                    select(Topic4ClaimModel)
                    .where(
                        Topic4ClaimModel.tenant_id == context.tenant_id,
                        Topic4ClaimModel.claim_id == claim_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is None:
            raise ComplianceEvidenceError("C11 Claim was not found")
        return await self.package_for_claim(row.verification_id, claim_id)

    async def _load_code_authority(
        self,
        verification_id: UUID,
        claim_id: UUID,
    ) -> tuple[ClaimV1, CodeArtifactV1, tuple[EvidenceRefV1, ...]]:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            results = await self._verification_repository.list_module_results(
                session, context.tenant_id, verification_id
            )
            c6_results = [
                item
                for item in results
                if item.claim_id == claim_id and item.module.value == "C6_CODE"
            ]
            if not c6_results:
                raise ComplianceEvidenceError("C11 persisted C6 result is unavailable")
            result = max(
                c6_results,
                key=lambda item: (
                    item.version_cas,
                    item.created_at,
                    str(item.module_result_id),
                ),
            )
        claim, evidence = await self._load_claim_authority(verification_id, claim_id)
        code_artifact = await self._read_code_artifact(result, claim)
        return claim, code_artifact, evidence

    async def _load_claim_authority(
        self,
        verification_id: UUID,
        claim_id: UUID,
    ) -> tuple[ClaimV1, tuple[EvidenceRefV1, ...]]:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            claims = await self._verification_repository.list_claims(
                session,
                context.tenant_id,
                verification_id,
            )
            claim = next((item for item in claims if item.claim_id == claim_id), None)
            if claim is None:
                raise ComplianceEvidenceError("C11 Claim was not found")
            evidence_rows = await self._knowledge_repository.list_evidence_refs(
                session,
                context.tenant_id,
                claim_id,
            )
        evidence = tuple(
            item
            for item in evidence_rows
            if item.verification_id == verification_id
            and item.claim_id == claim_id
            and item.trace_id == claim.trace_id
        )
        return claim, evidence

    async def _read_code_artifact(
        self,
        result: ModuleRunResultV1,
        claim: ClaimV1,
    ) -> CodeArtifactV1:
        raw = await self._artifact_store.read(
            tenant_id=claim.tenant_id,
            storage_namespace=result.result_artifact.storage_namespace,
            object_key=result.result_artifact.object_key,
            expected_byte_size=result.result_artifact.byte_size,
            expected_sha256=result.result_artifact.sha256,
        )
        try:
            document = json.loads(raw.decode("utf-8"))
            artifact = CodeArtifactV1.model_validate(document["code_artifact"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise ComplianceEvidenceError("C11 persisted C6 artifact is invalid") from exc
        if (
            not record_integrity_valid(artifact)
            or artifact.tenant_id != claim.tenant_id
            or artifact.verification_id != claim.verification_id
            or artifact.claim_id != claim.claim_id
            or artifact.candidate_id != claim.candidate_id
            or artifact.candidate_version != claim.candidate_version
        ):
            raise ComplianceEvidenceError("C11 C6 CodeArtifact binding or integrity failed")
        return artifact

    async def _build_package(
        self,
        command: ComplianceEvidenceImportCommandV1,
        claim: ClaimV1,
        code_artifact: CodeArtifactV1,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> ComplianceEvidencePackageV1:
        provenance_input = command.provenance_document
        self._policy.assert_builder(provenance_input)
        if provenance_input.source_sha256 != code_artifact.source_sha256:
            raise ComplianceEvidenceError("C11 provenance source SHA does not match C6")
        sbom_document = command.sbom_document
        if sbom_document.get("bomFormat") != "CycloneDX":
            raise ComplianceEvidenceError("C11 SBOM must use CycloneDX")
        spec_version = str(sbom_document.get("specVersion", ""))
        serial_number = str(sbom_document.get("serialNumber", ""))
        raw_components = sbom_document.get("components")
        if not spec_version or not serial_number or not isinstance(raw_components, list):
            raise ComplianceEvidenceError("C11 CycloneDX document is incomplete")
        if len(raw_components) > 65_536 or any(
            not isinstance(item, dict) for item in raw_components
        ):
            raise ComplianceEvidenceError("C11 CycloneDX components are invalid")
        now = datetime.now(UTC)
        sbom_sha256 = canonical_sha256(sbom_document)
        sbom_artifact = await self._store_json(
            claim.tenant_id,
            f"c11/import/{claim.verification_id}/{claim.claim_id}/sbom/{sbom_sha256}.json",
            sbom_document,
            now,
        )
        manifest_id = uuid5(code_artifact.code_artifact_id, f"sbom:{sbom_sha256}")
        components: list[SBOMComponentV1] = []
        bom_refs: dict[str, UUID] = {}
        for raw in raw_components:
            bom_ref = str(raw.get("bom-ref", ""))
            name = str(raw.get("name", ""))
            version = str(raw.get("version", ""))
            if not bom_ref or not name or not version or bom_ref in bom_refs:
                raise ComplianceEvidenceError("C11 CycloneDX component identity is invalid")
            component_id = uuid5(manifest_id, f"component:{bom_ref}")
            bom_refs[bom_ref] = component_id
            licenses = self._licenses(raw.get("licenses", []))
            component_sha256 = self._sha256_hash(raw.get("hashes", []))
            components.append(
                build_topic4_record(
                    SBOMComponentV1,
                    trace_id=claim.trace_id,
                    tenant_id=claim.tenant_id,
                    version_cas=1,
                    created_at=now,
                    immutable=True,
                    schema_version="sbom-component.v1",
                    component_id=component_id,
                    name=name,
                    version=version,
                    package_url=raw.get("purl"),
                    licenses=licenses,
                    component_sha256=component_sha256,
                )
            )
        manifest = build_topic4_record(
            SBOMManifestV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="sbom-manifest.v1",
            sbom_manifest_id=manifest_id,
            code_artifact_id=code_artifact.code_artifact_id,
            format="CYCLONEDX_JSON",
            spec_version=spec_version,
            serial_number=serial_number,
            components=components,
            sbom_artifact=sbom_artifact,
            sbom_sha256=sbom_sha256,
        )
        vulnerabilities: list[VulnerabilityRecordV1] = []
        for item in command.vulnerability_records:
            component_id = bom_refs.get(item.component_bom_ref)
            if component_id is None:
                raise ComplianceEvidenceError("C11 vulnerability references an unknown component")
            vulnerability_id = uuid5(
                manifest_id,
                f"vulnerability:{component_id}:{item.advisory_id}",
            )
            vulnerabilities.append(
                build_topic4_record(
                    VulnerabilityRecordV1,
                    trace_id=claim.trace_id,
                    tenant_id=claim.tenant_id,
                    version_cas=1,
                    created_at=now,
                    immutable=True,
                    schema_version="vulnerability-record.v1",
                    vulnerability_record_id=vulnerability_id,
                    sbom_manifest_id=manifest_id,
                    component_id=component_id,
                    advisory_id=item.advisory_id,
                    severity=item.severity,
                    cvss_score=item.cvss_score,
                    affected_range=item.affected_range,
                    fixed_version=item.fixed_version,
                    status=item.status,
                    non_waivable=item.non_waivable,
                )
            )
        output_sha256 = canonical_sha256(provenance_input.build_output_document)
        output_artifact = await self._store_json(
            claim.tenant_id,
            f"c11/import/{claim.verification_id}/{claim.claim_id}/build/{output_sha256}.json",
            provenance_input.build_output_document,
            now,
        )
        provenance = build_topic4_record(
            BuildProvenanceV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="build-provenance.v1",
            build_provenance_id=uuid5(
                code_artifact.code_artifact_id, f"provenance:{output_sha256}"
            ),
            code_artifact_id=code_artifact.code_artifact_id,
            builder_id=provenance_input.builder_id,
            builder_version=provenance_input.builder_version,
            toolchain_manifest_version=provenance_input.toolchain_manifest_version,
            source_sha256=provenance_input.source_sha256,
            build_output_artifact=output_artifact,
            build_output_sha256=output_sha256,
            sbom_manifest_id=manifest_id,
            sandbox_policy_id=provenance_input.sandbox_policy_id,
            reproducible=provenance_input.reproducible,
            build_command_sha256=provenance_input.build_command_sha256,
        )
        return build_topic4_record(
            ComplianceEvidencePackageV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="compliance-evidence.package.v1",
            compliance_evidence_package_id=uuid5(
                command.import_command_id,
                f"package:{manifest.sbom_manifest_id}:{provenance.build_provenance_id}",
            ),
            import_command_id=command.import_command_id,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            code_artifact=code_artifact,
            sbom_manifest=manifest,
            vulnerabilities=vulnerabilities,
            provenance=provenance,
            evidence_refs=list(evidence),
            policy_version=self._policy.policy_version,
            expires_at=now + timedelta(seconds=self._policy.max_evidence_age_seconds),
        )

    async def _latest_package(
        self,
        code_artifact: CodeArtifactV1,
        claim: ClaimV1,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> ComplianceEvidencePackageV1 | None:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            manifest_row = (
                await session.execute(
                    select(Topic4SBOMManifestModel)
                    .where(
                        Topic4SBOMManifestModel.tenant_id == context.tenant_id,
                        Topic4SBOMManifestModel.code_artifact_id == code_artifact.code_artifact_id,
                    )
                    .order_by(Topic4SBOMManifestModel.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if manifest_row is None:
                return None
            wrapper = manifest_row.manifest_document
            try:
                record = SBOMManifestV1.model_validate(wrapper["record"])
                package_id = UUID(wrapper["package_id"])
                import_command_id = UUID(wrapper["import_command_id"])
                stored_package_sha256 = str(wrapper["package_sha256"])
                stored_evidence = tuple(
                    EvidenceRefV1.model_validate(item) for item in wrapper["evidence_refs"]
                )
                expires_at = datetime.fromisoformat(wrapper["expires_at"])
                policy_version = str(wrapper["policy_version"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ComplianceEvidenceError("C11 persisted package metadata is invalid") from exc
            if (
                manifest_row.tenant_id != context.tenant_id
                or record.tenant_id != claim.tenant_id
                or record.trace_id != claim.trace_id
                or record.code_artifact_id != code_artifact.code_artifact_id
                or manifest_row.record_sha256 != record.record_sha256
                or not record_integrity_valid(record)
            ):
                raise ComplianceEvidenceError("C11 persisted SBOM manifest binding failed")
            if any(
                item.tenant_id != claim.tenant_id
                or item.trace_id != claim.trace_id
                or item.verification_id != claim.verification_id
                or item.claim_id != claim.claim_id
                or not record_integrity_valid(item)
                for item in stored_evidence
            ):
                raise ComplianceEvidenceError("C11 persisted evidence binding failed")
            current_evidence_ids = {item.evidence_ref_id for item in evidence}
            if any(item.evidence_ref_id not in current_evidence_ids for item in stored_evidence):
                raise ComplianceEvidenceError("C11 persisted evidence reference is unavailable")
            component_rows = (
                await session.execute(
                    select(Topic4SBOMComponentModel)
                    .where(
                        Topic4SBOMComponentModel.tenant_id == context.tenant_id,
                        Topic4SBOMComponentModel.sbom_manifest_id == record.sbom_manifest_id,
                    )
                    .order_by(Topic4SBOMComponentModel.created_at.asc())
                )
            ).scalars()
            components = []
            for row in component_rows:
                try:
                    component = SBOMComponentV1.model_validate(row.component_document["record"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ComplianceEvidenceError(
                        "C11 persisted SBOM component is invalid"
                    ) from exc
                if (
                    component.tenant_id != claim.tenant_id
                    or component.trace_id != claim.trace_id
                    or component.version_cas != row.version_cas
                    or component.record_sha256 != row.record_sha256
                    or not record_integrity_valid(component)
                    or component.component_id != row.component_id
                    or component.component_id
                    not in {item.component_id for item in record.components}
                ):
                    raise ComplianceEvidenceError("C11 persisted SBOM component binding failed")
                components.append(component)
            vulnerability_rows = (
                await session.execute(
                    select(Topic4VulnerabilityRecordModel)
                    .where(
                        Topic4VulnerabilityRecordModel.tenant_id == context.tenant_id,
                        Topic4VulnerabilityRecordModel.sbom_manifest_id == record.sbom_manifest_id,
                    )
                    .order_by(Topic4VulnerabilityRecordModel.created_at.asc())
                )
            ).scalars()
            vulnerabilities = []
            for row in vulnerability_rows:
                try:
                    vulnerability = VulnerabilityRecordV1.model_validate(
                        row.vulnerability_document["record"]
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ComplianceEvidenceError("C11 persisted vulnerability is invalid") from exc
                if (
                    vulnerability.tenant_id != claim.tenant_id
                    or vulnerability.trace_id != claim.trace_id
                    or vulnerability.version_cas != row.version_cas
                    or vulnerability.record_sha256 != row.record_sha256
                    or not record_integrity_valid(vulnerability)
                    or vulnerability.vulnerability_record_id != row.vulnerability_record_id
                    or vulnerability.sbom_manifest_id != record.sbom_manifest_id
                ):
                    raise ComplianceEvidenceError("C11 persisted vulnerability binding failed")
                vulnerabilities.append(vulnerability)
            provenance_row = (
                await session.execute(
                    select(Topic4BuildProvenanceModel)
                    .where(
                        Topic4BuildProvenanceModel.tenant_id == context.tenant_id,
                        Topic4BuildProvenanceModel.sbom_manifest_id == record.sbom_manifest_id,
                    )
                    .order_by(Topic4BuildProvenanceModel.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if provenance_row is None:
                return None
            try:
                provenance = BuildProvenanceV1.model_validate(
                    provenance_row.provenance_document["record"]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ComplianceEvidenceError("C11 persisted provenance is invalid") from exc
            if (
                provenance.tenant_id != claim.tenant_id
                or provenance.trace_id != claim.trace_id
                or provenance.version_cas != provenance_row.version_cas
                or provenance.record_sha256 != provenance_row.record_sha256
                or not record_integrity_valid(provenance)
                or provenance.code_artifact_id != code_artifact.code_artifact_id
                or provenance.sbom_manifest_id != record.sbom_manifest_id
            ):
                raise ComplianceEvidenceError("C11 persisted provenance binding failed")
        package = build_topic4_record(
            ComplianceEvidencePackageV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=manifest_row.version_cas,
            created_at=record.created_at,
            immutable=True,
            schema_version="compliance-evidence.package.v1",
            compliance_evidence_package_id=package_id,
            import_command_id=import_command_id,
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            code_artifact=code_artifact,
            sbom_manifest=record.model_copy(update={"components": components}),
            vulnerabilities=vulnerabilities,
            provenance=provenance,
            evidence_refs=list(stored_evidence),
            policy_version=policy_version,
            expires_at=expires_at,
        )
        if package.record_sha256 != stored_package_sha256:
            raise ComplianceEvidenceError("C11 persisted package SHA mismatch")
        return package

    async def _store_json(
        self,
        tenant_id: str,
        object_key: str,
        document: dict[str, Any],
        created_at: datetime,
    ):
        content = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest = canonical_sha256(document)
        stored = await self._artifact_store.put(
            tenant_id=tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise ComplianceEvidenceError("C11 artifact store integrity mismatch")
        from liyans_contracts.artifacts import ArtifactObjectRefV1

        return ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=object_key,
            media_type="application/json",
            content_encoding="identity",
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=created_at,
        )

    @staticmethod
    def _licenses(raw: object) -> list[str]:
        if not isinstance(raw, list):
            raise ComplianceEvidenceError("C11 component licenses are invalid")
        values: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            license_item = item.get("license")
            if isinstance(license_item, dict):
                value = license_item.get("id") or license_item.get("name")
            else:
                value = item.get("expression")
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        return sorted(set(values))

    @staticmethod
    def _sha256_hash(raw: object) -> str | None:
        if not isinstance(raw, list):
            return None
        for item in raw:
            if isinstance(item, dict) and str(item.get("alg", "")).upper() == "SHA-256":
                value = item.get("content")
                if isinstance(value, str) and len(value) == 64:
                    return value.lower()
        return None

    async def _append_outbox(
        self,
        session: AsyncSession,
        context: TenantContext,
        package: ComplianceEvidencePackageV1,
        audit_event_id: UUID,
    ) -> None:
        partition = f"topic4:compliance:{context.tenant_id}:{package.claim_id}"
        await self._lock(session, f"outbox:{partition}")
        sequence = int(
            (
                await session.execute(
                    select(func.coalesce(func.max(OutboxMessageModel.sequence) + 1, 0)).where(
                        OutboxMessageModel.tenant_id == context.tenant_id,
                        OutboxMessageModel.partition_key == partition,
                    )
                )
            ).scalar_one()
        )
        now = datetime.now(UTC)
        outbox_id = uuid5(package.compliance_evidence_package_id, "outbox")
        envelope = Topic3EnvelopeV1(
            envelope_id=uuid5(package.compliance_evidence_package_id, "envelope"),
            event_type=COMPLIANCE_EVENT,
            message_kind=MessageKind.EVENT,
            tenant_id=context.tenant_id,
            session_id=context.session_id or package.claim_id,
            subject_ref=context.subject_ref,
            correlation_id=package.verification_id,
            causation_id=None,
            sequence=sequence,
            partition_key=partition,
            producer=ProducerMetadataV1(
                agent=None,
                service="topic4-compliance-import",
                instance_id=self._instance_id,
                build_version="topic4-c11-import-v1",
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=f"topic4:compliance:{package.compliance_evidence_package_id}",
                available_at=now,
                expires_at=now + timedelta(days=7),
                priority=MessagePriority.HIGH,
            ),
            resource=None,
            trace_id=package.trace_id,
            span_id=None,
            created_at=now,
            error=None,
            payload={
                "package_id": str(package.compliance_evidence_package_id),
                "verification_id": str(package.verification_id),
                "claim_id": str(package.claim_id),
                "package_sha256": package.record_sha256,
                "audit_event_id": str(audit_event_id),
            },
        )
        await self._outbox.append(
            session,
            OutboxMessage(
                outbox_id=outbox_id,
                tenant_id=context.tenant_id,
                envelope=envelope,
                created_at=now,
                available_at=now,
                published_at=None,
                max_attempts=envelope.delivery.max_attempts,
            ),
        )

    async def _reserve_idempotency(
        self,
        session: AsyncSession,
        context: TenantContext,
        key: str,
        digest: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        statement = (
            insert(IdempotencyRecordModel)
            .values(
                tenant_id=context.tenant_id,
                idempotency_key=key,
                operation=COMPLIANCE_OPERATION,
                request_digest=digest,
                state=IdempotencyStatus.PROCESSING.value,
                lease_owner=self._instance_id,
                lease_expires_at=now + timedelta(minutes=2),
                expires_at=now + IDEMPOTENCY_RETENTION,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyRecordModel.tenant_id,
                    IdempotencyRecordModel.idempotency_key,
                ]
            )
            .returning(IdempotencyRecordModel.idempotency_key)
        )
        if (await session.execute(statement)).scalar_one_or_none() is not None:
            return None
        record = (
            await session.execute(
                select(IdempotencyRecordModel)
                .where(
                    IdempotencyRecordModel.tenant_id == context.tenant_id,
                    IdempotencyRecordModel.idempotency_key == key,
                )
                .with_for_update()
            )
        ).scalar_one()
        if record.request_digest != digest or record.operation != COMPLIANCE_OPERATION:
            raise ComplianceEvidenceError("C11 Idempotency-Key was reused for different content")
        if record.state == IdempotencyStatus.COMPLETED.value:
            if not isinstance(record.result_payload, dict):
                raise ComplianceEvidenceError("C11 idempotent result is unavailable")
            return dict(record.result_payload)
        if record.lease_expires_at is not None and record.lease_expires_at > now:
            raise ComplianceEvidenceError("C11 import is already in progress")
        record.lease_owner = self._instance_id
        record.lease_expires_at = now + timedelta(minutes=2)
        record.expires_at = now + IDEMPOTENCY_RETENTION
        record.updated_at = now
        return None

    @staticmethod
    async def _complete_idempotency(
        session: AsyncSession,
        context: TenantContext,
        key: str,
        result: dict[str, Any],
    ) -> None:
        record = (
            await session.execute(
                select(IdempotencyRecordModel)
                .where(
                    IdempotencyRecordModel.tenant_id == context.tenant_id,
                    IdempotencyRecordModel.idempotency_key == key,
                )
                .with_for_update()
            )
        ).scalar_one()
        record.state = IdempotencyStatus.COMPLETED.value
        record.lease_owner = None
        record.lease_expires_at = None
        record.response_status_code = 200
        record.result_payload = result
        record.updated_at = datetime.now(UTC)

    @staticmethod
    async def _lock(session: AsyncSession, key: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": key},
        )

    @staticmethod
    async def _append_audit(
        session: AsyncSession,
        context: TenantContext,
        *,
        action: str,
        target_ref: str,
        metadata: dict[str, Any],
    ) -> AuditRecord:
        await ComplianceEvidenceService._lock(session, f"audit:{context.tenant_id}")
        previous = (
            await session.execute(
                select(AuditEventModel)
                .where(AuditEventModel.tenant_id == context.tenant_id)
                .order_by(AuditEventModel.sequence.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        draft = AuditDraft(
            tenant_id=context.tenant_id,
            category="TOPIC4",
            action=action,
            outcome="SUCCEEDED",
            actor_ref=context.subject_ref,
            target_ref=target_ref,
            trace_id=context.trace_id,
            envelope_id=None,
            metadata=metadata,
            occurred_at=datetime.now(UTC),
        )
        record = build_audit_record(
            draft,
            0 if previous is None else previous.sequence + 1,
            GENESIS_HASH if previous is None else previous.event_hash,
        )
        session.add(
            AuditEventModel(
                event_id=record.event_id,
                tenant_id=record.tenant_id,
                sequence=record.sequence,
                category=record.category,
                action=record.action,
                outcome=record.outcome,
                actor_ref=record.actor_ref,
                target_ref=record.target_ref,
                trace_id=record.trace_id,
                envelope_id=None,
                event_metadata=record.metadata,
                occurred_at=record.occurred_at,
                previous_hash=record.previous_hash,
                event_hash=record.event_hash,
            )
        )
        await session.flush()
        return record
