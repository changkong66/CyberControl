from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic3 import CandidateV1
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c2 import EvidenceRefV1

from liyans.core.tenant import assert_tenant
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository
from liyans.domains.verification.records import record_integrity_valid
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.session import DatabaseSessionManager


@dataclass(frozen=True, slots=True)
class QuizEvidenceBundle:
    candidate: CandidateV1 | None
    snapshot: Topic1GraphSnapshotV1 | None
    evidence: tuple[EvidenceRefV1, ...]
    knowledge_base_version_id: UUID | None = None


class QuizEvidenceSource(Protocol):
    async def load(self, claim: ClaimV1) -> QuizEvidenceBundle: ...


class PostgresQuizEvidenceSource:
    """Atomically binds a quiz Claim to Topic3, C2, and Topic1 immutable state."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        knowledge_repository: PostgresKnowledgeRepository,
        topic1_repository: PostgresTopic1Repository,
        topic3_repository: PostgresTopic3Repository,
    ) -> None:
        self._database = database
        self._knowledge_repository = knowledge_repository
        self._topic1_repository = topic1_repository
        self._topic3_repository = topic3_repository

    async def load(self, claim: ClaimV1) -> QuizEvidenceBundle:
        assert_tenant(claim.tenant_id)
        async with self._database.transaction(context=current_session_context()) as session:
            candidate_record = await self._topic3_repository.get_candidate(
                session,
                claim.tenant_id,
                claim.candidate_id,
                claim.candidate_version,
            )
            candidate = None if candidate_record is None else candidate_record.candidate
            self._validate_candidate(candidate, claim)

            bundle = await self._knowledge_repository.latest_evidence_bundle(
                session,
                claim.tenant_id,
                claim.verification_id,
                claim.claim_id,
            )
            if bundle is None:
                return QuizEvidenceBundle(candidate, None, ())
            if (
                bundle.tenant_id != claim.tenant_id
                or bundle.verification_id != claim.verification_id
                or bundle.claim_id != claim.claim_id
                or bundle.trace_id != claim.trace_id
            ):
                raise ValueError("quiz evidence bundle is not bound to the Claim")
            if not record_integrity_valid(bundle):
                raise ValueError("quiz evidence bundle record integrity check failed")

            knowledge_base = await self._knowledge_repository.get_knowledge_base_version(
                session,
                claim.tenant_id,
                bundle.knowledge_base_version_id,
            )
            if knowledge_base is None:
                raise ValueError("quiz evidence bundle references an unavailable knowledge base")
            if (
                knowledge_base.knowledge_base_version_id != bundle.knowledge_base_version_id
                or not record_integrity_valid(knowledge_base)
            ):
                raise ValueError("quiz knowledge base binding or integrity check failed")

            snapshot = await self._topic1_repository.get_snapshot(
                session,
                claim.tenant_id,
                knowledge_base.graph_snapshot_id,
            )
            if snapshot is None:
                raise ValueError("quiz knowledge base references an unavailable Topic1 snapshot")
            if (
                snapshot.snapshot_id != knowledge_base.graph_snapshot_id
                or snapshot.graph_version != knowledge_base.graph_snapshot_version
            ):
                raise ValueError("quiz Topic1 snapshot binding failed")

            refs = await self._knowledge_repository.list_evidence_refs(
                session, claim.tenant_id, claim.claim_id
            )

        by_id = {ref.evidence_ref_id: ref for ref in refs}
        if len(by_id) != len(refs):
            raise ValueError("quiz evidence repository returned duplicate references")
        missing = set(bundle.evidence_ref_ids) - set(by_id)
        if missing:
            raise ValueError("quiz evidence bundle references unavailable evidence")
        ordered = tuple(by_id[identifier] for identifier in bundle.evidence_ref_ids)
        self._validate_evidence(ordered, claim, bundle.knowledge_base_version_id)
        return QuizEvidenceBundle(
            candidate=candidate,
            snapshot=snapshot,
            evidence=ordered,
            knowledge_base_version_id=bundle.knowledge_base_version_id,
        )

    @staticmethod
    def _validate_candidate(candidate: CandidateV1 | None, claim: ClaimV1) -> None:
        if candidate is None:
            return
        if (
            candidate.candidate_id != claim.candidate_id
            or candidate.candidate_version != claim.candidate_version
            or candidate.candidate_sha256 != claim.candidate_sha256
        ):
            raise ValueError("quiz candidate is not bound to the Claim")
        if (
            canonical_sha256(candidate.model_dump(mode="json", exclude={"candidate_sha256"}))
            != candidate.candidate_sha256
        ):
            raise ValueError("quiz candidate integrity check failed")

    @staticmethod
    def _validate_evidence(
        evidence: tuple[EvidenceRefV1, ...],
        claim: ClaimV1,
        knowledge_base_version_id: UUID,
    ) -> None:
        seen: set[UUID] = set()
        for ref in evidence:
            if ref.tenant_id != claim.tenant_id:
                raise ValueError("quiz evidence crosses tenant boundaries")
            if ref.verification_id != claim.verification_id or ref.claim_id != claim.claim_id:
                raise ValueError("quiz evidence is not bound to the Claim")
            if ref.trace_id != claim.trace_id:
                raise ValueError("quiz evidence is not bound to the Trace")
            if ref.knowledge_base_version_id != knowledge_base_version_id:
                raise ValueError("quiz evidence is not bound to the knowledge base version")
            if not record_integrity_valid(ref):
                raise ValueError("quiz evidence record integrity check failed")
            if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
                raise ValueError("quiz evidence excerpt integrity check failed")
            if ref.evidence_ref_id in seen:
                raise ValueError("quiz evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)
