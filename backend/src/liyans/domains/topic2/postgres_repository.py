from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant

from .entities import (
    BehaviorEventType,
    BehaviorSourceType,
    LearningBehaviorEventDraft,
    LearningBehaviorEventRecord,
    LearningPathRecord,
    LearningPathSnapshotDraft,
    MemoryRiskLevel,
    MemoryStateDraft,
    MemoryStateRecord,
    PathChangeDraft,
    PathChangeType,
    PathPlanType,
    ProfileDimension,
    ProfileFeatureDraft,
    StudentProfileDraft,
    StudentProfileRecord,
)
from .models import (
    Topic2LearningBehaviorEventModel,
    Topic2LearningPathSnapshotModel,
    Topic2MemoryStateModel,
    Topic2PathChangeLogModel,
    Topic2ProfileFeatureModel,
    Topic2StudentProfileModel,
)


class PostgresTopic2Repository:
    async def append_behavior_event(
        self,
        session: AsyncSession,
        tenant_id: str,
        event: LearningBehaviorEventDraft,
        audit_event_id: UUID,
    ) -> LearningBehaviorEventRecord:
        self._assert_write(session, tenant_id)
        row = Topic2LearningBehaviorEventModel(
            event_id=event.event_id,
            tenant_id=tenant_id,
            source_event_id=event.source_event_id,
            event_version=event.event_version,
            learner_ref=event.learner_ref,
            course_id=event.course_id,
            kp_id=event.kp_id,
            session_id=event.session_id,
            event_type=event.event_type.value,
            source_type=event.source_type.value,
            duration_seconds=event.duration_seconds,
            response_latency_ms=event.response_latency_ms,
            correctness=event.correctness,
            score=event.score,
            attempt_count=event.attempt_count,
            interaction_count=event.interaction_count,
            attention_ratio=event.attention_ratio,
            misconception_ids=list(event.misconception_ids),
            goal_tags=list(event.goal_tags),
            payload=event.payload,
            payload_sha256=event.payload_sha256,
            occurred_at=event.occurred_at,
            received_at=event.received_at,
            audit_event_id=audit_event_id,
            created_at=event.received_at,
        )
        session.add(row)
        await session.flush()
        return self._behavior_record(row)

    async def list_behavior_events(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        received_after: datetime | None = None,
        received_after_event_id: UUID | None = None,
        limit: int = 1000,
    ) -> list[LearningBehaviorEventRecord]:
        assert_tenant(tenant_id)
        if not 1 <= limit <= 5000:
            raise ValueError("behavior event limit must be between one and 5000")
        statement = select(Topic2LearningBehaviorEventModel).where(
            Topic2LearningBehaviorEventModel.tenant_id == tenant_id,
            Topic2LearningBehaviorEventModel.learner_ref == learner_ref,
            Topic2LearningBehaviorEventModel.course_id == course_id,
        )
        if since is not None:
            statement = statement.where(Topic2LearningBehaviorEventModel.occurred_at >= since)
        if until is not None:
            statement = statement.where(Topic2LearningBehaviorEventModel.occurred_at <= until)
        if received_after is not None:
            cursor = Topic2LearningBehaviorEventModel.received_at > received_after
            if received_after_event_id is not None:
                cursor = or_(
                    cursor,
                    and_(
                        Topic2LearningBehaviorEventModel.received_at == received_after,
                        Topic2LearningBehaviorEventModel.event_id > received_after_event_id,
                    ),
                )
            statement = statement.where(cursor)
        result = await session.execute(
            statement.order_by(
                Topic2LearningBehaviorEventModel.occurred_at,
                Topic2LearningBehaviorEventModel.event_id,
            ).limit(limit)
        )
        return [self._behavior_record(row) for row in result.scalars()]

    async def list_review_events(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        received_after: datetime | None = None,
        received_after_event_id: UUID | None = None,
        received_until: datetime | None = None,
        occurred_until: datetime | None = None,
        limit: int = 1000,
    ) -> list[LearningBehaviorEventRecord]:
        assert_tenant(tenant_id)
        if not 1 <= limit <= 5001:
            raise ValueError("review event limit must be between one and 5001")
        statement = select(Topic2LearningBehaviorEventModel).where(
            Topic2LearningBehaviorEventModel.tenant_id == tenant_id,
            Topic2LearningBehaviorEventModel.learner_ref == learner_ref,
            Topic2LearningBehaviorEventModel.course_id == course_id,
            Topic2LearningBehaviorEventModel.event_type == BehaviorEventType.REVIEW_COMPLETED.value,
            Topic2LearningBehaviorEventModel.kp_id.is_not(None),
        )
        if occurred_until is not None:
            statement = statement.where(
                Topic2LearningBehaviorEventModel.occurred_at <= occurred_until
            )
        if received_until is not None:
            statement = statement.where(
                Topic2LearningBehaviorEventModel.received_at <= received_until
            )
        if received_after is not None:
            cursor = Topic2LearningBehaviorEventModel.received_at > received_after
            if received_after_event_id is not None:
                cursor = or_(
                    cursor,
                    and_(
                        Topic2LearningBehaviorEventModel.received_at == received_after,
                        Topic2LearningBehaviorEventModel.event_id > received_after_event_id,
                    ),
                )
            statement = statement.where(cursor)
        result = await session.execute(
            statement.order_by(
                Topic2LearningBehaviorEventModel.received_at,
                Topic2LearningBehaviorEventModel.event_id,
            ).limit(limit)
        )
        return [self._behavior_record(row) for row in result.scalars()]

    async def append_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        profile: StudentProfileDraft,
        audit_event_id: UUID,
        created_by_subject: str,
    ) -> StudentProfileRecord:
        self._assert_write(session, tenant_id)
        row = Topic2StudentProfileModel(
            profile_id=profile.profile_id,
            tenant_id=tenant_id,
            learner_ref=profile.learner_ref,
            course_id=profile.course_id,
            profile_version=profile.profile_version,
            parent_profile_id=profile.parent_profile_id,
            policy_version=profile.policy_version,
            knowledge_mastery=profile.knowledge_mastery,
            problem_solving_proficiency=profile.problem_solving_proficiency,
            misconception_preference=profile.misconception_preference,
            learning_pace=profile.learning_pace,
            forgetting_rate=profile.forgetting_rate,
            learning_goal_tendency=profile.learning_goal_tendency,
            confidence_score=profile.confidence_score,
            activity_count=profile.activity_count,
            last_event_at=profile.last_event_at,
            source_window_start=profile.source_window_start,
            source_window_end=profile.source_window_end,
            profile_document=profile.profile_document,
            content_sha256=profile.content_sha256,
            audit_event_id=audit_event_id,
            created_by_subject=created_by_subject,
            frozen_at=profile.frozen_at,
            created_at=profile.frozen_at,
        )
        session.add(row)
        await session.flush()
        session.add_all(
            [
                Topic2ProfileFeatureModel(
                    feature_id=feature.feature_id,
                    tenant_id=tenant_id,
                    profile_id=profile.profile_id,
                    dimension=feature.dimension.value,
                    feature_key=feature.feature_key,
                    value_document=feature.value_document,
                    normalized_score=feature.normalized_score,
                    confidence=feature.confidence,
                    evidence_count=feature.evidence_count,
                    source_event_ids=list(feature.source_event_ids),
                    computed_at=feature.computed_at,
                    audit_event_id=audit_event_id,
                    created_at=profile.frozen_at,
                )
                for feature in profile.features
            ]
        )
        await session.flush()
        return StudentProfileRecord(
            draft=profile,
            audit_event_id=audit_event_id,
            created_by_subject=created_by_subject,
            created_at=profile.frozen_at,
        )

    async def latest_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
    ) -> StudentProfileRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic2StudentProfileModel)
            .where(
                Topic2StudentProfileModel.tenant_id == tenant_id,
                Topic2StudentProfileModel.learner_ref == learner_ref,
                Topic2StudentProfileModel.course_id == course_id,
            )
            .order_by(Topic2StudentProfileModel.profile_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        features = await self.list_profile_features(session, tenant_id, row.profile_id)
        return self._profile_record(row, features)

    async def get_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        profile_id: UUID,
    ) -> StudentProfileRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic2StudentProfileModel).where(
                Topic2StudentProfileModel.tenant_id == tenant_id,
                Topic2StudentProfileModel.profile_id == profile_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        features = await self.list_profile_features(session, tenant_id, row.profile_id)
        return self._profile_record(row, features)

    async def list_profile_versions(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        limit: int = 100,
    ) -> list[StudentProfileRecord]:
        assert_tenant(tenant_id)
        if not 1 <= limit <= 1000:
            raise ValueError("profile version limit must be between one and 1000")
        result = await session.execute(
            select(Topic2StudentProfileModel)
            .where(
                Topic2StudentProfileModel.tenant_id == tenant_id,
                Topic2StudentProfileModel.learner_ref == learner_ref,
                Topic2StudentProfileModel.course_id == course_id,
            )
            .order_by(Topic2StudentProfileModel.profile_version.desc())
            .limit(limit)
        )
        rows = list(result.scalars())
        if not rows:
            return []
        feature_result = await session.execute(
            select(Topic2ProfileFeatureModel).where(
                Topic2ProfileFeatureModel.tenant_id == tenant_id,
                Topic2ProfileFeatureModel.profile_id.in_([row.profile_id for row in rows]),
            )
        )
        grouped: dict[UUID, list[ProfileFeatureDraft]] = defaultdict(list)
        for feature in feature_result.scalars():
            grouped[feature.profile_id].append(self._profile_feature(feature))
        return [self._profile_record(row, grouped[row.profile_id]) for row in rows]

    async def list_profile_features(
        self,
        session: AsyncSession,
        tenant_id: str,
        profile_id: UUID,
    ) -> list[ProfileFeatureDraft]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic2ProfileFeatureModel)
            .where(
                Topic2ProfileFeatureModel.tenant_id == tenant_id,
                Topic2ProfileFeatureModel.profile_id == profile_id,
            )
            .order_by(
                Topic2ProfileFeatureModel.dimension,
                Topic2ProfileFeatureModel.feature_key,
            )
        )
        return [self._profile_feature(row) for row in result.scalars()]

    async def append_memory_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        states: Sequence[MemoryStateDraft],
        audit_event_id: UUID,
    ) -> list[MemoryStateRecord]:
        self._assert_write(session, tenant_id)
        rows = [
            Topic2MemoryStateModel(
                memory_state_id=state.memory_state_id,
                tenant_id=tenant_id,
                learner_ref=state.learner_ref,
                course_id=state.course_id,
                kp_id=state.kp_id,
                state_version=state.state_version,
                parent_memory_state_id=state.parent_memory_state_id,
                model_version=state.model_version,
                stability_days=state.stability_days,
                effective_stability_days=state.effective_stability_days,
                elapsed_days=state.elapsed_days,
                retrievability=state.retrievability,
                forgetting_rate=state.forgetting_rate,
                difficulty_factor=state.difficulty_factor,
                review_gain=state.review_gain,
                review_count=state.review_count,
                lapse_count=state.lapse_count,
                last_reviewed_at=state.last_reviewed_at,
                last_activity_at=state.last_activity_at,
                next_review_at=state.next_review_at,
                risk_level=state.risk_level.value,
                model_parameters=state.model_parameters,
                content_sha256=state.content_sha256,
                computed_at=state.computed_at,
                audit_event_id=audit_event_id,
                created_at=state.computed_at,
            )
            for state in states
        ]
        session.add_all(rows)
        await session.flush()
        return [self._memory_record(row) for row in rows]

    async def latest_memory_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        kp_ids: Sequence[str] | None = None,
    ) -> list[MemoryStateRecord]:
        assert_tenant(tenant_id)
        latest = (
            select(
                Topic2MemoryStateModel.learner_ref,
                Topic2MemoryStateModel.course_id,
                Topic2MemoryStateModel.kp_id,
                func.max(Topic2MemoryStateModel.state_version).label("max_version"),
            )
            .where(
                Topic2MemoryStateModel.tenant_id == tenant_id,
                Topic2MemoryStateModel.learner_ref == learner_ref,
                Topic2MemoryStateModel.course_id == course_id,
            )
            .group_by(
                Topic2MemoryStateModel.learner_ref,
                Topic2MemoryStateModel.course_id,
                Topic2MemoryStateModel.kp_id,
            )
            .subquery()
        )
        statement = (
            select(Topic2MemoryStateModel)
            .join(
                latest,
                and_(
                    Topic2MemoryStateModel.learner_ref == latest.c.learner_ref,
                    Topic2MemoryStateModel.course_id == latest.c.course_id,
                    Topic2MemoryStateModel.kp_id == latest.c.kp_id,
                    Topic2MemoryStateModel.state_version == latest.c.max_version,
                ),
            )
            .where(Topic2MemoryStateModel.tenant_id == tenant_id)
        )
        if kp_ids is not None:
            statement = statement.where(Topic2MemoryStateModel.kp_id.in_(tuple(kp_ids)))
        result = await session.execute(statement.order_by(Topic2MemoryStateModel.kp_id))
        return [self._memory_record(row) for row in result.scalars()]

    async def get_memory_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        memory_state_ids: Sequence[UUID],
    ) -> list[MemoryStateRecord]:
        assert_tenant(tenant_id)
        if not memory_state_ids:
            return []
        result = await session.execute(
            select(Topic2MemoryStateModel).where(
                Topic2MemoryStateModel.tenant_id == tenant_id,
                Topic2MemoryStateModel.memory_state_id.in_(tuple(memory_state_ids)),
            )
        )
        records = [self._memory_record(row) for row in result.scalars()]
        by_id = {record.draft.memory_state_id: record for record in records}
        return [by_id[state_id] for state_id in memory_state_ids if state_id in by_id]

    async def due_memory_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        due_at: datetime,
        limit: int,
    ) -> list[MemoryStateRecord]:
        assert_tenant(tenant_id)
        if not 1 <= limit <= 5000:
            raise ValueError("due memory-state limit must be between one and 5000")
        latest = (
            select(
                Topic2MemoryStateModel.learner_ref,
                Topic2MemoryStateModel.course_id,
                Topic2MemoryStateModel.kp_id,
                func.max(Topic2MemoryStateModel.state_version).label("max_version"),
            )
            .where(Topic2MemoryStateModel.tenant_id == tenant_id)
            .group_by(
                Topic2MemoryStateModel.learner_ref,
                Topic2MemoryStateModel.course_id,
                Topic2MemoryStateModel.kp_id,
            )
            .subquery()
        )
        result = await session.execute(
            select(Topic2MemoryStateModel)
            .join(
                latest,
                and_(
                    Topic2MemoryStateModel.learner_ref == latest.c.learner_ref,
                    Topic2MemoryStateModel.course_id == latest.c.course_id,
                    Topic2MemoryStateModel.kp_id == latest.c.kp_id,
                    Topic2MemoryStateModel.state_version == latest.c.max_version,
                ),
            )
            .where(
                Topic2MemoryStateModel.tenant_id == tenant_id,
                Topic2MemoryStateModel.next_review_at <= due_at,
            )
            .order_by(
                Topic2MemoryStateModel.next_review_at,
                Topic2MemoryStateModel.learner_ref,
                Topic2MemoryStateModel.kp_id,
            )
            .limit(limit)
        )
        return [self._memory_record(row) for row in result.scalars()]

    async def append_learning_path(
        self,
        session: AsyncSession,
        tenant_id: str,
        snapshot: LearningPathSnapshotDraft,
        change: PathChangeDraft,
        audit_event_id: UUID,
        created_by_subject: str,
    ) -> LearningPathRecord:
        self._assert_write(session, tenant_id)
        path_row = Topic2LearningPathSnapshotModel(
            path_snapshot_id=snapshot.path_snapshot_id,
            tenant_id=tenant_id,
            learner_ref=snapshot.learner_ref,
            course_id=snapshot.course_id,
            path_version=snapshot.path_version,
            parent_path_snapshot_id=snapshot.parent_path_snapshot_id,
            topic1_graph_snapshot_id=snapshot.topic1_graph_snapshot_id,
            topic1_graph_version=snapshot.topic1_graph_version,
            profile_id=snapshot.profile_id,
            plan_type=snapshot.plan_type.value,
            trigger_reason=snapshot.trigger_reason,
            target_goal=snapshot.target_goal,
            policy_version=snapshot.policy_version,
            path_document=snapshot.path_document,
            decision_document=snapshot.decision_document,
            node_count=snapshot.node_count,
            estimated_minutes=snapshot.estimated_minutes,
            manual_override=snapshot.manual_override,
            content_sha256=snapshot.content_sha256,
            audit_event_id=audit_event_id,
            created_by_subject=created_by_subject,
            frozen_at=snapshot.frozen_at,
            created_at=snapshot.frozen_at,
        )
        change_row = Topic2PathChangeLogModel(
            change_id=change.change_id,
            tenant_id=tenant_id,
            learner_ref=change.learner_ref,
            course_id=change.course_id,
            from_path_snapshot_id=change.from_path_snapshot_id,
            to_path_snapshot_id=change.to_path_snapshot_id,
            change_type=change.change_type.value,
            reason=change.reason,
            policy_version=change.policy_version,
            change_document=change.change_document,
            audit_event_id=audit_event_id,
            occurred_at=change.occurred_at,
            created_at=change.occurred_at,
        )
        session.add(path_row)
        await session.flush()
        session.add(change_row)
        await session.flush()
        return LearningPathRecord(
            draft=snapshot,
            change=change,
            audit_event_id=audit_event_id,
            created_by_subject=created_by_subject,
            created_at=snapshot.frozen_at,
        )

    async def latest_learning_path(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
    ) -> LearningPathRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic2LearningPathSnapshotModel)
            .where(
                Topic2LearningPathSnapshotModel.tenant_id == tenant_id,
                Topic2LearningPathSnapshotModel.learner_ref == learner_ref,
                Topic2LearningPathSnapshotModel.course_id == course_id,
            )
            .order_by(Topic2LearningPathSnapshotModel.path_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else await self._path_record(session, tenant_id, row)

    async def get_learning_path(
        self,
        session: AsyncSession,
        tenant_id: str,
        path_snapshot_id: UUID,
    ) -> LearningPathRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic2LearningPathSnapshotModel).where(
                Topic2LearningPathSnapshotModel.tenant_id == tenant_id,
                Topic2LearningPathSnapshotModel.path_snapshot_id == path_snapshot_id,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else await self._path_record(session, tenant_id, row)

    async def list_learning_paths(
        self,
        session: AsyncSession,
        tenant_id: str,
        learner_ref: str,
        course_id: str,
        *,
        limit: int = 100,
    ) -> list[LearningPathRecord]:
        assert_tenant(tenant_id)
        if not 1 <= limit <= 1000:
            raise ValueError("learning path limit must be between one and 1000")
        result = await session.execute(
            select(Topic2LearningPathSnapshotModel)
            .where(
                Topic2LearningPathSnapshotModel.tenant_id == tenant_id,
                Topic2LearningPathSnapshotModel.learner_ref == learner_ref,
                Topic2LearningPathSnapshotModel.course_id == course_id,
            )
            .order_by(Topic2LearningPathSnapshotModel.path_version.desc())
            .limit(limit)
        )
        return [await self._path_record(session, tenant_id, row) for row in result.scalars()]

    @staticmethod
    def _assert_write(session: AsyncSession, tenant_id: str) -> None:
        assert_tenant(tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Topic 2 persistence requires an active business transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )

    @staticmethod
    def _profile_feature(row: Topic2ProfileFeatureModel) -> ProfileFeatureDraft:
        return ProfileFeatureDraft(
            feature_id=row.feature_id,
            dimension=ProfileDimension(row.dimension),
            feature_key=row.feature_key,
            value_document=row.value_document,
            normalized_score=row.normalized_score,
            confidence=row.confidence,
            evidence_count=row.evidence_count,
            source_event_ids=tuple(row.source_event_ids),
            computed_at=row.computed_at,
        )

    @classmethod
    def _profile_record(
        cls,
        row: Topic2StudentProfileModel,
        features: Sequence[ProfileFeatureDraft],
    ) -> StudentProfileRecord:
        return StudentProfileRecord(
            draft=StudentProfileDraft(
                profile_id=row.profile_id,
                learner_ref=row.learner_ref,
                course_id=row.course_id,
                profile_version=row.profile_version,
                parent_profile_id=row.parent_profile_id,
                policy_version=row.policy_version,
                knowledge_mastery=row.knowledge_mastery,
                problem_solving_proficiency=row.problem_solving_proficiency,
                misconception_preference=row.misconception_preference,
                learning_pace=row.learning_pace,
                forgetting_rate=row.forgetting_rate,
                learning_goal_tendency=row.learning_goal_tendency,
                confidence_score=row.confidence_score,
                activity_count=row.activity_count,
                last_event_at=row.last_event_at,
                source_window_start=row.source_window_start,
                source_window_end=row.source_window_end,
                profile_document=row.profile_document,
                content_sha256=row.content_sha256,
                frozen_at=row.frozen_at,
                features=tuple(features),
            ),
            audit_event_id=row.audit_event_id,
            created_by_subject=row.created_by_subject,
            created_at=row.created_at,
        )

    @staticmethod
    def _behavior_record(row: Topic2LearningBehaviorEventModel) -> LearningBehaviorEventRecord:
        return LearningBehaviorEventRecord(
            draft=LearningBehaviorEventDraft(
                event_id=row.event_id,
                source_event_id=row.source_event_id,
                event_version=row.event_version,
                learner_ref=row.learner_ref,
                course_id=row.course_id,
                kp_id=row.kp_id,
                session_id=row.session_id,
                event_type=BehaviorEventType(row.event_type),
                source_type=BehaviorSourceType(row.source_type),
                duration_seconds=row.duration_seconds,
                response_latency_ms=row.response_latency_ms,
                correctness=row.correctness,
                score=row.score,
                attempt_count=row.attempt_count,
                interaction_count=row.interaction_count,
                attention_ratio=row.attention_ratio,
                misconception_ids=tuple(row.misconception_ids),
                goal_tags=tuple(row.goal_tags),
                payload=row.payload,
                payload_sha256=row.payload_sha256,
                occurred_at=row.occurred_at,
                received_at=row.received_at,
            ),
            audit_event_id=row.audit_event_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _memory_record(row: Topic2MemoryStateModel) -> MemoryStateRecord:
        return MemoryStateRecord(
            draft=MemoryStateDraft(
                memory_state_id=row.memory_state_id,
                learner_ref=row.learner_ref,
                course_id=row.course_id,
                kp_id=row.kp_id,
                state_version=row.state_version,
                parent_memory_state_id=row.parent_memory_state_id,
                model_version=row.model_version,
                stability_days=row.stability_days,
                effective_stability_days=row.effective_stability_days,
                elapsed_days=row.elapsed_days,
                retrievability=row.retrievability,
                forgetting_rate=row.forgetting_rate,
                difficulty_factor=row.difficulty_factor,
                review_gain=row.review_gain,
                review_count=row.review_count,
                lapse_count=row.lapse_count,
                last_reviewed_at=row.last_reviewed_at,
                last_activity_at=row.last_activity_at,
                next_review_at=row.next_review_at,
                risk_level=MemoryRiskLevel(row.risk_level),
                model_parameters=row.model_parameters,
                content_sha256=row.content_sha256,
                computed_at=row.computed_at,
            ),
            audit_event_id=row.audit_event_id,
            created_at=row.created_at,
        )

    async def _path_record(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: Topic2LearningPathSnapshotModel,
    ) -> LearningPathRecord:
        result = await session.execute(
            select(Topic2PathChangeLogModel)
            .where(
                Topic2PathChangeLogModel.tenant_id == tenant_id,
                Topic2PathChangeLogModel.to_path_snapshot_id == row.path_snapshot_id,
            )
            .order_by(Topic2PathChangeLogModel.occurred_at.desc())
            .limit(1)
        )
        change = result.scalar_one_or_none()
        if change is None:
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "A Topic 2 learning path is missing its change record.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
        return LearningPathRecord(
            draft=LearningPathSnapshotDraft(
                path_snapshot_id=row.path_snapshot_id,
                learner_ref=row.learner_ref,
                course_id=row.course_id,
                path_version=row.path_version,
                parent_path_snapshot_id=row.parent_path_snapshot_id,
                topic1_graph_snapshot_id=row.topic1_graph_snapshot_id,
                topic1_graph_version=row.topic1_graph_version,
                profile_id=row.profile_id,
                plan_type=PathPlanType(row.plan_type),
                trigger_reason=row.trigger_reason,
                target_goal=row.target_goal,
                policy_version=row.policy_version,
                path_document=row.path_document,
                decision_document=row.decision_document,
                node_count=row.node_count,
                estimated_minutes=row.estimated_minutes,
                manual_override=row.manual_override,
                content_sha256=row.content_sha256,
                frozen_at=row.frozen_at,
            ),
            change=PathChangeDraft(
                change_id=change.change_id,
                learner_ref=change.learner_ref,
                course_id=change.course_id,
                from_path_snapshot_id=change.from_path_snapshot_id,
                to_path_snapshot_id=change.to_path_snapshot_id,
                change_type=PathChangeType(change.change_type),
                reason=change.reason,
                policy_version=change.policy_version,
                change_document=change.change_document,
                occurred_at=change.occurred_at,
            ),
            audit_event_id=row.audit_event_id,
            created_by_subject=row.created_by_subject,
            created_at=row.created_at,
        )
