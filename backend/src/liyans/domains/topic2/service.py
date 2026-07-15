from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError, MessageConflictError
from liyans.core.tenant import TenantContext, current_tenant
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
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

from .entities import (
    BehaviorEventType,
    LearningBehaviorEventDraft,
    LearningBehaviorEventRecord,
    LearningPathRecord,
    LearningPathSnapshotDraft,
    MemoryStateDraft,
    MemoryStateRecord,
    PathChangeDraft,
    ProfileFeatureDraft,
    StudentProfileDraft,
    StudentProfileRecord,
)
from .postgres_repository import PostgresTopic2Repository

IDEMPOTENCY_RETENTION = timedelta(days=1)
OUTBOX_RETENTION = timedelta(days=1)
MAX_MEMORY_BATCH = 1000

MutationCallback = Callable[[AsyncSession, TenantContext], Awaitable[dict[str, Any]]]
PersistenceCallback = Callable[[UUID], Awaitable[dict[str, Any]]]


class Topic2Service:
    def __init__(
        self,
        database: DatabaseSessionManager,
        repository: PostgresTopic2Repository,
        topic1_repository: PostgresTopic1Repository,
        outbox: PostgresOutboxRepository,
        *,
        instance_id: str,
    ) -> None:
        self._database = database
        self._repository = repository
        self._topic1_repository = topic1_repository
        self._outbox = outbox
        self._instance_id = instance_id

    async def list_behavior_events(
        self,
        learner_ref: str,
        course_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        received_after: datetime | None = None,
        received_after_event_id: UUID | None = None,
        limit: int = 1000,
    ) -> list[LearningBehaviorEventRecord]:
        context = current_tenant()
        self._assert_learner_access(context, learner_ref)
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.list_behavior_events(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
                since=since,
                until=until,
                received_after=received_after,
                received_after_event_id=received_after_event_id,
                limit=limit,
            )

    async def list_review_events(
        self,
        learner_ref: str,
        course_id: str,
        *,
        received_after: datetime | None = None,
        received_after_event_id: UUID | None = None,
        received_until: datetime | None = None,
        occurred_until: datetime | None = None,
        limit: int = 1000,
    ) -> list[LearningBehaviorEventRecord]:
        context = current_tenant()
        self._assert_learner_access(context, learner_ref)
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.list_review_events(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
                received_after=received_after,
                received_after_event_id=received_after_event_id,
                received_until=received_until,
                occurred_until=occurred_until,
                limit=limit,
            )

    async def latest_profile(
        self,
        learner_ref: str,
        course_id: str,
    ) -> StudentProfileRecord | None:
        context = current_tenant()
        self._assert_learner_access(context, learner_ref)
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.latest_profile(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
            )

    async def get_profile(self, profile_id: UUID) -> StudentProfileRecord:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            record = await self._repository.get_profile(session, context.tenant_id, profile_id)
        if record is None:
            raise self._not_found("student profile")
        self._assert_learner_access(context, record.draft.learner_ref)
        return record

    async def list_profile_versions(
        self,
        learner_ref: str,
        course_id: str,
        *,
        limit: int = 100,
    ) -> list[StudentProfileRecord]:
        context = current_tenant()
        self._assert_learner_access(context, learner_ref)
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.list_profile_versions(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
                limit=limit,
            )

    async def latest_memory_states(
        self,
        learner_ref: str,
        course_id: str,
        *,
        kp_ids: Sequence[str] | None = None,
    ) -> list[MemoryStateRecord]:
        context = current_tenant()
        self._assert_learner_access(context, learner_ref)
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.latest_memory_states(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
                kp_ids=kp_ids,
            )

    async def get_memory_states(
        self,
        memory_state_ids: Sequence[UUID],
    ) -> list[MemoryStateRecord]:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            records = await self._repository.get_memory_states(
                session,
                context.tenant_id,
                memory_state_ids,
            )
        for record in records:
            self._assert_learner_access(context, record.draft.learner_ref)
        return records

    async def due_memory_states(
        self,
        *,
        due_at: datetime,
        limit: int = 1000,
    ) -> list[MemoryStateRecord]:
        context = current_tenant()
        if "topic2:memory:batch" not in context.scopes:
            raise LiyanError(
                ErrorCode.AUTH_FORBIDDEN,
                "The authenticated identity cannot run tenant-wide memory jobs.",
                category=ErrorCategory.AUTH,
                status_code=403,
            )
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.due_memory_states(
                session,
                context.tenant_id,
                due_at=due_at,
                limit=limit,
            )

    async def latest_learning_path(
        self,
        learner_ref: str,
        course_id: str,
    ) -> LearningPathRecord | None:
        context = current_tenant()
        self._assert_learner_access(context, learner_ref)
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.latest_learning_path(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
            )

    async def get_learning_path(self, path_snapshot_id: UUID) -> LearningPathRecord:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            record = await self._repository.get_learning_path(
                session,
                context.tenant_id,
                path_snapshot_id,
            )
        if record is None:
            raise self._not_found("learning path")
        self._assert_learner_access(context, record.draft.learner_ref)
        return record

    async def list_learning_paths(
        self,
        learner_ref: str,
        course_id: str,
        *,
        limit: int = 100,
    ) -> list[LearningPathRecord]:
        context = current_tenant()
        self._assert_learner_access(context, learner_ref)
        async with self._database.transaction(context=current_session_context()) as session:
            return await self._repository.list_learning_paths(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
                limit=limit,
            )

    async def record_behavior_event(
        self,
        event: LearningBehaviorEventDraft,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if canonical_sha256(event.payload) != event.payload_sha256:
            raise self._contract_error("The behavior payload digest is invalid.")
        if event.event_type == BehaviorEventType.REVIEW_COMPLETED and (
            event.kp_id is None or (event.correctness is None and event.score is None)
        ):
            raise self._contract_error(
                "A completed review must identify a knowledge point and include score evidence."
            )

        async def callback(session: AsyncSession, context: TenantContext) -> dict[str, Any]:
            self._assert_learner_access(context, event.learner_ref)
            payload = {
                "schema_version": "topic2.behavior-recorded.v1",
                "event_id": str(event.event_id),
                "source_event_id": event.source_event_id,
                "learner_ref": event.learner_ref,
                "course_id": event.course_id,
                "kp_id": event.kp_id,
                "event_type": event.event_type.value,
                "occurred_at": event.occurred_at.isoformat(),
                "payload_sha256": event.payload_sha256,
            }

            async def persist(audit_event_id: UUID) -> dict[str, Any]:
                record = await self._repository.append_behavior_event(
                    session,
                    context.tenant_id,
                    event,
                    audit_event_id,
                )
                return {"event": self.behavior_record_document(record)}

            return await self._commit_change(
                session,
                context,
                action="BEHAVIOR_RECORDED",
                target_ref=str(event.event_id),
                metadata=payload,
                event_type="topic2.behavior.recorded",
                event_payload=payload,
                partition_key=self._partition_key(
                    context.tenant_id, event.learner_ref, event.course_id
                ),
                persist=persist,
            )

        return await self._execute_mutation(
            operation="topic2.behavior.record",
            idempotency_key=idempotency_key,
            request_document=self.behavior_idempotency_document(event),
            callback=callback,
        )

    async def initialize_learning_state(
        self,
        profile: StudentProfileDraft,
        states: Sequence[MemoryStateDraft],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._validate_profile_document(profile)
        if canonical_sha256(profile.profile_document) != profile.content_sha256:
            raise self._contract_error("The initial profile snapshot digest is invalid.")
        if len(states) > MAX_MEMORY_BATCH:
            raise LiyanError(
                ErrorCode.TOPIC2_BATCH_LIMIT,
                f"Initial memory state count cannot exceed {MAX_MEMORY_BATCH}.",
                category=ErrorCategory.CONTRACT,
                status_code=413,
            )
        if len({state.kp_id for state in states}) != len(states):
            raise self._contract_error("Initial memory states must use unique knowledge points.")
        if any(
            (state.learner_ref, state.course_id) != (profile.learner_ref, profile.course_id)
            for state in states
        ):
            raise self._contract_error(
                "Initial profile and memory states must target one learner and course."
            )
        for state in states:
            if canonical_sha256(self.memory_hash_document(state)) != state.content_sha256:
                raise self._contract_error("An initial memory-state digest is invalid.")

        try:
            graph_snapshot_id = UUID(str(profile.profile_document["topic1_graph_snapshot_id"]))
            graph_version = int(profile.profile_document["topic1_graph_version"])
            graph_sha256 = str(profile.profile_document["topic1_graph_sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise self._contract_error(
                "The initial profile must bind an accepted Topic 1 graph snapshot."
            ) from exc

        async def callback(session: AsyncSession, context: TenantContext) -> dict[str, Any]:
            self._assert_learner_access(context, profile.learner_ref)
            await self._lock_learner_course(
                session,
                context.tenant_id,
                profile.learner_ref,
                profile.course_id,
            )
            latest_profile = await self._repository.latest_profile(
                session,
                context.tenant_id,
                profile.learner_ref,
                profile.course_id,
            )
            self._validate_profile_version(profile, latest_profile)
            current_memory = await self._repository.latest_memory_states(
                session,
                context.tenant_id,
                profile.learner_ref,
                profile.course_id,
                kp_ids=[state.kp_id for state in states],
            )
            current_by_kp = {record.draft.kp_id: record for record in current_memory}
            for state in states:
                self._validate_memory_version(state, current_by_kp.get(state.kp_id))
            graph = await self._topic1_repository.get_snapshot(
                session,
                context.tenant_id,
                graph_snapshot_id,
            )
            if graph is None:
                raise self._not_found("Topic 1 graph snapshot")
            if (
                graph.course_id != profile.course_id
                or graph.graph_version != graph_version
                or graph.content_sha256 != graph_sha256
            ):
                raise self._contract_error(
                    "The initial profile references an inconsistent Topic 1 graph snapshot."
                )
            payload = {
                "schema_version": "topic2.learner-initialized.v1",
                "profile_id": str(profile.profile_id),
                "learner_ref": profile.learner_ref,
                "course_id": profile.course_id,
                "topic1_graph_snapshot_id": str(graph_snapshot_id),
                "topic1_graph_version": graph_version,
                "memory_state_count": len(states),
                "profile_content_sha256": profile.content_sha256,
            }

            async def persist(audit_event_id: UUID) -> dict[str, Any]:
                profile_record = await self._repository.append_profile(
                    session,
                    context.tenant_id,
                    profile,
                    audit_event_id,
                    context.subject_ref,
                )
                memory_records = await self._repository.append_memory_states(
                    session,
                    context.tenant_id,
                    states,
                    audit_event_id,
                )
                return {
                    "profile": self.profile_record_document(profile_record),
                    "memory_states": [
                        self.memory_record_document(record)
                        for record in sorted(memory_records, key=lambda item: item.draft.kp_id)
                    ],
                }

            return await self._commit_change(
                session,
                context,
                action="LEARNER_STATE_INITIALIZED",
                target_ref=f"{profile.learner_ref}:{profile.course_id}",
                metadata=payload,
                event_type="topic2.learner.initialized",
                event_payload=payload,
                partition_key=self._partition_key(
                    context.tenant_id,
                    profile.learner_ref,
                    profile.course_id,
                ),
                persist=persist,
            )

        return await self._execute_mutation(
            operation="topic2.learner.initialize",
            idempotency_key=idempotency_key,
            request_document={
                "profile": self.profile_draft_document(profile),
                "memory_states": [
                    self.memory_draft_document(state)
                    for state in sorted(states, key=lambda item: item.kp_id)
                ],
            },
            callback=callback,
        )

    async def save_profile(
        self,
        profile: StudentProfileDraft,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._validate_profile_document(profile)
        if canonical_sha256(profile.profile_document) != profile.content_sha256:
            raise self._contract_error("The profile snapshot digest is invalid.")

        async def callback(session: AsyncSession, context: TenantContext) -> dict[str, Any]:
            self._assert_learner_access(context, profile.learner_ref)
            await self._lock_learner_course(
                session,
                context.tenant_id,
                profile.learner_ref,
                profile.course_id,
            )
            latest = await self._repository.latest_profile(
                session,
                context.tenant_id,
                profile.learner_ref,
                profile.course_id,
            )
            self._validate_profile_version(profile, latest)
            payload = {
                "schema_version": "topic2.profile-updated.v1",
                "profile_id": str(profile.profile_id),
                "profile_version": profile.profile_version,
                "parent_profile_id": (
                    None if profile.parent_profile_id is None else str(profile.parent_profile_id)
                ),
                "learner_ref": profile.learner_ref,
                "course_id": profile.course_id,
                "policy_version": profile.policy_version,
                "content_sha256": profile.content_sha256,
                "frozen_at": profile.frozen_at.isoformat(),
            }

            async def persist(audit_event_id: UUID) -> dict[str, Any]:
                record = await self._repository.append_profile(
                    session,
                    context.tenant_id,
                    profile,
                    audit_event_id,
                    context.subject_ref,
                )
                return {"profile": self.profile_record_document(record)}

            return await self._commit_change(
                session,
                context,
                action="PROFILE_SNAPSHOT_APPENDED",
                target_ref=str(profile.profile_id),
                metadata=payload,
                event_type="topic2.profile.updated",
                event_payload=payload,
                partition_key=self._partition_key(
                    context.tenant_id,
                    profile.learner_ref,
                    profile.course_id,
                ),
                persist=persist,
            )

        return await self._execute_mutation(
            operation="topic2.profile.save",
            idempotency_key=idempotency_key,
            request_document=self.profile_draft_document(profile),
            callback=callback,
        )

    async def restore_profile(
        self,
        profile_id: UUID,
        *,
        operation_id: UUID,
        restored_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        target = await self.get_profile(profile_id)
        latest = await self.latest_profile(target.draft.learner_ref, target.draft.course_id)
        if latest is None:
            raise self._not_found("current student profile")
        restored_profile_id = uuid5(operation_id, "profile-restore")
        document = deepcopy(target.draft.profile_document)
        document.update(
            {
                "profile_id": str(restored_profile_id),
                "profile_version": latest.draft.profile_version + 1,
                "parent_profile_id": str(latest.draft.profile_id),
                "restored_from_profile_id": str(target.draft.profile_id),
                "operation_id": str(operation_id),
                "policy_version": "topic2.profile-restore.v1",
                "generated_at": restored_at.isoformat(),
            }
        )
        features = tuple(
            replace(
                feature,
                feature_id=uuid5(
                    operation_id,
                    f"restore-feature:{feature.dimension.value}:{feature.feature_key}",
                ),
                computed_at=restored_at,
            )
            for feature in target.draft.features
        )
        restored = replace(
            target.draft,
            profile_id=restored_profile_id,
            profile_version=latest.draft.profile_version + 1,
            parent_profile_id=latest.draft.profile_id,
            policy_version="topic2.profile-restore.v1",
            profile_document=document,
            content_sha256=canonical_sha256(document),
            frozen_at=restored_at,
            features=features,
        )
        return await self.save_profile(restored, idempotency_key=idempotency_key)

    async def save_memory_states(
        self,
        states: Sequence[MemoryStateDraft],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not states or len(states) > MAX_MEMORY_BATCH:
            raise LiyanError(
                ErrorCode.TOPIC2_BATCH_LIMIT,
                f"Memory updates must contain between one and {MAX_MEMORY_BATCH} states.",
                category=ErrorCategory.CONTRACT,
                status_code=413,
            )
        learner_courses = {(state.learner_ref, state.course_id) for state in states}
        if len(learner_courses) != 1 or len({state.kp_id for state in states}) != len(states):
            raise self._contract_error(
                "A memory batch must target one learner/course and contain unique knowledge points."
            )
        for state in states:
            if canonical_sha256(self.memory_hash_document(state)) != state.content_sha256:
                raise self._contract_error("A memory-state digest is invalid.")
        learner_ref, course_id = next(iter(learner_courses))

        async def callback(session: AsyncSession, context: TenantContext) -> dict[str, Any]:
            self._assert_learner_access(context, learner_ref)
            await self._lock_learner_course(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
            )
            current = await self._repository.latest_memory_states(
                session,
                context.tenant_id,
                learner_ref,
                course_id,
                kp_ids=[state.kp_id for state in states],
            )
            current_by_kp = {record.draft.kp_id: record for record in current}
            for state in states:
                self._validate_memory_version(state, current_by_kp.get(state.kp_id))
            payload = {
                "schema_version": "topic2.memory-updated.v1",
                "learner_ref": learner_ref,
                "course_id": course_id,
                "state_count": len(states),
                "states": [
                    {
                        "memory_state_id": str(state.memory_state_id),
                        "kp_id": state.kp_id,
                        "state_version": state.state_version,
                        "retrievability": state.retrievability,
                        "risk_level": state.risk_level.value,
                        "content_sha256": state.content_sha256,
                    }
                    for state in sorted(states, key=lambda item: item.kp_id)
                ],
            }

            async def persist(audit_event_id: UUID) -> dict[str, Any]:
                records = await self._repository.append_memory_states(
                    session,
                    context.tenant_id,
                    states,
                    audit_event_id,
                )
                return {
                    "memory_states": [
                        self.memory_record_document(record)
                        for record in sorted(records, key=lambda item: item.draft.kp_id)
                    ]
                }

            return await self._commit_change(
                session,
                context,
                action="MEMORY_STATES_APPENDED",
                target_ref=f"{learner_ref}:{course_id}",
                metadata=payload,
                event_type="topic2.memory.updated",
                event_payload=payload,
                partition_key=self._partition_key(context.tenant_id, learner_ref, course_id),
                persist=persist,
            )

        return await self._execute_mutation(
            operation="topic2.memory.save",
            idempotency_key=idempotency_key,
            request_document={
                "states": [
                    self.memory_draft_document(state)
                    for state in sorted(states, key=lambda item: item.kp_id)
                ]
            },
            callback=callback,
        )

    async def save_learning_path(
        self,
        snapshot: LearningPathSnapshotDraft,
        change: PathChangeDraft,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if snapshot.path_snapshot_id != change.to_path_snapshot_id:
            raise self._contract_error("The path change target does not match the snapshot.")
        if snapshot.parent_path_snapshot_id != change.from_path_snapshot_id:
            raise self._contract_error("The path change source does not match the parent snapshot.")
        if (snapshot.learner_ref, snapshot.course_id) != (change.learner_ref, change.course_id):
            raise self._contract_error("The path snapshot and change identity do not match.")
        if canonical_sha256(self.path_hash_document(snapshot)) != snapshot.content_sha256:
            raise self._contract_error("The learning-path snapshot digest is invalid.")

        async def callback(session: AsyncSession, context: TenantContext) -> dict[str, Any]:
            self._assert_learner_access(context, snapshot.learner_ref)
            await self._lock_learner_course(
                session,
                context.tenant_id,
                snapshot.learner_ref,
                snapshot.course_id,
            )
            profile = await self._repository.get_profile(
                session,
                context.tenant_id,
                snapshot.profile_id,
            )
            if profile is None:
                raise self._not_found("path profile snapshot")
            if (profile.draft.learner_ref, profile.draft.course_id) != (
                snapshot.learner_ref,
                snapshot.course_id,
            ):
                raise self._contract_error("The path profile belongs to another learner or course.")
            graph = await self._topic1_repository.get_snapshot(
                session,
                context.tenant_id,
                snapshot.topic1_graph_snapshot_id,
            )
            if graph is None:
                raise self._not_found("Topic 1 graph snapshot")
            if (
                graph.course_id != snapshot.course_id
                or graph.graph_version != snapshot.topic1_graph_version
            ):
                raise self._contract_error(
                    "The path references an inconsistent Topic 1 graph version."
                )
            latest = await self._repository.latest_learning_path(
                session,
                context.tenant_id,
                snapshot.learner_ref,
                snapshot.course_id,
            )
            self._validate_path_version(snapshot, latest)
            payload = {
                "schema_version": "topic2.path-updated.v1",
                "path_snapshot_id": str(snapshot.path_snapshot_id),
                "path_version": snapshot.path_version,
                "parent_path_snapshot_id": (
                    None
                    if snapshot.parent_path_snapshot_id is None
                    else str(snapshot.parent_path_snapshot_id)
                ),
                "learner_ref": snapshot.learner_ref,
                "course_id": snapshot.course_id,
                "profile_id": str(snapshot.profile_id),
                "topic1_graph_snapshot_id": str(snapshot.topic1_graph_snapshot_id),
                "topic1_graph_version": snapshot.topic1_graph_version,
                "plan_type": snapshot.plan_type.value,
                "content_sha256": snapshot.content_sha256,
            }

            async def persist(audit_event_id: UUID) -> dict[str, Any]:
                record = await self._repository.append_learning_path(
                    session,
                    context.tenant_id,
                    snapshot,
                    change,
                    audit_event_id,
                    context.subject_ref,
                )
                return {"learning_path": self.path_record_document(record)}

            return await self._commit_change(
                session,
                context,
                action="LEARNING_PATH_APPENDED",
                target_ref=str(snapshot.path_snapshot_id),
                metadata=payload,
                event_type="topic2.path.updated",
                event_payload=payload,
                partition_key=self._partition_key(
                    context.tenant_id,
                    snapshot.learner_ref,
                    snapshot.course_id,
                ),
                persist=persist,
            )

        return await self._execute_mutation(
            operation="topic2.path.save",
            idempotency_key=idempotency_key,
            request_document={
                "snapshot": self.path_draft_document(snapshot),
                "change": self.path_change_document(change),
            },
            callback=callback,
        )

    async def _execute_mutation(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_document: dict[str, Any],
        callback: MutationCallback,
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
            result = await callback(session, context)
            await self._complete_idempotency(session, context, idempotency_key, result)
            return result

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
                    "The Topic 2 mutation conflicts with an existing version."
                ) from exc
            if sqlstate == "23503":
                raise self._contract_error(
                    "The Topic 2 mutation references a missing or mismatched frozen resource."
                ) from exc
            raise self._contract_error(
                "The Topic 2 mutation violates a persistence constraint."
            ) from exc

    async def _commit_change(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        action: str,
        target_ref: str,
        metadata: dict[str, Any],
        event_type: str,
        event_payload: dict[str, Any],
        partition_key: str,
        persist: PersistenceCallback,
    ) -> dict[str, Any]:
        audit = await self._append_audit(
            session,
            context,
            action=action,
            target_ref=target_ref,
            metadata=metadata,
        )
        result = await persist(audit.event_id)
        await self._append_outbox(
            session,
            context,
            event_type=event_type,
            payload=event_payload,
            partition_key=partition_key,
        )
        return result

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
                "The idempotency key was reused for different Topic 2 content.",
            )
        if record.state == IdempotencyStatus.COMPLETED.value:
            if not isinstance(record.result_payload, dict):
                raise self._conflict("The completed idempotency result is unavailable.")
            return dict(record.result_payload)
        if record.lease_expires_at is not None and record.lease_expires_at > now:
            raise self._conflict("The idempotent Topic 2 operation is already in progress.")
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
        *,
        action: str,
        target_ref: str,
        metadata: dict[str, Any],
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
            category="TOPIC2",
            action=action,
            outcome="SUCCEEDED",
            actor_ref=context.subject_ref,
            target_ref=target_ref,
            trace_id=context.trace_id,
            envelope_id=None,
            metadata=metadata,
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
        *,
        event_type: str,
        payload: dict[str, Any],
        partition_key: str,
    ) -> None:
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
            event_type=event_type,
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
                service="topic2-adaptive-learning-service",
                instance_id=self._instance_id,
                build_version="topic2-v1",
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=f"topic2:{canonical_sha256(payload)}",
                available_at=now,
                expires_at=now + OUTBOX_RETENTION,
            ),
            resource=None,
            trace_id=context.trace_id,
            span_id=None,
            created_at=now,
            error=None,
            payload=payload,
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

    @staticmethod
    async def _lock_learner_course(
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
    ) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"topic2:{tenant_id}:{learner_ref}:{course_id}"},
        )

    @staticmethod
    def _validate_profile_version(
        profile: StudentProfileDraft,
        latest: StudentProfileRecord | None,
    ) -> None:
        if latest is None:
            valid = profile.profile_version == 1 and profile.parent_profile_id is None
        else:
            valid = (
                profile.profile_version == latest.draft.profile_version + 1
                and profile.parent_profile_id == latest.draft.profile_id
            )
        if not valid:
            raise Topic2Service._version_conflict("The profile parent/version is stale.")

    @staticmethod
    def _validate_profile_document(profile: StudentProfileDraft) -> None:
        document = profile.profile_document
        expected_identity = {
            "schema_version": "topic2.student-profile.v1",
            "profile_id": str(profile.profile_id),
            "profile_version": profile.profile_version,
            "learner_ref": profile.learner_ref,
            "course_id": profile.course_id,
            "policy_version": profile.policy_version,
        }
        if any(document.get(key) != value for key, value in expected_identity.items()):
            raise Topic2Service._contract_error(
                "The profile document identity does not match its persistence fields."
            )
        expected_dimensions = {
            "knowledge_mastery": profile.knowledge_mastery,
            "problem_solving_proficiency": profile.problem_solving_proficiency,
            "misconception_preference": profile.misconception_preference,
            "learning_pace": profile.learning_pace,
            "forgetting_rate": profile.forgetting_rate,
            "learning_goal_tendency": profile.learning_goal_tendency,
        }
        if document.get("dimensions") != expected_dimensions:
            raise Topic2Service._contract_error(
                "The profile document dimensions do not match the indexed aggregate."
            )
        aggregate_dimensions = {
            feature.dimension for feature in profile.features if feature.feature_key == "aggregate"
        }
        expected_feature_dimensions = {feature.dimension for feature in profile.features}
        if aggregate_dimensions != expected_feature_dimensions:
            raise Topic2Service._contract_error(
                "Every profile dimension must expose one aggregate feature."
            )

    @staticmethod
    def _validate_memory_version(
        state: MemoryStateDraft,
        latest: MemoryStateRecord | None,
    ) -> None:
        if latest is None:
            valid = state.state_version == 1 and state.parent_memory_state_id is None
        else:
            valid = (
                state.state_version == latest.draft.state_version + 1
                and state.parent_memory_state_id == latest.draft.memory_state_id
            )
        if not valid:
            raise Topic2Service._version_conflict(
                f"The memory parent/version for {state.kp_id} is stale."
            )

    @staticmethod
    def _validate_path_version(
        snapshot: LearningPathSnapshotDraft,
        latest: LearningPathRecord | None,
    ) -> None:
        if latest is None:
            valid = snapshot.path_version == 1 and snapshot.parent_path_snapshot_id is None
        else:
            valid = (
                snapshot.path_version == latest.draft.path_version + 1
                and snapshot.parent_path_snapshot_id == latest.draft.path_snapshot_id
            )
        if not valid:
            raise Topic2Service._version_conflict("The learning-path parent/version is stale.")

    @staticmethod
    def _assert_learner_access(context: TenantContext, learner_ref: str) -> None:
        privileged = bool(
            {"topic2:learner:any", "topic2:admin", "topic2:memory:batch"} & context.scopes
        )
        if learner_ref != context.subject_ref and not privileged:
            raise LiyanError(
                ErrorCode.AUTH_FORBIDDEN,
                "The authenticated identity cannot access another learner.",
                category=ErrorCategory.AUTH,
                status_code=403,
            )

    @staticmethod
    def _partition_key(tenant_id: str, learner_ref: str, course_id: str) -> str:
        learner_digest = canonical_sha256({"learner_ref": learner_ref})[:24]
        return f"topic2:{tenant_id}:{course_id}:{learner_digest}"

    @staticmethod
    def _validate_idempotency_key(value: str) -> None:
        if not 16 <= len(value) <= 160:
            raise Topic2Service._contract_error(
                "The idempotency key must contain between 16 and 160 characters."
            )

    @staticmethod
    def _not_found(resource: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC2_NOT_FOUND,
            f"The requested Topic 2 {resource} does not exist.",
            category=ErrorCategory.CONTRACT,
            status_code=404,
        )

    @staticmethod
    def _conflict(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC2_CONFLICT,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )

    @staticmethod
    def _version_conflict(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC2_VERSION_CONFLICT,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=409,
        )

    @staticmethod
    def _contract_error(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.CONTRACT_INVALID,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )

    @staticmethod
    def behavior_draft_document(event: LearningBehaviorEventDraft) -> dict[str, Any]:
        return {
            "schema_version": "topic2.learning-behavior-event.v1",
            "event_id": str(event.event_id),
            "source_event_id": event.source_event_id,
            "event_version": event.event_version,
            "learner_ref": event.learner_ref,
            "course_id": event.course_id,
            "kp_id": event.kp_id,
            "session_id": None if event.session_id is None else str(event.session_id),
            "event_type": event.event_type.value,
            "source_type": event.source_type.value,
            "duration_seconds": event.duration_seconds,
            "response_latency_ms": event.response_latency_ms,
            "correctness": event.correctness,
            "score": event.score,
            "attempt_count": event.attempt_count,
            "interaction_count": event.interaction_count,
            "attention_ratio": event.attention_ratio,
            "misconception_ids": list(event.misconception_ids),
            "goal_tags": list(event.goal_tags),
            "payload": event.payload,
            "payload_sha256": event.payload_sha256,
            "occurred_at": event.occurred_at.isoformat(),
            "received_at": event.received_at.isoformat(),
        }

    @classmethod
    def behavior_idempotency_document(
        cls,
        event: LearningBehaviorEventDraft,
    ) -> dict[str, Any]:
        document = cls.behavior_draft_document(event)
        document.pop("received_at")
        return document

    @classmethod
    def behavior_record_document(cls, record: LearningBehaviorEventRecord) -> dict[str, Any]:
        return {
            **cls.behavior_draft_document(record.draft),
            "audit_event_id": str(record.audit_event_id),
            "created_at": record.created_at.isoformat(),
        }

    @staticmethod
    def feature_document(feature: ProfileFeatureDraft) -> dict[str, Any]:
        return {
            "feature_id": str(feature.feature_id),
            "dimension": feature.dimension.value,
            "feature_key": feature.feature_key,
            "value_document": feature.value_document,
            "normalized_score": feature.normalized_score,
            "confidence": feature.confidence,
            "evidence_count": feature.evidence_count,
            "source_event_ids": list(feature.source_event_ids),
            "computed_at": feature.computed_at.isoformat(),
        }

    @classmethod
    def profile_draft_document(cls, profile: StudentProfileDraft) -> dict[str, Any]:
        return {
            "profile_id": str(profile.profile_id),
            "learner_ref": profile.learner_ref,
            "course_id": profile.course_id,
            "profile_version": profile.profile_version,
            "parent_profile_id": (
                None if profile.parent_profile_id is None else str(profile.parent_profile_id)
            ),
            "policy_version": profile.policy_version,
            "knowledge_mastery": profile.knowledge_mastery,
            "problem_solving_proficiency": profile.problem_solving_proficiency,
            "misconception_preference": profile.misconception_preference,
            "learning_pace": profile.learning_pace,
            "forgetting_rate": profile.forgetting_rate,
            "learning_goal_tendency": profile.learning_goal_tendency,
            "confidence_score": profile.confidence_score,
            "activity_count": profile.activity_count,
            "last_event_at": (
                None if profile.last_event_at is None else profile.last_event_at.isoformat()
            ),
            "source_window_start": (
                None
                if profile.source_window_start is None
                else profile.source_window_start.isoformat()
            ),
            "source_window_end": (
                None if profile.source_window_end is None else profile.source_window_end.isoformat()
            ),
            "profile_document": profile.profile_document,
            "content_sha256": profile.content_sha256,
            "frozen_at": profile.frozen_at.isoformat(),
            "features": [
                cls.feature_document(feature)
                for feature in sorted(
                    profile.features,
                    key=lambda item: (item.dimension.value, item.feature_key),
                )
            ],
        }

    @classmethod
    def profile_record_document(cls, record: StudentProfileRecord) -> dict[str, Any]:
        return {
            **cls.profile_draft_document(record.draft),
            "audit_event_id": str(record.audit_event_id),
            "created_by_subject": record.created_by_subject,
            "created_at": record.created_at.isoformat(),
        }

    @staticmethod
    def memory_hash_document(state: MemoryStateDraft) -> dict[str, Any]:
        return {
            "schema_version": "topic2.memory-state.v1",
            "memory_state_id": str(state.memory_state_id),
            "learner_ref": state.learner_ref,
            "course_id": state.course_id,
            "kp_id": state.kp_id,
            "state_version": state.state_version,
            "parent_memory_state_id": (
                None if state.parent_memory_state_id is None else str(state.parent_memory_state_id)
            ),
            "model_version": state.model_version,
            "stability_days": state.stability_days,
            "effective_stability_days": state.effective_stability_days,
            "elapsed_days": state.elapsed_days,
            "retrievability": state.retrievability,
            "forgetting_rate": state.forgetting_rate,
            "difficulty_factor": state.difficulty_factor,
            "review_gain": state.review_gain,
            "review_count": state.review_count,
            "lapse_count": state.lapse_count,
            "last_reviewed_at": (
                None if state.last_reviewed_at is None else state.last_reviewed_at.isoformat()
            ),
            "last_activity_at": state.last_activity_at.isoformat(),
            "next_review_at": state.next_review_at.isoformat(),
            "risk_level": state.risk_level.value,
            "model_parameters": state.model_parameters,
            "computed_at": state.computed_at.isoformat(),
        }

    @classmethod
    def memory_draft_document(cls, state: MemoryStateDraft) -> dict[str, Any]:
        return {**cls.memory_hash_document(state), "content_sha256": state.content_sha256}

    @classmethod
    def memory_record_document(cls, record: MemoryStateRecord) -> dict[str, Any]:
        return {
            **cls.memory_draft_document(record.draft),
            "audit_event_id": str(record.audit_event_id),
            "created_at": record.created_at.isoformat(),
        }

    @staticmethod
    def path_hash_document(snapshot: LearningPathSnapshotDraft) -> dict[str, Any]:
        return {
            "schema_version": "topic2.learning-path-snapshot.v1",
            "path_snapshot_id": str(snapshot.path_snapshot_id),
            "learner_ref": snapshot.learner_ref,
            "course_id": snapshot.course_id,
            "path_version": snapshot.path_version,
            "parent_path_snapshot_id": (
                None
                if snapshot.parent_path_snapshot_id is None
                else str(snapshot.parent_path_snapshot_id)
            ),
            "topic1_graph_snapshot_id": str(snapshot.topic1_graph_snapshot_id),
            "topic1_graph_version": snapshot.topic1_graph_version,
            "profile_id": str(snapshot.profile_id),
            "plan_type": snapshot.plan_type.value,
            "trigger_reason": snapshot.trigger_reason,
            "target_goal": snapshot.target_goal,
            "policy_version": snapshot.policy_version,
            "path_document": snapshot.path_document,
            "decision_document": snapshot.decision_document,
            "node_count": snapshot.node_count,
            "estimated_minutes": snapshot.estimated_minutes,
            "manual_override": snapshot.manual_override,
            "frozen_at": snapshot.frozen_at.isoformat(),
        }

    @classmethod
    def path_draft_document(cls, snapshot: LearningPathSnapshotDraft) -> dict[str, Any]:
        return {**cls.path_hash_document(snapshot), "content_sha256": snapshot.content_sha256}

    @staticmethod
    def path_change_document(change: PathChangeDraft) -> dict[str, Any]:
        return {
            "schema_version": "topic2.path-change.v1",
            "change_id": str(change.change_id),
            "learner_ref": change.learner_ref,
            "course_id": change.course_id,
            "from_path_snapshot_id": (
                None if change.from_path_snapshot_id is None else str(change.from_path_snapshot_id)
            ),
            "to_path_snapshot_id": str(change.to_path_snapshot_id),
            "change_type": change.change_type.value,
            "reason": change.reason,
            "policy_version": change.policy_version,
            "change_document": change.change_document,
            "occurred_at": change.occurred_at.isoformat(),
        }

    @classmethod
    def path_record_document(cls, record: LearningPathRecord) -> dict[str, Any]:
        return {
            "snapshot": cls.path_draft_document(record.draft),
            "change": cls.path_change_document(record.change),
            "audit_event_id": str(record.audit_event_id),
            "created_by_subject": record.created_by_subject,
            "created_at": record.created_at.isoformat(),
        }
