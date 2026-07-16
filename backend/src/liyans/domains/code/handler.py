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
from liyans_contracts.topic4_c6 import (
    CodeArtifactV1,
    CodeDependencyV1,
    CodeLanguage,
    CodeVerificationResultV1,
    NumericAssertionResultV1,
    SandboxExecutionState,
    SandboxPolicyV1,
)
from liyans_contracts.topic4_common import ClaimKind, VerificationVerdict

from liyans.domains.verification.execution import ModuleExecutionContext, ModuleFinding
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore

from .analysis import CodeAnalysis, CodeStaticAnalyzer, claims_stability
from .evidence_source import CodeEvidenceBundle, CodeEvidenceSource
from .parser import CodeParseError, FrozenCodeBundleParser, ParsedCodeBundle

C6_HANDLER_VERSION = "c6-code-handler-v1"
C6_POLICY_VERSION = "c6-static-sandbox-policy-v1"
ANALYZER_IMAGE_DIGEST = "sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4"
_DENIED_COMMANDS = (
    "network",
    "filesystem-write",
    "process-spawn",
    "dynamic-eval",
    "native-extension",
    "package-install",
    "gui",
)
_LICENSES = {
    "control": "BSD-3-Clause",
    "math": "PSF-2.0",
    "matplotlib": "PSF-2.0",
    "numpy": "BSD-3-Clause",
    "scipy": "BSD-3-Clause",
}
_UNSAFE_CODES = frozenset(
    {
        "C6_AST_NODE_LIMIT",
        "C6_DANGEROUS_CALL",
        "C6_DANGEROUS_IMPORT",
        "C6_DUNDER_ACCESS_BLOCKED",
        "C6_LOOP_LIMIT",
        "C6_MATLAB_DANGEROUS_OPERATION",
        "C6_NONDETERMINISTIC_RANDOM",
        "C6_NUMERIC_BOUND_EXCEEDED",
        "C6_TIME_GRID_LIMIT",
        "C6_UNAPPROVED_IMPORT",
        "C6_UNBOUNDED_FOR_LOOP",
        "C6_UNBOUNDED_WHILE_LOOP",
    }
)
_INSUFFICIENT_CODES = frozenset({"C6_STABILITY_UNRESOLVED"})


class CodeEvidenceLoader(Protocol):
    async def __call__(self, claim: ClaimV1) -> CodeEvidenceBundle: ...


@dataclass(frozen=True, slots=True)
class C6HandlerPolicy:
    max_evidence_count: int = 512
    max_artifact_bytes: int = 33_554_432

    def __post_init__(self) -> None:
        if not 1 <= self.max_evidence_count <= 4096:
            raise ValueError("max_evidence_count must be between 1 and 4096")
        if not 1 <= self.max_artifact_bytes <= 33_554_432:
            raise ValueError("max_artifact_bytes must be between 1 and 33554432")


