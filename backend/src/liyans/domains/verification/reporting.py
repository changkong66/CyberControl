from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import (
    AggregationResultV1,
    ClaimRiskV1,
    ClaimV1,
    ClaimVerdictV1,
    ModuleRunResultV1,
    VerificationReportV1,
)
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.infrastructure.database.models import ArtifactStatus
from liyans.infrastructure.persistence.artifacts import (
    ArtifactObjectStore,
    ArtifactRegistration,
    ArtifactRepository,
)

from .aggregation import build_evidence_chain_manifest
from .records import build_topic4_record


class TransactionalVerificationArtifactWriter:
    """Writes immutable bytes first and binds them in the caller's database transaction."""

    def __init__(
        self,
        repository: ArtifactRepository,
        object_store: ArtifactObjectStore,
    ) -> None:
        self._repository = repository
        self._object_store = object_store

    async def write_json(
        self,
        session: AsyncSession,
        *,
        artifact_id: UUID,
        tenant_id: str,
        subject_ref: str,
        resource_type: str,
        object_key: str,
        document: dict[str, Any],
        candidate_id: UUID,
        candidate_version: int,
        trace_id: str,
        created_at: datetime,
    ) -> ArtifactObjectRefV1:
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Topic 4 artifact registration requires an active transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        content = self._canonical_json_bytes(document)
        expected_digest = canonical_sha256(document)
        stored = await self._object_store.put(
            tenant_id=tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != expected_digest or stored.byte_size != len(content):
            raise LiyanError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Topic 4 artifact object metadata does not match canonical JSON.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        await self._repository.add(
            session,
            ArtifactRegistration(
                artifact_id=artifact_id,
                tenant_id=tenant_id,
                schema_version="topic4.verification-artifact.v1",
                artifact_version=1,
                resource_type=resource_type,
                storage_namespace="verification-artifacts",
                object_key=object_key,
                media_type="application/json",
                content_encoding="identity",
                byte_size=stored.byte_size,
                sha256=stored.sha256,
                created_by_subject=subject_ref,
                status=ArtifactStatus.STAGED.value,
                candidate_id=candidate_id,
                candidate_version=candidate_version,
                provenance={"trace_id": trace_id, "topic": "TOPIC4"},
                created_at=created_at,
                updated_at=created_at,
            ),
        )
        await self._repository.transition_status_in_transaction(
            session,
            artifact_id,
            tenant_id=tenant_id,
            expected_status=ArtifactStatus.STAGED.value,
            target_status=ArtifactStatus.VERIFIED.value,
            changed_at=created_at,
        )
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
    def _canonical_json_bytes(document: dict[str, Any]) -> bytes:
        return json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


class VerificationReportBuilder:
    def __init__(
        self,
        artifact_writer: TransactionalVerificationArtifactWriter,
        *,
        knowledge_base_version: str,
        policy_version: str,
    ) -> None:
        if not knowledge_base_version or len(knowledge_base_version) > 128:
            raise ValueError("knowledge base version must contain 1 to 128 characters")
        if not policy_version or len(policy_version) > 128:
            raise ValueError("report policy version must contain 1 to 128 characters")
        self._artifact_writer = artifact_writer
        self._knowledge_base_version = knowledge_base_version
        self._policy_version = policy_version

    async def build(
        self,
        session: AsyncSession,
        *,
        claims: list[ClaimV1],
        risks: list[ClaimRiskV1],
        module_results: list[ModuleRunResultV1],
        claim_verdicts: list[ClaimVerdictV1],
        aggregation: AggregationResultV1,
        evidence_digests: dict[UUID, str],
        subject_ref: str,
        trace_id: str,
        tenant_id: str,
        resource_type: str,
        completed_at: datetime,
    ) -> VerificationReportV1:
        if not claims:
            raise ValueError("verification report requires at least one claim")
        report_id = uuid5(
            NAMESPACE_URL,
            (
                f"liyans:topic4:report:{tenant_id}:{aggregation.verification_id}:"
                f"{aggregation.aggregation_result_id}"
            ),
        )
        evidence_manifest = build_evidence_chain_manifest(
            verification_id=aggregation.verification_id,
            report_id=report_id,
            evidence_digests=evidence_digests,
            module_results=module_results,
            trace_id=trace_id,
            tenant_id=tenant_id,
            created_at=completed_at,
        )
        candidate = claims[0]
        manifest_document = evidence_manifest.model_dump(mode="json")
        await self._artifact_writer.write_json(
            session,
            artifact_id=evidence_manifest.evidence_chain_manifest_id,
            tenant_id=tenant_id,
            subject_ref=subject_ref,
            resource_type=resource_type,
            object_key=(
                f"evidence-chains/{aggregation.verification_id}/"
                f"{evidence_manifest.evidence_chain_manifest_id}.json"
            ),
            document=manifest_document,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            trace_id=trace_id,
            created_at=completed_at,
        )
        report_document = {
            "schema_version": "topic4.verification-report.document.v1",
            "report_id": str(report_id),
            "verification_id": str(aggregation.verification_id),
            "candidate_id": str(candidate.candidate_id),
            "candidate_version": candidate.candidate_version,
            "candidate_sha256": candidate.candidate_sha256,
            "decision": aggregation.decision.value,
            "aggregation": aggregation.model_dump(mode="json"),
            "claims": [claim.model_dump(mode="json") for claim in claims],
            "risks": [risk.model_dump(mode="json") for risk in risks],
            "module_results": [result.model_dump(mode="json") for result in module_results],
            "claim_verdicts": [verdict.model_dump(mode="json") for verdict in claim_verdicts],
            "evidence_chain_manifest": manifest_document,
            "knowledge_base_version": self._knowledge_base_version,
            "policy_version": self._policy_version,
            "completed_at": completed_at.isoformat(),
        }
        report_artifact = await self._artifact_writer.write_json(
            session,
            artifact_id=report_id,
            tenant_id=tenant_id,
            subject_ref=subject_ref,
            resource_type=resource_type,
            object_key=f"reports/{aggregation.verification_id}/{report_id}.json",
            document=report_document,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            trace_id=trace_id,
            created_at=completed_at,
        )
        return build_topic4_record(
            VerificationReportV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=aggregation.version_cas,
            created_at=completed_at,
            immutable=True,
            schema_version="verification.report.v1",
            report_id=report_id,
            verification_id=aggregation.verification_id,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            candidate_sha256=candidate.candidate_sha256,
            knowledge_base_version=self._knowledge_base_version,
            aggregation_result_id=aggregation.aggregation_result_id,
            decision=aggregation.decision,
            claim_verdict_ids=[verdict.claim_verdict_id for verdict in claim_verdicts],
            evidence_chain_manifest_id=evidence_manifest.evidence_chain_manifest_id,
            report_artifact=report_artifact,
            report_sha256=report_artifact.sha256,
            policy_version=self._policy_version,
            completed_at=completed_at,
        )
