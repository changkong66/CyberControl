from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import VerificationProfile
from liyans_contracts.topic4_c1 import (
    ClaimRiskV1,
    ClaimV1,
    ModuleDispatchItemV1,
    ModuleDispatchPlanV1,
)
from liyans_contracts.topic4_common import RiskLevel, VerificationModule

from .records import build_topic4_record

_MODULE_TIMEOUT_MS: dict[VerificationModule, int] = {
    VerificationModule.C2_RAG: 2_000,
    VerificationModule.C3_ACADEMIC: 8_000,
    VerificationModule.C4_GRAPH: 3_000,
    VerificationModule.C5_QUIZ: 8_000,
    VerificationModule.C6_CODE: 30_000,
    VerificationModule.C7_EXTENSION: 8_000,
    VerificationModule.C9_SECURITY: 2_000,
    VerificationModule.C10_PRIVACY: 2_000,
    VerificationModule.C11_COMPLIANCE: 8_000,
}

_MODULE_ORDER = {module: index for index, module in enumerate(VerificationModule)}


class DispatchPlanError(ValueError):
    """Raised when a dispatch plan cannot be proven acyclic and complete."""


@dataclass(frozen=True, slots=True)
class DispatchPolicy:
    policy_version: str
    standard_parallelism: int = 16
    strict_parallelism: int = 8
    code_parallelism: int = 6

    def __post_init__(self) -> None:
        if not self.policy_version or len(self.policy_version) > 128:
            raise ValueError("dispatch policy version must contain 1 to 128 characters")
        parallelism = (
            self.standard_parallelism,
            self.strict_parallelism,
            self.code_parallelism,
        )
        if any(value < 1 or value > 32 for value in parallelism):
            raise ValueError("dispatch parallelism must be between 1 and 32")


