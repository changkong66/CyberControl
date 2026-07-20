from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime

from liyans.core.settings import get_settings
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.knowledge.artifact_writer import KnowledgeArtifactWriter
from liyans.domains.knowledge.ingestion import SourceImportCommand
from liyans.domains.knowledge.lifecycle import (
    KnowledgeBaseBuildCommand,
    KnowledgeBaseLifecycleService,
)
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.domains.knowledge.retrieval import HotReloadableRAGIndex
from liyans.domains.knowledge.transactions import KnowledgeTransactionCoordinator
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.infrastructure.database import DatabaseSessionManager, create_database_engine
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.persistence import (
    FileSystemArtifactObjectStore,
    PostgresArtifactRepository,
    PostgresOutboxRepository,
)
from liyans_contracts.topic4_c2 import SourceAuthorityTier

DEFAULT_COURSE_ID = "CRS_ATC_001"
DEFAULT_TARGET_KP_ID = "KP_ATC_202_LAPLACE_TRANSFORM"
DEFAULT_VERSION = "system-acceptance-2026.07.19.v3"
FIXTURE_EVIDENCE = (
    "This deterministic local fixture uses only the frozen Topic1 input segment. ",
    "It demonstrates the complete generation, verification, and release pipeline ",
    "through the configured local fixture provider.",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build and activate the local C2 knowledge base used by the real system "
            "acceptance flow. Run this inside the API container so artifacts are written "
            "to the same persistent volume as the application."
        )
    )
    parser.add_argument("--tenant-id", default="demo-academy")
    parser.add_argument("--subject-ref", default="system:acceptance-bootstrap")
    parser.add_argument("--trace-id", default="a" * 32)
    parser.add_argument("--course-id", default=DEFAULT_COURSE_ID)
    parser.add_argument("--target-kp-id", default=DEFAULT_TARGET_KP_ID)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    return parser


def _source_document(graph: object, *, course_id: str, target_kp_id: str) -> bytes:
    target = next(
        (point for point in graph.content.knowledge_points if point.kp_id == target_kp_id),
        None,
    )
    if target is None:
        raise ValueError(f"Target knowledge point {target_kp_id!r} is absent from Topic1")

    evidence_parts = [
        target.title,
        target.summary,
        *target.learning_objectives,
        *target.formula_signatures,
        *target.aliases,
        *target.tags,
        f"Local fixture lesson: {target.title}",
        f"Explain the core definition and boundary of {target.title}.",
        "Authoritative foundation",
        "ENGINEERING",
        "fixture_foundation",
        target.kp_id,
        f"Review the Topic1 evidence bound to {target.kp_id}.",
        "".join(FIXTURE_EVIDENCE),
    ]
    sections = [
        {
            "section_id": f"release-eligible-{target.kp_id.lower()}",
            "title": f"Release-eligible authority for {target.title}",
            "text": "\n".join(part for part in evidence_parts if part),
            "topic1_knowledge_point_ids": [target.kp_id],
        }
    ]
    document = {
        "schema_version": "system-acceptance-authority.v1",
        "course_id": course_id,
        "graph_snapshot_id": str(graph.snapshot_id),
        "graph_snapshot_sha256": graph.content_sha256,
        "sections": sections,
    }
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if len(args.trace_id) < 16 or len(args.trace_id) > 64:
        raise ValueError("--trace-id must contain between 16 and 64 characters")

    settings = get_settings()
    database = DatabaseSessionManager(create_database_engine(settings))
    topic1_repository = PostgresTopic1Repository()
    knowledge_repository = PostgresKnowledgeRepository()
    artifact_store = FileSystemArtifactObjectStore(
        settings.artifact_root,
        max_object_bytes=settings.artifact_max_object_bytes,
    )
    artifact_writer = KnowledgeArtifactWriter(
        PostgresArtifactRepository(database),
        artifact_store,
    )
    transactions = KnowledgeTransactionCoordinator(
        database,
        PostgresOutboxRepository(database),
        instance_id=f"{settings.service_instance_id}-acceptance-bootstrap",
        build_version="topic4-c2-system-acceptance-v1",
    )
    indexes = HotReloadableRAGIndex()
    lifecycle = KnowledgeBaseLifecycleService(
        database,
        knowledge_repository,
        topic1_repository,
        artifact_writer,
        transactions,
        indexes,
    )
    context = TenantContext(
        tenant_id=args.tenant_id,
        subject_ref=args.subject_ref,
        roles=frozenset({"reviewer"}),
        scopes=frozenset({"topic1:read", "topic4:rag:read"}),
        trace_id=args.trace_id,
        session_id=None,
    )

    try:
        with tenant_scope(context):
            async with database.transaction(context=current_session_context()) as session:
                graph = await topic1_repository.latest_snapshot(
                    session,
                    args.tenant_id,
                    args.course_id,
                )
            if graph is None or not graph.content.knowledge_points:
                raise RuntimeError(
                    "The frozen Topic1 graph must be imported before building C2 evidence."
                )

            source = SourceImportCommand(
                course_id=args.course_id,
                title="CyberControl release-eligible system acceptance authority",
                authors=("CyberControl frozen Topic1 graph",),
                publisher="CyberControl local acceptance environment",
                authority_tier=SourceAuthorityTier.CURATED_INTERNAL,
                source_type="SYSTEM_ACCEPTANCE_CORPUS",
                canonical_citation=(
                    "CyberControl. Frozen Topic1-derived system acceptance authority. "
                    f"{args.version}."
                ),
                license_expression="LicenseRef-CyberControl-Internal-Acceptance",
                version=args.version,
                content=_source_document(
                    graph,
                    course_id=args.course_id,
                    target_kp_id=args.target_kp_id,
                ),
                media_type="application/json",
                effective_from=datetime(2026, 7, 19, tzinfo=UTC),
            )
            imported = await lifecycle.import_source(
                source,
                idempotency_key=f"system-acceptance-c2-source-{args.version}",
            )
            built = await lifecycle.build_and_activate(
                KnowledgeBaseBuildCommand(
                    course_id=args.course_id,
                    version=args.version,
                    source_document_version_ids=(
                        imported.source_version.source_document_version_id,
                    ),
                    graph_snapshot_id=graph.snapshot_id,
                ),
                idempotency_key=f"system-acceptance-c2-build-{args.version}",
            )

            return {
                "tenant_id": args.tenant_id,
                "course_id": args.course_id,
                "target_kp_id": args.target_kp_id,
                "trace_id": args.trace_id,
                "graph_snapshot_id": str(graph.snapshot_id),
                "graph_snapshot_version": graph.graph_version,
                "graph_snapshot_sha256": graph.content_sha256,
                "source_document_version_id": str(
                    imported.source_version.source_document_version_id
                ),
                "source_sha256": imported.source_version.content_sha256,
                "knowledge_base_version_id": str(built.knowledge_base.knowledge_base_version_id),
                "knowledge_base_version": built.knowledge_base.version,
                "knowledge_base_sha256": built.knowledge_base.record_sha256,
                "chunk_count": built.chunk_count,
                "index_state": built.ready_manifest.state.value,
                "index_manifest_sha256": built.ready_manifest.record_sha256,
                "active_index_version_id": str(
                    indexes.active_version(args.tenant_id, args.course_id)
                ),
            }
    finally:
        await database.close()


def main() -> int:
    args = _parser().parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
