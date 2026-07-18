from __future__ import annotations

from uuid import UUID

from liyans_contracts.topic4_c2 import EvidenceRefV1

from liyans.core.tenant import assert_tenant
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.session import DatabaseSessionManager


class PostgresAcademicEvidenceSource:
    """Loads only the evidence refs bound by the latest immutable C2 bundle."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: PostgresKnowledgeRepository,
    ) -> None:
        self._database = database
        self._repository = repository

    async def load(
        self,
        *,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> tuple[EvidenceRefV1, ...]:
        assert_tenant(tenant_id)
        async with self._database.transaction(context=current_session_context()) as session:
            bundle = await self._repository.latest_evidence_bundle(
                session,
                tenant_id,
                verification_id,
                claim_id,
            )
            if bundle is None:
                return ()
            if (
                bundle.tenant_id != tenant_id
                or bundle.verification_id != verification_id
                or bundle.claim_id != claim_id
            ):
                raise ValueError("latest evidence bundle is not bound to the requested claim")
            refs = await self._repository.list_evidence_refs(session, tenant_id, claim_id)
        by_id = {ref.evidence_ref_id: ref for ref in refs}
        if len(by_id) != len(refs):
            raise ValueError("evidence repository returned duplicate immutable references")
        missing = set(bundle.evidence_ref_ids) - set(by_id)
        if missing:
            raise ValueError("evidence bundle references unavailable immutable evidence")
        return tuple(by_id[evidence_id] for evidence_id in bundle.evidence_ref_ids)
