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
from liyans_contracts.topic4_c10 import (
    PIIFindingV1,
    PrivacyAction,
    PrivacyTenantResultV1,
    TokenizedValueV1,
)
from liyans_contracts.topic4_common import FindingSeverity, VerificationVerdict

from liyans.domains.verification.execution import ModuleExecutionContext, ModuleFinding
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore

from .detector import DeterministicPIIDetector, PIIMatch, replace_json_pointer
from .evidence_source import PrivacyEvidenceBundle, PrivacyEvidenceSource

C10_HANDLER_VERSION = "c10-privacy-handler-v1"
C10_POLICY_VERSION = "c10-privacy-policy-v1"
C10_TOKEN_KEY_VERSION = "c10-token-vault-v1"


class PrivacyLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> PrivacyEvidenceBundle: ...


@dataclass(frozen=True, slots=True)
class C10HandlerPolicy:
    max_evidence_count: int = 512
    max_artifact_bytes: int = 33_554_432

    def __post_init__(self) -> None:
        if not 1 <= self.max_evidence_count <= 4096:
            raise ValueError("max_evidence_count must be between 1 and 4096")
        if not 1 <= self.max_artifact_bytes <= 33_554_432:
            raise ValueError("max_artifact_bytes must be between 1 and 33554432")


class C10PrivacyHandler:
    """Local PII gate with immutable findings and a redacted candidate artifact."""

    def __init__(
        self,
        evidence_source: PrivacyEvidenceSource | PrivacyLoader | Callable[..., object],
        artifact_store: ArtifactObjectStore,
        *,
        policy: C10HandlerPolicy | None = None,
        detector: DeterministicPIIDetector | None = None,
    ) -> None:
        self._evidence_source = evidence_source
        self._artifact_store = artifact_store
        self._policy = policy or C10HandlerPolicy()
        self._detector = detector or DeterministicPIIDetector()

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        claim = context.claim
        if claim.tenant_id != context.dispatch_item.tenant_id:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C10_TENANT_CONTEXT_MISMATCH"
            )
        try:
            bundle = await self._load_bundle(claim)
            self._validate_bundle(claim, bundle)
            if bundle.candidate is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C10_TOPIC3_CANDIDATE_MISSING",
                )
            if not bundle.evidence:
                return await self._error_finding(
                    context, VerificationVerdict.INSUFFICIENT_EVIDENCE, "C10_LOCAL_EVIDENCE_MISSING"
                )
            matches = self._detector.scan(bundle.candidate)
            findings = tuple(self._finding(context, claim, match) for match in matches)
            tokens = tuple(
                self._token(context, finding, match)
                for finding, match in zip(findings, matches, strict=True)
                if match.action == PrivacyAction.TOKENIZE
            )
            redacted_ref, redacted_sha = await self._write_redacted_candidate(
                context, bundle.candidate, matches
            )
            result = self._privacy_result(
                context, claim, findings, tokens, redacted_ref, redacted_sha
            )
            document = self._document(context, bundle, result, findings, tokens)
            artifact = await self._write_artifact(context, document, prefix="c10/results")
            codes = tuple(sorted({match.reason_code for match in matches})) or (
                "C10_PII_SCAN_CLEAN",
            )
            return ModuleFinding(
                verdict=result.verdict,
                confidence=0.99 if not matches else 0.98,
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
                context, VerificationVerdict.ERROR, "C10_HANDLER_UNEXPECTED_ERROR"
            )

    async def _load_bundle(self, claim: ClaimV1) -> PrivacyEvidenceBundle:
        source = self._evidence_source
        result = source.load(claim) if hasattr(source, "load") else source(claim)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, PrivacyEvidenceBundle):
            raise ValueError("C10 evidence source returned an invalid bundle")
        return result

    def _validate_bundle(self, claim: ClaimV1, bundle: PrivacyEvidenceBundle) -> None:
        if bundle.source_tenant_id != claim.tenant_id:
            raise ValueError("C10 trusted source tenant does not match Claim tenant")
        if len(bundle.evidence) > self._policy.max_evidence_count:
            raise ValueError("C10 evidence count exceeds the safety limit")
        candidate = bundle.candidate
        if candidate is not None:
            if (
                candidate.candidate_id != claim.candidate_id
                or candidate.candidate_version != claim.candidate_version
                or candidate.candidate_sha256 != claim.candidate_sha256
            ):
                raise ValueError("C10 candidate is not bound to the Claim")
            if (
                canonical_sha256(candidate.model_dump(mode="json", exclude={"candidate_sha256"}))
                != candidate.candidate_sha256
            ):
                raise ValueError("C10 candidate integrity check failed")
        seen: set[UUID] = set()
        for ref in bundle.evidence:
            if ref.tenant_id != claim.tenant_id:
                raise ValueError("C10 evidence crosses tenant boundaries")
            if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
                raise ValueError("C10 evidence is not bound to the Claim")
            if ref.trace_id != claim.trace_id or not record_integrity_valid(ref):
                raise ValueError("C10 evidence record integrity check failed")
            if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
                raise ValueError("C10 evidence excerpt integrity check failed")
            if ref.evidence_ref_id in seen:
                raise ValueError("C10 evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)

    @staticmethod
    def _finding(context: ModuleExecutionContext, claim: ClaimV1, match: PIIMatch) -> PIIFindingV1:
        finding_id = uuid5(
            NAMESPACE_URL,
            f"c10:{claim.tenant_id}:{claim.claim_id}:{match.json_pointer}:{match.pii_type}:{match.original_value_sha256}",
        )
        severity = (
            FindingSeverity.CRITICAL
            if match.action == PrivacyAction.BLOCK
            else FindingSeverity.HIGH
        )
        return build_topic4_record(
            PIIFindingV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=1,
            created_at=claim.created_at,
            immutable=True,
            schema_version="pii-finding.v1",
            pii_finding_id=finding_id,
            verification_id=context.verification_id,
            candidate_id=claim.candidate_id,
            candidate_version=claim.candidate_version,
            block_id=match.block_id,
            json_pointer=match.json_pointer,
            pii_type=match.pii_type,
            severity=severity,
            confidence=match.confidence,
            action=match.action,
            original_value_sha256=match.original_value_sha256,
            non_waivable=match.action == PrivacyAction.BLOCK,
        )

    @staticmethod
    def _token(
        context: ModuleExecutionContext, finding: PIIFindingV1, match: PIIMatch
    ) -> TokenizedValueV1:
        token_id = uuid5(NAMESPACE_URL, f"c10-token:{finding.pii_finding_id}")
        return build_topic4_record(
            TokenizedValueV1,
            trace_id=finding.trace_id,
            tenant_id=finding.tenant_id,
            version_cas=1,
            created_at=finding.created_at,
            immutable=True,
            schema_version="tokenized-value.v1",
            tokenized_value_id=token_id,
            pii_finding_id=finding.pii_finding_id,
            token=match.replacement,
            original_value_sha256=match.original_value_sha256,
            vault_reference=f"privacy-vault/{context.claim.tenant_id}/{token_id}",
            key_version=C10_TOKEN_KEY_VERSION,
            reversible=False,
        )

    @staticmethod
    def _privacy_result(
        context: ModuleExecutionContext,
        claim: ClaimV1,
        findings: tuple[PIIFindingV1, ...],
        tokens: tuple[TokenizedValueV1, ...],
        redacted_ref: ArtifactObjectRefV1 | None,
        redacted_sha: str | None,
    ) -> PrivacyTenantResultV1:
        blocked = any(finding.non_waivable for finding in findings)
        verdict = (
            VerificationVerdict.UNSAFE
            if blocked
            else VerificationVerdict.PARTIALLY_SUPPORTED
            if findings
            else VerificationVerdict.SUPPORTED
        )
        result_id = uuid5(NAMESPACE_URL, f"c10-result:{claim.tenant_id}:{context.verification_id}")
        return build_topic4_record(
            PrivacyTenantResultV1,
            trace_id=claim.trace_id,
            tenant_id=claim.tenant_id,
            version_cas=1,
            created_at=claim.created_at,
            immutable=True,
            schema_version="privacy-tenant.result.v1",
            privacy_tenant_result_id=result_id,
            verification_id=context.verification_id,
            candidate_id=claim.candidate_id,
            candidate_version=claim.candidate_version,
            candidate_sha256=claim.candidate_sha256,
            tenant_boundary_valid=True,
            pii_finding_ids=[finding.pii_finding_id for finding in findings],
            tokenized_value_ids=[token.tokenized_value_id for token in tokens],
            redacted_candidate_artifact=redacted_ref,
            redacted_candidate_sha256=redacted_sha,
            policy_version=C10_POLICY_VERSION,
            verdict=verdict,
        )

    async def _write_redacted_candidate(self, context, candidate, matches):
        if not matches:
            return None, None
        blocks = []
        for block in candidate.blocks:
            content = block.content
            block_matches = [match for match in matches if match.block_id == block.block_id]
            for match in sorted(
                block_matches, key=lambda item: len(item.json_pointer), reverse=True
            ):
                content = replace_json_pointer(
                    content,
                    match.json_pointer.replace(f"/blocks/{block.ordinal}/content", ""),
                    match.replacement,
                )
            blocks.append(
                {
                    "block_id": block.block_id,
                    "ordinal": block.ordinal,
                    "block_type": block.block_type.value,
                    "content_schema_version": block.content_schema_version,
                    "content": content,
                    "content_sha256": canonical_sha256(content),
                }
            )
        document = {
            "schema_version": "topic3.candidate.redacted.v1",
            "candidate_id": str(candidate.candidate_id),
            "candidate_version": candidate.candidate_version,
            "blocks": blocks,
            "policy_version": C10_POLICY_VERSION,
            "original_candidate_sha256": candidate.candidate_sha256,
        }
        digest = canonical_sha256(document)
        ref = await self._write_artifact(context, document, prefix="c10/redacted")
        return ref, digest

    @staticmethod
    def _document(context, bundle, result, findings, tokens):
        return {
            "schema_version": "c10-privacy-result.v1",
            "handler_version": C10_HANDLER_VERSION,
            "policy_version": C10_POLICY_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "candidate_id": str(context.claim.candidate_id),
            "candidate_version": context.claim.candidate_version,
            "candidate_sha256": context.claim.candidate_sha256,
            "source_tenant_id": bundle.source_tenant_id,
            "verdict": result.verdict.value,
            "pii_findings": [finding.model_dump(mode="json") for finding in findings],
            "tokenized_values": [token.model_dump(mode="json") for token in tokens],
            "privacy_result": result.model_dump(mode="json"),
            "raw_content_retained": False,
        }

    async def _write_artifact(self, context, document, *, prefix):
        content = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(content) > self._policy.max_artifact_bytes:
            raise ValueError("C10 result artifact exceeds the safety limit")
        digest = canonical_sha256(document)
        object_key = (
            f"{prefix}/{context.claim.verification_id}/{context.claim.claim_id}/{digest}.json"
        )
        stored = await self._artifact_store.put(
            tenant_id=context.claim.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise ValueError("C10 result artifact metadata failed integrity validation")
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

    async def _error_finding(self, context, verdict, code):
        document = {
            "schema_version": "c10-privacy-result.v1",
            "handler_version": C10_HANDLER_VERSION,
            "policy_version": C10_POLICY_VERSION,
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
        artifact = await self._write_artifact(context, document, prefix="c10/errors")
        return ModuleFinding(verdict, 0.0, (), (code,), artifact, artifact.sha256, True)

    @staticmethod
    def _error_code(error: ValueError) -> str:
        message = str(error).casefold()
        if "tenant" in message:
            return "C10_TENANT_ISOLATION_FAILED"
        if "evidence" in message:
            return "C10_EVIDENCE_INTEGRITY_FAILED"
        if "candidate" in message or "claim" in message:
            return "C10_CANDIDATE_BINDING_FAILED"
        return "C10_HANDLER_VALIDATION_FAILED"
