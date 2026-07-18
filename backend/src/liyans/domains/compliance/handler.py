from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c6 import CodeArtifactV1
from liyans_contracts.topic4_c11 import (
    BuildProvenanceV1,
    SBOMComponentV1,
    SBOMManifestV1,
    VulnerabilityRecordV1,
    VulnerabilityStatus,
)
from liyans_contracts.topic4_common import FindingSeverity, VerificationVerdict

from liyans.domains.verification.execution import ModuleExecutionContext, ModuleFinding
from liyans.domains.verification.records import record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore

from .evidence_source import ComplianceEvidenceBundle, ComplianceEvidenceSource

C11_HANDLER_VERSION = "c11-compliance-handler-v1"
C11_POLICY_VERSION = "c11-supply-chain-policy-v1"

_ALLOWED_LICENSES = frozenset(
    {
        value.upper()
        for value in {
            "0BSD",
            "Apache-2.0",
            "BSD-2-Clause",
            "BSD-3-Clause",
            "ISC",
            "MIT",
            "MPL-2.0",
            "PSF-2.0",
            "Unicode-3.0",
            "Zlib",
        }
    }
)
_UNKNOWN_LICENSES = frozenset({"", "NONE", "NOASSERTION", "UNKNOWN"})
_PROHIBITED_LICENSE_MARKERS = (
    "AGPL",
    "GPL",
    "SSPL",
    "BUSL",
    "COMMONS CLAUSE",
    "ELASTIC LICENSE",
)
_INTERNAL_PACKAGE_PREFIXES = ("liyans", "@liyans/")


@dataclass(frozen=True, slots=True)
class ComplianceIssue:
    code: str
    severity: FindingSeverity
    detail: str
    non_waivable: bool = False


class ComplianceLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> ComplianceEvidenceBundle: ...


@dataclass(frozen=True, slots=True)
class C11HandlerPolicy:
    max_evidence_count: int = 512
    max_components: int = 65_536
    max_artifact_bytes: int = 33_554_432

    def __post_init__(self) -> None:
        if not 1 <= self.max_evidence_count <= 4096:
            raise ValueError("max_evidence_count must be between 1 and 4096")
        if not 1 <= self.max_components <= 65_536:
            raise ValueError("max_components must be between 1 and 65536")
        if not 1 <= self.max_artifact_bytes <= 33_554_432:
            raise ValueError("max_artifact_bytes must be between 1 and 33554432")


