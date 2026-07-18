from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c2 import (
    DocumentIRV1,
    EmbeddingProfileV1,
    EvidenceBundleV1,
    EvidenceRefV1,
    FormulaSignatureV1,
    IndexBuildManifestV1,
    KnowledgeBaseVersionV1,
    KnowledgeChunkV1,
    QueryPlanV1,
    RetrievalResponseV1,
    SourceDocumentV1,
    SourceDocumentVersionV1,
)
from liyans_contracts.topic4_common import Topic4RecordV1
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant

from .entities import KnowledgeBaseActivation, SourceVersionBundle
from .models import (
    Topic4EmbeddingProfileModel,
    Topic4EvidenceBundleModel,
    Topic4EvidenceRefModel,
    Topic4FormulaSignatureModel,
    Topic4IndexBuildManifestModel,
    Topic4KnowledgeBaseActivationModel,
    Topic4KnowledgeBaseVersionModel,
    Topic4KnowledgeChunkModel,
    Topic4QueryPlanModel,
    Topic4RetrievalRunModel,
    Topic4SourceDocumentModel,
    Topic4SourceDocumentVersionModel,
)

BATCH_SIZE = 1000


class PostgresKnowledgeRepository:
    async def append_source_document(
        self,
        session: AsyncSession,
        tenant_id: str,
        source: SourceDocumentV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, source.tenant_id)
        session.add(
            Topic4SourceDocumentModel(
                source_document_record_id=source.source_document_id,
                source_document_id=source.source_document_id,
                course_id=source.course_id,
                title=source.title,
                publisher=source.publisher,
                authority_tier=source.authority_tier.value,
                lifecycle=source.lifecycle.value,
                license_expression=source.license_expression,
                canonical_citation_sha256=canonical_sha256(source.canonical_citation),
                document=source.model_dump(mode="json"),
                **self._record_columns(source, audit_event_id),
            )
        )
        await session.flush()

    async def get_source_document(
        self,
        session: AsyncSession,
        tenant_id: str,
        source_document_id: UUID,
    ) -> SourceDocumentV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4SourceDocumentModel).where(
                Topic4SourceDocumentModel.tenant_id == tenant_id,
                Topic4SourceDocumentModel.source_document_id == source_document_id,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else SourceDocumentV1.model_validate(row.document)

    async def get_source_document_by_citation(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
        citation_sha256: str,
    ) -> SourceDocumentV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4SourceDocumentModel).where(
                Topic4SourceDocumentModel.tenant_id == tenant_id,
                Topic4SourceDocumentModel.course_id == course_id,
                Topic4SourceDocumentModel.canonical_citation_sha256 == citation_sha256,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else SourceDocumentV1.model_validate(row.document)

    async def append_source_version(
        self,
        session: AsyncSession,
        tenant_id: str,
        bundle: SourceVersionBundle,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        version = bundle.source_version
        self._assert_record_tenant(tenant_id, version.tenant_id)
        session.add(
            Topic4SourceDocumentVersionModel(
                source_document_version_record_id=version.source_document_version_id,
                source_document_version_id=version.source_document_version_id,
                source_document_id=version.source_document_id,
                version=version.version,
                content_sha256=version.content_sha256,
                parser_version=version.parser_version,
                published_on=version.published_on,
                effective_from=version.effective_from,
                effective_until=version.effective_until,
                lifecycle=version.lifecycle.value,
                version_document={
                    "schema_version": "source-version.bundle.v1",
                    "source_version": version.model_dump(mode="json"),
                    "document_ir": bundle.document_ir.model_dump(mode="json"),
                    "graph_snapshot_id": str(bundle.graph_snapshot_id),
                    "graph_snapshot_version": bundle.graph_snapshot_version,
                },
                **self._record_columns(version, audit_event_id),
            )
        )
        await session.flush()

    async def get_source_version_bundle(
        self,
        session: AsyncSession,
        tenant_id: str,
        source_document_version_id: UUID,
    ) -> SourceVersionBundle | None:
        bundles = await self.list_source_version_bundles(
            session,
            tenant_id,
            (source_document_version_id,),
        )
        return None if not bundles else bundles[0]

    async def list_source_version_bundles(
        self,
        session: AsyncSession,
        tenant_id: str,
        source_document_version_ids: Sequence[UUID],
    ) -> list[SourceVersionBundle]:
        assert_tenant(tenant_id)
        if not source_document_version_ids:
            return []
        version_result = await session.execute(
            select(Topic4SourceDocumentVersionModel).where(
                Topic4SourceDocumentVersionModel.tenant_id == tenant_id,
                Topic4SourceDocumentVersionModel.source_document_version_id.in_(
                    source_document_version_ids
                ),
            )
        )
        version_rows = list(version_result.scalars())
        document_ids = {row.source_document_id for row in version_rows}
        document_result = await session.execute(
            select(Topic4SourceDocumentModel).where(
                Topic4SourceDocumentModel.tenant_id == tenant_id,
                Topic4SourceDocumentModel.source_document_id.in_(document_ids),
            )
        )
        documents = {
            row.source_document_id: SourceDocumentV1.model_validate(row.document)
            for row in document_result.scalars()
        }
        by_version: dict[UUID, SourceVersionBundle] = {}
        for row in version_rows:
            raw = row.version_document
            if not isinstance(raw, dict) or raw.get("schema_version") != "source-version.bundle.v1":
                raise self._integrity_error("Source version persistence bundle is invalid.")
            source = documents.get(row.source_document_id)
            if source is None:
                raise self._integrity_error("Source version has no source document.")
            try:
                bundle = SourceVersionBundle(
                    source_document=source,
                    source_version=SourceDocumentVersionV1.model_validate(raw["source_version"]),
                    document_ir=DocumentIRV1.model_validate(raw["document_ir"]),
                    graph_snapshot_id=UUID(str(raw["graph_snapshot_id"])),
                    graph_snapshot_version=int(raw["graph_snapshot_version"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise self._integrity_error(
                    "Source version persistence bundle is invalid."
                ) from exc
            by_version[row.source_document_version_id] = bundle
        return [
            by_version[identifier]
            for identifier in source_document_version_ids
            if identifier in by_version
        ]

    async def append_embedding_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        profile: EmbeddingProfileV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, profile.tenant_id)
        session.add(
            Topic4EmbeddingProfileModel(
                embedding_profile_record_id=profile.embedding_profile_id,
                embedding_profile_id=profile.embedding_profile_id,
                algorithm=profile.algorithm,
                dimension=profile.dimension,
                tokenizer_version=profile.tokenizer_version,
                hash_seed_version=profile.hash_seed_version,
                signed_hashing=profile.signed_hashing,
                network_access=profile.network_access,
                profile_document=profile.model_dump(mode="json"),
                **self._record_columns(profile, audit_event_id),
            )
        )
        await session.flush()

    async def get_embedding_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        tokenizer_version: str,
        hash_seed_version: str,
    ) -> EmbeddingProfileV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4EmbeddingProfileModel).where(
                Topic4EmbeddingProfileModel.tenant_id == tenant_id,
                Topic4EmbeddingProfileModel.algorithm == "HASHED_LEXICAL_2048",
                Topic4EmbeddingProfileModel.tokenizer_version == tokenizer_version,
                Topic4EmbeddingProfileModel.hash_seed_version == hash_seed_version,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else EmbeddingProfileV1.model_validate(row.profile_document)

    async def append_knowledge_base_version(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
        knowledge_base: KnowledgeBaseVersionV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, knowledge_base.tenant_id)
        session.add(
            Topic4KnowledgeBaseVersionModel(
                knowledge_base_version_record_id=knowledge_base.knowledge_base_version_id,
                knowledge_base_version_id=knowledge_base.knowledge_base_version_id,
                course_id=course_id,
                version=knowledge_base.version,
                lifecycle=knowledge_base.lifecycle.value,
                source_document_version_ids=[
                    str(identifier) for identifier in knowledge_base.source_document_version_ids
                ],
                graph_snapshot_id=knowledge_base.graph_snapshot_id,
                graph_snapshot_version=knowledge_base.graph_snapshot_version,
                embedding_profile_id=knowledge_base.embedding_profile_id,
                version_document=knowledge_base.model_dump(mode="json"),
                **self._record_columns(knowledge_base, audit_event_id),
            )
        )
        await session.flush()

    async def get_knowledge_base_version(
        self,
        session: AsyncSession,
        tenant_id: str,
        knowledge_base_version_id: UUID,
    ) -> KnowledgeBaseVersionV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4KnowledgeBaseVersionModel).where(
                Topic4KnowledgeBaseVersionModel.tenant_id == tenant_id,
                Topic4KnowledgeBaseVersionModel.knowledge_base_version_id
                == knowledge_base_version_id,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else KnowledgeBaseVersionV1.model_validate(row.version_document)

    async def get_knowledge_base_version_by_label(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
        version: str,
    ) -> KnowledgeBaseVersionV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4KnowledgeBaseVersionModel).where(
                Topic4KnowledgeBaseVersionModel.tenant_id == tenant_id,
                Topic4KnowledgeBaseVersionModel.course_id == course_id,
                Topic4KnowledgeBaseVersionModel.version == version,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else KnowledgeBaseVersionV1.model_validate(row.version_document)

    async def append_chunks(
        self,
        session: AsyncSession,
        tenant_id: str,
        chunks: Sequence[KnowledgeChunkV1],
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            rows: list[dict[str, object]] = []
            for chunk in batch:
                self._assert_record_tenant(tenant_id, chunk.tenant_id)
                rows.append(
                    {
                        "knowledge_chunk_record_id": chunk.knowledge_chunk_id,
                        "knowledge_chunk_id": chunk.knowledge_chunk_id,
                        "knowledge_base_version_id": chunk.knowledge_base_version_id,
                        "source_document_version_id": chunk.source_document_version_id,
                        "section_id": chunk.section_id,
                        "chunk_ordinal": chunk.chunk_ordinal,
                        "normalized_text": chunk.normalized_text,
                        "content_sha256": chunk.content_sha256,
                        "token_count": chunk.token_count,
                        "vector_ordinal": chunk.vector_ordinal,
                        "topic1_knowledge_point_ids": list(chunk.topic1_knowledge_point_ids),
                        "formula_signature_ids": [
                            str(identifier) for identifier in chunk.formula_signature_ids
                        ],
                        "chunk_document": chunk.model_dump(mode="json"),
                        **self._record_columns(chunk, audit_event_id),
                    }
                )
            await session.execute(insert(Topic4KnowledgeChunkModel), rows)
        await session.flush()

    async def list_chunks(
        self,
        session: AsyncSession,
        tenant_id: str,
        knowledge_base_version_id: UUID,
    ) -> list[KnowledgeChunkV1]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4KnowledgeChunkModel)
            .where(
                Topic4KnowledgeChunkModel.tenant_id == tenant_id,
                Topic4KnowledgeChunkModel.knowledge_base_version_id == knowledge_base_version_id,
            )
            .order_by(Topic4KnowledgeChunkModel.vector_ordinal)
        )
        return [KnowledgeChunkV1.model_validate(row.chunk_document) for row in result.scalars()]

    async def append_formula_signatures(
        self,
        session: AsyncSession,
        tenant_id: str,
        signatures: Sequence[FormulaSignatureV1],
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        if not signatures:
            return
        rows: list[dict[str, object]] = []
        for signature in signatures:
            self._assert_record_tenant(tenant_id, signature.tenant_id)
            rows.append(
                {
                    "formula_signature_record_id": signature.formula_signature_id,
                    "formula_signature_id": signature.formula_signature_id,
                    "source_document_version_id": signature.source_document_version_id,
                    "section_id": signature.section_id,
                    "canonical_expression": signature.canonical_expression,
                    "signature_sha256": signature.signature_sha256,
                    "signature_document": signature.model_dump(mode="json"),
                    **self._record_columns(signature, audit_event_id),
                }
            )
        await session.execute(insert(Topic4FormulaSignatureModel), rows)
        await session.flush()

    async def list_formula_signatures(
        self,
        session: AsyncSession,
        tenant_id: str,
        source_document_version_ids: Sequence[UUID],
    ) -> list[FormulaSignatureV1]:
        assert_tenant(tenant_id)
        if not source_document_version_ids:
            return []
        result = await session.execute(
            select(Topic4FormulaSignatureModel)
            .where(
                Topic4FormulaSignatureModel.tenant_id == tenant_id,
                Topic4FormulaSignatureModel.source_document_version_id.in_(
                    source_document_version_ids
                ),
            )
            .order_by(
                Topic4FormulaSignatureModel.source_document_version_id,
                Topic4FormulaSignatureModel.section_id,
                Topic4FormulaSignatureModel.signature_sha256,
            )
        )
        return [
            FormulaSignatureV1.model_validate(row.signature_document) for row in result.scalars()
        ]

    async def append_manifest(
        self,
        session: AsyncSession,
        tenant_id: str,
        manifest: IndexBuildManifestV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, manifest.tenant_id)
        session.add(
            Topic4IndexBuildManifestModel(
                manifest_snapshot_id=uuid5(
                    manifest.index_build_manifest_id,
                    f"manifest-snapshot:{manifest.version_cas}",
                ),
                index_build_manifest_id=manifest.index_build_manifest_id,
                manifest_version=manifest.version_cas,
                knowledge_base_version_id=manifest.knowledge_base_version_id,
                embedding_profile_id=manifest.embedding_profile_id,
                state=manifest.state.value,
                chunk_count=manifest.chunk_count,
                shard_count=manifest.shard_count,
                manifest_sha256=manifest.record_sha256,
                manifest_document=manifest.model_dump(mode="json"),
                built_at=manifest.built_at,
                **self._record_columns(manifest, audit_event_id),
            )
        )
        await session.flush()

    async def latest_manifest(
        self,
        session: AsyncSession,
        tenant_id: str,
        index_build_manifest_id: UUID,
    ) -> IndexBuildManifestV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4IndexBuildManifestModel)
            .where(
                Topic4IndexBuildManifestModel.tenant_id == tenant_id,
                Topic4IndexBuildManifestModel.index_build_manifest_id == index_build_manifest_id,
            )
            .order_by(Topic4IndexBuildManifestModel.manifest_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else IndexBuildManifestV1.model_validate(row.manifest_document)

    async def append_activation(
        self,
        session: AsyncSession,
        tenant_id: str,
        activation: KnowledgeBaseActivation,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        if activation.tenant_id != tenant_id:
            raise self._tenant_mismatch()
        session.add(
            Topic4KnowledgeBaseActivationModel(
                activation_record_id=activation.activation_record_id,
                activation_id=activation.activation_id,
                course_id=activation.course_id,
                activation_version=activation.activation_version,
                knowledge_base_version_id=activation.knowledge_base_version_id,
                replaces_activation_id=activation.replaces_activation_id,
                activated_at=activation.activated_at,
                activation_document=activation.to_document(),
                tenant_id=activation.tenant_id,
                trace_id=activation.trace_id,
                version_cas=activation.version_cas,
                record_sha256=activation.record_sha256,
                immutable=activation.immutable,
                audit_event_id=audit_event_id,
                created_at=activation.created_at,
            )
        )
        await session.flush()

    async def latest_activation(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> KnowledgeBaseActivation | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4KnowledgeBaseActivationModel)
            .where(
                Topic4KnowledgeBaseActivationModel.tenant_id == tenant_id,
                Topic4KnowledgeBaseActivationModel.course_id == course_id,
            )
            .order_by(Topic4KnowledgeBaseActivationModel.activation_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return KnowledgeBaseActivation(
            activation_record_id=row.activation_record_id,
            activation_id=row.activation_id,
            tenant_id=row.tenant_id,
            trace_id=row.trace_id,
            course_id=row.course_id,
            activation_version=row.activation_version,
            knowledge_base_version_id=row.knowledge_base_version_id,
            replaces_activation_id=row.replaces_activation_id,
            activated_at=row.activated_at,
            version_cas=row.version_cas,
            record_sha256=row.record_sha256,
            immutable=row.immutable,
            created_at=row.created_at,
        )

    async def append_query_plan(
        self,
        session: AsyncSession,
        tenant_id: str,
        plan: QueryPlanV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, plan.tenant_id)
        session.add(
            Topic4QueryPlanModel(
                query_plan_record_id=plan.query_plan_id,
                query_plan_id=plan.query_plan_id,
                verification_id=plan.verification_id,
                claim_id=plan.claim_id,
                knowledge_base_version_id=plan.knowledge_base_version_id,
                timeout_ms=plan.timeout_ms,
                plan_sha256=plan.record_sha256,
                plan_document=plan.model_dump(mode="json"),
                **self._record_columns(plan, audit_event_id),
            )
        )
        await session.flush()

    async def latest_query_plan(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> QueryPlanV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4QueryPlanModel)
            .where(
                Topic4QueryPlanModel.tenant_id == tenant_id,
                Topic4QueryPlanModel.verification_id == verification_id,
                Topic4QueryPlanModel.claim_id == claim_id,
            )
            .order_by(Topic4QueryPlanModel.version_cas.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else QueryPlanV1.model_validate(row.plan_document)

    async def append_retrieval_result(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        plan: QueryPlanV1,
        response: RetrievalResponseV1,
        evidence_refs: Sequence[EvidenceRefV1],
        evidence_bundle: EvidenceBundleV1 | None,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        for record in (plan, response, *evidence_refs):
            self._assert_record_tenant(tenant_id, record.tenant_id)
        if evidence_bundle is not None:
            self._assert_record_tenant(tenant_id, evidence_bundle.tenant_id)
        await self.append_query_plan(session, tenant_id, plan, audit_event_id)
        if evidence_refs:
            rows = [
                {
                    "evidence_ref_record_id": evidence.evidence_ref_id,
                    "evidence_ref_id": evidence.evidence_ref_id,
                    "verification_id": evidence.verification_id,
                    "claim_id": evidence.claim_id,
                    "knowledge_base_version_id": evidence.knowledge_base_version_id,
                    "knowledge_chunk_id": evidence.knowledge_chunk_id,
                    "source_document_version_id": evidence.source_document_version_id,
                    "excerpt_sha256": evidence.excerpt_sha256,
                    "fused_score": evidence.fused_score,
                    "evidence_document": evidence.model_dump(mode="json"),
                    **self._record_columns(evidence, audit_event_id),
                }
                for evidence in evidence_refs
            ]
            await session.execute(insert(Topic4EvidenceRefModel), rows)
        if evidence_bundle is not None:
            session.add(
                Topic4EvidenceBundleModel(
                    evidence_bundle_record_id=evidence_bundle.evidence_bundle_id,
                    evidence_bundle_id=evidence_bundle.evidence_bundle_id,
                    verification_id=evidence_bundle.verification_id,
                    claim_id=evidence_bundle.claim_id,
                    query_plan_id=evidence_bundle.query_plan_id,
                    knowledge_base_version_id=evidence_bundle.knowledge_base_version_id,
                    evidence_ref_ids=[
                        str(identifier) for identifier in evidence_bundle.evidence_ref_ids
                    ],
                    coverage_score=evidence_bundle.coverage_score,
                    conflicting_evidence=evidence_bundle.conflicting_evidence,
                    total_ms=evidence_bundle.retrieval_timing.total_ms,
                    bundle_document=evidence_bundle.model_dump(mode="json"),
                    **self._record_columns(evidence_bundle, audit_event_id),
                )
            )
        session.add(
            Topic4RetrievalRunModel(
                retrieval_run_snapshot_id=uuid5(
                    response.retrieval_request_id,
                    f"retrieval-run:{response.version_cas}",
                ),
                retrieval_request_id=response.retrieval_request_id,
                run_version=response.version_cas,
                verification_id=response.verification_id,
                claim_id=response.claim_id,
                query_plan_id=plan.query_plan_id,
                index_build_manifest_id=response.index_build_manifest_id,
                status=response.status.value,
                elapsed_ms=response.elapsed_ms,
                run_document=response.model_dump(mode="json"),
                completed_at=response.completed_at,
                **self._record_columns(response, audit_event_id),
            )
        )
        await session.flush()

    async def get_retrieval_response(
        self,
        session: AsyncSession,
        tenant_id: str,
        retrieval_request_id: UUID,
    ) -> RetrievalResponseV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4RetrievalRunModel)
            .where(
                Topic4RetrievalRunModel.tenant_id == tenant_id,
                Topic4RetrievalRunModel.retrieval_request_id == retrieval_request_id,
            )
            .order_by(Topic4RetrievalRunModel.run_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else RetrievalResponseV1.model_validate(row.run_document)

    async def list_evidence_refs(
        self,
        session: AsyncSession,
        tenant_id: str,
        claim_id: UUID,
    ) -> list[EvidenceRefV1]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4EvidenceRefModel)
            .where(
                Topic4EvidenceRefModel.tenant_id == tenant_id,
                Topic4EvidenceRefModel.claim_id == claim_id,
            )
            .order_by(Topic4EvidenceRefModel.fused_score.desc())
        )
        return [EvidenceRefV1.model_validate(row.evidence_document) for row in result.scalars()]

    async def latest_evidence_bundle(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> EvidenceBundleV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4EvidenceBundleModel)
            .where(
                Topic4EvidenceBundleModel.tenant_id == tenant_id,
                Topic4EvidenceBundleModel.verification_id == verification_id,
                Topic4EvidenceBundleModel.claim_id == claim_id,
            )
            .order_by(Topic4EvidenceBundleModel.version_cas.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else EvidenceBundleV1.model_validate(row.bundle_document)

    @staticmethod
    def _record_columns(record: Topic4RecordV1, audit_event_id: UUID) -> dict[str, object]:
        return {
            "tenant_id": record.tenant_id,
            "trace_id": record.trace_id,
            "version_cas": record.version_cas,
            "record_sha256": record.record_sha256,
            "immutable": record.immutable,
            "audit_event_id": audit_event_id,
            "created_at": record.created_at,
        }

    @staticmethod
    def _assert_record_tenant(expected: str, actual: str) -> None:
        if expected != actual:
            raise PostgresKnowledgeRepository._tenant_mismatch()

    @staticmethod
    def _assert_write(session: AsyncSession, tenant_id: str) -> None:
        assert_tenant(tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Topic 4 knowledge persistence requires an active transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )

    @staticmethod
    def _tenant_mismatch() -> LiyanError:
        return LiyanError(
            ErrorCode.TENANT_MISMATCH,
            "Topic 4 knowledge record tenant does not match the transaction tenant.",
            category=ErrorCategory.TENANT,
            status_code=403,
        )

    @staticmethod
    def _integrity_error(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC4_INTEGRITY_FAILED,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )
