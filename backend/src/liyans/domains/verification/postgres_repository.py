from __future__ import annotations

from uuid import UUID

from liyans_contracts.topic4_c1 import (
    AggregationResultV1,
    ClaimRiskV1,
    ClaimV1,
    ClaimVerdictV1,
    HumanReviewDecisionV1,
    HumanReviewTaskV1,
    ModuleDispatchPlanV1,
    ModuleRunResultV1,
    ModuleRunV1,
    VerificationReportV1,
)
from liyans_contracts.topic4_common import Topic4RecordV1
from liyans_contracts.verification import (
    VerificationAcceptedPayloadV1,
    VerificationRequestPayloadV1,
    VerificationStateChangedPayloadV1,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import assert_tenant
from liyans.domains.knowledge.models import Topic4EvidenceRefModel

from .entities import VerificationRecord, VerificationStateRecord
from .models import (
    Topic4AggregationResultModel,
    Topic4ClaimModel,
    Topic4ClaimRiskModel,
    Topic4ClaimVerdictModel,
    Topic4DispatchPlanModel,
    Topic4HumanReviewDecisionModel,
    Topic4HumanReviewTaskModel,
    Topic4ModuleResultModel,
    Topic4ModuleRunModel,
    Topic4VerificationModel,
    Topic4VerificationReportModel,
    Topic4VerificationStateModel,
)


class PostgresVerificationRepository:
    async def append_verification(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: VerificationRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        request = record.request
        accepted = record.accepted
        source = request.source_snapshot_ref
        session.add(
            Topic4VerificationModel(
                verification_record_id=record.verification_record_id,
                verification_id=request.verification_id,
                idempotency_key=request.idempotency_key,
                trigger=request.trigger.value,
                parent_verification_id=request.parent_verification_id,
                source_candidate_id=source.candidate_id,
                source_candidate_version=source.candidate_version,
                source_candidate_sha256=source.candidate_sha256,
                requested_profile=request.requested_profile.value,
                binding_document=accepted.binding.model_dump(mode="json"),
                accepted_document=accepted.model_dump(mode="json"),
                request_document=request.model_dump(mode="json"),
                accepted_at=accepted.accepted_at,
                deadline_at=accepted.deadline_at,
                tenant_id=tenant_id,
                trace_id=accepted.trace_id,
                version_cas=accepted.version_cas,
                record_sha256=accepted.record_sha256,
                immutable=accepted.immutable,
                audit_event_id=audit_event_id,
                created_at=accepted.created_at,
            )
        )
        await session.flush()

    async def get_verification(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> VerificationRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4VerificationModel).where(
                Topic4VerificationModel.tenant_id == tenant_id,
                Topic4VerificationModel.verification_id == verification_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return VerificationRecord(
            verification_record_id=row.verification_record_id,
            request=VerificationRequestPayloadV1.model_validate(row.request_document),
            accepted=VerificationAcceptedPayloadV1.model_validate(row.accepted_document),
        )

    async def append_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        record: VerificationStateRecord,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        change = record.change
        session.add(
            Topic4VerificationStateModel(
                state_snapshot_id=record.state_snapshot_id,
                verification_id=change.verification_id,
                state_version=change.state_version,
                previous_state=None
                if change.previous_state is None
                else change.previous_state.value,
                current_state=change.current_state.value,
                reason_code=change.reason_code,
                revision_round=change.revision_round,
                state_document=change.model_dump(mode="json"),
                changed_at=change.changed_at,
                tenant_id=tenant_id,
                trace_id=change.trace_id,
                version_cas=change.version_cas,
                record_sha256=change.record_sha256,
                immutable=change.immutable,
                audit_event_id=audit_event_id,
                created_at=change.created_at,
            )
        )
        await session.flush()

    async def latest_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> VerificationStateRecord | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4VerificationStateModel)
            .where(
                Topic4VerificationStateModel.tenant_id == tenant_id,
                Topic4VerificationStateModel.verification_id == verification_id,
            )
            .order_by(Topic4VerificationStateModel.state_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return VerificationStateRecord(
            state_snapshot_id=row.state_snapshot_id,
            change=VerificationStateChangedPayloadV1.model_validate(row.state_document),
        )

    async def append_claims(
        self,
        session: AsyncSession,
        tenant_id: str,
        claims: list[ClaimV1],
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        for claim in claims:
            self._assert_record_tenant(tenant_id, claim.tenant_id)
            session.add(
                Topic4ClaimModel(
                    claim_record_id=claim.claim_id,
                    claim_id=claim.claim_id,
                    verification_id=claim.verification_id,
                    candidate_id=claim.candidate_id,
                    candidate_version=claim.candidate_version,
                    block_id=claim.block_id,
                    claim_kind=claim.claim_kind.value,
                    claim_subtype=claim.claim_subtype,
                    ordinal=claim.ordinal,
                    claim_sha256=claim.claim_sha256,
                    claim_document=claim.model_dump(mode="json"),
                    **self._record_columns(claim, audit_event_id),
                )
            )
        await session.flush()

    async def list_claims(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> list[ClaimV1]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4ClaimModel)
            .where(
                Topic4ClaimModel.tenant_id == tenant_id,
                Topic4ClaimModel.verification_id == verification_id,
            )
            .order_by(Topic4ClaimModel.block_id, Topic4ClaimModel.ordinal)
        )
        return [ClaimV1.model_validate(row.claim_document) for row in result.scalars()]

    async def append_risks(
        self,
        session: AsyncSession,
        tenant_id: str,
        risks: list[ClaimRiskV1],
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        for risk in risks:
            self._assert_record_tenant(tenant_id, risk.tenant_id)
            session.add(
                Topic4ClaimRiskModel(
                    risk_record_id=risk.risk_id,
                    risk_id=risk.risk_id,
                    verification_id=risk.verification_id,
                    claim_id=risk.claim_id,
                    level=risk.level.value,
                    score=risk.score,
                    policy_version=risk.policy_version,
                    risk_document=risk.model_dump(mode="json"),
                    **self._record_columns(risk, audit_event_id),
                )
            )
        await session.flush()

    async def list_risks(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> list[ClaimRiskV1]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4ClaimRiskModel)
            .where(
                Topic4ClaimRiskModel.tenant_id == tenant_id,
                Topic4ClaimRiskModel.verification_id == verification_id,
            )
            .order_by(Topic4ClaimRiskModel.claim_id)
        )
        return [ClaimRiskV1.model_validate(row.risk_document) for row in result.scalars()]

    async def append_dispatch_plan(
        self,
        session: AsyncSession,
        tenant_id: str,
        plan: ModuleDispatchPlanV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, plan.tenant_id)
        session.add(
            Topic4DispatchPlanModel(
                dispatch_plan_record_id=plan.dispatch_plan_id,
                dispatch_plan_id=plan.dispatch_plan_id,
                verification_id=plan.verification_id,
                max_parallelism=plan.max_parallelism,
                policy_version=plan.policy_version,
                plan_sha256=plan.plan_sha256,
                plan_document=plan.model_dump(mode="json"),
                **self._record_columns(plan, audit_event_id),
            )
        )
        await session.flush()

    async def latest_dispatch_plan(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> ModuleDispatchPlanV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4DispatchPlanModel)
            .where(
                Topic4DispatchPlanModel.tenant_id == tenant_id,
                Topic4DispatchPlanModel.verification_id == verification_id,
            )
            .order_by(Topic4DispatchPlanModel.version_cas.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else ModuleDispatchPlanV1.model_validate(row.plan_document)

    async def append_module_runs(
        self,
        session: AsyncSession,
        tenant_id: str,
        runs: list[ModuleRunV1],
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        for run in runs:
            self._assert_record_tenant(tenant_id, run.tenant_id)
            session.add(
                Topic4ModuleRunModel(
                    module_run_snapshot_id=UUID(
                        bytes=bytes.fromhex(run.record_sha256[:32]),
                    ),
                    module_run_id=run.module_run_id,
                    run_version=run.version_cas,
                    verification_id=run.verification_id,
                    dispatch_plan_id=run.dispatch_plan_id,
                    claim_id=run.claim_id,
                    module=run.module.value,
                    state=run.state.value,
                    attempt=run.attempt,
                    max_attempts=run.max_attempts,
                    input_sha256=run.input_sha256,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    error_code=run.error_code,
                    run_document=run.model_dump(mode="json"),
                    **self._record_columns(run, audit_event_id),
                )
            )
        await session.flush()

    async def list_latest_module_runs(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> list[ModuleRunV1]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4ModuleRunModel)
            .where(
                Topic4ModuleRunModel.tenant_id == tenant_id,
                Topic4ModuleRunModel.verification_id == verification_id,
            )
            .order_by(
                Topic4ModuleRunModel.module_run_id,
                Topic4ModuleRunModel.run_version.desc(),
            )
        )
        latest: dict[UUID, ModuleRunV1] = {}
        for row in result.scalars():
            latest.setdefault(row.module_run_id, ModuleRunV1.model_validate(row.run_document))
        return list(latest.values())

    async def append_module_results(
        self,
        session: AsyncSession,
        tenant_id: str,
        results: list[ModuleRunResultV1],
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        for module_result in results:
            self._assert_record_tenant(tenant_id, module_result.tenant_id)
            session.add(
                Topic4ModuleResultModel(
                    module_result_record_id=module_result.module_result_id,
                    module_result_id=module_result.module_result_id,
                    module_run_id=module_result.module_run_id,
                    module_run_version=module_result.version_cas,
                    verification_id=module_result.verification_id,
                    claim_id=module_result.claim_id,
                    module=module_result.module.value,
                    verdict=module_result.verdict.value,
                    confidence=module_result.confidence,
                    result_sha256=module_result.result_sha256,
                    deterministic=module_result.deterministic,
                    result_document=module_result.model_dump(mode="json"),
                    **self._record_columns(module_result, audit_event_id),
                )
            )
        await session.flush()

    async def list_module_results(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> list[ModuleRunResultV1]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4ModuleResultModel)
            .where(
                Topic4ModuleResultModel.tenant_id == tenant_id,
                Topic4ModuleResultModel.verification_id == verification_id,
            )
            .order_by(Topic4ModuleResultModel.claim_id, Topic4ModuleResultModel.module)
        )
        return [ModuleRunResultV1.model_validate(row.result_document) for row in result.scalars()]

    async def append_claim_verdicts(
        self,
        session: AsyncSession,
        tenant_id: str,
        verdicts: list[ClaimVerdictV1],
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        for verdict in verdicts:
            self._assert_record_tenant(tenant_id, verdict.tenant_id)
            session.add(
                Topic4ClaimVerdictModel(
                    claim_verdict_record_id=verdict.claim_verdict_id,
                    claim_verdict_id=verdict.claim_verdict_id,
                    verification_id=verdict.verification_id,
                    claim_id=verdict.claim_id,
                    verdict=verdict.verdict.value,
                    confidence=verdict.confidence,
                    non_waivable=verdict.non_waivable,
                    verdict_document=verdict.model_dump(mode="json"),
                    **self._record_columns(verdict, audit_event_id),
                )
            )
        await session.flush()

    async def list_claim_verdicts(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> list[ClaimVerdictV1]:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4ClaimVerdictModel)
            .where(
                Topic4ClaimVerdictModel.tenant_id == tenant_id,
                Topic4ClaimVerdictModel.verification_id == verification_id,
            )
            .order_by(Topic4ClaimVerdictModel.claim_id, Topic4ClaimVerdictModel.version_cas)
        )
        return [ClaimVerdictV1.model_validate(row.verdict_document) for row in result.scalars()]

    async def append_aggregation(
        self,
        session: AsyncSession,
        tenant_id: str,
        aggregation: AggregationResultV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, aggregation.tenant_id)
        session.add(
            Topic4AggregationResultModel(
                aggregation_record_id=aggregation.aggregation_result_id,
                aggregation_result_id=aggregation.aggregation_result_id,
                verification_id=aggregation.verification_id,
                candidate_id=aggregation.candidate_id,
                candidate_version=aggregation.candidate_version,
                candidate_sha256=aggregation.candidate_sha256,
                decision=aggregation.decision.value,
                overall_confidence=aggregation.overall_confidence,
                unsafe_count=aggregation.unsafe_count,
                policy_version=aggregation.policy_version,
                result_document=aggregation.model_dump(mode="json"),
                **self._record_columns(aggregation, audit_event_id),
            )
        )
        await session.flush()

    async def latest_aggregation(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> AggregationResultV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4AggregationResultModel)
            .where(
                Topic4AggregationResultModel.tenant_id == tenant_id,
                Topic4AggregationResultModel.verification_id == verification_id,
            )
            .order_by(Topic4AggregationResultModel.version_cas.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else AggregationResultV1.model_validate(row.result_document)

    async def append_report(
        self,
        session: AsyncSession,
        tenant_id: str,
        report: VerificationReportV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, report.tenant_id)
        session.add(
            Topic4VerificationReportModel(
                report_record_id=report.report_id,
                report_id=report.report_id,
                verification_id=report.verification_id,
                candidate_id=report.candidate_id,
                candidate_version=report.candidate_version,
                candidate_sha256=report.candidate_sha256,
                aggregation_result_id=report.aggregation_result_id,
                knowledge_base_version=report.knowledge_base_version,
                decision=report.decision.value,
                report_sha256=report.report_sha256,
                policy_version=report.policy_version,
                report_document=report.model_dump(mode="json"),
                completed_at=report.completed_at,
                **self._record_columns(report, audit_event_id),
            )
        )
        await session.flush()

    async def latest_report(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> VerificationReportV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4VerificationReportModel)
            .where(
                Topic4VerificationReportModel.tenant_id == tenant_id,
                Topic4VerificationReportModel.verification_id == verification_id,
            )
            .order_by(Topic4VerificationReportModel.version_cas.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else VerificationReportV1.model_validate(row.report_document)

    async def append_review_task(
        self,
        session: AsyncSession,
        tenant_id: str,
        task: HumanReviewTaskV1,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, task.tenant_id)
        session.add(
            Topic4HumanReviewTaskModel(
                review_task_snapshot_id=UUID(bytes=bytes.fromhex(task.record_sha256[:32])),
                review_task_id=task.review_task_id,
                task_version=task.version_cas,
                verification_id=task.verification_id,
                state=task.state.value,
                risk_level=task.risk_level.value,
                assigned_role=task.assigned_role,
                due_at=task.due_at,
                task_document=task.model_dump(mode="json"),
                **self._record_columns(task, audit_event_id),
            )
        )
        await session.flush()

    async def latest_review_task(
        self,
        session: AsyncSession,
        tenant_id: str,
        verification_id: UUID,
    ) -> HumanReviewTaskV1 | None:
        assert_tenant(tenant_id)
        result = await session.execute(
            select(Topic4HumanReviewTaskModel)
            .where(
                Topic4HumanReviewTaskModel.tenant_id == tenant_id,
                Topic4HumanReviewTaskModel.verification_id == verification_id,
            )
            .order_by(Topic4HumanReviewTaskModel.task_version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return None if row is None else HumanReviewTaskV1.model_validate(row.task_document)

    async def append_review_decision(
        self,
        session: AsyncSession,
        tenant_id: str,
        decision: HumanReviewDecisionV1,
        *,
        review_task_version: int,
        audit_event_id: UUID,
    ) -> None:
        self._assert_write(session, tenant_id)
        self._assert_record_tenant(tenant_id, decision.tenant_id)
        session.add(
            Topic4HumanReviewDecisionModel(
                review_decision_record_id=decision.review_decision_id,
                review_decision_id=decision.review_decision_id,
                review_task_id=decision.review_task_id,
                review_task_version=review_task_version,
                verification_id=decision.verification_id,
                decision=decision.decision.value,
                reviewer_subject_ref=decision.reviewer_subject_ref,
                decision_document=decision.model_dump(mode="json"),
                decided_at=decision.decided_at,
                **self._record_columns(decision, audit_event_id),
            )
        )
        await session.flush()

    async def evidence_digests(
        self,
        session: AsyncSession,
        tenant_id: str,
        evidence_ref_ids: set[UUID],
    ) -> dict[UUID, str]:
        assert_tenant(tenant_id)
        if not evidence_ref_ids:
            return {}
        result = await session.execute(
            select(
                Topic4EvidenceRefModel.evidence_ref_id,
                Topic4EvidenceRefModel.record_sha256,
            ).where(
                Topic4EvidenceRefModel.tenant_id == tenant_id,
                Topic4EvidenceRefModel.evidence_ref_id.in_(evidence_ref_ids),
            )
        )
        return {evidence_ref_id: digest for evidence_ref_id, digest in result.all()}

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
            raise LiyanError(
                ErrorCode.TENANT_MISMATCH,
                "Topic 4 record tenant does not match the transaction tenant.",
                category=ErrorCategory.TENANT,
                status_code=403,
            )

    @staticmethod
    def _assert_write(session: AsyncSession, tenant_id: str) -> None:
        assert_tenant(tenant_id)
        if not session.in_transaction():
            raise LiyanError(
                ErrorCode.DATABASE_TRANSACTION_STATE,
                "Topic 4 persistence requires an active transaction.",
                category=ErrorCategory.DATABASE,
                status_code=500,
            )