class C6CodeHandler:
    """C1-compatible static code verifier that never executes Candidate source."""

    def __init__(
        self,
        evidence_source: CodeEvidenceSource | CodeEvidenceLoader | Callable[..., object],
        artifact_store: ArtifactObjectStore,
        *,
        policy: C6HandlerPolicy | None = None,
        analyzer: CodeStaticAnalyzer | None = None,
    ) -> None:
        self._evidence_source = evidence_source
        self._artifact_store = artifact_store
        self._policy = policy or C6HandlerPolicy()
        self._parser = FrozenCodeBundleParser()
        self._analyzer = analyzer or CodeStaticAnalyzer()

    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding:
        claim = context.claim
        if claim.tenant_id != self._claim_tenant(context):
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C6_TENANT_CONTEXT_MISMATCH"
            )
        if claim.claim_kind != ClaimKind.CODE:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C6_CLAIM_KIND_MISMATCH"
            )
        try:
            bundle = await self._load_bundle(claim)
            self._validate_bundle(claim, bundle)
            if bundle.candidate is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C6_TOPIC3_CANDIDATE_MISSING",
                )
            if bundle.snapshot is None:
                return await self._error_finding(
                    context,
                    VerificationVerdict.INSUFFICIENT_EVIDENCE,
                    "C6_TOPIC1_SNAPSHOT_MISSING",
                )
            self._validate_snapshot(bundle)
            parsed = self._parser.parse(claim, bundle.candidate)
            claims_text = " ".join(
                [
                    parsed.content.objective,
                    parsed.content.result_analysis,
                    *parsed.content.expected_observations,
                ]
            )
            stable_claimed, unstable_claimed = claims_stability(claims_text)
            analysis = self._analyzer.analyze(
                parsed.files,
                stable_claimed=stable_claimed,
                unstable_claimed=unstable_claimed,
            )
            source_artifact = await self._write_document(
                context,
                parsed.source_document,
                object_prefix="c6/source",
            )
            dependencies = self._dependencies(context, analysis)
            code_artifact = self._code_artifact(
                context,
                parsed,
                source_artifact,
                dependencies,
            )
            sandbox_policy = self._sandbox_policy(context, parsed.language)
            result = self._verification_result(
                context,
                code_artifact,
                sandbox_policy,
                analysis,
                evidence_ref_ids=tuple(ref.evidence_ref_id for ref in bundle.evidence),
            )
            document = self._result_document(
                context,
                bundle,
                parsed,
                analysis,
                code_artifact,
                sandbox_policy,
                result,
            )
            artifact = await self._write_document(
                context,
                document,
                object_prefix="c6/results",
            )
            return ModuleFinding(
                verdict=result.verdict,
                confidence=result.confidence,
                evidence_ref_ids=tuple(ref.evidence_ref_id for ref in bundle.evidence),
                finding_codes=tuple(result.finding_codes),
                result_artifact=artifact,
                result_sha256=artifact.sha256,
                deterministic=True,
            )
        except CodeParseError:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, "C6_CODE_CONTRACT_INVALID"
            )
        except ValueError as exc:
            return await self._error_finding(
                context, VerificationVerdict.UNSAFE, self._error_code(exc)
            )
        except Exception:
            return await self._error_finding(
                context, VerificationVerdict.ERROR, "C6_HANDLER_UNEXPECTED_ERROR"
            )

    async def _load_bundle(self, claim: ClaimV1) -> CodeEvidenceBundle:
        source = self._evidence_source
        if hasattr(source, "load"):
            result = source.load(claim)
        else:
            result = source(claim)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, CodeEvidenceBundle):
            raise ValueError("C6 evidence source returned an invalid bundle")
        return result

    def _validate_bundle(self, claim: ClaimV1, bundle: CodeEvidenceBundle) -> None:
        if len(bundle.evidence) > self._policy.max_evidence_count:
            raise ValueError("C6 evidence count exceeds the safety limit")
        if bundle.snapshot is not None and bundle.knowledge_base_version_id is None:
            raise ValueError("C6 snapshot is missing its knowledge base binding")
        if bundle.candidate is not None and (
            bundle.candidate.candidate_id != claim.candidate_id
            or bundle.candidate.candidate_version != claim.candidate_version
            or bundle.candidate.candidate_sha256 != claim.candidate_sha256
        ):
            raise ValueError("C6 Candidate is not bound to the Claim")
        seen: set[UUID] = set()
        for ref in bundle.evidence:
            self._validate_evidence_ref(claim, ref, bundle.knowledge_base_version_id)
            if ref.evidence_ref_id in seen:
                raise ValueError("C6 evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)

    @staticmethod
    def _validate_evidence_ref(
        claim: ClaimV1,
        ref: EvidenceRefV1,
        knowledge_base_version_id: UUID | None,
    ) -> None:
        if ref.tenant_id != claim.tenant_id:
            raise ValueError("C6 evidence crosses tenant boundaries")
        if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
            raise ValueError("C6 evidence is not bound to the Claim")
        if ref.trace_id != claim.trace_id or not record_integrity_valid(ref):
            raise ValueError("C6 evidence record integrity check failed")
        if knowledge_base_version_id is not None and (
            ref.knowledge_base_version_id != knowledge_base_version_id
        ):
            raise ValueError("C6 evidence is not bound to the knowledge base version")
        if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
            raise ValueError("C6 evidence excerpt integrity check failed")

    @staticmethod
    def _validate_snapshot(bundle: CodeEvidenceBundle) -> None:
        snapshot = bundle.snapshot
        if snapshot is None:
            return
        if canonical_sha256(snapshot.content.model_dump(mode="json")) != snapshot.content_sha256:
            raise ValueError("C6 Topic1 snapshot integrity check failed")
        if snapshot.node_count != len(snapshot.content.knowledge_points):
            raise ValueError("C6 Topic1 snapshot node count failed")
        if snapshot.edge_count != len(snapshot.content.prerequisites):
            raise ValueError("C6 Topic1 snapshot edge count failed")

    @staticmethod
    def _claim_tenant(context: ModuleExecutionContext) -> str:
        if context.claim.tenant_id != context.dispatch_item.tenant_id:
            return ""
        return context.dispatch_item.tenant_id

    @staticmethod
    def _dependencies(
        context: ModuleExecutionContext,
        analysis: CodeAnalysis,
    ) -> list[CodeDependencyV1]:
        return [
            build_topic4_record(
                CodeDependencyV1,
                trace_id=context.claim.trace_id,
                tenant_id=context.claim.tenant_id,
                version_cas=1,
                created_at=context.claim.created_at,
                immutable=True,
                schema_version="code-dependency.v1",
                name=name,
                version=None,
                package_url=None if name == "math" else f"pkg:pypi/{name}",
                declared_license=_LICENSES.get(name),
            )
            for name in analysis.dependencies
        ]

    @staticmethod
    def _code_artifact(
        context: ModuleExecutionContext,
        parsed: ParsedCodeBundle,
        source_artifact: ArtifactObjectRefV1,
        dependencies: list[CodeDependencyV1],
    ) -> CodeArtifactV1:
        return build_topic4_record(
            CodeArtifactV1,
            trace_id=context.claim.trace_id,
            tenant_id=context.claim.tenant_id,
            version_cas=1,
            created_at=context.claim.created_at,
            immutable=True,
            schema_version="code-artifact.v1",
            code_artifact_id=uuid5(context.claim.claim_id, f"code-artifact:{parsed.source_sha256}"),
            verification_id=context.verification_id,
            claim_id=context.claim.claim_id,
            candidate_id=context.claim.candidate_id,
            candidate_version=context.claim.candidate_version,
            block_id=context.claim.block_id,
            language=parsed.language,
            source_artifact=source_artifact,
            source_sha256=parsed.source_sha256,
            entrypoint=parsed.entrypoint.path,
            dependencies=dependencies,
            expected_outputs=list(parsed.content.expected_observations),
        )

    @staticmethod
    def _sandbox_policy(
        context: ModuleExecutionContext,
        language: CodeLanguage,
    ) -> SandboxPolicyV1:
        digest = canonical_sha256(
            {
                "policy_version": C6_POLICY_VERSION,
                "language": language.value,
                "network_access": False,
                "root_filesystem_read_only": True,
                "memory_limit_mb": 256,
                "cpu_quota_millis": 1000,
                "pids_limit": 32,
                "timeout_ms": 10_000,
                "denied_commands": list(_DENIED_COMMANDS),
            }
        )
        return build_topic4_record(
            SandboxPolicyV1,
            trace_id=context.claim.trace_id,
            tenant_id=context.claim.tenant_id,
            version_cas=1,
            created_at=context.claim.created_at,
            immutable=True,
            schema_version="sandbox-policy.v1",
            sandbox_policy_id=uuid5(NAMESPACE_URL, f"liyans:c6:policy:{digest}"),
            language=language,
            policy_version=C6_POLICY_VERSION,
            runtime_image_digest=ANALYZER_IMAGE_DIGEST,
            network_access=False,
            root_filesystem_read_only=True,
            memory_limit_mb=256,
            cpu_quota_millis=1000,
            pids_limit=32,
            timeout_ms=10_000,
            allowed_commands=[],
            denied_commands=list(_DENIED_COMMANDS),
            syscall_profile_sha256=digest,
        )

    @staticmethod
    def _verification_result(
        context: ModuleExecutionContext,
        artifact: CodeArtifactV1,
        policy: SandboxPolicyV1,
        analysis: CodeAnalysis,
        *,
        evidence_ref_ids: tuple[UUID, ...],
    ) -> CodeVerificationResultV1:
        codes = set(analysis.finding_codes)
        unsafe = bool(codes & _UNSAFE_CODES)
        if unsafe:
            verdict = VerificationVerdict.UNSAFE
            confidence = 0.99
            execution_state = SandboxExecutionState.POLICY_BLOCKED
        elif codes & _INSUFFICIENT_CODES:
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
            confidence = 0.35
            execution_state = SandboxExecutionState.NOT_RUN
        elif not analysis.syntax_valid or not analysis.static_analysis_passed:
            verdict = VerificationVerdict.CONTRADICTED
            confidence = 0.97
            execution_state = SandboxExecutionState.NOT_RUN
        elif not evidence_ref_ids:
            codes.add("C6_EVIDENCE_REQUIRED")
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
            confidence = 0.25
            execution_state = SandboxExecutionState.NOT_RUN
        else:
            verdict = VerificationVerdict.SUPPORTED
            confidence = 0.96
            execution_state = SandboxExecutionState.NOT_RUN
        numeric_assertions = [
            build_topic4_record(
                NumericAssertionResultV1,
                trace_id=context.claim.trace_id,
                tenant_id=context.claim.tenant_id,
                version_cas=1,
                created_at=context.claim.created_at,
                immutable=True,
                schema_version="numeric-assertion-result.v1",
                assertion_id=f"pole-real-{index}",
                passed=pole.real < -1e-9,
                actual=float(pole.real),
                expected=0.0,
                tolerance=1e-9,
            )
            for index, pole in enumerate(analysis.poles)
        ]
        return build_topic4_record(
            CodeVerificationResultV1,
            trace_id=context.claim.trace_id,
            tenant_id=context.claim.tenant_id,
            version_cas=1,
            created_at=context.claim.created_at,
            immutable=True,
            schema_version="code-verification.result.v1",
            code_verification_result_id=uuid5(
                artifact.code_artifact_id,
                f"code-verification:{canonical_sha256(sorted(codes))}",
            ),
            verification_id=context.verification_id,
            claim_id=context.claim.claim_id,
            code_artifact_id=artifact.code_artifact_id,
            sandbox_policy_id=policy.sandbox_policy_id,
            syntax_valid=analysis.syntax_valid,
            static_analysis_passed=analysis.static_analysis_passed,
            execution_state=execution_state,
            exit_code=None,
            stdout_artifact=None,
            stderr_artifact=None,
            stdout_sha256=None,
            stderr_sha256=None,
            numeric_assertions=numeric_assertions,
            finding_codes=sorted(codes),
            verdict=verdict,
            confidence=confidence,
        )

    @staticmethod
    def _result_document(
        context: ModuleExecutionContext,
        bundle: CodeEvidenceBundle,
        parsed: ParsedCodeBundle,
        analysis: CodeAnalysis,
        artifact: CodeArtifactV1,
        policy: SandboxPolicyV1,
        result: CodeVerificationResultV1,
    ) -> dict[str, object]:
        return {
            "schema_version": "c6-code-finding.v1",
            "handler_version": C6_HANDLER_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "candidate_sha256": context.claim.candidate_sha256,
            "source_sha256": parsed.source_sha256,
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
            "analysis": {
                "model_detected": analysis.model_detected,
                "simulation_detected": analysis.simulation_detected,
                "time_grid_size": analysis.time_grid_size,
                "stable_claimed": analysis.stable_claimed,
                "unstable_claimed": analysis.unstable_claimed,
                "poles": [
                    {"real": float(pole.real), "imaginary": float(pole.imag)}
                    for pole in analysis.poles
                ],
                "files": [
                    {
                        "path": file.path,
                        "syntax_valid": file.syntax_valid,
                        "static_analysis_passed": file.static_analysis_passed,
                        "finding_codes": list(file.finding_codes),
                    }
                    for file in analysis.files
                ],
            },
            "code_artifact": artifact.model_dump(mode="json"),
            "sandbox_policy": policy.model_dump(mode="json"),
            "verification_result": result.model_dump(mode="json"),
        }

    async def _write_document(
        self,
        context: ModuleExecutionContext,
        document: dict[str, object],
        *,
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
            raise ValueError("C6 artifact exceeds the safety limit")
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
            raise ValueError("C6 artifact metadata failed integrity validation")
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
            "schema_version": "c6-code-finding.v1",
            "handler_version": C6_HANDLER_VERSION,
            "trace_id": context.claim.trace_id,
            "tenant_id": context.claim.tenant_id,
            "verification_id": str(context.verification_id),
            "claim_id": str(context.claim.claim_id),
            "module_run_id": str(context.module_run_id),
            "verdict": verdict.value,
            "confidence": 0.0,
            "finding_codes": [finding_code],
        }
        artifact = await self._write_document(
            context,
            document,
            object_prefix="c6/errors",
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
            return "C6_HANDLER_VALIDATION_FAILED"
        if "tenant" in message:
            return "C6_TENANT_ISOLATION_FAILED"
        if "candidate" in message or "claim" in message:
            return "C6_CANDIDATE_BINDING_FAILED"
        if "knowledge base" in message or "snapshot" in message:
            return "C6_KNOWLEDGE_BASE_BINDING_FAILED"
        if "evidence" in message:
            return "C6_EVIDENCE_INTEGRITY_FAILED"
        if "artifact" in message:
            return "C6_ARTIFACT_INTEGRITY_FAILED"
        return "C6_HANDLER_VALIDATION_FAILED"
