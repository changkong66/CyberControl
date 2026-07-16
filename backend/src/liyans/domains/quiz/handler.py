from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_common import ClaimKind, VerificationVerdict

from liyans.domains.verification.execution import ModuleExecutionContext, ModuleFinding
from liyans.domains.verification.records import record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore

from .evidence_source import QuizEvidenceBundle, QuizEvidenceSource
from .parser import FrozenQuizParser, QuizParseError
from .verifier import QuizAnalysis, QuizIntegrityError, Topic1QuizVerifier

C5_HANDLER_VERSION = "c5-quiz-handler-v1"


class QuizEvidenceLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> QuizEvidenceBundle: ...


@dataclass(frozen=True, slots=True)
class C5HandlerPolicy:
    max_evidence_count: int = 512
    max_artifact_bytes: int = 33_554_432

    def __post_init__(self) -> None:
        if not 1 <= self.max_evidence_count <= 4096:
            raise ValueError("max_evidence_count must be between 1 and 4096")
        if not 1 <= self.max_artifact_bytes <= 33_554_432:
            raise ValueError("max_artifact_bytes must be between 1 and 33554432")


class C5QuizHandler:
    """C1-compatible deterministic Topic3 quiz and Topic1 authority verifier."""

    def __init__(
        self,
        evidence_source: QuizEvidenceSource | QuizEvidenceLoader | Callable[..., object],
        artifact_store: ArtifactObjectStore,
        *,
        policy: C5HandlerPolicy | None = None,
    ) -> None:
        self._evidence_source = evidence_source
        self._artifact_store = artifact_store
        self._policy = policy or C5HandlerPolicy()
        self._parser = FrozenQuizParser()
        self._verifier = Topic1QuizVerifier()

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        claim = context.claim
        if claim.tenant_id != self._claim_tenant(context):
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C5_TENANT_CONTEXT_MISMATCH"
            )
        if claim.claim_kind != ClaimKind.QUIZ:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C5_CLAIM_KIND_MISMATCH"
            )
        try:
            bundle = await self._load_bundle(claim)
            self._validate_bundle(claim, bundle)
            if bundle.candidate is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C5_TOPIC3_CANDIDATE_MISSING",
                )
            if bundle.snapshot is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C5_TOPIC1_SNAPSHOT_MISSING",
                )
            parsed = self._parser.parse(claim, bundle.candidate)
            analysis = self._verifier.verify(
                parsed,
                bundle.snapshot,
                evidence_ref_ids=tuple(ref.evidence_ref_id for ref in bundle.evidence),
            )
            document = self._document(context, bundle, parsed.verifier_ir, analysis)
            artifact = await self._write_artifact(context, document)
            return ModuleFinding(
                verdict=analysis.result.verdict,
                confidence=analysis.result.confidence,
                evidence_ref_ids=tuple(analysis.result.evidence_ref_ids),
                finding_codes=tuple(analysis.result.finding_codes),
                result_artifact=artifact,
                result_sha256=artifact.sha256,
                deterministic=True,
            )
        except QuizParseError:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C5_QUIZ_CONTRACT_INVALID"
            )
        except QuizIntegrityError:
            return await self._error_finding(
                context, VerificationVerdict.ERROR, "C5_TOPIC1_AUTHORITY_INTEGRITY_FAILED"
            )
        except ValueError as exc:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, self._error_code(exc)
            )
        except Exception:
            return await self._error_finding(
                context, VerificationVerdict.ERROR, "C5_HANDLER_UNEXPECTED_ERROR"
            )

    async def _load_bundle(self, claim: ClaimV1) -> QuizEvidenceBundle:
        source = self._evidence_source
        if hasattr(source, "load"):
            result = source.load(claim)
        else:
            result = source(claim)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, QuizEvidenceBundle):
            raise ValueError("C5 evidence source returned an invalid bundle")
        return result

    def _validate_bundle(self, claim: ClaimV1, bundle: QuizEvidenceBundle) -> None:
        if len(bundle.evidence) > self._policy.max_evidence_count:
            raise ValueError("C5 evidence count exceeds the safety limit")
        if bundle.snapshot is not None and bundle.knowledge_base_version_id is None:
            raise ValueError("C5 snapshot is missing its knowledge base binding")
        if bundle.candidate is not None:
            if (
                bundle.candidate.candidate_id != claim.candidate_id
                or bundle.candidate.candidate_version != claim.candidate_version
                or bundle.candidate.candidate_sha256 != claim.candidate_sha256
            ):
                raise ValueError("C5 candidate is not bound to the Claim")
        seen: set[object] = set()
        for ref in bundle.evidence:
            self._validate_evidence_ref(claim, ref, bundle.knowledge_base_version_id)
            if ref.evidence_ref_id in seen:
                raise ValueError("C5 evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)

    @staticmethod
    def _validate_evidence_ref(
        claim: ClaimV1,
        ref: EvidenceRefV1,
        knowledge_base_version_id: object,
    ) -> None:
        if ref.tenant_id != claim.tenant_id:
            raise ValueError("C5 evidence crosses tenant boundaries")
        if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
            raise ValueError("C5 evidence is not bound to the Claim")
        if ref.trace_id != claim.trace_id or not record_integrity_valid(ref):
            raise ValueError("C5 evidence record integrity check failed")
        if knowledge_base_version_id is not None and (
            ref.knowledge_base_version_id != knowledge_base_version_id
        ):
            raise ValueError("C5 evidence is not bound to the knowledge base version")
        if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
            raise ValueError("C5 evidence excerpt integrity check failed")

    @staticmethod
    def _claim_tenant(context: ModuleExecutionContext) -> str:
        if context.claim.tenant_id != context.dispatch_item.tenant_id:
            return ""
        return context.dispatch_item.tenant_id

    @staticmethod
    def _document(
        context: ModuleExecutionContext,
        bundle: QuizEvidenceBundle,
        verifier_ir: object,
        analysis: QuizAnalysis,
    ) -> dict[str, object]:
        return {
            "schema_version": "c5-quiz-finding.v1",
            "handler_version": C5_HANDLER_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "candidate_id": str(context.claim.candidate_id),
            "candidate_version": context.claim.candidate_version,
            "candidate_sha256": context.claim.candidate_sha256,
            "knowledge_base_version_id": (
                None
                if bundle.knowledge_base_version_id is None
                else str(bundle.knowledge_base_version_id)
            ),
            "topic1_snapshot": {
                "snapshot_id": str(bundle.snapshot.snapshot_id),
                "graph_version": bundle.snapshot.graph_version,
                "content_sha256": bundle.snapshot.content_sha256,
            }
            if bundle.snapshot is not None
            else None,
            "golden_question_id": analysis.golden_question_id,
            "stem_similarity": analysis.stem_similarity,
            "answer_coverage": analysis.answer_coverage,
            "expected_difficulty": analysis.expected_difficulty,
            "evidence_ref_ids": [str(ref.evidence_ref_id) for ref in bundle.evidence],
            "quiz_item_verifier_ir": verifier_ir.model_dump(mode="json"),
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
            raise ValueError("C5 result artifact exceeds the safety limit")
        object_key = f"c5/{context.claim.verification_id}/{context.claim.claim_id}/{digest}.json"
        stored = await self._artifact_store.put(
            tenant_id=context.claim.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise ValueError("C5 result artifact metadata failed integrity validation")
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
            "schema_version": "c5-quiz-finding.v1",
            "handler_version": C5_HANDLER_VERSION,
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
            return "C5_HANDLER_VALIDATION_FAILED"
        if "tenant" in message:
            return "C5_TENANT_ISOLATION_FAILED"
        if "candidate" in message or "claim" in message:
            return "C5_CANDIDATE_BINDING_FAILED"
        if "knowledge base" in message or "snapshot" in message:
            return "C5_KNOWLEDGE_BASE_BINDING_FAILED"
        if "evidence" in message:
            return "C5_EVIDENCE_INTEGRITY_FAILED"
        return "C5_HANDLER_VALIDATION_FAILED"
