from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c9 import SecurityDisposition, SecurityFindingV1
from liyans_contracts.topic4_common import FindingSeverity, VerificationVerdict

from liyans.domains.verification.execution import ModuleExecutionContext, ModuleFinding
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore

from .detector import DeterministicSecurityDetector, SecurityMatch
from .evidence_source import SecurityEvidenceBundle, SecurityEvidenceSource

C9_HANDLER_VERSION = "c9-security-handler-v1"
C9_POLICY_VERSION = "c9-content-security-policy-v1"


class SecurityEvidenceLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> SecurityEvidenceBundle: ...


@dataclass(frozen=True, slots=True)
class C9HandlerPolicy:
    max_evidence_count: int = 512
    max_artifact_bytes: int = 33_554_432

    def __post_init__(self) -> None:
        if not 1 <= self.max_evidence_count <= 4096:
            raise ValueError("max_evidence_count must be between 1 and 4096")
        if not 1 <= self.max_artifact_bytes <= 33_554_432:
            raise ValueError("max_artifact_bytes must be between 1 and 33554432")


class C9SecurityHandler:
    """Deterministic C9 security gate for candidate content and tenant references."""

    def __init__(
        self,
        evidence_source: SecurityEvidenceSource | SecurityEvidenceLoader | Callable[..., object],
        artifact_store: ArtifactObjectStore,
        *,
        policy: C9HandlerPolicy | None = None,
        detector: DeterministicSecurityDetector | None = None,
    ) -> None:
        self._evidence_source = evidence_source
        self._artifact_store = artifact_store
        self._policy = policy or C9HandlerPolicy()
        self._detector = detector or DeterministicSecurityDetector()

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        claim = context.claim
        if claim.tenant_id != context.dispatch_item.tenant_id:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C9_TENANT_CONTEXT_MISMATCH"
            )
        try:
            bundle = await self._load_bundle(claim)
            self._validate_bundle(claim, bundle)
            if bundle.candidate is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C9_TOPIC3_CANDIDATE_MISSING",
                )
            if not bundle.evidence:
                return await self._error_finding(
                    context, VerificationVerdict.INSUFFICIENT_EVIDENCE, "C9_LOCAL_EVIDENCE_MISSING"
                )
            matches = self._detector.scan(bundle.candidate, tenant_id=claim.tenant_id)
            findings = tuple(self._finding(context, claim, match) for match in matches)
            verdict, confidence, codes = self._verdict(findings)
            document = self._document(context, bundle, findings, verdict, confidence, codes)
            artifact = await self._write_artifact(context, document)
            return ModuleFinding(
                verdict=verdict,
                confidence=confidence,
                evidence_ref_ids=tuple(ref.evidence_ref_id for ref in bundle.evidence),
                finding_codes=tuple(codes),
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
                context, VerificationVerdict.ERROR, "C9_HANDLER_UNEXPECTED_ERROR"
            )

    async def _load_bundle(self, claim: ClaimV1) -> SecurityEvidenceBundle:
        source = self._evidence_source
        result = source.load(claim) if hasattr(source, "load") else source(claim)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, SecurityEvidenceBundle):
            raise ValueError("C9 evidence source returned an invalid bundle")
        return result

    def _validate_bundle(self, claim: ClaimV1, bundle: SecurityEvidenceBundle) -> None:
        if len(bundle.evidence) > self._policy.max_evidence_count:
            raise ValueError("C9 evidence count exceeds the safety limit")
        candidate = bundle.candidate
        if candidate is not None:
            if (
                candidate.candidate_id != claim.candidate_id
                or candidate.candidate_version != claim.candidate_version
                or candidate.candidate_sha256 != claim.candidate_sha256
            ):
                raise ValueError("C9 candidate is not bound to the Claim")
            if (
                canonical_sha256(candidate.model_dump(mode="json", exclude={"candidate_sha256"}))
                != candidate.candidate_sha256
            ):
                raise ValueError("C9 candidate integrity check failed")
        seen: set[UUID] = set()
        for ref in bundle.evidence:
            if ref.tenant_id != claim.tenant_id:
                raise ValueError("C9 evidence crosses tenant boundaries")
            if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
                raise ValueError("C9 evidence is not bound to the Claim")
            if ref.trace_id != claim.trace_id or not record_integrity_valid(ref):
                raise ValueError("C9 evidence record integrity check failed")
            if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
                raise ValueError("C9 evidence excerpt integrity check failed")
            if ref.evidence_ref_id in seen:
                raise ValueError("C9 evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)

    @staticmethod
    def _finding(
        context: ModuleExecutionContext, claim: ClaimV1, match: SecurityMatch
    ) -> SecurityFindingV1:
        finding_id = uuid5(
            NAMESPACE_URL,
            f"c9:{claim.tenant_id}:{claim.claim_id}:{match.path}:{match.reason_code}:{match.fingerprint}",
        )
        severity = FindingSeverity(match.severity)
        disposition = (
            SecurityDisposition.BLOCK if match.non_waivable else SecurityDisposition.REVIEW
        )
        return build_topic4_record(
            SecurityFindingV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=1,
            created_at=claim.created_at,
            immutable=True,
            schema_version="security-finding.v1",
            security_finding_id=finding_id,
            verification_id=context.verification_id,
            candidate_id=claim.candidate_id,
            candidate_version=claim.candidate_version,
            block_id=claim.block_id,
            category=match.category,
            severity=severity,
            disposition=disposition,
            detector=match.detector,
            detector_version=DeterministicSecurityDetector.detector_version,
            evidence_fingerprint_sha256=match.fingerprint,
            reason_code=match.reason_code,
            non_waivable=match.non_waivable,
        )

    @staticmethod
    def _verdict(
        findings: tuple[SecurityFindingV1, ...],
    ) -> tuple[VerificationVerdict, float, tuple[str, ...]]:
        if not findings:
            return VerificationVerdict.SUPPORTED, 0.99, ("C9_SECURITY_SCAN_CLEAN",)
        codes = tuple(sorted({finding.reason_code for finding in findings}))
        if any(finding.non_waivable for finding in findings):
            return VerificationVerdict.UNSAFE, 0.99, codes
        return VerificationVerdict.UNSAFE, 0.95, codes

    @staticmethod
    def _document(
        context: ModuleExecutionContext,
        bundle: SecurityEvidenceBundle,
        findings: tuple[SecurityFindingV1, ...],
        verdict: VerificationVerdict,
        confidence: float,
        codes: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "schema_version": "c9-security-finding.v1",
            "handler_version": C9_HANDLER_VERSION,
            "policy_version": C9_POLICY_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "candidate_id": str(context.claim.candidate_id),
            "candidate_version": context.claim.candidate_version,
            "candidate_sha256": context.claim.candidate_sha256,
            "knowledge_base_version_id": str(bundle.knowledge_base_version_id)
            if bundle.knowledge_base_version_id is not None
            else None,
            "verdict": verdict.value,
            "confidence": confidence,
            "finding_codes": list(codes),
            "evidence_ref_ids": [str(ref.evidence_ref_id) for ref in bundle.evidence],
            "findings": [finding.model_dump(mode="json") for finding in findings],
            "raw_content_retained": False,
        }

    async def _write_artifact(
        self, context: ModuleExecutionContext, document: dict[str, object]
    ) -> ArtifactObjectRefV1:
        content = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(content) > self._policy.max_artifact_bytes:
            raise ValueError("C9 result artifact exceeds the safety limit")
        digest = canonical_sha256(document)
        object_key = f"c9/{context.claim.verification_id}/{context.claim.claim_id}/{digest}.json"
        stored = await self._artifact_store.put(
            tenant_id=context.claim.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise ValueError("C9 result artifact metadata failed integrity validation")
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

    async def _error_finding(
        self, context: ModuleExecutionContext, verdict: VerificationVerdict, code: str
    ) -> ModuleFinding:
        document = {
            "schema_version": "c9-security-finding.v1",
            "handler_version": C9_HANDLER_VERSION,
            "policy_version": C9_POLICY_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "verdict": verdict.value,
            "confidence": 0.0,
            "finding_codes": [code],
            "findings": [],
            "raw_content_retained": False,
        }
        artifact = await self._write_artifact(context, document)
        return ModuleFinding(verdict, 0.0, (), (code,), artifact, artifact.sha256, True)

    @staticmethod
    def _error_code(error: ValueError) -> str:
        message = str(error).casefold()
        if "tenant" in message:
            return "C9_TENANT_ISOLATION_FAILED"
        if "evidence" in message:
            return "C9_EVIDENCE_INTEGRITY_FAILED"
        if "candidate" in message or "claim" in message:
            return "C9_CANDIDATE_BINDING_FAILED"
        return "C9_HANDLER_VALIDATION_FAILED"
