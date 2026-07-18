from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid5

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import (
    ClaimV1,
    ModuleDispatchItemV1,
    ModuleDispatchPlanV1,
    ModuleRunResultV1,
    ModuleRunV1,
)
from liyans_contracts.topic4_common import (
    ModuleRunState,
    VerificationModule,
    VerificationVerdict,
)

from .dispatch import ModuleDispatchPlanner
from .records import build_topic4_record, record_integrity_valid


@dataclass(frozen=True, slots=True)
class ModuleFinding:
    verdict: VerificationVerdict
    confidence: float
    evidence_ref_ids: tuple[UUID, ...]
    finding_codes: tuple[str, ...]
    result_artifact: ArtifactObjectRefV1
    result_sha256: str
    deterministic: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("module finding confidence must be between zero and one")
        if self.result_artifact.sha256 != self.result_sha256:
            raise ValueError("module finding artifact hash does not match result_sha256")
        if self.verdict == VerificationVerdict.SUPPORTED and not self.evidence_ref_ids:
            raise ValueError("supported module finding requires evidence")


@dataclass(frozen=True, slots=True)
class ModuleExecutionContext:
    verification_id: UUID
    dispatch_plan_id: UUID
    dispatch_item: ModuleDispatchItemV1
    claim: ClaimV1
    module_run_id: UUID
    attempt: int
    deadline_at: datetime


class VerificationModuleHandler(Protocol):
    async def verify(self, context: ModuleExecutionContext) -> ModuleFinding: ...


@dataclass(frozen=True, slots=True)
class ModuleExecutionBundle:
    run_snapshots: tuple[ModuleRunV1, ...]
    results: tuple[ModuleRunResultV1, ...]


@dataclass(frozen=True, slots=True)
class _ItemOutcome:
    dispatch_item_id: UUID
    runs: tuple[ModuleRunV1, ...]
    result: ModuleRunResultV1 | None


class BoundedModuleExecutor:
    """Executes the frozen dispatch DAG with bounded concurrency and retries."""

    def __init__(
        self,
        handlers: Mapping[VerificationModule, VerificationModuleHandler],
        *,
        worker_instance_id: str,
        retry_backoff_ms: int = 25,
    ) -> None:
        if not worker_instance_id or len(worker_instance_id) > 128:
            raise ValueError("worker_instance_id must contain 1 to 128 characters")
        if retry_backoff_ms < 0 or retry_backoff_ms > 5000:
            raise ValueError("retry_backoff_ms must be between zero and 5000")
        self._handlers = dict(handlers)
        self._worker_instance_id = worker_instance_id
        self._retry_backoff_ms = retry_backoff_ms

    async def execute(
        self,
        plan: ModuleDispatchPlanV1,
        claims: Sequence[ClaimV1],
        *,
        deadline_at: datetime,
    ) -> ModuleExecutionBundle:
        if deadline_at.tzinfo is None:
            raise ValueError("module execution deadline must be timezone-aware")
        claim_by_id = {claim.claim_id: claim for claim in claims}
        if set(plan.claim_ids) != set(claim_by_id):
            raise ValueError("dispatch plan and claim set differ")
        semaphore = asyncio.Semaphore(plan.max_parallelism)
        successful_items: set[UUID] = set()
        outcomes: list[_ItemOutcome] = []
        for wave in ModuleDispatchPlanner.execution_waves(plan.items):
            wave_outcomes = await asyncio.gather(
                *[
                    self._execute_or_skip(
                        plan,
                        item,
                        claim_by_id[item.claim_id],
                        successful_items=successful_items,
                        semaphore=semaphore,
                        deadline_at=deadline_at,
                    )
                    for item in wave
                ]
            )
            outcomes.extend(wave_outcomes)
            successful_items.update(
                outcome.dispatch_item_id for outcome in wave_outcomes if outcome.result is not None
            )
        ordered = {item.dispatch_item_id: index for index, item in enumerate(plan.items)}
        outcomes.sort(key=lambda outcome: ordered[outcome.dispatch_item_id])
        return ModuleExecutionBundle(
            run_snapshots=tuple(run for outcome in outcomes for run in outcome.runs),
            results=tuple(outcome.result for outcome in outcomes if outcome.result is not None),
        )

    async def _execute_or_skip(
        self,
        plan: ModuleDispatchPlanV1,
        item: ModuleDispatchItemV1,
        claim: ClaimV1,
        *,
        successful_items: set[UUID],
        semaphore: asyncio.Semaphore,
        deadline_at: datetime,
    ) -> _ItemOutcome:
        if not set(item.dependency_item_ids) <= successful_items:
            return self._skipped(plan, item, claim, deadline_at=deadline_at)
        async with semaphore:
            return await self._execute_item(plan, item, claim, deadline_at=deadline_at)

    async def _execute_item(
        self,
        plan: ModuleDispatchPlanV1,
        item: ModuleDispatchItemV1,
        claim: ClaimV1,
        *,
        deadline_at: datetime,
    ) -> _ItemOutcome:
        handler = self._handlers.get(item.module)
        if handler is None:
            return self._handler_missing(plan, item, claim, deadline_at=deadline_at)

        runs: list[ModuleRunV1] = []
        for attempt in range(1, item.max_attempts + 1):
            run_id = uuid5(item.dispatch_item_id, f"attempt:{attempt}")
            pending = self._run(
                plan,
                item,
                claim,
                run_id=run_id,
                version=1,
                attempt=attempt,
                state=ModuleRunState.PENDING,
                started_at=None,
                completed_at=None,
                error_code=None,
            )
            started_at = datetime.now(UTC)
            running = self._run(
                plan,
                item,
                claim,
                run_id=run_id,
                version=2,
                attempt=attempt,
                state=ModuleRunState.RUNNING,
                started_at=started_at,
                completed_at=None,
                error_code=None,
            )
            runs.extend((pending, running))
            finding, error_code, terminal_state = await self._invoke(
                handler,
                ModuleExecutionContext(
                    verification_id=plan.verification_id,
                    dispatch_plan_id=plan.dispatch_plan_id,
                    dispatch_item=item,
                    claim=claim,
                    module_run_id=run_id,
                    attempt=attempt,
                    deadline_at=deadline_at,
                ),
                timeout_ms=item.timeout_ms,
                deadline_at=deadline_at,
            )
            completed_at = datetime.now(UTC)
            terminal = self._run(
                plan,
                item,
                claim,
                run_id=run_id,
                version=3,
                attempt=attempt,
                state=terminal_state,
                started_at=started_at,
                completed_at=completed_at,
                error_code=error_code,
            )
            runs.append(terminal)
            if finding is not None:
                return _ItemOutcome(
                    dispatch_item_id=item.dispatch_item_id,
                    runs=tuple(runs),
                    result=self._result(terminal, finding),
                )
            if attempt < item.max_attempts and completed_at < deadline_at:
                await asyncio.sleep(self._retry_backoff_ms * attempt / 1000)
        return _ItemOutcome(item.dispatch_item_id, tuple(runs), None)

    async def _invoke(
        self,
        handler: VerificationModuleHandler,
        context: ModuleExecutionContext,
        *,
        timeout_ms: int,
        deadline_at: datetime,
    ) -> tuple[ModuleFinding | None, str | None, ModuleRunState]:
        remaining = (deadline_at - datetime.now(UTC)).total_seconds()
        timeout_seconds = min(timeout_ms / 1000, remaining)
        if timeout_seconds <= 0:
            return None, "VERIFICATION_DEADLINE_EXPIRED", ModuleRunState.TIMED_OUT
        try:
            async with asyncio.timeout(timeout_seconds):
                finding = await handler.verify(context)
            return finding, None, ModuleRunState.SUCCEEDED
        except TimeoutError:
            return None, "MODULE_TIMEOUT", ModuleRunState.TIMED_OUT
        except Exception:
            return None, "MODULE_HANDLER_ERROR", ModuleRunState.FAILED

    def _skipped(
        self,
        plan: ModuleDispatchPlanV1,
        item: ModuleDispatchItemV1,
        claim: ClaimV1,
        *,
        deadline_at: datetime,
    ) -> _ItemOutcome:
        now = min(datetime.now(UTC), deadline_at)
        run_id = uuid5(item.dispatch_item_id, "dependency-skipped")
        run = self._run(
            plan,
            item,
            claim,
            run_id=run_id,
            version=1,
            attempt=0,
            state=ModuleRunState.SKIPPED,
            started_at=now,
            completed_at=now,
            error_code="MODULE_DEPENDENCY_FAILED",
        )
        return _ItemOutcome(item.dispatch_item_id, (run,), None)

    def _handler_missing(
        self,
        plan: ModuleDispatchPlanV1,
        item: ModuleDispatchItemV1,
        claim: ClaimV1,
        *,
        deadline_at: datetime,
    ) -> _ItemOutcome:
        now = min(datetime.now(UTC), deadline_at)
        run_id = uuid5(item.dispatch_item_id, "handler-missing")
        run = self._run(
            plan,
            item,
            claim,
            run_id=run_id,
            version=1,
            attempt=0,
            state=ModuleRunState.FAILED,
            started_at=now,
            completed_at=now,
            error_code="MODULE_HANDLER_MISSING",
        )
        return _ItemOutcome(item.dispatch_item_id, (run,), None)

    def _run(
        self,
        plan: ModuleDispatchPlanV1,
        item: ModuleDispatchItemV1,
        claim: ClaimV1,
        *,
        run_id: UUID,
        version: int,
        attempt: int,
        state: ModuleRunState,
        started_at: datetime | None,
        completed_at: datetime | None,
        error_code: str | None,
    ) -> ModuleRunV1:
        return build_topic4_record(
            ModuleRunV1,
            trace_id=plan.trace_id,
            tenant_id=plan.tenant_id,
            version_cas=version,
            created_at=started_at or plan.created_at,
            immutable=True,
            schema_version="module-run.v1",
            module_run_id=run_id,
            verification_id=plan.verification_id,
            dispatch_plan_id=plan.dispatch_plan_id,
            dispatch_item_id=item.dispatch_item_id,
            claim_id=claim.claim_id,
            module=item.module,
            state=state,
            attempt=attempt,
            max_attempts=item.max_attempts,
            input_sha256=canonical_sha256(
                {
                    "claim_sha256": claim.claim_sha256,
                    "dispatch_item_sha256": item.record_sha256,
                }
            ),
            worker_instance_id=self._worker_instance_id,
            started_at=started_at,
            completed_at=completed_at,
            error_code=error_code,
        )

    @staticmethod
    def _result(run: ModuleRunV1, finding: ModuleFinding) -> ModuleRunResultV1:
        result = build_topic4_record(
            ModuleRunResultV1,
            trace_id=run.trace_id,
            tenant_id=run.tenant_id,
            version_cas=run.version_cas,
            created_at=run.completed_at,
            immutable=True,
            schema_version="module-run.result.v1",
            module_result_id=uuid5(run.module_run_id, "result"),
            module_run_id=run.module_run_id,
            verification_id=run.verification_id,
            claim_id=run.claim_id,
            module=run.module,
            verdict=finding.verdict,
            confidence=finding.confidence,
            evidence_ref_ids=list(finding.evidence_ref_ids),
            finding_codes=list(finding.finding_codes),
            result_artifact=finding.result_artifact,
            result_sha256=finding.result_sha256,
            deterministic=finding.deterministic,
        )
        if not record_integrity_valid(result):
            raise RuntimeError("module result record integrity validation failed")
        return result
