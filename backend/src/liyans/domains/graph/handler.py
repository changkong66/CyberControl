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
from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_common import ClaimKind, VerificationVerdict

from liyans.domains.verification.execution import ModuleExecutionContext, ModuleFinding
from liyans.domains.verification.records import record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore

from .evidence_source import GraphEvidenceBundle, GraphEvidenceSource
from .mermaid import (
    BoundedMermaidParser,
    MermaidPolicy,
    MermaidSecurityError,
    MermaidSyntaxError,
)
from .verifier import GraphAnalysis, GraphIntegrityError, Topic1GraphVerifier

C4_HANDLER_VERSION = "c4-graph-handler-v1"


class GraphEvidenceLoader(Protocol):
    async def __call__(
        self,
        *,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> GraphEvidenceBundle: ...


@dataclass(frozen=True, slots=True)
class C4HandlerPolicy:
    max_artifact_bytes: int = 33_554_432

    def __post_init__(self) -> None:
        if not 1 <= self.max_artifact_bytes <= 33_554_432:
            raise ValueError("max_artifact_bytes must be between 1 and 33554432")


class C4GraphHandler:
    """C1-compatible deterministic Mermaid and Topic1 topology verifier."""

    def __init__(
        self,
        evidence_source: GraphEvidenceSource | GraphEvidenceLoader | Callable[..., object],
        artifact_store: ArtifactObjectStore,
        *,
        policy: C4HandlerPolicy | None = None,
        mermaid_policy: MermaidPolicy | None = None,
    ) -> None:
        self._evidence_source = evidence_source
        self._artifact_store = artifact_store
        self._policy = policy or C4HandlerPolicy()
        self._parser = BoundedMermaidParser(mermaid_policy)
        self._verifier = Topic1GraphVerifier()

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        claim = context.claim
        if claim.tenant_id != self._claim_tenant(context):
            return await self._error_finding(
                context,
                VerificationVerdict.UNSAFE,
                "C4_TENANT_CONTEXT_MISMATCH",
            )
        if claim.claim_kind != ClaimKind.GRAPH:
            return await self._error_finding(
                context,
                VerificationVerdict.UNSAFE,
                "C4_CLAIM_KIND_MISMATCH",
            )
        try:
            bundle = await self._load_bundle(claim)
            evidence = tuple(bundle.evidence)
            self._validate_bundle_binding(bundle, evidence)
            self._validate_evidence(
                claim,
                evidence,
                knowledge_base_version_id=bundle.knowledge_base_version_id,
            )
            if bundle.snapshot is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C4_TOPIC1_SNAPSHOT_MISSING",
                )
            parsed = self._parser.parse(claim.normalized_statement)
            analysis = self._verifier.verify(
                parsed,
                bundle.snapshot,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
                candidate_id=claim.candidate_id,
                candidate_version=claim.candidate_version,
                block_id=claim.block_id,
                trace_id=claim.trace_id,
                tenant_id=claim.tenant_id,
                created_at=claim.created_at,
                evidence_ref_ids=tuple(ref.evidence_ref_id for ref in evidence),
            )
            document = self._document(context, bundle, parsed.normalized_source, analysis)
            artifact = await self._write_artifact(context, document)
            evidence_ids = tuple(ref.evidence_ref_id for ref in evidence)
            return ModuleFinding(
                verdict=analysis.result.verdict,
                confidence=analysis.result.confidence,
                evidence_ref_ids=evidence_ids,
                finding_codes=tuple(analysis.result.topology_mismatch_codes),
                result_artifact=artifact,
                result_sha256=artifact.sha256,
                deterministic=True,
            )
        except MermaidSecurityError:
            return await self._error_finding(
                context,
                VerificationVerdict.UNSAFE,
                "C4_MERMAID_SECURITY_POLICY",
            )
        except MermaidSyntaxError:
            return await self._error_finding(
                context,
                VerificationVerdict.UNSAFE,
                "C4_MERMAID_SYNTAX_INVALID",
            )
        except GraphIntegrityError:
            return await self._error_finding(
                context,
                VerificationVerdict.ERROR,
                "C4_TOPIC1_SNAPSHOT_INTEGRITY",
            )
        except ValueError as exc:
            return await self._error_finding(
                context,
                VerificationVerdict.UNSAFE,
                self._error_code(exc),
            )
        except Exception:
            return await self._error_finding(
                context,
                VerificationVerdict.ERROR,
                "C4_HANDLER_UNEXPECTED_ERROR",
            )

    async def _load_bundle(self, claim: ClaimV1) -> GraphEvidenceBundle:
        source = self._evidence_source
        if hasattr(source, "load"):
            result = source.load(
                tenant_id=claim.tenant_id,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )
        else:
            result = source(
                tenant_id=claim.tenant_id,
                verification_id=claim.verification_id,
                claim_id=claim.claim_id,
            )
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, GraphEvidenceBundle):
            raise ValueError("C4 evidence source returned an invalid bundle")
        return result

    @staticmethod
    def _claim_tenant(context: ModuleExecutionContext) -> str:
        if context.claim.tenant_id != context.dispatch_item.tenant_id:
            return ""
        return context.dispatch_item.tenant_id

    @staticmethod
    def _validate_bundle_binding(
        bundle: GraphEvidenceBundle,
        evidence: tuple[EvidenceRefV1, ...],
    ) -> None:
        if bundle.snapshot is not None and bundle.knowledge_base_version_id is None:
            raise ValueError("C4 graph bundle is missing its knowledge base binding")
        if bundle.knowledge_base_version_id is not None and any(
            ref.knowledge_base_version_id != bundle.knowledge_base_version_id for ref in evidence
        ):
            raise ValueError("C4 evidence is not bound to the knowledge base version")

    @staticmethod
    def _validate_evidence(
        claim: ClaimV1,
        evidence: tuple[EvidenceRefV1, ...],
        *,
        knowledge_base_version_id: UUID | None = None,
    ) -> None:
        seen: set[UUID] = set()
        for ref in evidence:
            if ref.tenant_id != claim.tenant_id:
                raise ValueError("C4 evidence crosses tenant boundaries")
            if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
                raise ValueError("C4 evidence is not bound to the claim")
            if ref.trace_id != claim.trace_id or not record_integrity_valid(ref):
                raise ValueError("C4 evidence record integrity check failed")
            if (
                knowledge_base_version_id is not None
                and ref.knowledge_base_version_id != knowledge_base_version_id
            ):
                raise ValueError("C4 evidence is not bound to the knowledge base version")
            if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
                raise ValueError("C4 evidence excerpt integrity check failed")
            if ref.evidence_ref_id in seen:
                raise ValueError("C4 evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)

    @staticmethod
    def _document(
        context: ModuleExecutionContext,
        bundle: GraphEvidenceBundle,
        source: str,
        analysis: GraphAnalysis,
    ) -> dict[str, object]:
        return {
            "schema_version": "c4-graph-finding.v1",
            "handler_version": C4_HANDLER_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "mermaid_source": source,
            "mermaid_source_sha256": canonical_sha256(source),
            "knowledge_base_version_id": (
                None
                if bundle.knowledge_base_version_id is None
                else str(bundle.knowledge_base_version_id)
            ),
            "topic1_snapshot": (
                None
                if bundle.snapshot is None
                else {
                    "snapshot_id": str(bundle.snapshot.snapshot_id),
                    "graph_version": bundle.snapshot.graph_version,
                    "content_sha256": bundle.snapshot.content_sha256,
                }
            ),
            "evidence_ref_ids": [str(ref.evidence_ref_id) for ref in bundle.evidence],
            "graph_ir": analysis.graph_ir.model_dump(mode="json"),
            "verification_result": analysis.result.model_dump(mode="json"),
        }

    async def _write_artifact(
        self,
        context: ModuleExecutionContext,
        document: dict[str, object],
    ) -> ArtifactObjectRefV1:
        content = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest = canonical_sha256(document)
        if len(content) > self._policy.max_artifact_bytes:
            raise ValueError("C4 result artifact exceeds the safety limit")
        object_key = f"c4/{context.claim.verification_id}/{context.claim.claim_id}/{digest}.json"
        stored = await self._artifact_store.put(
            tenant_id=context.claim.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise ValueError("C4 result artifact metadata failed integrity validation")
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
        document = {
            "schema_version": "c4-graph-finding.v1",
            "handler_version": C4_HANDLER_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "verdict": verdict.value,
            "confidence": 0.0,
            "finding_codes": [finding_code],
        }
        artifact = await self._write_artifact(context, document)
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
            return "C4_HANDLER_VALIDATION_FAILED"
        if "knowledge base binding" in message or "knowledge base version" in message:
            return "C4_KNOWLEDGE_BASE_BINDING_FAILED"
        if "tenant" in message:
            return "C4_TENANT_ISOLATION_FAILED"
        if "evidence" in message:
            return "C4_EVIDENCE_INTEGRITY_FAILED"
        if "snapshot" in message or "knowledge base" in message:
            return "C4_TOPIC1_SNAPSHOT_UNAVAILABLE"
        return "C4_HANDLER_VALIDATION_FAILED"
