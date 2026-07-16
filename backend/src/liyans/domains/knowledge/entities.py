from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.topic4_c2 import (
    DocumentIRV1,
    EmbeddingProfileV1,
    IndexBuildManifestV1,
    KnowledgeBaseVersionV1,
    SourceDocumentV1,
    SourceDocumentVersionV1,
)

from liyans.infrastructure.persistence.artifacts import ArtifactRegistration


@dataclass(frozen=True, slots=True)
class StagedArtifact:
    registration: ArtifactRegistration
    reference: ArtifactObjectRefV1


@dataclass(frozen=True, slots=True)
class SourceVersionBundle:
    source_document: SourceDocumentV1
    source_version: SourceDocumentVersionV1
    document_ir: DocumentIRV1
    graph_snapshot_id: UUID
    graph_snapshot_version: int


@dataclass(frozen=True, slots=True)
class KnowledgeBaseActivation:
    activation_record_id: UUID
    activation_id: UUID
    tenant_id: str
    trace_id: str
    course_id: str
    activation_version: int
    knowledge_base_version_id: UUID
    replaces_activation_id: UUID | None
    activated_at: datetime
    version_cas: int
    record_sha256: str
    immutable: bool
    created_at: datetime

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": "knowledge-base.activation.v1",
            "activation_id": str(self.activation_id),
            "tenant_id": self.tenant_id,
            "trace_id": self.trace_id,
            "course_id": self.course_id,
            "activation_version": self.activation_version,
            "knowledge_base_version_id": str(self.knowledge_base_version_id),
            "replaces_activation_id": (
                None if self.replaces_activation_id is None else str(self.replaces_activation_id)
            ),
            "activated_at": self.activated_at.isoformat(),
            "version_cas": self.version_cas,
            "record_sha256": self.record_sha256,
            "immutable": self.immutable,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ImportedSourceResult:
    source_document: SourceDocumentV1
    source_version: SourceDocumentVersionV1
    document_ir: DocumentIRV1
    formula_signature_count: int

    def to_document(self) -> dict[str, object]:
        return {
            "source_document": self.source_document.model_dump(mode="json"),
            "source_version": self.source_version.model_dump(mode="json"),
            "document_ir": self.document_ir.model_dump(mode="json"),
            "formula_signature_count": self.formula_signature_count,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeBaseBuildResult:
    knowledge_base: KnowledgeBaseVersionV1
    embedding_profile: EmbeddingProfileV1
    ready_manifest: IndexBuildManifestV1
    activation: KnowledgeBaseActivation
    chunk_count: int

    def to_document(self) -> dict[str, object]:
        return {
            "knowledge_base": self.knowledge_base.model_dump(mode="json"),
            "embedding_profile": self.embedding_profile.model_dump(mode="json"),
            "ready_manifest": self.ready_manifest.model_dump(mode="json"),
            "activation": self.activation.to_document(),
            "chunk_count": self.chunk_count,
        }
