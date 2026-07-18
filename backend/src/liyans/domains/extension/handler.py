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
from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_c7 import (
    ExtensionResourceType,
    ExtensionVerificationResultV1,
    VerifierExtensionResourceV1,
)
from liyans_contracts.topic4_common import ClaimKind, VerificationVerdict

from liyans.domains.verification.execution import ModuleExecutionContext, ModuleFinding
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore

from .evidence_source import ExtensionEvidenceBundle, ExtensionEvidenceSource
from .parser import ExtensionParseError, FrozenExtensionParser, ParsedExtensionResource
from .verifier import ExtensionAnalysis, Topic1ExtensionVerifier

C7_HANDLER_VERSION = "c7-extension-handler-v1"


class ExtensionEvidenceLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> ExtensionEvidenceBundle: ...


@dataclass(frozen=True, slots=True)
class C7HandlerPolicy:
    max_evidence_count: int = 512
    max_artifact_bytes: int = 33_554_432

    def __post_init__(self) -> None:
        if not 1 <= self.max_evidence_count <= 4096:
            raise ValueError("max_evidence_count must be between 1 and 4096")
        if not 1 <= self.max_artifact_bytes <= 33_554_432:
            raise ValueError("max_artifact_bytes must be between 1 and 33554432")


class C7ExtensionHandler:
    """C1-compatible local-corpus extension provenance verifier."""

    def __init__(
        self,
        evidence_source: ExtensionEvidenceSource | ExtensionEvidenceLoader | Callable[..., object],
        artifact_store: ArtifactObjectStore,
        *,
        policy: C7HandlerPolicy | None = None,
        verifier: Topic1ExtensionVerifier | None = None,
    ) -> None:
        self._evidence_source = evidence_source
        self._artifact_store = artifact_store
        self._policy = policy or C7HandlerPolicy()
        self._parser = FrozenExtensionParser()
        self._verifier = verifier or Topic1ExtensionVerifier()

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        claim = context.claim
        if claim.tenant_id != self._claim_tenant(context):
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C7_TENANT_CONTEXT_MISMATCH"
            )
        if claim.claim_kind != ClaimKind.EXTENSION:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C7_CLAIM_KIND_MISMATCH"
            )
        try:
            bundle = await self._load_bundle(claim)
            self._validate_bundle(claim, bundle)
            if bundle.candidate is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C7_TOPIC3_CANDIDATE_MISSING",
                )
            if bundle.snapshot is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C7_TOPIC1_SNAPSHOT_MISSING",
                )
            self._validate_snapshot(bundle)
            parsed = self._parser.parse(claim, bundle.candidate)
            analysis = self._verifier.analyze(parsed.resource, bundle.snapshot, bundle.evidence)
            extension_resource = self._resource_record(context, parsed, analysis, bundle.evidence)
            result = self._result_record(context, extension_resource, analysis, bundle.evidence)
            document = self._document(context, bundle, parsed, extension_resource, result, analysis)
            artifact = await self._write_document(context, document, "c7/results")
            return ModuleFinding(
                verdict=result.verdict,
                confidence=result.confidence,
                evidence_ref_ids=tuple(ref.evidence_ref_id for ref in bundle.evidence),
                finding_codes=tuple(result.finding_codes),
                result_artifact=artifact,
                result_sha256=artifact.sha256,
                deterministic=True,
            )
        except ExtensionParseError:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C7_EXTENSION_CONTRACT_INVALID"
            )
        except ValueError as exc:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, self._error_code(exc)
            )
        except Exception:
            return await self._error_finding(
                context, VerificationVerdict.ERROR, "C7_HANDLER_UNEXPECTED_ERROR"
            )

    async def _load_bundle(self, claim: ClaimV1) -> ExtensionEvidenceBundle:
        source = self._evidence_source
        if hasattr(source, "load"):
            result = source.load(claim)
        else:
            result = source(claim)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ExtensionEvidenceBundle):
            raise ValueError("C7 evidence source returned an invalid bundle")
        return result

    def _validate_bundle(self, claim: ClaimV1, bundle: ExtensionEvidenceBundle) -> None:
        if len(bundle.evidence) > self._policy.max_evidence_count:
            raise ValueError("C7 evidence count exceeds the safety limit")
        if bundle.snapshot is not None and bundle.knowledge_base_version_id is None:
            raise ValueError("C7 snapshot is missing its knowledge base binding")
        if bundle.candidate is not None and (
            bundle.candidate.candidate_id != claim.candidate_id
            or bundle.candidate.candidate_version != claim.candidate_version
            or bundle.candidate.candidate_sha256 != claim.candidate_sha256
        ):
            raise ValueError("C7 Candidate is not bound to the Claim")
        seen: set[UUID] = set()
        for ref in bundle.evidence:
            self._validate_evidence_ref(claim, ref, bundle.knowledge_base_version_id)
            if ref.evidence_ref_id in seen:
                raise ValueError("C7 evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)

    @staticmethod
    def _validate_evidence_ref(
        claim: ClaimV1,
        ref: EvidenceRefV1,
        knowledge_base_version_id: UUID | None,
    ) -> None:
        if ref.tenant_id != claim.tenant_id:
            raise ValueError("C7 evidence crosses tenant boundaries")
        if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
            raise ValueError("C7 evidence is not bound to the Claim")
        if ref.trace_id != claim.trace_id or not record_integrity_valid(ref):
            raise ValueError("C7 evidence record integrity check failed")
        if knowledge_base_version_id is not None and (
            ref.knowledge_base_version_id != knowledge_base_version_id
        ):
            raise ValueError("C7 evidence is not bound to the knowledge base version")
        if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
            raise ValueError("C7 evidence excerpt integrity check failed")

    @staticmethod
    def _validate_snapshot(bundle: ExtensionEvidenceBundle) -> None:
        snapshot = bundle.snapshot
        if snapshot is None:
            return
        if canonical_sha256(snapshot.content.model_dump(mode="json")) != snapshot.content_sha256:
            raise ValueError("C7 Topic1 snapshot integrity check failed")
        if snapshot.node_count != len(snapshot.content.knowledge_points):
            raise ValueError("C7 Topic1 snapshot node count failed")
        if snapshot.edge_count != len(snapshot.content.prerequisites):
            raise ValueError("C7 Topic1 snapshot edge count failed")

    @staticmethod
    def _claim_tenant(context: ModuleExecutionContext) -> str:
        if context.claim.tenant_id != context.dispatch_item.tenant_id:
            return ""
        return context.dispatch_item.tenant_id

    @staticmethod
    def _resource_type(resource_kind: str) -> ExtensionResourceType:
        if resource_kind == "PAPER" or resource_kind == "RESEARCH":
            return ExtensionResourceType.PAPER
        if resource_kind == "ENGINEERING" or resource_kind == "INDUSTRY":
            return ExtensionResourceType.ENGINEERING_CASE
        if resource_kind == "COMPETITION":
            return ExtensionResourceType.STANDARD
        raise ValueError("C7 unsupported Topic3 extension resource kind")

    @classmethod
    def _resource_record(
        cls,
        context: ModuleExecutionContext,
        parsed: ParsedExtensionResource,
        analysis: ExtensionAnalysis,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> VerifierExtensionResourceV1:
        resource = parsed.resource
        digest = canonical_sha256(
            {
                "candidate_id": str(context.claim.candidate_id),
                "candidate_version": context.claim.candidate_version,
                "block_id": context.claim.block_id,
                "resource_id": resource.resource_id,
                "citation": resource.citation_text,
            }
        )
        return build_topic4_record(
            VerifierExtensionResourceV1,
            trace_id=context.claim.trace_id,
            tenant_id=context.claim.tenant_id,
            version_cas=1,
            created_at=context.claim.created_at,
            immutable=True,
            schema_version="extension-resource.v1",
            extension_resource_id=uuid5(NAMESPACE_URL, f"liyans:c7:resource:{digest}"),
            verification_id=context.verification_id,
            claim_id=context.claim.claim_id,
            resource_type=cls._resource_type(resource.resource_kind),
            title=resource.title,
            authors=[],
            publisher="C2_APPROVED_CORPUS",
            publication_date=None,
            identifier=resource.source_url,
            canonical_uri=resource.source_url,
            canonical_citation=resource.citation_text,
            citation_sha256=canonical_sha256(resource.citation_text),
            license_expression=analysis.license_expression,
            topic1_knowledge_point_ids=list(resource.relevance_to_kp_ids),
            source_evidence_ref_ids=[ref.evidence_ref_id for ref in evidence],
        )

    @staticmethod
    def _result_record(
        context: ModuleExecutionContext,
        resource: VerifierExtensionResourceV1,
        analysis: ExtensionAnalysis,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> ExtensionVerificationResultV1:
        return build_topic4_record(
            ExtensionVerificationResultV1,
            trace_id=context.claim.trace_id,
            tenant_id=context.claim.tenant_id,
            version_cas=1,
            created_at=context.claim.created_at,
            immutable=True,
            schema_version="extension-verification.result.v1",
            extension_verification_result_id=uuid5(
                resource.extension_resource_id, "extension-verification"
            ),
            verification_id=context.verification_id,
            claim_id=context.claim.claim_id,
            extension_resource_id=resource.extension_resource_id,
            source_present_in_approved_corpus=analysis.source_present_in_approved_corpus,
            citation_valid=analysis.citation_valid,
            license_compatible=analysis.license_compatible,
            knowledge_relevance=analysis.knowledge_relevance,
            temporal_validity=analysis.temporal_validity,
            finding_codes=list(analysis.finding_codes),
            evidence_ref_ids=[ref.evidence_ref_id for ref in evidence],
            verdict=analysis.verdict,
            confidence=analysis.confidence,
        )

    @staticmethod
    def _document(
        context: ModuleExecutionContext,
        bundle: ExtensionEvidenceBundle,
        parsed: ParsedExtensionResource,
        resource: VerifierExtensionResourceV1,
        result: ExtensionVerificationResultV1,
        analysis: ExtensionAnalysis,
    ) -> dict[str, object]:
        return {
            "schema_version": "c7-extension-finding.v1",
            "handler_version": C7_HANDLER_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "candidate_sha256": context.claim.candidate_sha256,
            "resource_id": parsed.resource.resource_id,
            "resource": resource.model_dump(mode="json"),
            "analysis": {
                "source_present_in_approved_corpus": analysis.source_present_in_approved_corpus,
                "citation_valid": analysis.citation_valid,
                "license_compatible": analysis.license_compatible,
                "license_expression": analysis.license_expression,
                "knowledge_relevance": analysis.knowledge_relevance,
                "temporal_validity": analysis.temporal_validity,
                "finding_codes": list(analysis.finding_codes),
            },
            "topic1_snapshot": {
                "snapshot_id": str(bundle.snapshot.snapshot_id),
                "graph_version": bundle.snapshot.graph_version,
                "content_sha256": bundle.snapshot.content_sha256,
            },
            "evidence_ref_ids": [str(ref.evidence_ref_id) for ref in bundle.evidence],
            "verification_result": result.model_dump(mode="json"),
        }

    async def _write_document(
        self,
        context: ModuleExecutionContext,
        document: dict[str, object],
        object_prefix: str,
    ) -> ArtifactObjectRefV1:
        content = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(content) > self._policy.max_artifact_bytes:
            raise ValueError("C7 artifact exceeds the safety limit")
        digest = canonical_sha256(document)
        object_key = (
            f"{object_prefix}/{context.claim.verification_id}/"
            f"{context.claim.claim_id}/{digest}.json"
        )
        stored = await self._artifact_store.put(
            tenant_id=context.claim.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise ValueError("C7 artifact metadata failed integrity validation")
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
        self,
        context: ModuleExecutionContext,
        verdict: VerificationVerdict,
        finding_code: str,
    ) -> ModuleFinding:
        artifact = await self._write_document(
            context,
            {
                "schema_version": "c7-extension-finding.v1",
                "handler_version": C7_HANDLER_VERSION,
                "trace_id": context.claim.trace_id,
                "tenant_id": context.claim.tenant_id,
                "verification_id": str(context.verification_id),
                "claim_id": str(context.claim.claim_id),
                "module_run_id": str(context.module_run_id),
                "verdict": verdict.value,
                "confidence": 0.0,
                "finding_codes": [finding_code],
            },
            "c7/errors",
        )
        return ModuleFinding(
            verdict=verdict,
            confidence=0.0,
            evidence_ref_ids=(),
            finding_codes=(finding_code,),
            result_artifact=artifact,
            result_sha256=artifact.sha256,
            deterministic=True,
        )

    @staticmethod
    def _error_code(error: ValueError) -> str:
        message = str(error).casefold()
        if "invalid bundle" in message:
            return "C7_HANDLER_VALIDATION_FAILED"
        if "tenant" in message:
            return "C7_TENANT_ISOLATION_FAILED"
        if "candidate" in message or "claim" in message:
            return "C7_CANDIDATE_BINDING_FAILED"
        if "knowledge base" in message or "snapshot" in message:
            return "C7_KNOWLEDGE_BASE_BINDING_FAILED"
        if "evidence" in message:
            return "C7_EVIDENCE_INTEGRITY_FAILED"
        if "artifact" in message:
            return "C7_ARTIFACT_INTEGRITY_FAILED"
        return "C7_HANDLER_VALIDATION_FAILED"