class C11ComplianceHandler:
    """Local SBOM, vulnerability, license, and provenance verifier."""

    def __init__(
        self,
        evidence_source: ComplianceEvidenceSource | ComplianceLoader | Callable[..., object],
        artifact_store: ArtifactObjectStore,
        *,
        policy: C11HandlerPolicy | None = None,
    ) -> None:
        self._evidence_source = evidence_source
        self._artifact_store = artifact_store
        self._policy = policy or C11HandlerPolicy()

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        claim = context.claim
        if claim.tenant_id != context.dispatch_item.tenant_id:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C11_TENANT_CONTEXT_MISMATCH"
            )
        try:
            bundle = await self._load_bundle(claim)
            self._validate_source_tenant(claim, bundle)
            if claim.claim_kind.value != "CODE":
                return await self._not_applicable(context, bundle)
            self._validate_bundle(claim, bundle)
            if not bundle.evidence:
                return await self._error_finding(
                    context, VerificationVerdict.INSUFFICIENT_EVIDENCE, "C11_LOCAL_EVIDENCE_MISSING"
                )
            issues = self._audit(claim, bundle)
            verdict = self._verdict(issues)
            document = self._document(context, bundle, issues, verdict)
            artifact = await self._write_artifact(context, document)
            codes = tuple(issue.code for issue in issues) or ("C11_COMPLIANCE_SCAN_CLEAN",)
            return ModuleFinding(
                verdict=verdict,
                confidence=0.99 if not issues else 0.98,
                evidence_ref_ids=tuple(ref.evidence_ref_id for ref in bundle.evidence),
                finding_codes=codes,
                result_artifact=artifact,
                result_sha256=artifact.sha256,
                deterministic=True,
            )
        except ValueError as exc:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, self._error_code(exc)
            )
        except Exception:
            return await self._error_finding(
                context, VerificationVerdict.ERROR, "C11_HANDLER_UNEXPECTED_ERROR"
            )

    async def _load_bundle(self, claim: ClaimV1) -> ComplianceEvidenceBundle:
        source = self._evidence_source
        result = source.load(claim) if hasattr(source, "load") else source(claim)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ComplianceEvidenceBundle):
            raise ValueError("C11 evidence source returned an invalid bundle")
        return result

    @staticmethod
    def _validate_source_tenant(claim: ClaimV1, bundle: ComplianceEvidenceBundle) -> None:
        if bundle.source_tenant_id != claim.tenant_id:
            raise ValueError("C11 trusted source tenant does not match Claim tenant")

    def _validate_bundle(self, claim: ClaimV1, bundle: ComplianceEvidenceBundle) -> None:
        if len(bundle.evidence) > self._policy.max_evidence_count:
            raise ValueError("C11 evidence count exceeds the safety limit")
        code = bundle.code_artifact
        sbom = bundle.sbom_manifest
        if (
            code is None
            or sbom is None
            or bundle.sbom_document is None
            or bundle.provenance is None
        ):
            raise ValueError("C11 code supply-chain evidence is incomplete")
        self._validate_code_artifact(claim, code)
        self._validate_sbom(code, sbom, bundle.sbom_document)
        self._validate_components(sbom.components)
        self._validate_vulnerabilities(sbom, sbom.components, bundle.vulnerabilities)
        self._validate_provenance(code, sbom, bundle.provenance)
        seen: set[UUID] = set()
        for ref in bundle.evidence:
            if ref.tenant_id != claim.tenant_id:
                raise ValueError("C11 evidence crosses tenant boundaries")
            if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
                raise ValueError("C11 evidence is not bound to the Claim")
            if ref.trace_id != claim.trace_id or not record_integrity_valid(ref):
                raise ValueError("C11 evidence record integrity check failed")
            if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
                raise ValueError("C11 evidence excerpt integrity check failed")
            if ref.evidence_ref_id in seen:
                raise ValueError("C11 evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)

    @staticmethod
    def _validate_code_artifact(claim: ClaimV1, code: CodeArtifactV1) -> None:
        if (
            code.tenant_id != claim.tenant_id
            or code.verification_id != claim.verification_id
            or code.claim_id != claim.claim_id
            or code.candidate_id != claim.candidate_id
            or code.candidate_version != claim.candidate_version
            or not record_integrity_valid(code)
        ):
            raise ValueError("C11 code artifact binding or integrity failed")
        if code.source_artifact.sha256 != code.source_sha256:
            raise ValueError("C11 code source artifact hash mismatch")
        for dependency in code.dependencies:
            if not record_integrity_valid(dependency):
                raise ValueError("C11 code dependency integrity failed")

    @staticmethod
    def _validate_sbom(
        code: CodeArtifactV1,
        sbom: SBOMManifestV1,
        sbom_document: dict[str, object],
    ) -> None:
        if (
            sbom.tenant_id != code.tenant_id
            or sbom.code_artifact_id != code.code_artifact_id
            or not record_integrity_valid(sbom)
        ):
            raise ValueError("C11 SBOM binding or integrity failed")
        if sbom.sbom_artifact.sha256 != sbom.sbom_sha256:
            raise ValueError("C11 SBOM artifact hash mismatch")
        if sbom_document.get("bomFormat") != "CycloneDX":
            raise ValueError("C11 SBOM format is not CycloneDX")
        components = sbom_document.get("components")
        if not isinstance(components, list):
            raise ValueError("C11 SBOM document components are invalid")
        if canonical_sha256(sbom_document) != sbom.sbom_sha256:
            raise ValueError("C11 SBOM document hash mismatch")

    def _validate_components(self, components: list[SBOMComponentV1]) -> None:
        if len(components) > self._policy.max_components:
            raise ValueError("C11 SBOM component count exceeds the safety limit")
        ids: set[UUID] = set()
        names: set[tuple[str, str, str | None]] = set()
        for component in components:
            if not record_integrity_valid(component):
                raise ValueError("C11 SBOM component integrity failed")
            if component.component_id in ids:
                raise ValueError("C11 SBOM contains duplicate component IDs")
            ids.add(component.component_id)
            key = (component.name, component.version, component.package_url)
            if key in names:
                raise ValueError("C11 SBOM contains duplicate components")
            names.add(key)

    @staticmethod
    def _validate_vulnerabilities(
        sbom: SBOMManifestV1,
        components: list[SBOMComponentV1],
        vulnerabilities: tuple[VulnerabilityRecordV1, ...],
    ) -> None:
        component_ids = {component.component_id for component in components}
        seen: set[tuple[UUID, str]] = set()
        for record in vulnerabilities:
            if not record_integrity_valid(record):
                raise ValueError("C11 vulnerability record integrity failed")
            if (
                record.tenant_id != sbom.tenant_id
                or record.sbom_manifest_id != sbom.sbom_manifest_id
            ):
                raise ValueError("C11 vulnerability record binding failed")
            if record.component_id not in component_ids:
                raise ValueError("C11 vulnerability references an unknown component")
            identity = (record.component_id, record.advisory_id)
            if identity in seen:
                raise ValueError("C11 duplicate vulnerability record")
            seen.add(identity)

    @staticmethod
    def _validate_provenance(
        code: CodeArtifactV1,
        sbom: SBOMManifestV1,
        provenance: BuildProvenanceV1,
    ) -> None:
        if (
            provenance.tenant_id != code.tenant_id
            or provenance.code_artifact_id != code.code_artifact_id
            or provenance.sbom_manifest_id != sbom.sbom_manifest_id
            or provenance.source_sha256 != code.source_sha256
            or provenance.build_output_artifact.sha256 != provenance.build_output_sha256
            or not provenance.reproducible
            or not record_integrity_valid(provenance)
        ):
            raise ValueError("C11 build provenance is not reproducible or bound")

    def _audit(
        self,
        claim: ClaimV1,
        bundle: ComplianceEvidenceBundle,
    ) -> tuple[ComplianceIssue, ...]:
        del claim
        code = bundle.code_artifact
        sbom = bundle.sbom_manifest
        provenance = bundle.provenance
        assert code is not None and sbom is not None and provenance is not None
        issues: list[ComplianceIssue] = []
        component_by_name = {
            (component.name, component.version): component for component in sbom.components
        }
        for dependency in code.dependencies:
            if not any(
                component.name == dependency.name
                and (dependency.version is None or component.version == dependency.version)
                for component in sbom.components
            ):
                issues.append(
                    ComplianceIssue(
                        "C11_SBOM_COMPONENT_MISSING",
                        FindingSeverity.HIGH,
                        f"dependency {dependency.name} is absent from the SBOM",
                    )
                )
        for component in sbom.components:
            licenses = tuple(
                sorted({license_value.strip() for license_value in component.licenses})
            )
            internal = component.name.casefold().startswith(_INTERNAL_PACKAGE_PREFIXES)
            if not licenses and not internal:
                issues.append(
                    ComplianceIssue(
                        "C11_LICENSE_EVIDENCE_MISSING",
                        FindingSeverity.HIGH,
                        f"license evidence missing for {component.name}",
                    )
                )
            for license_value in licenses:
                normalized = license_value.upper()
                if normalized in _UNKNOWN_LICENSES and not internal:
                    issues.append(
                        ComplianceIssue(
                            "C11_LICENSE_UNKNOWN",
                            FindingSeverity.HIGH,
                            f"unknown license for {component.name}",
                        )
                    )
                if normalized not in _ALLOWED_LICENSES and not internal:
                    if any(marker in normalized for marker in _PROHIBITED_LICENSE_MARKERS):
                        issues.append(
                            ComplianceIssue(
                                "C11_LICENSE_PROHIBITED",
                                FindingSeverity.CRITICAL,
                                f"prohibited license for {component.name}",
                                non_waivable=True,
                            )
                        )
                    else:
                        issues.append(
                            ComplianceIssue(
                                "C11_LICENSE_UNAPPROVED",
                                FindingSeverity.HIGH,
                                f"unapproved license for {component.name}",
                            )
                        )
        for vulnerability in bundle.vulnerabilities:
            if vulnerability.status == VulnerabilityStatus.OPEN and vulnerability.severity in {
                FindingSeverity.HIGH,
                FindingSeverity.CRITICAL,
            }:
                issues.append(
                    ComplianceIssue(
                        "C11_OPEN_HIGH_VULNERABILITY",
                        vulnerability.severity,
                        f"open vulnerability {vulnerability.advisory_id}",
                        non_waivable=vulnerability.non_waivable,
                    )
                )
            if (
                vulnerability.non_waivable
                and vulnerability.status == VulnerabilityStatus.ACCEPTED_RISK
            ):
                issues.append(
                    ComplianceIssue(
                        "C11_NON_WAIVABLE_ACCEPTED_RISK",
                        FindingSeverity.CRITICAL,
                        f"non-waivable vulnerability {vulnerability.advisory_id} is accepted",
                        non_waivable=True,
                    )
                )
        if not component_by_name:
            issues.append(
                ComplianceIssue(
                    "C11_SBOM_EMPTY",
                    FindingSeverity.HIGH,
                    "SBOM contains no components",
                )
            )
        if not provenance.reproducible:
            issues.append(
                ComplianceIssue(
                    "C11_BUILD_NOT_REPRODUCIBLE",
                    FindingSeverity.CRITICAL,
                    "build provenance is not reproducible",
                    non_waivable=True,
                )
            )
        return tuple(issues)

    @staticmethod
    def _verdict(issues: tuple[ComplianceIssue, ...]) -> VerificationVerdict:
        return VerificationVerdict.UNSAFE if issues else VerificationVerdict.SUPPORTED

    @staticmethod
    def _document(context, bundle, issues, verdict):
        return {
            "schema_version": "c11-compliance-result.v1",
            "handler_version": C11_HANDLER_VERSION,
            "policy_version": C11_POLICY_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "candidate_id": str(context.claim.candidate_id),
            "candidate_version": context.claim.candidate_version,
            "candidate_sha256": context.claim.candidate_sha256,
            "source_tenant_id": bundle.source_tenant_id,
            "verdict": verdict.value,
            "code_artifact": bundle.code_artifact.model_dump(mode="json")
            if bundle.code_artifact
            else None,
            "sbom_manifest": bundle.sbom_manifest.model_dump(mode="json")
            if bundle.sbom_manifest
            else None,
            "vulnerabilities": [
                record.model_dump(mode="json") for record in bundle.vulnerabilities
            ],
            "provenance": bundle.provenance.model_dump(mode="json") if bundle.provenance else None,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "detail": issue.detail,
                    "non_waivable": issue.non_waivable,
                }
                for issue in issues
            ],
            "raw_content_retained": False,
        }

    async def _write_artifact(self, context, document):
        content = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(content) > self._policy.max_artifact_bytes:
            raise ValueError("C11 result artifact exceeds the safety limit")
        digest = canonical_sha256(document)
        object_key = f"c11/{context.claim.verification_id}/{context.claim.claim_id}/{digest}.json"
        stored = await self._artifact_store.put(
            tenant_id=context.claim.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise ValueError("C11 result artifact metadata failed integrity validation")
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

    async def _not_applicable(self, context, bundle):
        document = {
            "schema_version": "c11-compliance-result.v1",
            "handler_version": C11_HANDLER_VERSION,
            "policy_version": C11_POLICY_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "verdict": VerificationVerdict.NOT_APPLICABLE.value,
            "finding_codes": ["C11_NON_CODE_CLAIM"],
            "source_tenant_id": bundle.source_tenant_id,
            "raw_content_retained": False,
        }
        artifact = await self._write_artifact(context, document)
        return ModuleFinding(
            VerificationVerdict.NOT_APPLICABLE,
            1.0,
            (),
            ("C11_NON_CODE_CLAIM",),
            artifact,
            artifact.sha256,
            True,
        )

    async def _error_finding(self, context, verdict, code):
        document = {
            "schema_version": "c11-compliance-result.v1",
            "handler_version": C11_HANDLER_VERSION,
            "policy_version": C11_POLICY_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "verdict": verdict.value,
            "confidence": 0.0,
            "finding_codes": [code],
            "raw_content_retained": False,
        }
        artifact = await self._write_artifact(context, document)
        return ModuleFinding(verdict, 0.0, (), (code,), artifact, artifact.sha256, True)

    @staticmethod
    def _error_code(error: ValueError) -> str:
        message = str(error).casefold()
        if "tenant" in message:
            return "C11_TENANT_ISOLATION_FAILED"
        if "evidence" in message:
            return "C11_EVIDENCE_INTEGRITY_FAILED"
        if "sbom" in message or "component" in message:
            return "C11_SBOM_INTEGRITY_FAILED"
        if "provenance" in message or "reproducible" in message:
            return "C11_PROVENANCE_INTEGRITY_FAILED"
        if "code artifact" in message or "candidate" in message:
            return "C11_CODE_ARTIFACT_BINDING_FAILED"
        return "C11_HANDLER_VALIDATION_FAILED"
