#!/usr/bin/env python3
"""Run the Phase 7 C3 golden set through real PostgreSQL and frozen interfaces."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from liyans.core.settings import Settings
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.academic.evidence_source import PostgresAcademicEvidenceSource
from liyans.domains.academic.handler import C3AcademicHandler
from liyans.domains.knowledge.artifact_writer import KnowledgeArtifactWriter
from liyans.domains.knowledge.ingestion import SourceImportCommand
from liyans.domains.knowledge.lifecycle import (
    KnowledgeBaseBuildCommand,
    KnowledgeBaseLifecycleService,
)
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.domains.knowledge.retrieval import HotReloadableRAGIndex
from liyans.domains.knowledge.retrieval_service import KnowledgeRetrievalService
from liyans.domains.knowledge.transactions import KnowledgeTransactionCoordinator
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic1.service import Topic1Service
from liyans.domains.topic2.memory import EbbinghausMemoryEngine
from liyans.domains.topic2.orchestrator import Topic2Orchestrator
from liyans.domains.topic2.path_planning import AdaptivePathPlanner
from liyans.domains.topic2.postgres_repository import PostgresTopic2Repository
from liyans.domains.topic2.profiling import SixDimensionProfileEngine
from liyans.domains.topic2.service import Topic2Service
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.entities import CandidateRecord
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository
from liyans.domains.topic3.service import Topic3Service
from liyans.domains.verification.execution import BoundedModuleExecutor
from liyans.domains.verification.postgres_repository import PostgresVerificationRepository
from liyans.domains.verification.records import build_topic4_record
from liyans.domains.verification.service import VerificationService, VerifierRuntimeVersions
from liyans.domains.verification.state_machine import VerificationStateMachine
from liyans.infrastructure.database import (
    DatabaseSessionManager,
    SessionExecutionContext,
    create_database_engine,
)
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.persistence import (
    FileSystemArtifactObjectStore,
    PostgresArtifactRepository,
    PostgresOutboxRepository,
)
from liyans_contracts.artifacts import (
    ArtifactObjectRefV1,
    BlockSnapshotManifestItemV1,
    SourceSnapshotRefV1,
)
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import (
    ResourceType,
    SourceAgent,
    VerificationProfile,
    VerificationTrigger,
)
from liyans_contracts.topic1 import CourseStatus, KnowledgePointStatus
from liyans_contracts.topic2 import Topic2AgentContextV1
from liyans_contracts.topic3 import (
    BlockStatus,
    BlockType,
    BlockV1,
    CandidateProvenanceV1,
    CandidateStatus,
    CandidateV1,
    LecturerDepth,
    Topic3ExecutionBlueprintV1,
    Topic3GenerationCommandV1,
)
from liyans_contracts.topic4_c1 import (
    ClaimV1,
    ExtractionMethod,
    ModuleDispatchItemV1,
    ModuleDispatchPlanV1,
)
from liyans_contracts.topic4_c2 import SourceAuthorityTier
from liyans_contracts.topic4_common import (
    ClaimKind,
    VerificationModule,
)
from liyans_contracts.verification import VerificationContextV1, VerificationRequestPayloadV1
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "tests/golden/phase7-academic-golden-facts.v1.jsonl"
REVIEW_PATH = ROOT / "tests/golden/phase7-academic-golden-review.v1.json"
LEDGER_PATH = ROOT / "docs/system-acceptance/evidence/phase7-academic-source-ledger.v1.json"
POLICY_PATH = ROOT / "docs/system-acceptance/phase7-c3-accuracy-policy.md"
DATASET_ID = "phase7-academic-human-reviewed-facts.v1"
POLICY_VERSION = "phase7.c3-accuracy-policy.v1"
COURSE_ID = "CRS_PHASE7_C3_GOLDEN"
BLOCK_ID = "phase7-c3-golden-claims"
EXPECTED_OUTCOMES = ("CONTRADICTED", "INSUFFICIENT_EVIDENCE", "SUPPORTED")
THRESHOLDS = {
    "overall_accuracy": 0.90,
    "per_class_precision": 0.90,
    "per_class_recall": 0.90,
    "abstention_accuracy": 0.90,
    "critical_unsafe_false_negatives": 0,
    "missing_results": 0,
    "nondeterministic_results": 0,
}
PARTICIPATING_TABLES = (
    "topic3_generated_candidates",
    "topic4_verifications",
    "topic4_claims",
    "topic4_query_plans",
    "topic4_retrieval_runs",
    "topic4_evidence_refs",
    "topic4_evidence_bundles",
)


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    topic: str
    knowledge_point_id: str
    fact_id: str
    source_id: str
    excerpt: str
    citation: str
    license_expression: str


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    knowledge_repository: PostgresKnowledgeRepository
    transactions: KnowledgeTransactionCoordinator
    lifecycle: KnowledgeBaseLifecycleService
    retrieval: KnowledgeRetrievalService
    object_store: FileSystemArtifactObjectStore


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _git_executable() -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git executable is required for source binding")
    return executable


def _git_revision(revision: str) -> str:
    if revision not in {"HEAD", "HEAD^{tree}"}:
        raise ValueError("revision is not permitted for source binding")
    return subprocess.run(  # noqa: S603 - executable and revision are allowlisted.
        [_git_executable(), "rev-parse", revision],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_status() -> list[str]:
    output = subprocess.run(  # noqa: S603 - command arguments are constant.
        [_git_executable(), "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in output.splitlines() if line]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _read_facts(path: Path = FACTS_PATH) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"golden fact line {line_number} must be an object")
        facts.append(value)
    return facts


def _knowledge_point_id(topic: str) -> str:
    normalized = "".join(character if character.isalnum() else "_" for character in topic)
    return f"KP_P7_{normalized.upper()}"


def _citation_text(source: dict[str, Any]) -> str:
    authors = ", ".join(str(value) for value in source["chapter_authors"])
    return (
        f"{authors}. {source['chapter_title']}. In {source['work_title']}. "
        f"{source['publisher']}, {source['publication_year']}. "
        f"doi:{source['doi']}. {source['license_expression']}."
    )


def _build_evidence_inputs(
    facts: Sequence[dict[str, Any]],
    ledger: dict[str, Any],
) -> tuple[list[EvidenceInput], dict[str, dict[str, Any]]]:
    source_index = {
        str(source["source_id"]): source for source in ledger.get("included_sources", [])
    }
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        by_topic[str(fact["topic"])].append(fact)

    inputs: list[EvidenceInput] = []
    for topic in sorted(by_topic):
        supported = [
            fact for fact in by_topic[topic] if fact.get("expected_outcome") == "SUPPORTED"
        ]
        if len(supported) != 1:
            raise ValueError(f"topic {topic} must have exactly one SUPPORTED evidence premise")
        fact = supported[0]
        citations = fact.get("citations")
        if not isinstance(citations, list) or len(citations) != 1:
            raise ValueError(f"supported fact {fact.get('fact_id')} must have one citation")
        source_id = str(citations[0]["source_id"])
        source = source_index.get(source_id)
        if source is None:
            raise ValueError(f"supported fact references unknown source {source_id}")
        inputs.append(
            EvidenceInput(
                topic=topic,
                knowledge_point_id=_knowledge_point_id(topic),
                fact_id=str(fact["fact_id"]),
                source_id=source_id,
                excerpt=str(fact["claim"]),
                citation=_citation_text(source),
                license_expression=str(source["license_expression"]),
            )
        )
    return inputs, source_index


def _safe_ratio(numerator: int, denominator: int) -> float | str:
    return "NOT_MEASURABLE" if denominator == 0 else round(numerator / denominator, 6)


def _classification_metrics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    confusion: dict[str, Counter[str]] = {expected: Counter() for expected in EXPECTED_OUTCOMES}
    actual_counts: Counter[str] = Counter()
    for record in records:
        expected = str(record["expected_outcome"])
        actual = str(record["actual_outcome"])
        if expected not in confusion:
            raise ValueError(f"unexpected reviewed outcome {expected}")
        confusion[expected][actual] += 1
        actual_counts[actual] += 1

    total = len(records)
    correct = sum(confusion[expected][expected] for expected in EXPECTED_OUTCOMES)
    per_class: dict[str, dict[str, Any]] = {}
    for expected in EXPECTED_OUTCOMES:
        tp = confusion[expected][expected]
        fp = actual_counts[expected] - tp
        fn = sum(confusion[expected].values()) - tp
        tn = total - tp - fp - fn
        per_class[expected] = {
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "precision": _safe_ratio(tp, tp + fp),
            "recall": _safe_ratio(tp, tp + fn),
        }

    unsafe = [
        str(record["fact_id"])
        for record in records
        if record["expected_outcome"] == "CONTRADICTED" and record["actual_outcome"] == "SUPPORTED"
    ]
    insufficient_total = sum(confusion["INSUFFICIENT_EVIDENCE"].values())
    return {
        "record_count": total,
        "correct_count": correct,
        "overall_accuracy": _safe_ratio(correct, total),
        "confusion_matrix": {
            expected: dict(sorted(values.items())) for expected, values in confusion.items()
        },
        "per_class": per_class,
        "abstention_accuracy": _safe_ratio(
            confusion["INSUFFICIENT_EVIDENCE"]["INSUFFICIENT_EVIDENCE"],
            insufficient_total,
        ),
        "critical_unsafe_false_negative_fact_ids": unsafe,
        "critical_unsafe_false_negatives": len(unsafe),
        "unexpected_actual_outcomes": sorted(set(actual_counts) - set(EXPECTED_OUTCOMES)),
    }


def _numeric_at_least(value: object, threshold: float) -> bool:
    return isinstance(value, int | float) and value >= threshold


def _evaluate_thresholds(
    metrics: dict[str, Any],
    *,
    missing_results: int,
    nondeterministic_results: int,
) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "overall_accuracy": _numeric_at_least(
            metrics["overall_accuracy"], THRESHOLDS["overall_accuracy"]
        ),
        "abstention_accuracy": _numeric_at_least(
            metrics["abstention_accuracy"], THRESHOLDS["abstention_accuracy"]
        ),
        "critical_unsafe_false_negatives": metrics["critical_unsafe_false_negatives"]
        == THRESHOLDS["critical_unsafe_false_negatives"],
        "missing_results": missing_results == THRESHOLDS["missing_results"],
        "nondeterministic_results": nondeterministic_results
        == THRESHOLDS["nondeterministic_results"],
    }
    for outcome in EXPECTED_OUTCOMES:
        class_metrics = metrics["per_class"][outcome]
        checks[f"{outcome}.precision"] = _numeric_at_least(
            class_metrics["precision"], THRESHOLDS["per_class_precision"]
        )
        checks[f"{outcome}.recall"] = _numeric_at_least(
            class_metrics["recall"], THRESHOLDS["per_class_recall"]
        )
    return {
        "thresholds": THRESHOLDS,
        "checks": checks,
        "passed": all(checks.values()),
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
    }


def _candidate_and_spans(
    facts: Sequence[dict[str, Any]],
    now: datetime,
    *,
    blueprint_id: UUID | None = None,
    blueprint_version: str = "phase7.c3-golden-blueprint.v1",
    blueprint_sha256: str | None = None,
) -> tuple[CandidateV1, list[tuple[int, int]]]:
    resolved_blueprint_id = blueprint_id or uuid5(
        NAMESPACE_URL, f"cybercontrol:{DATASET_ID}:blueprint"
    )
    resolved_blueprint_sha256 = blueprint_sha256 or canonical_sha256({"dataset_id": DATASET_ID})
    statements = [str(fact["claim"]) for fact in facts]
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for statement in statements:
        offsets.append((cursor, cursor + len(statement)))
        cursor += len(statement) + 1
    content = {"text": "\n".join(statements)}
    block = BlockV1(
        schema_version="topic3.block.v1",
        block_id=BLOCK_ID,
        block_type=BlockType.MARKDOWN,
        ordinal=0,
        title="Phase 7 C3 academic golden claims",
        content_schema_version="phase7.c3-golden-claims.v1",
        content=content,
        content_sha256=canonical_sha256(content),
        dependency_block_ids=[],
        status=BlockStatus.COMPLETE,
        created_at=now,
    )
    draft = CandidateV1.model_construct(
        schema_version="topic3.candidate.v1",
        candidate_id=uuid5(NAMESPACE_URL, f"cybercontrol:{DATASET_ID}:candidate"),
        candidate_version=1,
        parent_candidate_version=None,
        blueprint_id=resolved_blueprint_id,
        blueprint_version=blueprint_version,
        blueprint_sha256=resolved_blueprint_sha256,
        resource_type=ResourceType.LECTURER_DOC,
        status=CandidateStatus.COMPLETE,
        blocks=[block],
        provenance=CandidateProvenanceV1(
            agent=SourceAgent.LECTURER,
            agent_build_version="phase7-c3-accuracy-harness-v1",
            prompt_bundle_version="not-applicable-reviewed-fixture",
            provider_alias="local",
            provider_request_ids=[],
        ),
        personalization_policy_digest=canonical_sha256(
            {"policy": "no-personalization-in-academic-accuracy"}
        ),
        candidate_sha256="0" * 64,
        created_at=now,
    )
    document = draft.model_dump(mode="json", exclude={"candidate_sha256"})
    return CandidateV1(**document, candidate_sha256=canonical_sha256(document)), offsets


def _verification_request(
    candidate: CandidateV1,
    *,
    tenant_id: str,
    trace_id: str,
    now: datetime,
) -> VerificationRequestPayloadV1:
    verification_id = uuid5(NAMESPACE_URL, f"cybercontrol:{tenant_id}:{DATASET_ID}:verification")
    block = candidate.blocks[0]
    block_bytes = _canonical_bytes(block.content)
    return build_topic4_record(
        VerificationRequestPayloadV1,
        trace_id=trace_id,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=now,
        immutable=True,
        schema_version="verification.request.v1",
        verification_id=verification_id,
        idempotency_key=f"phase7:c3:accept:{verification_id.hex}",
        trigger=VerificationTrigger.INITIAL_GENERATION,
        parent_verification_id=None,
        source_snapshot_ref=SourceSnapshotRefV1(
            schema_version="source.snapshot.ref.v1",
            source_envelope_id=uuid5(verification_id, "source-envelope"),
            source_envelope_version="phase7.c3-golden-envelope.v1",
            source_envelope_sha256=canonical_sha256(
                {"candidate_id": str(candidate.candidate_id), "dataset_id": DATASET_ID}
            ),
            blueprint_id=candidate.blueprint_id,
            blueprint_version=candidate.blueprint_version,
            blueprint_sha256=candidate.blueprint_sha256,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            candidate_sha256=candidate.candidate_sha256,
            source_agent=SourceAgent.LECTURER,
            resource_type=candidate.resource_type,
            full_snapshot=ArtifactObjectRefV1(
                schema_version="artifact.object.ref.v1",
                storage_namespace="verification-artifacts",
                object_key=f"phase7/c3/{candidate.candidate_id}.json",
                media_type="application/json",
                content_encoding="identity",
                byte_size=len(_canonical_bytes(candidate.model_dump(mode="json"))),
                sha256=candidate.candidate_sha256,
                created_at=now,
            ),
            block_manifest=[
                BlockSnapshotManifestItemV1(
                    block_id=block.block_id,
                    block_type=block.block_type.value,
                    ordinal=block.ordinal,
                    json_pointer="/blocks/0",
                    sha256=block.content_sha256,
                    byte_size=len(block_bytes),
                )
            ],
        ),
        context=VerificationContextV1(
            schema_version="verification.context.v1",
            course_id=COURSE_ID,
            course_version="phase7-c3-golden-v1",
            target_kp_id=_knowledge_point_id(str(_read_facts()[0]["topic"])),
            locale="zh-CN",
            subject_domain="AUTOMATION",
            personalization_policy_digest=candidate.personalization_policy_digest,
        ),
        requested_profile=VerificationProfile.STRICT,
        requested_optional_modules=[],
        deadline_at=now + timedelta(minutes=30),
        requested_at=now,
    )


def _runtime_versions() -> VerifierRuntimeVersions:
    return VerifierRuntimeVersions(
        state_machine_version="c1-state-machine-v1",
        verifier_build_version="phase7-c3-accuracy-harness-v1",
        policy_version=POLICY_VERSION,
        prompt_bundle_version="not-applicable-reviewed-fixture",
        retrieval_pipeline_version="local-hybrid-rag-v1",
        knowledge_base_version="phase7-c3-golden-kb-v1",
        toolchain_manifest_version="phase7-c3-accuracy-toolchain-v1",
        content_security_policy_version="security-v1",
        license_policy_version="phase7-academic-review-policy.v1",
    )


def _build_claims(
    facts: Sequence[dict[str, Any]],
    offsets: Sequence[tuple[int, int]],
    *,
    candidate: CandidateV1,
    verification_id: UUID,
    context: TenantContext,
    now: datetime,
) -> list[ClaimV1]:
    claims: list[ClaimV1] = []
    for ordinal, (fact, (start, end)) in enumerate(zip(facts, offsets, strict=True)):
        statement = str(fact["claim"])
        normalized = " ".join(statement.split())
        claims.append(
            build_topic4_record(
                ClaimV1,
                trace_id=context.trace_id,
                tenant_id=context.tenant_id,
                version_cas=1,
                created_at=now,
                immutable=True,
                schema_version="claim.v1",
                claim_id=uuid5(NAMESPACE_URL, f"cybercontrol:{DATASET_ID}:{fact['fact_id']}"),
                verification_id=verification_id,
                candidate_id=candidate.candidate_id,
                candidate_version=candidate.candidate_version,
                candidate_sha256=candidate.candidate_sha256,
                block_id=BLOCK_ID,
                claim_kind=ClaimKind.TEXT,
                claim_subtype="phase7_academic_golden",
                statement=statement,
                normalized_statement=normalized,
                json_pointer="/blocks/0/content/text",
                ordinal=ordinal,
                source_span_start=start,
                source_span_end=end,
                claim_sha256=canonical_sha256(normalized),
                extraction_method=ExtractionMethod.DETERMINISTIC,
                dependent_claim_ids=[],
            )
        )
    return claims


def _source_commands(
    evidence_inputs: Sequence[EvidenceInput],
    source_index: dict[str, dict[str, Any]],
    now: datetime,
) -> list[SourceImportCommand]:
    grouped: dict[str, list[EvidenceInput]] = defaultdict(list)
    for evidence in evidence_inputs:
        grouped[evidence.source_id].append(evidence)
    commands: list[SourceImportCommand] = []
    for source_id in sorted(grouped):
        source = source_index[source_id]
        sections = [
            {
                "section_id": evidence.topic,
                "title": evidence.topic.replace("_", " ").title(),
                "text": evidence.excerpt,
                "topic1_knowledge_point_ids": [evidence.knowledge_point_id],
            }
            for evidence in sorted(grouped[source_id], key=lambda item: item.topic)
        ]
        commands.append(
            SourceImportCommand(
                course_id=COURSE_ID,
                title=str(source["chapter_title"]),
                authors=tuple(str(value) for value in source["chapter_authors"]),
                publisher=str(source["publisher"]),
                authority_tier=SourceAuthorityTier.AUTHORITATIVE_TEXTBOOK,
                source_type="LICENSED_ACADEMIC_CHAPTER",
                canonical_citation=_citation_text(source),
                license_expression=str(source["license_expression"]),
                version=f"phase7-{source_id.lower()}",
                content=_canonical_bytes({"sections": sections}),
                media_type="application/json",
                effective_from=now,
                published_on=date(int(source["publication_year"]), 1, 1),
                source_document_id=uuid5(NAMESPACE_URL, f"cybercontrol:{source_id}:document"),
                source_document_version_id=uuid5(
                    NAMESPACE_URL, f"cybercontrol:{source_id}:version"
                ),
            )
        )
    return commands


def _dispatch_plan(
    claims: Sequence[ClaimV1], *, context: TenantContext, now: datetime
) -> ModuleDispatchPlanV1:
    verification_id = claims[0].verification_id
    dispatch_plan_id = uuid5(verification_id, "phase7-c3-accuracy-plan")
    items = [
        build_topic4_record(
            ModuleDispatchItemV1,
            trace_id=context.trace_id,
            tenant_id=context.tenant_id,
            version_cas=1,
            created_at=now,
            immutable=True,
            schema_version="module-dispatch-item.v1",
            dispatch_item_id=uuid5(dispatch_plan_id, f"c3:{claim.claim_id}"),
            claim_id=claim.claim_id,
            module=VerificationModule.C3_ACADEMIC,
            required=True,
            priority=100,
            dependency_item_ids=[],
            timeout_ms=8_000,
            max_attempts=1,
        )
        for claim in claims
    ]
    plan_sha256 = canonical_sha256(
        {
            "dispatch_plan_id": str(dispatch_plan_id),
            "verification_id": str(verification_id),
            "claim_ids": [str(claim.claim_id) for claim in claims],
            "items": [item.model_dump(mode="json") for item in items],
            "max_parallelism": 8,
            "policy_version": POLICY_VERSION,
        }
    )
    return build_topic4_record(
        ModuleDispatchPlanV1,
        trace_id=context.trace_id,
        tenant_id=context.tenant_id,
        version_cas=1,
        created_at=now,
        immutable=True,
        schema_version="module-dispatch-plan.v1",
        dispatch_plan_id=dispatch_plan_id,
        verification_id=verification_id,
        claim_ids=[claim.claim_id for claim in claims],
        items=items,
        max_parallelism=8,
        policy_version=POLICY_VERSION,
        plan_sha256=plan_sha256,
    )


def _database(url: str, application_name: str) -> DatabaseSessionManager:
    return DatabaseSessionManager(
        create_database_engine(
            Settings(database_url=url, database_pool_timeout_seconds=60),
            application_name=application_name,
        )
    )


async def _role_evidence(database: DatabaseSessionManager) -> dict[str, Any]:
    async with database.transaction() as session:
        result = await session.execute(
            text(
                "SELECT current_user, current_database(), version(), rolsuper, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        )
        role, database_name, version, superuser, bypass_rls = result.one()
    return {
        "role": role,
        "database": database_name,
        "server_version": version,
        "superuser": bool(superuser),
        "bypass_rls": bool(bypass_rls),
        "restricted": not superuser and not bypass_rls,
    }


async def _provision_tenant(
    migrator: DatabaseSessionManager,
    context: TenantContext,
    *,
    display_name: str,
) -> None:
    async with migrator.transaction(
        context=SessionExecutionContext(
            tenant_id=context.tenant_id,
            subject_ref="system:phase7-c3-provisioner",
            trace_id=context.trace_id,
        )
    ) as session:
        await session.execute(
            text(
                "INSERT INTO tenants "
                "(tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim) "
                "VALUES (:tenant_id, :slug, :display_name, :issuer, :tenant_claim)"
            ),
            {
                "tenant_id": context.tenant_id,
                "slug": context.tenant_id,
                "display_name": display_name,
                "issuer": "https://phase7-acceptance.invalid",
                "tenant_claim": context.tenant_id,
            },
        )


def _runtime_services(
    database: DatabaseSessionManager,
    artifact_root: Path,
) -> RuntimeServices:
    object_store = FileSystemArtifactObjectStore(artifact_root)
    repository = PostgresKnowledgeRepository()
    writer = KnowledgeArtifactWriter(PostgresArtifactRepository(database), object_store)
    transactions = KnowledgeTransactionCoordinator(
        database,
        PostgresOutboxRepository(database),
        instance_id="phase7-c3-accuracy",
        build_version="phase7-c3-accuracy-harness-v1",
    )
    indexes = HotReloadableRAGIndex()
    lifecycle = KnowledgeBaseLifecycleService(
        database,
        repository,
        PostgresTopic1Repository(),
        writer,
        transactions,
        indexes,
    )
    retrieval = KnowledgeRetrievalService(
        database,
        repository,
        PostgresTopic1Repository(),
        writer,
        transactions,
        indexes,
    )
    return RuntimeServices(repository, transactions, lifecycle, retrieval, object_store)


async def _seed_topic1(
    database: DatabaseSessionManager,
    evidence_inputs: Sequence[EvidenceInput],
) -> None:
    service = Topic1Service(
        database,
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="phase7-c3-topic1",
    )
    await service.upsert_course(
        course_id=COURSE_ID,
        document={
            "course_code": "P7-C3-GOLDEN",
            "title": "Phase 7 C3 Academic Golden Evaluation",
            "description": "Isolated academic accuracy evaluation course.",
            "locale": "en-US",
            "academic_level": "UNDERGRADUATE",
            "credit_hours": 1,
            "status": CourseStatus.ACTIVE,
            "authority_sources": [],
        },
        expected_revision=None,
        idempotency_key="phase7:c3:topic1:course:seed:0001",
    )
    for evidence in evidence_inputs:
        await service.upsert_knowledge_point(
            course_id=COURSE_ID,
            kp_id=evidence.knowledge_point_id,
            document={
                "title": evidence.topic.replace("_", " ").title(),
                "aliases": [evidence.topic],
                "summary": evidence.excerpt,
                "learning_objectives": ["Evaluate the reviewed academic assertion."],
                "category": "AUTOMATIC_CONTROL",
                "difficulty_level": 4,
                "difficulty_score": 0.5,
                "estimated_minutes": 10,
                "formula_signatures": [],
                "tags": ["phase7", "c3", evidence.topic],
                "status": KnowledgePointStatus.ACTIVE,
                "authority_sources": [],
            },
            expected_revision=None,
            idempotency_key=f"phase7:c3:topic1:kp:{canonical_sha256(evidence.topic)}",
        )


async def _seed_topic2_and_create_topic3_workflow(
    database: DatabaseSessionManager,
    context: TenantContext,
    evidence_inputs: Sequence[EvidenceInput],
    now: datetime,
) -> Topic3ExecutionBlueprintV1:
    topic1 = Topic1Service(
        database,
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="phase7-c3-topic1-reader",
    )
    topic2_persistence = Topic2Service(
        database,
        PostgresTopic2Repository(),
        PostgresTopic1Repository(),
        PostgresOutboxRepository(database),
        instance_id="phase7-c3-topic2",
    )
    topic2 = Topic2Orchestrator(
        database,
        PostgresTopic1Repository(),
        topic2_persistence,
        SixDimensionProfileEngine(),
        EbbinghausMemoryEngine(),
        AdaptivePathPlanner(),
    )
    topic2_operation_id = uuid5(
        NAMESPACE_URL,
        f"cybercontrol:{context.tenant_id}:{DATASET_ID}:topic2-operation",
    )
    await topic2.initialize_learner(
        learner_ref=context.subject_ref,
        course_id=COURSE_ID,
        operation_id=topic2_operation_id,
        requested_at=now,
        idempotency_key="phase7:c3:topic2:initialize:0001",
    )
    await topic2.generate_path(
        learner_ref=context.subject_ref,
        course_id=COURSE_ID,
        operation_id=uuid5(topic2_operation_id, "learning-path"),
        requested_at=now,
        target_goal="Evaluate the Phase 7 human-reviewed automatic-control facts.",
        target_kp_ids=[item.knowledge_point_id for item in evidence_inputs],
        idempotency_key="phase7:c3:topic2:path:0001",
    )
    personalization = Topic2AgentContextV1.model_validate(
        await topic2.agent_context(context.subject_ref, COURSE_ID)
    )
    graph = (await topic1.list_snapshots(COURSE_ID))[0]
    operation_id = uuid5(
        NAMESPACE_URL,
        f"cybercontrol:{context.tenant_id}:{DATASET_ID}:topic3-operation",
    )
    command = Topic3GenerationCommandV1(
        schema_version="topic3.generation-command.v1",
        operation_id=operation_id,
        generation_session_id=uuid5(operation_id, "generation-session"),
        learner_ref=context.subject_ref,
        course_id=COURSE_ID,
        target_kp_ids=[item.knowledge_point_id for item in evidence_inputs],
        requested_resources=[ResourceType.LECTURER_DOC],
        lecturer_depth=LecturerDepth.FOUNDATION,
        learning_goal="Evaluate the Phase 7 human-reviewed automatic-control facts.",
        locale="zh-CN",
        max_parallelism=1,
        allow_partial=False,
        requested_at=now,
    )
    decision = ImmutableBlueprintPlanner().build(command, graph, personalization)
    await Topic3Service(
        database,
        PostgresTopic3Repository(),
        PostgresOutboxRepository(database),
        instance_id="phase7-c3-topic3",
    ).create_workflow(
        command,
        graph,
        personalization,
        decision,
        idempotency_key="phase7:c3:topic3:workflow:0001",
    )
    return decision.blueprint


async def _seed_candidate_and_verification(
    database: DatabaseSessionManager,
    services: RuntimeServices,
    context: TenantContext,
    candidate: CandidateV1,
    request: VerificationRequestPayloadV1,
    now: datetime,
) -> None:
    topic3 = PostgresTopic3Repository()
    async with database.transaction(context=current_session_context()) as session:
        audit_event_id = await services.transactions.append_audit(
            session,
            context,
            action="PHASE7_C3_GOLDEN_CANDIDATE_SEEDED",
            target_ref=str(candidate.candidate_id),
            metadata={"dataset_id": DATASET_ID, "candidate_sha256": candidate.candidate_sha256},
        )
        await topic3.append_candidate(
            session,
            context.tenant_id,
            CandidateRecord(uuid4(), candidate, now),
            audit_event_id,
        )
    verifier = VerificationService(
        database,
        PostgresVerificationRepository(),
        topic3,
        PostgresOutboxRepository(database),
        VerificationStateMachine(),
        _runtime_versions(),
        instance_id="phase7-c3-verifier",
    )
    await verifier.accept_verification(request)


async def _append_claims(
    database: DatabaseSessionManager,
    services: RuntimeServices,
    context: TenantContext,
    claims: list[ClaimV1],
) -> None:
    async with database.transaction(context=current_session_context()) as session:
        audit_event_id = await services.transactions.append_audit(
            session,
            context,
            action="PHASE7_C3_GOLDEN_CLAIMS_SEEDED",
            target_ref=str(claims[0].verification_id),
            metadata={"dataset_id": DATASET_ID, "claim_count": len(claims)},
        )
        await PostgresVerificationRepository().append_claims(
            session,
            context.tenant_id,
            claims,
            audit_event_id,
        )


async def _build_knowledge_base(
    services: RuntimeServices,
    evidence_inputs: Sequence[EvidenceInput],
    source_index: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    imported = [
        await services.lifecycle.import_source(
            command,
            idempotency_key=f"phase7:c3:source:{command.source_document_id.hex}",
        )
        for command in _source_commands(evidence_inputs, source_index, now)
    ]
    built = await services.lifecycle.build_and_activate(
        KnowledgeBaseBuildCommand(
            course_id=COURSE_ID,
            version="phase7-c3-golden-kb-v1",
            source_document_version_ids=tuple(
                item.source_version.source_document_version_id for item in imported
            ),
        ),
        idempotency_key="phase7:c3:knowledge-base:build:0001",
    )
    return {
        "knowledge_base_version_id": str(built.knowledge_base.knowledge_base_version_id),
        "knowledge_base_record_sha256": built.knowledge_base.record_sha256,
        "index_build_manifest_id": str(built.ready_manifest.index_build_manifest_id),
        "index_manifest_record_sha256": built.ready_manifest.record_sha256,
        "source_version_count": len(imported),
    }


async def _retrieve_evidence(
    services: RuntimeServices,
    claims: Sequence[ClaimV1],
    facts: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for claim, fact in zip(claims, facts, strict=True):
        response = await services.retrieval.retrieve_claim(
            claim,
            course_id=COURSE_ID,
            target_kp_id=_knowledge_point_id(str(fact["topic"])),
            idempotency_key=f"phase7:c3:retrieve:{claim.claim_id.hex}",
        )
        bundle = response.evidence_bundle
        if bundle is None or not bundle.evidence_ref_ids:
            raise RuntimeError(f"retrieval produced no evidence for {fact['fact_id']}")
        evidence.append(
            {
                "fact_id": fact["fact_id"],
                "status": response.status.value,
                "evidence_ref_count": len(bundle.evidence_ref_ids),
                "bundle_sha256": bundle.record_sha256,
            }
        )
    return evidence


async def _execute_c3(
    database: DatabaseSessionManager,
    services: RuntimeServices,
    context: TenantContext,
    claims: Sequence[ClaimV1],
    facts: Sequence[dict[str, Any]],
    now: datetime,
) -> tuple[list[dict[str, Any]], int, int]:
    plan = _dispatch_plan(claims, context=context, now=now)
    bundle = await BoundedModuleExecutor(
        {
            VerificationModule.C3_ACADEMIC: C3AcademicHandler(
                PostgresAcademicEvidenceSource(database, services.knowledge_repository),
                services.object_store,
            )
        },
        worker_instance_id="phase7-c3-accuracy-worker",
        retry_backoff_ms=0,
    ).execute(plan, claims, deadline_at=now + timedelta(minutes=20))
    result_by_claim = {result.claim_id: result for result in bundle.results}
    records: list[dict[str, Any]] = []
    nondeterministic = 0
    for claim, fact in zip(claims, facts, strict=True):
        result = result_by_claim.get(claim.claim_id)
        if result is None:
            records.append(
                {
                    "fact_id": fact["fact_id"],
                    "topic": fact["topic"],
                    "expected_outcome": fact["expected_outcome"],
                    "actual_outcome": "MISSING_RESULT",
                    "confidence": None,
                    "finding_codes": [],
                    "evidence_ref_count": 0,
                    "deterministic": False,
                }
            )
            continue
        if not result.deterministic:
            nondeterministic += 1
        records.append(
            {
                "fact_id": fact["fact_id"],
                "topic": fact["topic"],
                "difficulty": fact["difficulty"],
                "expected_outcome": fact["expected_outcome"],
                "actual_outcome": result.verdict.value,
                "confidence": result.confidence,
                "finding_codes": result.finding_codes,
                "evidence_ref_count": len(result.evidence_ref_ids),
                "result_sha256": result.result_sha256,
                "deterministic": result.deterministic,
            }
        )
    return records, len(claims) - len(bundle.results), nondeterministic


async def _rls_flags(database: DatabaseSessionManager) -> list[dict[str, Any]]:
    async with database.transaction() as session:
        result = await session.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:tables) "
                "ORDER BY c.relname"
            ),
            {"tables": list(PARTICIPATING_TABLES)},
        )
        return [
            {"table": name, "rls": bool(rls), "force_rls": bool(force_rls)}
            for name, rls, force_rls in result.all()
        ]


async def _visible_counts(
    database: DatabaseSessionManager,
    *,
    foreign_tenant_id: str,
) -> dict[str, int]:
    queries = {
        "claims": "SELECT count(*) FROM topic4_claims WHERE tenant_id = :tenant_id",
        "query_plans": "SELECT count(*) FROM topic4_query_plans WHERE tenant_id = :tenant_id",
        "retrieval_runs": "SELECT count(*) FROM topic4_retrieval_runs WHERE tenant_id = :tenant_id",
        "evidence_refs": "SELECT count(*) FROM topic4_evidence_refs WHERE tenant_id = :tenant_id",
        "evidence_bundles": (
            "SELECT count(*) FROM topic4_evidence_bundles WHERE tenant_id = :tenant_id"
        ),
    }
    counts: dict[str, int] = {}
    async with database.transaction(context=current_session_context()) as session:
        for name, query in queries.items():
            counts[name] = int(
                (await session.execute(text(query), {"tenant_id": foreign_tenant_id})).scalar_one()
            )
    return counts


async def _changed_content_replay(
    database: DatabaseSessionManager,
    services: RuntimeServices,
    context: TenantContext,
    original: ClaimV1,
) -> dict[str, Any]:
    changed_statement = original.statement + " Altered after immutable persistence."
    changed = build_topic4_record(
        ClaimV1,
        **{
            **original.model_dump(mode="python", exclude={"record_sha256"}),
            "statement": changed_statement,
            "normalized_statement": changed_statement,
            "claim_sha256": canonical_sha256(changed_statement),
        },
    )
    rejected = False
    error_type: str | None = None
    try:
        async with database.transaction(context=current_session_context()) as session:
            audit_event_id = await services.transactions.append_audit(
                session,
                context,
                action="PHASE7_C3_CHANGED_CLAIM_REPLAY",
                target_ref=str(original.claim_id),
                metadata={"changed_claim_sha256": changed.claim_sha256},
            )
            await PostgresVerificationRepository().append_claims(
                session,
                context.tenant_id,
                [changed],
                audit_event_id,
            )
    except IntegrityError as exc:
        rejected = True
        error_type = type(exc).__name__
    async with database.transaction(context=current_session_context()) as session:
        persisted = await PostgresVerificationRepository().list_claims(
            session,
            context.tenant_id,
            original.verification_id,
        )
    persisted_by_id = {claim.claim_id: claim for claim in persisted}
    stored = persisted_by_id[original.claim_id]
    return {
        "rejected": rejected,
        "error_type": error_type,
        "original_record_sha256": original.record_sha256,
        "stored_record_sha256": stored.record_sha256,
        "original_preserved": stored.record_sha256 == original.record_sha256,
    }


async def _run_evaluation(
    *,
    runtime_url: str,
    migration_url: str,
    artifact_root: Path,
    facts: Sequence[dict[str, Any]],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    run_id = uuid4().hex[:16]
    primary = TenantContext(
        tenant_id=f"p7-c3-{run_id}",
        subject_ref="subject:phase7-c3-evaluator",
        roles=frozenset({"acceptance"}),
        scopes=frozenset({"test"}),
        trace_id=hashlib.sha256(f"primary:{run_id}".encode()).hexdigest()[:32],
    )
    adversarial = TenantContext(
        tenant_id=f"p7-c3-other-{run_id}",
        subject_ref="subject:phase7-c3-adversary",
        roles=frozenset({"acceptance"}),
        scopes=frozenset({"test"}),
        trace_id=hashlib.sha256(f"other:{run_id}".encode()).hexdigest()[:32],
    )
    runtime = _database(runtime_url, "phase7-c3-accuracy-runtime")
    migrator = _database(migration_url, "phase7-c3-accuracy-migrator")
    try:
        runtime_role = await _role_evidence(runtime)
        migration_role = await _role_evidence(migrator)
        if not runtime_role["restricted"] or not migration_role["restricted"]:
            raise RuntimeError("Phase 7 C3 evaluation requires restricted PostgreSQL roles")
        await _provision_tenant(migrator, primary, display_name="Phase 7 C3 Evaluation")
        await _provision_tenant(migrator, adversarial, display_name="Phase 7 C3 Adversarial")

        evidence_inputs, source_index = _build_evidence_inputs(facts, ledger)
        now = datetime.now(UTC)
        services = _runtime_services(runtime, artifact_root)
        with tenant_scope(primary):
            await _seed_topic1(runtime, evidence_inputs)
            blueprint = await _seed_topic2_and_create_topic3_workflow(
                runtime,
                primary,
                evidence_inputs,
                now,
            )
            candidate, spans = _candidate_and_spans(
                facts,
                now,
                blueprint_id=blueprint.blueprint_id,
                blueprint_version=blueprint.blueprint_version,
                blueprint_sha256=blueprint.blueprint_sha256,
            )
            request = _verification_request(
                candidate,
                tenant_id=primary.tenant_id,
                trace_id=primary.trace_id,
                now=now,
            )
            await _seed_candidate_and_verification(
                runtime, services, primary, candidate, request, now
            )
            claims = _build_claims(
                facts,
                spans,
                candidate=candidate,
                verification_id=request.verification_id,
                context=primary,
                now=now,
            )
            await _append_claims(runtime, services, primary, claims)
            knowledge = await _build_knowledge_base(services, evidence_inputs, source_index, now)
            retrieval = await _retrieve_evidence(services, claims, facts)
            result_records, missing_results, nondeterministic = await _execute_c3(
                runtime, services, primary, claims, facts, now
            )
            primary_counts = await _visible_counts(runtime, foreign_tenant_id=primary.tenant_id)
            replay = await _changed_content_replay(runtime, services, primary, claims[0])

        with tenant_scope(adversarial):
            foreign_counts = await _visible_counts(runtime, foreign_tenant_id=primary.tenant_id)
            foreign_refs = 0
            async with runtime.transaction(context=current_session_context()) as session:
                for claim in claims:
                    foreign_refs += len(
                        await services.knowledge_repository.list_evidence_refs(
                            session, adversarial.tenant_id, claim.claim_id
                        )
                    )

        rls_flags = await _rls_flags(runtime)
        metrics = _classification_metrics(result_records)
        threshold_evaluation = _evaluate_thresholds(
            metrics,
            missing_results=missing_results,
            nondeterministic_results=nondeterministic,
        )
        database_checks = {
            "runtime_role_restricted": runtime_role["restricted"],
            "migration_role_restricted": migration_role["restricted"],
            "all_participating_tables_present": len(rls_flags) == len(PARTICIPATING_TABLES),
            "all_participating_tables_force_rls": len(rls_flags) == len(PARTICIPATING_TABLES)
            and all(item["rls"] and item["force_rls"] for item in rls_flags),
            "foreign_visible_rows_zero": all(value == 0 for value in foreign_counts.values()),
            "foreign_repository_evidence_refs_zero": foreign_refs == 0,
            "changed_content_replay_rejected": replay["rejected"],
            "changed_content_original_preserved": replay["original_preserved"],
        }
        database_passed = all(database_checks.values())
        return {
            "runtime_role": runtime_role,
            "migration_role": migration_role,
            "primary_tenant_id": primary.tenant_id,
            "adversarial_tenant_id": adversarial.tenant_id,
            "participating_table_rls": rls_flags,
            "primary_visible_counts": primary_counts,
            "adversarial_visible_primary_counts": foreign_counts,
            "adversarial_repository_evidence_ref_count": foreign_refs,
            "changed_content_replay": replay,
            "database_checks": database_checks,
            "database_passed": database_passed,
            "knowledge_base": knowledge,
            "retrieval": retrieval,
            "result_records": result_records,
            "missing_results": missing_results,
            "nondeterministic_results": nondeterministic,
            "metrics": metrics,
            "threshold_evaluation": threshold_evaluation,
            "evidence_input_count": len(evidence_inputs),
            "evidence_input_sha256": canonical_sha256(
                [
                    {
                        "topic": item.topic,
                        "knowledge_point_id": item.knowledge_point_id,
                        "fact_id": item.fact_id,
                        "source_id": item.source_id,
                        "excerpt": item.excerpt,
                        "citation": item.citation,
                        "license_expression": item.license_expression,
                    }
                    for item in evidence_inputs
                ]
            ),
        }
    finally:
        await runtime.close()
        await migrator.close()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument(
        "--runtime-database-url",
        default=os.getenv("LIYAN_TEST_DATABASE_URL"),
    )
    parser.add_argument(
        "--migration-database-url",
        default=os.getenv("LIYAN_TEST_MIGRATION_DATABASE_URL"),
    )
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="Permit local harness development from a dirty tree; never use for formal evidence.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    if not arguments.runtime_database_url or not arguments.migration_database_url:
        raise SystemExit("runtime and migration PostgreSQL URLs are required")
    dirty_files = _git_status()
    if dirty_files and not arguments.allow_dirty_source:
        raise SystemExit("formal C3 accuracy evidence requires a clean source tree")

    facts = _read_facts()
    review = _read_json(REVIEW_PATH)
    ledger = _read_json(LEDGER_PATH)
    if review.get("decision") != "ACCEPTED" or review.get("rights_review_decision") != "ACCEPTED":
        raise SystemExit("the human-reviewed golden set is not ACCEPTED")
    if review.get("facts_content_sha256") != _sha256_file(FACTS_PATH):
        raise SystemExit("the accepted facts SHA256 does not match")
    if len(facts) != 72:
        raise SystemExit("the Phase 7 C3 golden set must contain exactly 72 facts")

    output = arguments.output if arguments.output.is_absolute() else ROOT / arguments.output
    artifact_root = (
        arguments.artifact_root
        if arguments.artifact_root.is_absolute()
        else ROOT / arguments.artifact_root
    )
    artifact_root.mkdir(parents=True, exist_ok=True)
    execution = asyncio.run(
        _run_evaluation(
            runtime_url=arguments.runtime_database_url,
            migration_url=arguments.migration_database_url,
            artifact_root=artifact_root,
            facts=facts,
            ledger=ledger,
        )
    )
    accepted = bool(execution["database_passed"] and execution["threshold_evaluation"]["passed"])
    report: dict[str, Any] = {
        "schema_version": "phase7.c3-academic-accuracy-evidence.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": _git_revision("HEAD"),
        "source_tree": _git_revision("HEAD^{tree}"),
        "clean_source": not dirty_files,
        "dirty_files_at_start": dirty_files,
        "dataset_id": DATASET_ID,
        "facts_content_sha256": _sha256_file(FACTS_PATH),
        "review_content_sha256": _sha256_file(REVIEW_PATH),
        "source_ledger_content_sha256": _sha256_file(LEDGER_PATH),
        "accuracy_policy_version": POLICY_VERSION,
        "accuracy_policy_content_sha256": _sha256_file(POLICY_PATH),
        "evidence_input_policy": "ONE_REVIEWED_SUPPORTED_PARAPHRASE_PER_TOPIC_NO_LABEL_LEAKAGE",
        "ephemeral_cleanup_required": True,
        "release_volume_used": False,
        "execution": execution,
        "local_gate_state": (
            "C3_ACCURACY_AND_POSTGRES_CONTROLS_ACCEPTED"
            if accepted
            else "BLOCKED_C3_ACCURACY_OR_POSTGRES_CONTROLS"
        ),
        "gate_b_local_eligible": accepted,
    }
    report["report_sha256"] = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "state": report["local_gate_state"],
                "overall_accuracy": execution["metrics"]["overall_accuracy"],
                "critical_unsafe_false_negatives": execution["metrics"][
                    "critical_unsafe_false_negatives"
                ],
                "database_passed": execution["database_passed"],
                "failed_thresholds": execution["threshold_evaluation"]["failed_checks"],
                "report_sha256": report["report_sha256"],
            },
            indent=2,
        )
    )
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