class ModuleDispatchPlanner:
    def __init__(self, policy: DispatchPolicy) -> None:
        self._policy = policy

    def plan(
        self,
        claims: list[ClaimV1],
        risks: list[ClaimRiskV1],
        *,
        profile: VerificationProfile,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> ModuleDispatchPlanV1:
        if not claims:
            raise DispatchPlanError("dispatch requires at least one claim")
        risk_by_claim = {risk.claim_id: risk for risk in risks}
        claim_ids = {claim.claim_id for claim in claims}
        if set(risk_by_claim) != claim_ids:
            raise DispatchPlanError("every claim must have exactly one risk assessment")

        plan_seed = canonical_sha256(
            {
                "verification_id": str(claims[0].verification_id),
                "claim_ids": [str(claim.claim_id) for claim in claims],
                "policy_version": self._policy.policy_version,
                "profile": profile.value,
            }
        )
        dispatch_plan_id = uuid5(
            NAMESPACE_URL,
            f"liyans:topic4:dispatch-plan:{tenant_id}:{plan_seed}",
        )
        items: list[ModuleDispatchItemV1] = []
        for claim in claims:
            risk = risk_by_claim[claim.claim_id]
            items.extend(
                self._claim_items(
                    claim,
                    risk,
                    dispatch_plan_id=dispatch_plan_id,
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    created_at=created_at,
                )
            )

        items.sort(
            key=lambda item: (
                -item.priority,
                str(item.claim_id),
                _MODULE_ORDER[item.module],
            )
        )
        self.execution_waves(items)
        max_parallelism = self._parallelism(profile)
        plan_sha256 = canonical_sha256(
            {
                "dispatch_plan_id": str(dispatch_plan_id),
                "verification_id": str(claims[0].verification_id),
                "claim_ids": [str(claim.claim_id) for claim in claims],
                "items": [item.model_dump(mode="json") for item in items],
                "max_parallelism": max_parallelism,
                "policy_version": self._policy.policy_version,
            }
        )
        return build_topic4_record(
            ModuleDispatchPlanV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="module-dispatch-plan.v1",
            dispatch_plan_id=dispatch_plan_id,
            verification_id=claims[0].verification_id,
            claim_ids=[claim.claim_id for claim in claims],
            items=items,
            max_parallelism=max_parallelism,
            policy_version=self._policy.policy_version,
            plan_sha256=plan_sha256,
        )

    def _claim_items(
        self,
        claim: ClaimV1,
        risk: ClaimRiskV1,
        *,
        dispatch_plan_id: UUID,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> list[ModuleDispatchItemV1]:
        item_ids = {
            module: uuid5(
                NAMESPACE_URL,
                (
                    f"liyans:topic4:dispatch-item:{tenant_id}:{dispatch_plan_id}:"
                    f"{claim.claim_id}:{module.value}"
                ),
            )
            for module in risk.mandatory_modules
        }
        items: list[ModuleDispatchItemV1] = []
        for module in risk.mandatory_modules:
            dependencies = self._dependencies(module, item_ids)
            items.append(
                build_topic4_record(
                    ModuleDispatchItemV1,
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    version_cas=1,
                    created_at=created_at,
                    immutable=True,
                    schema_version="module-dispatch-item.v1",
                    dispatch_item_id=item_ids[module],
                    claim_id=claim.claim_id,
                    module=module,
                    required=True,
                    priority=self._priority(risk.level, module),
                    dependency_item_ids=dependencies,
                    timeout_ms=_MODULE_TIMEOUT_MS[module],
                    max_attempts=2,
                )
            )
        return items

    @staticmethod
    def _dependencies(
        module: VerificationModule,
        item_ids: dict[VerificationModule, UUID],
    ) -> list[UUID]:
        if module in {
            VerificationModule.C3_ACADEMIC,
            VerificationModule.C4_GRAPH,
            VerificationModule.C5_QUIZ,
            VerificationModule.C6_CODE,
            VerificationModule.C7_EXTENSION,
            VerificationModule.C11_COMPLIANCE,
        }:
            rag_item_id = item_ids.get(VerificationModule.C2_RAG)
            return [] if rag_item_id is None else [rag_item_id]
        return []

    @staticmethod
    def _priority(level: RiskLevel, module: VerificationModule) -> int:
        risk_priority = {
            RiskLevel.LOW: 400,
            RiskLevel.MEDIUM: 550,
            RiskLevel.HIGH: 750,
            RiskLevel.CRITICAL: 900,
        }[level]
        module_priority = {
            VerificationModule.C9_SECURITY: 50,
            VerificationModule.C10_PRIVACY: 40,
            VerificationModule.C2_RAG: 30,
            VerificationModule.C11_COMPLIANCE: 20,
        }.get(module, 10)
        return min(1000, risk_priority + module_priority)

    def _parallelism(self, profile: VerificationProfile) -> int:
        return {
            VerificationProfile.STANDARD: self._policy.standard_parallelism,
            VerificationProfile.STRICT: self._policy.strict_parallelism,
            VerificationProfile.CODE_STRICT: self._policy.code_parallelism,
        }[profile]

    @staticmethod
    def execution_waves(
        items: list[ModuleDispatchItemV1],
    ) -> list[list[ModuleDispatchItemV1]]:
        item_by_id = {item.dispatch_item_id: item for item in items}
        if len(item_by_id) != len(items):
            raise DispatchPlanError("dispatch item identifiers must be unique")
        unknown_dependencies = {
            dependency
            for item in items
            for dependency in item.dependency_item_ids
            if dependency not in item_by_id
        }
        if unknown_dependencies:
            raise DispatchPlanError("dispatch plan references an unknown dependency")

        remaining = set(item_by_id)
        completed: set[UUID] = set()
        waves: list[list[ModuleDispatchItemV1]] = []
        while remaining:
            ready_ids = sorted(
                (
                    item_id
                    for item_id in remaining
                    if set(item_by_id[item_id].dependency_item_ids) <= completed
                ),
                key=str,
            )
            if not ready_ids:
                raise DispatchPlanError("dispatch plan contains a dependency cycle")
            wave = [item_by_id[item_id] for item_id in ready_ids]
            waves.append(wave)
            completed.update(ready_ids)
            remaining.difference_update(ready_ids)
        return waves
