from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic1 import (
    Topic1CourseV1,
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1ImportBundleV1,
    Topic1KnowledgePointV1,
    Topic1PrerequisiteV1,
)
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, MessageConflictError
from liyans.core.hashing import canonical_json_bytes
from liyans.core.tenant import TenantContext, current_tenant
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import (
    AuditEventModel,
    IdempotencyRecordModel,
    IdempotencyStatus,
    OutboxMessageModel,
)
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    TransactionIsolation,
    TransactionRetryPolicy,
)
from liyans.infrastructure.observability.audit import (
    GENESIS_HASH,
    AuditDraft,
    AuditRecord,
    build_audit_record,
)
from liyans.infrastructure.persistence.outbox import OutboxMessage
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

from .postgres_repository import PostgresTopic1Repository
from .topology import TopologyCycleError, TopologyEdge, analyze_topology, classify_difficulty

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_HTTP_BYTES = MAX_IMPORT_BYTES + 65_536
MAX_IMPORT_KNOWLEDGE_POINTS = 500
MAX_IMPORT_EDGES = 2500
IDEMPOTENCY_RETENTION = timedelta(days=1)
OUTBOX_RETENTION = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class MutationPlan:
    data: dict[str, Any]
    course_id: str
    action: str
    target_ref: str
    event_type: str
    event_payload: dict[str, Any]
    snapshot: Topic1GraphSnapshotV1


MutationOperation = Callable[[AsyncSession, TenantContext], Awaitable[MutationPlan]]


