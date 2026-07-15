from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import (
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1KnowledgePointV1,
)

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import current_tenant
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.session import DatabaseSessionManager

from .entities import (
    LearningBehaviorEventDraft,
    LearningBehaviorEventRecord,
    LearningPathSnapshotDraft,
    MemoryStateDraft,
    MemoryStateRecord,
    PathChangeDraft,
    PathChangeType,
    StudentProfileDraft,
)
from .memory import EbbinghausMemoryEngine
from .path_planning import AdaptivePathPlanner
from .profiling import SixDimensionProfileEngine
from .seed import blank_profile_seed_to_drafts, build_blank_profile_seed
from .service import Topic2Service

MAX_REVIEW_EVENTS_PER_REFRESH = 5000


class Topic2Orchestrator:
    def __init__(
        self,
        database: DatabaseSessionManager,
        topic1_repository: PostgresTopic1Repository,
        persistence: Topic2Service,
        profile_engine: SixDimensionProfileEngine,
        memory_engine: EbbinghausMemoryEngine,
        path_planner: AdaptivePathPlanner,
    ) -> None:
        self._database = database
        self._topic1_repository = topic1_repository
        self._persistence = persistence
        self._profile_engine = profile_engine
        self._memory_engine = memory_engine
        self._path_planner = path_planner

    async def record_behavior(
        self,
        event: LearningBehaviorEventDraft,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._persistence.record_behavior_event(
            event,
            idempotency_key=idempotency_key,
        )

    async def initialize_learner(
        self,
        *,
        learner_ref: str,
        course_id: str,
        operation_id: UUID,
        requested_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        graph, graph_snapshot = await self._load_topic1(course_id)
        active_points = sorted(
            (item for item in graph.knowledge_points if item.status.value == "ACTIVE"),
            key=lambda item: item.kp_id,
        )
        profile_id = uuid5(operation_id, "seed-profile")
        state_ids = [uuid5(operation_id, f"seed-memory:{item.kp_id}") for item in active_points]
        replay = await self._initialization_replay(profile_id, state_ids, operation_id)
        if replay is not None:
            return replay
        latest = await self._persistence.latest_profile(learner_ref, course_id)
        if latest is not None:
            raise self._conflict("The learner already has a Topic 2 profile for this course.")
        seed = build_blank_profile_seed(
            learner_ref=learner_ref,
            course_id=course_id,
            knowledge_points=active_points,
            generated_at=requested_at,
            operation_id=operation_id,
            topic1_graph_snapshot_id=graph_snapshot.snapshot_id,
            topic1_graph_version=graph_snapshot.graph_version,
            topic1_graph_sha256=graph_snapshot.content_sha256,
        )
        profile, memory_states = blank_profile_seed_to_drafts(seed)
        return await self._persistence.initialize_learning_state(
            profile,
            memory_states,
            idempotency_key=idempotency_key,
        )

    async def restore_profile(
        self,
        *,
        profile_id: UUID,
        operation_id: UUID,
        requested_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        stable_profile_id = uuid5(operation_id, "profile-restore")
        replay = await self._profile_restore_replay(
            stable_profile_id,
            source_profile_id=profile_id,
            operation_id=operation_id,
        )
        if replay is not None:
            return replay
        return await self._persistence.restore_profile(
            profile_id,
            operation_id=operation_id,
            restored_at=requested_at,
            idempotency_key=idempotency_key,
        )

    async def rebuild_profile(
        self,
        *,
        learner_ref: str,
        course_id: str,
        operation_id: UUID,
        requested_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        stable_profile_id = uuid5(operation_id, "profile")
        existing = await self._profile_replay(stable_profile_id, operation_id)
        if existing is not None:
            return existing
        previous = await self._persistence.latest_profile(learner_ref, course_id)
        cursor_at, cursor_event_id = self._profile_cursor(previous)
        events = await self._persistence.list_behavior_events(
            learner_ref,
            course_id,
            received_after=cursor_at,
            received_after_event_id=cursor_event_id,
            limit=5000,
        )
        graph, graph_snapshot = await self._load_topic1(course_id)
        draft = self._profile_engine.build_profile(
            learner_ref=learner_ref,
            course_id=course_id,
            events=events,
            knowledge_points={item.kp_id: item for item in graph.knowledge_points},
            misconceptions={item.misconception_id: item for item in graph.misconceptions},
            generated_at=requested_at,
            previous=previous,
        )
        draft = self._stabilize_profile(
            draft,
            operation_id=operation_id,
            graph_snapshot=graph_snapshot,
        )
        return await self._persistence.save_profile(draft, idempotency_key=idempotency_key)

    async def refresh_memory(
        self,
        *,
        learner_ref: str,
        course_id: str,
        operation_id: UUID,
        requested_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        graph, _graph_snapshot = await self._load_topic1(course_id)
        active_points = sorted(
            (item for item in graph.knowledge_points if item.status.value == "ACTIVE"),
            key=lambda item: item.kp_id,
        )
        return await self._refresh_memory_points(
            learner_ref=learner_ref,
            course_id=course_id,
            knowledge_points=active_points,
            operation_id=operation_id,
            requested_at=requested_at,
            idempotency_key=idempotency_key,
        )

    async def refresh_due_memory(
        self,
        *,
        operation_id: UUID,
        requested_at: datetime,
        idempotency_key: str,
        limit: int,
    ) -> dict[str, Any]:
        due = await self._persistence.due_memory_states(due_at=requested_at, limit=limit)
        grouped: dict[tuple[str, str], list[MemoryStateRecord]] = defaultdict(list)
        for record in due:
            grouped[(record.draft.learner_ref, record.draft.course_id)].append(record)

        refreshed_groups: list[dict[str, Any]] = []
        refreshed_state_count = 0
        for (learner_ref, course_id), records in sorted(grouped.items()):
            graph, _graph_snapshot = await self._load_topic1(course_id)
            due_kp_ids = {record.draft.kp_id for record in records}
            points = sorted(
                (
                    item
                    for item in graph.knowledge_points
                    if item.status.value == "ACTIVE" and item.kp_id in due_kp_ids
                ),
                key=lambda item: item.kp_id,
            )
            if not points:
                continue
            partition_digest = canonical_sha256(
                {
                    "learner_ref": learner_ref,
                    "course_id": course_id,
                    "kp_ids": [item.kp_id for item in points],
                }
            )
            group_operation_id = uuid5(operation_id, f"due-memory:{partition_digest}")
            group_idempotency_key = self._child_idempotency_key(
                idempotency_key,
                group_operation_id,
            )
            result = await self._refresh_memory_points(
                learner_ref=learner_ref,
                course_id=course_id,
                knowledge_points=points,
                operation_id=group_operation_id,
                requested_at=requested_at,
                idempotency_key=group_idempotency_key,
            )
            state_count = len(result.get("memory_states", []))
            refreshed_state_count += state_count
            refreshed_groups.append(
                {
                    "learner_ref": learner_ref,
                    "course_id": course_id,
                    "state_count": state_count,
                    "operation_id": str(group_operation_id),
                }
            )
        return {
            "schema_version": "topic2.memory-batch-refresh.v1",
            "operation_id": str(operation_id),
            "requested_at": requested_at.isoformat(),
            "selected_state_count": len(due),
            "refreshed_state_count": refreshed_state_count,
            "group_count": len(refreshed_groups),
            "groups": refreshed_groups,
        }

    async def _refresh_memory_points(
        self,
        *,
        learner_ref: str,
        course_id: str,
        knowledge_points: Sequence[Topic1KnowledgePointV1],
        operation_id: UUID,
        requested_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not knowledge_points:
            return {"memory_states": []}
        stable_ids = [uuid5(operation_id, f"memory:{item.kp_id}") for item in knowledge_points]
        replay = await self._memory_replay(stable_ids, operation_id)
        if replay is not None:
            return replay
        profile = await self._persistence.latest_profile(learner_ref, course_id)
        if profile is None:
            raise self._not_found("student profile")
        kp_ids = [item.kp_id for item in knowledge_points]
        current = await self._persistence.latest_memory_states(
            learner_ref,
            course_id,
            kp_ids=kp_ids,
        )
        current_by_kp = {record.draft.kp_id: record for record in current}
        review_events = await self._pending_review_events(
            learner_ref=learner_ref,
            course_id=course_id,
            current=current,
            expected_point_count=len(knowledge_points),
            requested_at=requested_at,
        )
        reviews_by_kp: dict[str, list[LearningBehaviorEventRecord]] = defaultdict(list)
        for event in review_events:
            if event.draft.kp_id is not None:
                reviews_by_kp[event.draft.kp_id].append(event)
        states: list[MemoryStateDraft] = []
        for point in knowledge_points:
            record = current_by_kp.get(point.kp_id)
            point_reviews = self._reviews_after_state_cursor(record, reviews_by_kp[point.kp_id])
            state = self._reconcile_memory_state(
                learner_ref=learner_ref,
                knowledge_point=point,
                current=record,
                review_events=point_reviews,
                forgetting_rate=profile.draft.forgetting_rate,
                requested_at=requested_at,
            )
            previous_cursor = self._memory_review_cursor(record)
            final_cursor = (
                previous_cursor
                if not point_reviews
                else (
                    point_reviews[-1].draft.received_at,
                    point_reviews[-1].draft.event_id,
                )
            )
            parameters = {
                **state.model_parameters,
                "operation_id": str(operation_id),
                "review_events_applied": len(point_reviews),
            }
            if final_cursor is not None:
                parameters["review_ingestion_cursor"] = {
                    "received_at": final_cursor[0].isoformat(),
                    "event_id": str(final_cursor[1]),
                }
            state_version = 1 if record is None else record.draft.state_version + 1
            parent_state_id = None if record is None else record.draft.memory_state_id
            state = replace(
                state,
                memory_state_id=uuid5(operation_id, f"memory:{point.kp_id}"),
                state_version=state_version,
                parent_memory_state_id=parent_state_id,
                model_parameters=parameters,
                content_sha256="0" * 64,
            )
            state = replace(
                state,
                content_sha256=canonical_sha256(self._memory_engine.hash_document(state)),
            )
            states.append(state)
        return await self._persistence.save_memory_states(
            states,
            idempotency_key=idempotency_key,
        )

    async def _pending_review_events(
        self,
        *,
        learner_ref: str,
        course_id: str,
        current: Sequence[MemoryStateRecord],
        expected_point_count: int,
        requested_at: datetime,
    ) -> list[LearningBehaviorEventRecord]:
        received_after: datetime | None = None
        received_after_event_id: UUID | None = None
        if len(current) == expected_point_count:
            cursors = [
                self._memory_review_cursor(record) or (record.draft.computed_at, UUID(int=0))
                for record in current
            ]
            if cursors:
                received_after, received_after_event_id = min(cursors)
        events = await self._persistence.list_review_events(
            learner_ref,
            course_id,
            received_after=received_after,
            received_after_event_id=received_after_event_id,
            received_until=requested_at,
            occurred_until=requested_at,
            limit=MAX_REVIEW_EVENTS_PER_REFRESH + 1,
        )
        if len(events) > MAX_REVIEW_EVENTS_PER_REFRESH:
            raise LiyanError(
                ErrorCode.TOPIC2_BATCH_LIMIT,
                "The review reconciliation window exceeds 5000 events.",
                category=ErrorCategory.CONTRACT,
                status_code=413,
            )
        return events

    def _reconcile_memory_state(
        self,
        *,
        learner_ref: str,
        knowledge_point: Topic1KnowledgePointV1,
        current: MemoryStateRecord | None,
        review_events: Sequence[LearningBehaviorEventRecord],
        forgetting_rate: float,
        requested_at: datetime,
    ) -> MemoryStateDraft:
        if current is not None and requested_at < current.draft.computed_at:
            raise self._conflict("Memory refresh time cannot precede the latest state version.")
        if current is None:
            initialized_at = (
                requested_at
                if not review_events
                else min(event.draft.occurred_at for event in review_events)
            )
            state = self._memory_engine.initialize_state(
                learner_ref=learner_ref,
                knowledge_point=knowledge_point,
                forgetting_rate=forgetting_rate,
                initialized_at=initialized_at,
            )
        else:
            state = current.draft

        review_metadata: dict[str, Any] = {}
        for event in review_events:
            effective_reviewed_at = max(
                event.draft.occurred_at,
                state.last_activity_at,
                state.computed_at,
            )
            state = self._memory_engine.apply_review(
                state,
                knowledge_point=knowledge_point,
                forgetting_rate=forgetting_rate,
                review_quality=self._memory_engine.quality_from_event(event),
                reviewed_at=effective_reviewed_at,
            )
            review_metadata = {
                "last_review_event_id": str(event.draft.event_id),
                "last_review_source_event_id": event.draft.source_event_id,
                "last_review_occurred_at": event.draft.occurred_at.isoformat(),
                "last_review_received_at": event.draft.received_at.isoformat(),
                "last_review_effective_at": effective_reviewed_at.isoformat(),
            }

        if requested_at < state.computed_at:
            raise self._conflict("Memory refresh time cannot precede reconciled review evidence.")
        if requested_at > state.computed_at or current is not None:
            state = self._memory_engine.refresh_state(
                state,
                knowledge_point=knowledge_point,
                forgetting_rate=forgetting_rate,
                as_of=requested_at,
            )
        if review_metadata:
            state = replace(
                state,
                model_parameters={**state.model_parameters, **review_metadata},
            )
        return state

    @classmethod
    def _reviews_after_state_cursor(
        cls,
        current: MemoryStateRecord | None,
        events: Sequence[LearningBehaviorEventRecord],
    ) -> list[LearningBehaviorEventRecord]:
        if current is None:
            return list(events)
        cursor = cls._memory_review_cursor(current) or (
            current.draft.computed_at,
            UUID(int=0),
        )
        return [
            event for event in events if (event.draft.received_at, event.draft.event_id) > cursor
        ]

    @staticmethod
    def _memory_review_cursor(
        current: MemoryStateRecord | None,
    ) -> tuple[datetime, UUID] | None:
        if current is None:
            return None
        cursor = current.draft.model_parameters.get("review_ingestion_cursor")
        if not isinstance(cursor, dict):
            return None
        received_at = cursor.get("received_at")
        event_id = cursor.get("event_id")
        if not isinstance(received_at, str) or not isinstance(event_id, str):
            return None
        try:
            parsed_at = datetime.fromisoformat(received_at)
            parsed_event_id = UUID(event_id)
        except ValueError:
            return None
        if parsed_at.tzinfo is None:
            return None
        return parsed_at, parsed_event_id

    @staticmethod
    def _child_idempotency_key(parent_key: str, operation_id: UUID) -> str:
        digest = canonical_sha256({"parent": parent_key, "operation_id": str(operation_id)})
        return f"topic2:child:{digest}"

    async def generate_path(
        self,
        *,
        learner_ref: str,
        course_id: str,
        operation_id: UUID,
        requested_at: datetime,
        target_goal: str,
        idempotency_key: str,
        target_kp_ids: list[str] | None = None,
        manual_order: list[str] | None = None,
        change_type: PathChangeType = PathChangeType.INITIALIZED,
        trigger_reason: str = "PROFILE_OR_MEMORY_UPDATED",
    ) -> dict[str, Any]:
        stable_path_id = uuid5(operation_id, "path")
        replay = await self._path_replay(stable_path_id, operation_id)
        if replay is not None:
            return replay
        graph, graph_snapshot = await self._load_topic1(course_id)
        profile = await self._persistence.latest_profile(learner_ref, course_id)
        if profile is None:
            raise self._not_found("student profile")
        memory = await self._persistence.latest_memory_states(learner_ref, course_id)
        previous = await self._persistence.latest_learning_path(learner_ref, course_id)
        snapshot, change = self._path_planner.plan(
            graph_snapshot=graph_snapshot,
            profile=profile,
            memory_states=memory,
            generated_at=requested_at,
            target_goal=target_goal,
            target_kp_ids=target_kp_ids,
            previous_path=previous,
            change_type=change_type,
            trigger_reason=trigger_reason,
            manual_order=manual_order,
        )
        snapshot, change = self._stabilize_path(snapshot, change, operation_id)
        return await self._persistence.save_learning_path(
            snapshot,
            change,
            idempotency_key=idempotency_key,
        )

    async def agent_context(self, learner_ref: str, course_id: str) -> dict[str, Any]:
        profile = await self._persistence.latest_profile(learner_ref, course_id)
        memory = await self._persistence.latest_memory_states(learner_ref, course_id)
        path = await self._persistence.latest_learning_path(learner_ref, course_id)
        if profile is None or path is None:
            raise self._not_found("agent personalization context")
        profile_document = self._persistence.profile_record_document(profile)
        memory_documents = [
            self._persistence.memory_record_document(record)
            for record in sorted(memory, key=lambda item: item.draft.kp_id)
        ]
        path_document = self._persistence.path_record_document(path)
        policy_digest = canonical_sha256(
            {
                "profile_id": str(profile.draft.profile_id),
                "profile_version": profile.draft.profile_version,
                "memory_states": [
                    {
                        "kp_id": record.draft.kp_id,
                        "memory_state_id": str(record.draft.memory_state_id),
                        "state_version": record.draft.state_version,
                    }
                    for record in sorted(memory, key=lambda item: item.draft.kp_id)
                ],
                "path_snapshot_id": str(path.draft.path_snapshot_id),
                "path_version": path.draft.path_version,
            }
        )
        return {
            "schema_version": "topic2.agent-context.v1",
            "learner_ref": learner_ref,
            "course_id": course_id,
            "profile": profile_document,
            "memory_states": memory_documents,
            "learning_path": path_document,
            "personalization_policy_digest": policy_digest,
        }

    async def _load_topic1(
        self,
        course_id: str,
    ) -> tuple[Topic1GraphContentV1, Topic1GraphSnapshotV1]:
        context = current_tenant()
        async with self._database.transaction(context=current_session_context()) as session:
            graph = await self._topic1_repository.load_graph_content(
                session,
                context.tenant_id,
                course_id,
            )
            snapshot = await self._topic1_repository.latest_snapshot(
                session,
                context.tenant_id,
                course_id,
            )
        if graph is None or snapshot is None:
            raise self._not_found("accepted Topic 1 graph")
        return graph, snapshot

    async def _initialization_replay(
        self,
        profile_id: UUID,
        state_ids: Sequence[UUID],
        operation_id: UUID,
    ) -> dict[str, Any] | None:
        try:
            profile = await self._persistence.get_profile(profile_id)
        except LiyanError as exc:
            if exc.code != ErrorCode.TOPIC2_NOT_FOUND:
                raise
            existing_states = await self._persistence.get_memory_states(state_ids)
            if existing_states:
                raise self._conflict(
                    "The deterministic initialization contains memory without its profile."
                ) from None
            return None
        if profile.draft.profile_document.get("operation_id") != str(operation_id):
            raise self._conflict("The deterministic seed profile belongs to another operation.")
        states = await self._persistence.get_memory_states(state_ids)
        if len(states) != len(state_ids) or any(
            record.draft.model_parameters.get("operation_id") != str(operation_id)
            for record in states
        ):
            raise self._conflict("The deterministic learner initialization is incomplete.")
        return {
            "profile": self._persistence.profile_record_document(profile),
            "memory_states": [
                self._persistence.memory_record_document(record) for record in states
            ],
        }

    async def _profile_restore_replay(
        self,
        profile_id: UUID,
        *,
        source_profile_id: UUID,
        operation_id: UUID,
    ) -> dict[str, Any] | None:
        try:
            record = await self._persistence.get_profile(profile_id)
        except LiyanError as exc:
            if exc.code == ErrorCode.TOPIC2_NOT_FOUND:
                return None
            raise
        document = record.draft.profile_document
        if document.get("operation_id") != str(operation_id) or document.get(
            "restored_from_profile_id"
        ) != str(source_profile_id):
            raise self._conflict("The deterministic restore profile belongs to another command.")
        return {"profile": self._persistence.profile_record_document(record)}

    async def _profile_replay(
        self,
        profile_id: UUID,
        operation_id: UUID,
    ) -> dict[str, Any] | None:
        try:
            record = await self._persistence.get_profile(profile_id)
        except LiyanError as exc:
            if exc.code == ErrorCode.TOPIC2_NOT_FOUND:
                return None
            raise
        if record.draft.profile_document.get("operation_id") != str(operation_id):
            raise self._conflict("The deterministic profile ID is bound to another operation.")
        return {"profile": self._persistence.profile_record_document(record)}

    async def _memory_replay(
        self,
        state_ids: list[UUID],
        operation_id: UUID,
    ) -> dict[str, Any] | None:
        records = await self._persistence.get_memory_states(state_ids)
        if not records:
            return None
        if len(records) != len(state_ids) or any(
            record.draft.model_parameters.get("operation_id") != str(operation_id)
            for record in records
        ):
            raise self._conflict("The deterministic memory IDs are only partially committed.")
        return {
            "memory_states": [
                self._persistence.memory_record_document(record) for record in records
            ]
        }

    async def _path_replay(
        self,
        path_id: UUID,
        operation_id: UUID,
    ) -> dict[str, Any] | None:
        try:
            record = await self._persistence.get_learning_path(path_id)
        except LiyanError as exc:
            if exc.code == ErrorCode.TOPIC2_NOT_FOUND:
                return None
            raise
        if record.draft.decision_document.get("operation_id") != str(operation_id):
            raise self._conflict("The deterministic path ID is bound to another operation.")
        return {"learning_path": self._persistence.path_record_document(record)}

    @staticmethod
    def _profile_cursor(record) -> tuple[datetime | None, UUID | None]:
        if record is None:
            return None, None
        cursor = record.draft.profile_document.get("ingestion_cursor")
        if not isinstance(cursor, dict):
            return None, None
        received_at = cursor.get("received_at")
        event_id = cursor.get("event_id")
        if not isinstance(received_at, str) or not isinstance(event_id, str):
            return None, None
        return datetime.fromisoformat(received_at), UUID(event_id)

    @staticmethod
    def _stabilize_profile(
        draft: StudentProfileDraft,
        *,
        operation_id: UUID,
        graph_snapshot: Topic1GraphSnapshotV1,
    ) -> StudentProfileDraft:
        profile_id = uuid5(operation_id, "profile")
        features = tuple(
            replace(
                feature,
                feature_id=uuid5(
                    operation_id,
                    f"feature:{feature.dimension.value}:{feature.feature_key}",
                ),
            )
            for feature in draft.features
        )
        document = {
            **draft.profile_document,
            "profile_id": str(profile_id),
            "operation_id": str(operation_id),
            "topic1_graph_snapshot_id": str(graph_snapshot.snapshot_id),
            "topic1_graph_version": graph_snapshot.graph_version,
            "topic1_graph_sha256": graph_snapshot.content_sha256,
        }
        return replace(
            draft,
            profile_id=profile_id,
            features=features,
            profile_document=document,
            content_sha256=canonical_sha256(document),
        )

    def _stabilize_path(
        self,
        snapshot: LearningPathSnapshotDraft,
        change: PathChangeDraft,
        operation_id: UUID,
    ) -> tuple[LearningPathSnapshotDraft, PathChangeDraft]:
        path_id = uuid5(operation_id, "path")
        decision = {**snapshot.decision_document, "operation_id": str(operation_id)}
        stable_snapshot = replace(
            snapshot,
            path_snapshot_id=path_id,
            decision_document=decision,
            content_sha256="0" * 64,
        )
        stable_snapshot = replace(
            stable_snapshot,
            content_sha256=canonical_sha256(self._path_planner.hash_document(stable_snapshot)),
        )
        stable_change = replace(
            change,
            change_id=uuid5(operation_id, "path-change"),
            to_path_snapshot_id=path_id,
        )
        return stable_snapshot, stable_change

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
