from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import Topic1GraphSnapshotV1
from liyans_contracts.topic4_c2 import EvidenceRefV1

from liyans.core.tenant import assert_tenant
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.verification.records import record_integrity_valid
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.session import DatabaseSessionManager


@dataclass(frozen=True, slots=True)
class GraphEvidenceBundle:
    snapshot: Topic1GraphSnapshotV1 | None
    evidence: tuple[EvidenceRefV1, ...]
    knowledge_base_version_id: UUID | None = None


class GraphEvidenceSource(Protocol):
    async def load(
        self,
        *,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> GraphEvidenceBundle: ...


class PostgresGraphEvidenceSource:
    """Loads one immutable Topic1 snapshot and its C2 evidence bundle atomically."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        knowledge_repository: PostgresKnowledgeRepository,
        topic1_repository: PostgresTopic1Repository,
    ) -> None:
        self._database = database
        self._knowledge_repository = knowledge_repository
        self._topic1_repository = topic1_repository

    async def load(
        self,
        *,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> GraphEvidenceBundle:
        assert_tenant(tenant_id)
        async with self._database.transaction(context=current_session_context()) as session:
            bundle = await self._knowledge_repository.latest_evidence_bundle(
                session,
                tenant_id,
                verification_id,
                claim_id,
            )
            if bundle is None:
                return GraphEvidenceBundle(snapshot=None, evidence=())
            if (
                bundle.tenant_id != tenant_id
                or bundle.verification_id != verification_id
                or bundle.claim_id != claim_id
            ):
                raise ValueError("graph evidence bundle is not bound to the requested claim")
            if not record_integrity_valid(bundle):
                raise ValueError("graph evidence bundle record integrity check failed")
            knowledge_base = await self._knowledge_repository.get_knowledge_base_version(
                session,
                tenant_id,
                bundle.knowledge_base_version_id,
            )
            if knowledge_base is None:
                raise ValueError("graph evidence bundle references an unavailable knowledge base")
            if not record_integrity_valid(knowledge_base):
                raise ValueError("graph knowledge base record integrity check failed")
            if knowledge_base.knowledge_base_version_id != bundle.knowledge_base_version_id:
                raise ValueError("graph knowledge base is not bound to the evidence bundle")
            snapshot = await self._topic1_repository.get_snapshot(
                session,
                tenant_id,
                knowledge_base.graph_snapshot_id,
            )
            if snapshot is None:
                raise ValueError("graph knowledge base references an unavailable Topic1 snapshot")
            if snapshot.snapshot_id != knowledge_base.graph_snapshot_id:
                raise ValueError("graph snapshot is not bound to the knowledge base")
            if snapshot.graph_version != knowledge_base.graph_snapshot_version:
                raise ValueError("graph snapshot version does not match the knowledge base")
            refs = await self._knowledge_repository.list_evidence_refs(session, tenant_id, claim_id)

        by_id = {ref.evidence_ref_id: ref for ref in refs}
        if len(by_id) != len(refs):
            raise ValueError("graph evidence repository returned duplicate references")
        missing = set(bundle.evidence_ref_ids) - set(by_id)
        if missing:
            raise ValueError("graph evidence bundle references unavailable evidence")
        ordered = tuple(by_id[identifier] for identifier in bundle.evidence_ref_ids)
        self._validate_evidence(
            ordered,
            tenant_id,
            verification_id,
            claim_id,
            knowledge_base_version_id=bundle.knowledge_base_version_id,
            trace_id=bundle.trace_id,
        )
        return GraphEvidenceBundle(
            snapshot=snapshot,
            evidence=ordered,
            knowledge_base_version_id=bundle.knowledge_base_version_id,
        )

    @staticmethod
    def _validate_evidence(
        evidence: tuple[EvidenceRefV1, ...],
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
        *,
        knowledge_base_version_id: UUID | None = None,
        trace_id: str | None = None,
    ) -> None:
        seen: set[UUID] = set()
        for ref in evidence:
            if ref.tenant_id != tenant_id:
                raise ValueError("graph evidence crosses tenant boundaries")
            if ref.verification_id != verification_id or ref.claim_id != claim_id:
                raise ValueError("graph evidence is not bound to the claim")
            if trace_id is not None and ref.trace_id != trace_id:
                raise ValueError("graph evidence is not bound to the evidence bundle trace")
            if (
                knowledge_base_version_id is not None
                and ref.knowledge_base_version_id != knowledge_base_version_id
            ):
                raise ValueError("graph evidence is not bound to the knowledge base version")
            if not record_integrity_valid(ref):
                raise ValueError("graph evidence record integrity check failed")
            if canonical_sha256(ref.excerpt) != ref.excerpt_sha256:
                raise ValueError("graph evidence excerpt integrity check failed")
            if ref.evidence_ref_id in seen:
                raise ValueError("graph evidence contains duplicate references")
            seen.add(ref.evidence_ref_id)