class Topic1Service:
    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: PostgresTopic1Repository,
        outbox: PostgresOutboxRepository,
        *,
        instance_id: str,
    ) -> None:
        self._database = database
        self._repository = repository
        self._outbox = outbox
        self._instance_id = instance_id

    async def list_courses(self) -> list[Topic1CourseV1]:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.list_courses(session, context.tenant_id)

    async def get_course(self, course_id: str) -> Topic1CourseV1:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            course = await self._repository.get_course(session, context.tenant_id, course_id)
            if course is None:
                raise self._not_found("course")
            return course

    async def get_graph(self, course_id: str) -> Topic1GraphContentV1:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            content = await self._repository.load_graph_content(
                session,
                context.tenant_id,
                course_id,
            )
            if content is None:
                raise self._not_found("course graph")
            return content

    async def list_snapshots(self, course_id: str) -> list[Topic1GraphSnapshotV1]:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.list_snapshots(session, context.tenant_id, course_id)

    async def upsert_course(
        self,
        *,
        course_id: str,
        document: dict[str, Any],
        expected_revision: int | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        async def operation(session: AsyncSession, context: TenantContext) -> MutationPlan:
            await self._lock_course(session, context.tenant_id, course_id)
            current = await self._repository.load_graph_content(
                session,
                context.tenant_id,
                course_id,
            )
            existing = None if current is None else current.course
            self._check_revision(existing.revision if existing else None, expected_revision)
            now = datetime.now(UTC)
            course = Topic1CourseV1(
                course_id=course_id,
                revision=1 if existing is None else existing.revision + 1,
                created_at=now if existing is None else existing.created_at,
                updated_at=now,
                **document,
            )
            content = Topic1GraphContentV1(
                course=course,
                knowledge_points=[] if current is None else current.knowledge_points,
                prerequisites=[] if current is None else current.prerequisites,
                misconceptions=[] if current is None else current.misconceptions,
                textbooks=[] if current is None else current.textbooks,
                textbook_sections=[] if current is None else current.textbook_sections,
                textbook_mappings=[] if current is None else current.textbook_mappings,
                golden_questions=[] if current is None else current.golden_questions,
            )
            content = self._normalize_content(content, now)
            await self._repository.replace_graph_content(
                session,
                context.tenant_id,
                content,
                context.subject_ref,
            )
            return await self._plan(session, context, content, "COURSE_UPSERTED", course_id)

        return await self._execute_mutation(
            operation="topic1.course.upsert",
            idempotency_key=idempotency_key,
            request_document={
                "course_id": course_id,
                "expected_revision": expected_revision,
                "document": document,
            },
            callback=operation,
        )

    async def upsert_knowledge_point(
        self,
        *,
        course_id: str,
        kp_id: str,
        document: dict[str, Any],
        expected_revision: int | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        async def operation(session: AsyncSession, context: TenantContext) -> MutationPlan:
            await self._lock_course(session, context.tenant_id, course_id)
            content = await self._required_content(session, context.tenant_id, course_id)
            existing = next(
                (item for item in content.knowledge_points if item.kp_id == kp_id), None
            )
            self._check_revision(existing.revision if existing else None, expected_revision)
            now = datetime.now(UTC)
            knowledge_point = Topic1KnowledgePointV1(
                kp_id=kp_id,
                course_id=course_id,
                revision=1 if existing is None else existing.revision + 1,
                topology_level=0 if existing is None else existing.topology_level,
                topology_weight=0 if existing is None else existing.topology_weight,
                created_at=now if existing is None else existing.created_at,
                updated_at=now,
                **document,
            )
            knowledge_points = [item for item in content.knowledge_points if item.kp_id != kp_id]
            knowledge_points.append(knowledge_point)
            content = content.model_copy(update={"knowledge_points": knowledge_points})
            content = self._normalize_content(content, now)
            await self._repository.replace_graph_content(
                session,
                context.tenant_id,
                content,
                context.subject_ref,
            )
            return await self._plan(
                session,
                context,
                content,
                "KNOWLEDGE_POINT_UPSERTED",
                kp_id,
            )

        return await self._execute_mutation(
            operation="topic1.knowledge-point.upsert",
            idempotency_key=idempotency_key,
            request_document={
                "course_id": course_id,
                "kp_id": kp_id,
                "expected_revision": expected_revision,
                "document": document,
            },
            callback=operation,
        )

    async def delete_knowledge_point(
        self,
        *,
        course_id: str,
        kp_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        async def operation(session: AsyncSession, context: TenantContext) -> MutationPlan:
            await self._lock_course(session, context.tenant_id, course_id)
            content = await self._required_content(session, context.tenant_id, course_id)
            existing = next(
                (item for item in content.knowledge_points if item.kp_id == kp_id), None
            )
            if existing is None:
                raise self._not_found("knowledge point")
            self._check_revision(existing.revision, expected_revision)
            now = datetime.now(UTC)
            content = content.model_copy(
                update={
                    "knowledge_points": [
                        item for item in content.knowledge_points if item.kp_id != kp_id
                    ],
                    "prerequisites": [
                        item
                        for item in content.prerequisites
                        if kp_id not in {item.prerequisite_kp_id, item.dependent_kp_id}
                    ],
                    "misconceptions": [
                        item for item in content.misconceptions if item.kp_id != kp_id
                    ],
                    "textbook_mappings": [
                        item for item in content.textbook_mappings if item.kp_id != kp_id
                    ],
                    "golden_questions": [
                        item
                        for item in content.golden_questions
                        if kp_id not in {item.primary_kp_id, *item.related_kp_ids}
                    ],
                }
            )
            content = self._normalize_content(content, now)
            await self._repository.replace_graph_content(
                session,
                context.tenant_id,
                content,
                context.subject_ref,
            )
            return await self._plan(
                session,
                context,
                content,
                "KNOWLEDGE_POINT_DELETED",
                kp_id,
            )

        return await self._execute_mutation(
            operation="topic1.knowledge-point.delete",
            idempotency_key=idempotency_key,
            request_document={
                "course_id": course_id,
                "kp_id": kp_id,
                "expected_revision": expected_revision,
            },
            callback=operation,
        )

    async def upsert_prerequisite(
        self,
        *,
        course_id: str,
        edge_id: str,
        document: dict[str, Any],
        expected_revision: int | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        async def operation(session: AsyncSession, context: TenantContext) -> MutationPlan:
            await self._lock_course(session, context.tenant_id, course_id)
            content = await self._required_content(session, context.tenant_id, course_id)
            existing = next(
                (item for item in content.prerequisites if item.edge_id == edge_id), None
            )
            self._check_revision(existing.revision if existing else None, expected_revision)
            now = datetime.now(UTC)
            edge = Topic1PrerequisiteV1(
                edge_id=edge_id,
                course_id=course_id,
                revision=1 if existing is None else existing.revision + 1,
                created_at=now if existing is None else existing.created_at,
                updated_at=now,
                **document,
            )
            prerequisites = [item for item in content.prerequisites if item.edge_id != edge_id]
            prerequisites.append(edge)
            content = content.model_copy(update={"prerequisites": prerequisites})
            content = self._normalize_content(content, now)
            await self._repository.replace_graph_content(
                session,
                context.tenant_id,
                content,
                context.subject_ref,
            )
            return await self._plan(
                session,
                context,
                content,
                "PREREQUISITE_UPSERTED",
                edge_id,
            )

        return await self._execute_mutation(
            operation="topic1.prerequisite.upsert",
            idempotency_key=idempotency_key,
            request_document={
                "course_id": course_id,
                "edge_id": edge_id,
                "expected_revision": expected_revision,
                "document": document,
            },
            callback=operation,
        )

    async def delete_prerequisite(
        self,
        *,
        course_id: str,
        edge_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        async def operation(session: AsyncSession, context: TenantContext) -> MutationPlan:
            await self._lock_course(session, context.tenant_id, course_id)
            content = await self._required_content(session, context.tenant_id, course_id)
            existing = next(
                (item for item in content.prerequisites if item.edge_id == edge_id), None
            )
            if existing is None:
                raise self._not_found("prerequisite")
            self._check_revision(existing.revision, expected_revision)
            content = content.model_copy(
                update={
                    "prerequisites": [
                        item for item in content.prerequisites if item.edge_id != edge_id
                    ]
                }
            )
            content = self._normalize_content(content, datetime.now(UTC))
            await self._repository.replace_graph_content(
                session,
                context.tenant_id,
                content,
                context.subject_ref,
            )
            return await self._plan(
                session,
                context,
                content,
                "PREREQUISITE_DELETED",
                edge_id,
            )

        return await self._execute_mutation(
            operation="topic1.prerequisite.delete",
            idempotency_key=idempotency_key,
            request_document={
                "course_id": course_id,
                "edge_id": edge_id,
                "expected_revision": expected_revision,
            },
            callback=operation,
        )

    async def import_bundle(
        self,
        bundle: Topic1ImportBundleV1,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._enforce_import_limits(bundle)
        course_id = bundle.content.course.course_id

        async def operation(session: AsyncSession, context: TenantContext) -> MutationPlan:
            await self._lock_course(session, context.tenant_id, course_id)
            latest = await self._latest_snapshot(session, context.tenant_id, course_id)
            latest_version = None if latest is None else latest.graph_version
            if bundle.expected_parent_version != latest_version:
                raise self._conflict("The import parent graph version is stale.")
            content = self._normalize_content(bundle.content, datetime.now(UTC))
            await self._repository.replace_graph_content(
                session,
                context.tenant_id,
                content,
                context.subject_ref,
            )
            return await self._plan(
                session,
                context,
                content,
                "GRAPH_IMPORTED",
                course_id,
            )

        return await self._execute_mutation(
            operation="topic1.graph.import",
            idempotency_key=idempotency_key,
            request_document=bundle.model_dump(mode="json"),
            callback=operation,
        )

    async def freeze_graph(self, course_id: str, *, idempotency_key: str) -> dict[str, Any]:
        async def operation(session: AsyncSession, context: TenantContext) -> MutationPlan:
            await self._lock_course(session, context.tenant_id, course_id)
            content = await self._required_content(session, context.tenant_id, course_id)
            content = self._normalize_content(content, datetime.now(UTC))
            await self._repository.replace_graph_content(
                session,
                context.tenant_id,
                content,
                context.subject_ref,
            )
            return await self._plan(
                session,
                context,
                content,
                "GRAPH_FROZEN",
                course_id,
            )

        return await self._execute_mutation(
            operation="topic1.graph.freeze",
            idempotency_key=idempotency_key,
            request_document={"course_id": course_id},
            callback=operation,
        )

    async def rollback_snapshot(
        self,
        snapshot_id: UUID,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            target = await self._repository.get_snapshot(session, context.tenant_id, snapshot_id)
        if target is None:
            raise self._not_found("graph snapshot")

        async def operation(session: AsyncSession, scoped: TenantContext) -> MutationPlan:
            await self._lock_course(session, scoped.tenant_id, target.course_id)
            latest = await self._latest_snapshot(session, scoped.tenant_id, target.course_id)
            next_version = 1 if latest is None else latest.graph_version + 1
            content = self._roll_forward_content(target.content, next_version, datetime.now(UTC))
            content = self._normalize_content(content, datetime.now(UTC))
            await self._repository.replace_graph_content(
                session,
                scoped.tenant_id,
                content,
                scoped.subject_ref,
            )
            return await self._plan(
                session,
                scoped,
                content,
                "GRAPH_ROLLED_BACK",
                target.course_id,
                restored_from_snapshot_id=target.snapshot_id,
            )

        return await self._execute_mutation(
            operation="topic1.graph.rollback",
            idempotency_key=idempotency_key,
            request_document={"snapshot_id": str(snapshot_id)},
            callback=operation,
        )

    async def _execute_mutation(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_document: dict[str, Any],
        callback: MutationOperation,
    ) -> dict[str, Any]:
        self._validate_idempotency_key(idempotency_key)
        digest = canonical_sha256({"operation": operation, "request": request_document})
        context = current_tenant()

        async def transaction(session: AsyncSession) -> dict[str, Any]:
            duplicate = await self._reserve_idempotency(
                session,
                context,
                idempotency_key,
                operation,
                digest,
            )
            if duplicate is not None:
                return duplicate
            plan = await callback(session, context)
            audit = await self._append_audit(session, context, plan)
            await self._repository.append_snapshot(
                session,
                context.tenant_id,
                plan.snapshot,
                audit.event_id,
            )
            await self._append_outbox(session, context, plan)
            await self._complete_idempotency(session, context, idempotency_key, plan.data)
            return plan.data

        try:
            return await self._database.run_transaction(
                transaction,
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=3),
            )
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if sqlstate == "23505":
                raise self._conflict(
                    "The Topic 1 mutation violates a uniqueness constraint."
                ) from exc
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "The Topic 1 mutation violates a persistence constraint.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            ) from exc

    async def _plan(
        self,
        session: AsyncSession,
        context: TenantContext,
        content: Topic1GraphContentV1,
        action: str,
        target_ref: str,
        *,
        restored_from_snapshot_id: UUID | None = None,
    ) -> MutationPlan:
        latest = await self._latest_snapshot(session, context.tenant_id, content.course.course_id)
        version = 1 if latest is None else latest.graph_version + 1
        frozen_at = datetime.now(UTC)
        snapshot = Topic1GraphSnapshotV1(
            snapshot_id=uuid4(),
            course_id=content.course.course_id,
            graph_version=version,
            parent_snapshot_id=None if latest is None else latest.snapshot_id,
            restored_from_snapshot_id=restored_from_snapshot_id,
            content=content,
            content_sha256=canonical_sha256(content.model_dump(mode="json")),
            node_count=len(content.knowledge_points),
            edge_count=len(content.prerequisites),
            created_by_subject=context.subject_ref,
            frozen_at=frozen_at,
        )
        payload = {
            "schema_version": "topic1.graph-changed.v1",
            "course_id": snapshot.course_id,
            "graph_version": snapshot.graph_version,
            "snapshot_id": str(snapshot.snapshot_id),
            "content_sha256": snapshot.content_sha256,
            "action": action,
        }
        return MutationPlan(
            data={"snapshot": snapshot.model_dump(mode="json")},
            course_id=snapshot.course_id,
            action=action,
            target_ref=target_ref,
            event_type="topic1.graph.changed",
            event_payload=payload,
            snapshot=snapshot,
        )

    async def _reserve_idempotency(
        self,
        session: AsyncSession,
        context: TenantContext,
        key: str,
        operation: str,
        digest: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        statement = (
            insert(IdempotencyRecordModel)
            .values(
                tenant_id=context.tenant_id,
                idempotency_key=key,
                operation=operation,
                request_digest=digest,
                state=IdempotencyStatus.PROCESSING.value,
                lease_owner=self._instance_id,
                lease_expires_at=now + timedelta(minutes=2),
                expires_at=now + IDEMPOTENCY_RETENTION,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyRecordModel.tenant_id,
                    IdempotencyRecordModel.idempotency_key,
                ]
            )
            .returning(IdempotencyRecordModel.idempotency_key)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return None
        result = await session.execute(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        record = result.scalar_one()
        if record.request_digest != digest or record.operation != operation:
            raise MessageConflictError(
                ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                "The idempotency key was reused for different request content.",
            )
        if record.state == IdempotencyStatus.COMPLETED.value:
            if not isinstance(record.result_payload, dict):
                raise self._conflict("The completed idempotency result is unavailable.")
            return dict(record.result_payload)
        if record.expires_at > now:
            raise self._conflict("The idempotent operation is already in progress.")
        record.state = IdempotencyStatus.PROCESSING.value
        record.lease_owner = self._instance_id
        record.lease_expires_at = now + timedelta(minutes=2)
        record.expires_at = now + IDEMPOTENCY_RETENTION
        record.updated_at = now
        return None

    @staticmethod
    async def _complete_idempotency(
        session: AsyncSession,
        context: TenantContext,
        key: str,
        data: dict[str, Any],
    ) -> None:
        result = await session.execute(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        record = result.scalar_one()
        record.state = IdempotencyStatus.COMPLETED.value
        record.lease_owner = None
        record.lease_expires_at = None
        record.response_status_code = 200
        record.result_payload = data
        record.updated_at = datetime.now(UTC)

    @staticmethod
    async def _append_audit(
        session: AsyncSession,
        context: TenantContext,
        plan: MutationPlan,
    ) -> AuditRecord:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"audit:{context.tenant_id}"},
        )
        result = await session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.tenant_id == context.tenant_id)
            .order_by(AuditEventModel.sequence.desc())
            .limit(1)
        )
        previous = result.scalar_one_or_none()
        draft = AuditDraft(
            tenant_id=context.tenant_id,
            category="TOPIC1",
            action=plan.action,
            outcome="SUCCEEDED",
            actor_ref=context.subject_ref,
            target_ref=plan.target_ref,
            trace_id=context.trace_id,
            envelope_id=None,
            metadata={
                "course_id": plan.course_id,
                "snapshot_id": str(plan.snapshot.snapshot_id),
                "graph_version": plan.snapshot.graph_version,
                "content_sha256": plan.snapshot.content_sha256,
            },
            occurred_at=datetime.now(UTC),
        )
        record = build_audit_record(
            draft,
            0 if previous is None else previous.sequence + 1,
            GENESIS_HASH if previous is None else previous.event_hash,
        )
        session.add(
            AuditEventModel(
                event_id=record.event_id,
                tenant_id=record.tenant_id,
                sequence=record.sequence,
                category=record.category,
                action=record.action,
                outcome=record.outcome,
                actor_ref=record.actor_ref,
                target_ref=record.target_ref,
                trace_id=record.trace_id,
                envelope_id=None,
                event_metadata=record.metadata,
                occurred_at=record.occurred_at,
                previous_hash=record.previous_hash,
                event_hash=record.event_hash,
            )
        )
        await session.flush()
        return record

    async def _append_outbox(
        self,
        session: AsyncSession,
        context: TenantContext,
        plan: MutationPlan,
    ) -> None:
        partition_key = f"topic1:{context.tenant_id}:{plan.course_id}"
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"outbox:{partition_key}"},
        )
        result = await session.execute(
            select(func.coalesce(func.max(OutboxMessageModel.sequence) + 1, 0)).where(
                OutboxMessageModel.tenant_id == context.tenant_id,
                OutboxMessageModel.partition_key == partition_key,
            )
        )
        sequence = int(result.scalar_one())
        now = datetime.now(UTC)
        correlation_id = uuid4()
        envelope = Topic3EnvelopeV1(
            envelope_id=uuid4(),
            event_type=plan.event_type,
            message_kind=MessageKind.EVENT,
            tenant_id=context.tenant_id,
            session_id=context.session_id or correlation_id,
            subject_ref=context.subject_ref,
            correlation_id=correlation_id,
            causation_id=None,
            sequence=sequence,
            partition_key=partition_key,
            producer=ProducerMetadataV1(
                agent=None,
                service="topic1-knowledge-service",
                instance_id=self._instance_id,
                build_version="topic1-v1",
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=f"topic1:{canonical_sha256(plan.event_payload)}",
                available_at=now,
                expires_at=now + OUTBOX_RETENTION,
            ),
            resource=None,
            trace_id=context.trace_id,
            span_id=None,
            created_at=now,
            error=None,
            payload=plan.event_payload,
        )
        await self._outbox.append(
            session,
            OutboxMessage(
                outbox_id=uuid4(),
                tenant_id=context.tenant_id,
                envelope=envelope,
                created_at=now,
                available_at=now,
                published_at=None,
                max_attempts=envelope.delivery.max_attempts,
            ),
        )

    async def _required_content(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> Topic1GraphContentV1:
        content = await self._repository.load_graph_content(session, tenant_id, course_id)
        if content is None:
            raise self._not_found("course graph")
        return content

    async def _latest_snapshot(
        self,
        session: AsyncSession,
        tenant_id: str,
        course_id: str,
    ) -> Topic1GraphSnapshotV1 | None:
        return await self._repository.latest_snapshot(session, tenant_id, course_id)

    @staticmethod
    async def _lock_course(session: AsyncSession, tenant_id: str, course_id: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"topic1:{tenant_id}:{course_id}"},
        )

    @staticmethod
    def _normalize_content(
        content: Topic1GraphContentV1,
        now: datetime,
    ) -> Topic1GraphContentV1:
        edges = [
            TopologyEdge(item.prerequisite_kp_id, item.dependent_kp_id)
            for item in content.prerequisites
        ]
        try:
            metrics = analyze_topology({item.kp_id for item in content.knowledge_points}, edges)
        except TopologyCycleError as exc:
            raise LiyanError(
                ErrorCode.TOPIC1_CYCLE,
                "The knowledge topology contains a directed cycle.",
                category=ErrorCategory.CONTRACT,
                status_code=409,
                details={"cycle": list(exc.cycle)},
            ) from exc
        prerequisites = Counter(item.dependent_kp_id for item in content.prerequisites)
        normalized: list[Topic1KnowledgePointV1] = []
        for item in content.knowledge_points:
            assessment = classify_difficulty(
                declared_score=item.difficulty_score,
                prerequisite_count=prerequisites[item.kp_id],
                formula_count=len(item.formula_signatures),
                objective_count=len(item.learning_objectives),
                estimated_minutes=item.estimated_minutes,
            )
            updates = {
                "difficulty_level": assessment.level,
                "topology_level": metrics.levels[item.kp_id],
                "topology_weight": metrics.weights[item.kp_id],
            }
            changed = any(getattr(item, field) != value for field, value in updates.items())
            if changed:
                updates.update({"revision": item.revision + 1, "updated_at": now})
            normalized.append(item.model_copy(update=updates))
        return content.model_copy(
            update={
                "knowledge_points": sorted(
                    normalized,
                    key=lambda item: (item.topology_level, item.kp_id),
                ),
                "prerequisites": sorted(
                    content.prerequisites,
                    key=lambda item: (
                        item.prerequisite_kp_id,
                        item.dependent_kp_id,
                        item.relation_type,
                        item.edge_id,
                    ),
                ),
                "misconceptions": sorted(
                    content.misconceptions,
                    key=lambda item: item.misconception_id,
                ),
                "textbooks": sorted(content.textbooks, key=lambda item: item.textbook_id),
                "textbook_sections": sorted(
                    content.textbook_sections,
                    key=lambda item: item.section_id,
                ),
                "textbook_mappings": sorted(
                    content.textbook_mappings,
                    key=lambda item: item.mapping_id,
                ),
                "golden_questions": sorted(
                    content.golden_questions,
                    key=lambda item: item.question_id,
                ),
            }
        )

    @staticmethod
    def _roll_forward_content(
        content: Topic1GraphContentV1,
        graph_version: int,
        now: datetime,
    ) -> Topic1GraphContentV1:
        def advance(item: Any) -> Any:
            updates = {"revision": max(item.revision + 1, graph_version), "updated_at": now}
            return item.model_copy(update=updates)

        return content.model_copy(
            update={
                "course": advance(content.course),
                "knowledge_points": [advance(item) for item in content.knowledge_points],
                "prerequisites": [advance(item) for item in content.prerequisites],
                "misconceptions": [advance(item) for item in content.misconceptions],
                "textbooks": [advance(item) for item in content.textbooks],
                "textbook_sections": [advance(item) for item in content.textbook_sections],
                "textbook_mappings": [advance(item) for item in content.textbook_mappings],
                "golden_questions": [advance(item) for item in content.golden_questions],
            }
        )

    @staticmethod
    def _enforce_import_limits(bundle: Topic1ImportBundleV1) -> None:
        size = len(canonical_json_bytes(bundle.model_dump(mode="json")))
        if (
            size > MAX_IMPORT_BYTES
            or len(bundle.content.knowledge_points) > MAX_IMPORT_KNOWLEDGE_POINTS
            or len(bundle.content.prerequisites) > MAX_IMPORT_EDGES
        ):
            raise LiyanError(
                ErrorCode.TOPIC1_IMPORT_LIMIT,
                "The Topic 1 import exceeds the accepted size limit.",
                category=ErrorCategory.CONTRACT,
                status_code=413,
                details={
                    "max_bytes": MAX_IMPORT_BYTES,
                    "max_knowledge_points": MAX_IMPORT_KNOWLEDGE_POINTS,
                    "max_edges": MAX_IMPORT_EDGES,
                },
            )

    @staticmethod
    def _check_revision(actual: int | None, expected: int | None) -> None:
        if actual is None and expected is not None:
            raise Topic1Service._conflict("The resource does not exist at the expected revision.")
        if actual is not None and expected != actual:
            raise Topic1Service._conflict("The resource revision is stale.")

    @staticmethod
    def _validate_idempotency_key(key: str) -> None:
        if not 16 <= len(key) <= 160 or any(character.isspace() for character in key):
            raise LiyanError(
                ErrorCode.CONTRACT_INVALID,
                "Idempotency-Key must contain 16 to 160 non-whitespace characters.",
                category=ErrorCategory.CONTRACT,
                status_code=422,
            )

    @staticmethod
    def _not_found(resource: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC1_NOT_FOUND,
            f"The requested Topic 1 {resource} was not found.",
            category=ErrorCategory.CONTRACT,
            status_code=404,
        )

    @staticmethod
    def _conflict(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC1_CONFLICT,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )
