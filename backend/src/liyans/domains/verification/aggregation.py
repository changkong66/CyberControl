from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c1 import (
    AggregationResultV1,
    ClaimRiskV1,
    ClaimV1,
    ClaimVerdictV1,
    EvidenceChainItemV1,
    EvidenceChainManifestV1,
    ModuleRunResultV1,
)
from liyans_contracts.topic4_common import (
    AggregateDecision,
    RiskLevel,
    VerificationModule,
    VerificationVerdict,
)

from .records import build_topic4_record

_MODULE_WEIGHT: dict[VerificationModule, float] = {
    VerificationModule.C2_RAG: 1.15,
    VerificationModule.C3_ACADEMIC: 1.25,
    VerificationModule.C4_GRAPH: 1.15,
    VerificationModule.C5_QUIZ: 1.25,
    VerificationModule.C6_CODE: 1.25,
    VerificationModule.C7_EXTENSION: 1.10,
    VerificationModule.C9_SECURITY: 1.40,
    VerificationModule.C10_PRIVACY: 1.40,
    VerificationModule.C11_COMPLIANCE: 1.30,
}
_NON_WAIVABLE_MODULES = {
    VerificationModule.C9_SECURITY,
    VerificationModule.C10_PRIVACY,
    VerificationModule.C11_COMPLIANCE,
}


class AggregationError(ValueError):
    """Raised when module output cannot be aggregated without ambiguity."""


@dataclass(frozen=True, slots=True)
class AggregationPolicy:
    policy_version: str
    partial_release_max_risk: RiskLevel = RiskLevel.MEDIUM

    def __post_init__(self) -> None:
        if not self.policy_version or len(self.policy_version) > 128:
            raise ValueError("aggregation policy version must contain 1 to 128 characters")


class VerificationResultAggregator:
    def __init__(self, policy: AggregationPolicy) -> None:
        self._policy = policy

    def aggregate(
        self,
        claims: list[ClaimV1],
        risks: list[ClaimRiskV1],
        results: list[ModuleRunResultV1],
        *,
        revision_round: int,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> tuple[list[ClaimVerdictV1], AggregationResultV1]:
        if not claims:
            raise AggregationError("aggregation requires at least one claim")
        if revision_round < 0 or revision_round > 2:
            raise AggregationError("revision_round must be between zero and two")
        risk_by_claim = {risk.claim_id: risk for risk in risks}
        if set(risk_by_claim) != {claim.claim_id for claim in claims}:
            raise AggregationError("every claim must have exactly one risk assessment")

        results_by_claim: dict[UUID, list[ModuleRunResultV1]] = {}
        known_claims = set(risk_by_claim)
        for result in results:
            if result.claim_id not in known_claims:
                raise AggregationError("module result references an unknown claim")
            if result.verification_id != claims[0].verification_id:
                raise AggregationError("module result belongs to a different verification")
            results_by_claim.setdefault(result.claim_id, []).append(result)

        verdicts = [
            self._claim_verdict(
                claim,
                risk_by_claim[claim.claim_id],
                results_by_claim.get(claim.claim_id, []),
                trace_id=trace_id,
                tenant_id=tenant_id,
                created_at=created_at,
            )
            for claim in claims
        ]
        aggregation = self._candidate_decision(
            claims,
            risks,
            verdicts,
            revision_round=revision_round,
            trace_id=trace_id,
            tenant_id=tenant_id,
            created_at=created_at,
        )
        return verdicts, aggregation

    def _claim_verdict(
        self,
        claim: ClaimV1,
        risk: ClaimRiskV1,
        results: list[ModuleRunResultV1],
        *,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> ClaimVerdictV1:
        latest_by_module: dict[VerificationModule, ModuleRunResultV1] = {}
        for result in results:
            current = latest_by_module.get(result.module)
            result_order = (result.version_cas, result.created_at, str(result.module_result_id))
            current_order = (
                (-1, datetime.min.replace(tzinfo=result.created_at.tzinfo), "")
                if current is None
                else (current.version_cas, current.created_at, str(current.module_result_id))
            )
            if result_order > current_order:
                latest_by_module[result.module] = result

        missing = [module for module in risk.mandatory_modules if module not in latest_by_module]
        selected = [
            latest_by_module[module]
            for module in risk.mandatory_modules
            if module in latest_by_module
        ]
        if not selected:
            raise AggregationError(
                f"claim {claim.claim_id} has no completed module result to aggregate"
            )
        verdict_values = {result.verdict for result in selected}
        reasons = sorted({code for result in selected for code in result.finding_codes})
        if missing:
            reasons.append("MODULE_RESULT_MISSING")
        if len(results) > len(selected):
            reasons.append("MODULE_RESULT_SUPERSEDED")
        if VerificationVerdict.SUPPORTED in verdict_values and (
            VerificationVerdict.CONTRADICTED in verdict_values
            or VerificationVerdict.UNSAFE in verdict_values
        ):
            reasons.append("EVIDENCE_CONFLICT")

        verdict = self._resolve_verdict(verdict_values, missing=bool(missing))
        confidence = self._confidence(selected, missing_count=len(missing))
        evidence_ref_ids = sorted(
            {evidence_id for result in selected for evidence_id in result.evidence_ref_ids},
            key=str,
        )
        disclosure_codes: list[str] = []
        if verdict == VerificationVerdict.PARTIALLY_SUPPORTED:
            disclosure_codes.append("PARTIAL_SUPPORT_DISCLOSURE")
        if verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE:
            disclosure_codes.append("INSUFFICIENT_EVIDENCE_DISCLOSURE")
        non_waivable = verdict == VerificationVerdict.UNSAFE or any(
            result.module in _NON_WAIVABLE_MODULES
            and result.verdict in {VerificationVerdict.UNSAFE, VerificationVerdict.CONTRADICTED}
            for result in selected
        )
        verdict_seed = canonical_sha256(
            {
                "claim_id": str(claim.claim_id),
                "module_result_ids": [str(result.module_result_id) for result in selected],
                "missing_modules": [module.value for module in missing],
                "policy_version": self._policy.policy_version,
            }
        )
        return build_topic4_record(
            ClaimVerdictV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="claim.verdict.v1",
            claim_verdict_id=uuid5(
                NAMESPACE_URL,
                f"liyans:topic4:claim-verdict:{tenant_id}:{verdict_seed}",
            ),
            verification_id=claim.verification_id,
            claim_id=claim.claim_id,
            verdict=verdict,
            confidence=round(confidence, 6),
            module_result_ids=[result.module_result_id for result in selected],
            evidence_ref_ids=evidence_ref_ids,
            reason_codes=sorted(set(reasons)),
            disclosure_codes=disclosure_codes,
            non_waivable=non_waivable,
        )

    @staticmethod
    def _resolve_verdict(
        verdicts: set[VerificationVerdict],
        *,
        missing: bool,
    ) -> VerificationVerdict:
        if VerificationVerdict.UNSAFE in verdicts:
            return VerificationVerdict.UNSAFE
        if VerificationVerdict.ERROR in verdicts or missing:
            return VerificationVerdict.ERROR
        if VerificationVerdict.CONTRADICTED in verdicts:
            return VerificationVerdict.CONTRADICTED
        if VerificationVerdict.INSUFFICIENT_EVIDENCE in verdicts:
            return VerificationVerdict.INSUFFICIENT_EVIDENCE
        if VerificationVerdict.PARTIALLY_SUPPORTED in verdicts:
            return VerificationVerdict.PARTIALLY_SUPPORTED
        if verdicts == {VerificationVerdict.NOT_APPLICABLE}:
            return VerificationVerdict.NOT_APPLICABLE
        if verdicts <= {VerificationVerdict.SUPPORTED, VerificationVerdict.NOT_APPLICABLE}:
            return VerificationVerdict.SUPPORTED
        return VerificationVerdict.ERROR

    @staticmethod
    def _confidence(results: list[ModuleRunResultV1], *, missing_count: int) -> float:
        if not results:
            return 0.0
        weighted = sum(result.confidence * _MODULE_WEIGHT[result.module] for result in results)
        total_weight = sum(_MODULE_WEIGHT[result.module] for result in results)
        confidence = weighted / total_weight
        if missing_count:
            confidence *= max(0.0, 1.0 - min(0.75, missing_count * 0.15))
        return max(0.0, min(1.0, confidence))

    def _candidate_decision(
        self,
        claims: list[ClaimV1],
        risks: list[ClaimRiskV1],
        verdicts: list[ClaimVerdictV1],
        *,
        revision_round: int,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> AggregationResultV1:
        claim_by_id = {claim.claim_id: claim for claim in claims}
        risk_by_claim = {risk.claim_id: risk for risk in risks}
        supported_count = sum(
            verdict.verdict in {VerificationVerdict.SUPPORTED, VerificationVerdict.NOT_APPLICABLE}
            for verdict in verdicts
        )
        contradicted_count = sum(
            verdict.verdict == VerificationVerdict.CONTRADICTED for verdict in verdicts
        )
        insufficient_count = sum(
            verdict.verdict
            in {VerificationVerdict.INSUFFICIENT_EVIDENCE, VerificationVerdict.ERROR}
            for verdict in verdicts
        )
        unsafe_count = sum(verdict.verdict == VerificationVerdict.UNSAFE for verdict in verdicts)
        partial = [
            verdict
            for verdict in verdicts
            if verdict.verdict == VerificationVerdict.PARTIALLY_SUPPORTED
        ]
        non_waivable = any(verdict.non_waivable for verdict in verdicts)
        critical_unresolved = any(
            risk_by_claim[verdict.claim_id].level == RiskLevel.CRITICAL
            and verdict.verdict
            not in {VerificationVerdict.SUPPORTED, VerificationVerdict.NOT_APPLICABLE}
            for verdict in verdicts
        )
        decision = self._decision(
            unsafe_count=unsafe_count,
            contradicted_count=contradicted_count,
            insufficient_count=insufficient_count,
            partial=partial,
            non_waivable=non_waivable,
            critical_unresolved=critical_unresolved,
            revision_round=revision_round,
            risk_by_claim=risk_by_claim,
        )
        revision_verdicts = [
            verdict
            for verdict in verdicts
            if verdict.verdict
            in {
                VerificationVerdict.PARTIALLY_SUPPORTED,
                VerificationVerdict.CONTRADICTED,
                VerificationVerdict.INSUFFICIENT_EVIDENCE,
                VerificationVerdict.ERROR,
            }
        ]
        revision_block_ids = sorted(
            {claim_by_id[verdict.claim_id].block_id for verdict in revision_verdicts}
        )
        disclosure_codes = sorted(
            {code for verdict in verdicts for code in verdict.disclosure_codes}
        )
        if decision == AggregateDecision.RELEASE_WITH_DISCLOSURE and not disclosure_codes:
            disclosure_codes.append("PARTIAL_SUPPORT_DISCLOSURE")
        overall_confidence = self._overall_confidence(verdicts, risk_by_claim)
        candidate = claims[0]
        seed = canonical_sha256(
            {
                "verification_id": str(candidate.verification_id),
                "claim_verdict_ids": [str(verdict.claim_verdict_id) for verdict in verdicts],
                "decision": decision.value,
                "revision_round": revision_round,
                "policy_version": self._policy.policy_version,
            }
        )
        return build_topic4_record(
            AggregationResultV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=revision_round + 1,
            created_at=created_at,
            immutable=True,
            schema_version="aggregation.result.v1",
            aggregation_result_id=uuid5(
                NAMESPACE_URL,
                f"liyans:topic4:aggregation:{tenant_id}:{seed}",
            ),
            verification_id=candidate.verification_id,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            candidate_sha256=candidate.candidate_sha256,
            decision=decision,
            claim_verdict_ids=[verdict.claim_verdict_id for verdict in verdicts],
            supported_count=supported_count,
            contradicted_count=contradicted_count,
            insufficient_count=insufficient_count,
            unsafe_count=unsafe_count,
            overall_confidence=round(overall_confidence, 6),
            revision_block_ids=revision_block_ids,
            disclosure_codes=disclosure_codes,
            policy_version=self._policy.policy_version,
        )

    def _decision(
        self,
        *,
        unsafe_count: int,
        contradicted_count: int,
        insufficient_count: int,
        partial: list[ClaimVerdictV1],
        non_waivable: bool,
        critical_unresolved: bool,
        revision_round: int,
        risk_by_claim: dict[UUID, ClaimRiskV1],
    ) -> AggregateDecision:
        if unsafe_count or non_waivable:
            return AggregateDecision.BLOCK
        if critical_unresolved:
            return AggregateDecision.REVIEW_REQUIRED
        if contradicted_count or insufficient_count:
            return (
                AggregateDecision.REVISE
                if revision_round < 2
                else AggregateDecision.REVIEW_REQUIRED
            )
        if partial:
            allowed = {RiskLevel.LOW, self._policy.partial_release_max_risk}
            if all(risk_by_claim[item.claim_id].level in allowed for item in partial):
                return AggregateDecision.RELEASE_WITH_DISCLOSURE
            return (
                AggregateDecision.REVISE
                if revision_round < 2
                else AggregateDecision.REVIEW_REQUIRED
            )
        return AggregateDecision.RELEASE

    @staticmethod
    def _overall_confidence(
        verdicts: list[ClaimVerdictV1],
        risk_by_claim: dict[UUID, ClaimRiskV1],
    ) -> float:
        weights = [1.0 + risk_by_claim[verdict.claim_id].score for verdict in verdicts]
        total = sum(weights)
        return (
            sum(
                verdict.confidence * weight
                for verdict, weight in zip(verdicts, weights, strict=True)
            )
            / total
        )


def build_evidence_chain_manifest(
    *,
    verification_id: UUID,
    report_id: UUID,
    evidence_digests: dict[UUID, str],
    module_results: list[ModuleRunResultV1],
    trace_id: str,
    tenant_id: str,
    created_at: datetime,
) -> EvidenceChainManifestV1:
    referenced_ids = sorted(
        {evidence_id for result in module_results for evidence_id in result.evidence_ref_ids},
        key=str,
    )
    if referenced_ids:
        missing = [
            evidence_id for evidence_id in referenced_ids if evidence_id not in evidence_digests
        ]
        if missing:
            raise AggregationError("evidence digest lookup is incomplete")
        evidence = [(evidence_id, evidence_digests[evidence_id]) for evidence_id in referenced_ids]
    else:
        evidence = sorted(
            ((result.module_result_id, result.result_sha256) for result in module_results),
            key=lambda item: str(item[0]),
        )
    if not evidence:
        raise AggregationError("verification report requires at least one evidence-chain item")

    previous_hash: str | None = None
    items: list[EvidenceChainItemV1] = []
    for sequence, (evidence_ref_id, digest) in enumerate(evidence):
        chain_sha256 = canonical_sha256(
            {
                "sequence": sequence,
                "evidence_ref_id": str(evidence_ref_id),
                "evidence_sha256": digest,
                "previous_chain_sha256": previous_hash,
            }
        )
        items.append(
            build_topic4_record(
                EvidenceChainItemV1,
                trace_id=trace_id,
                tenant_id=tenant_id,
                version_cas=1,
                created_at=created_at,
                immutable=True,
                schema_version="evidence-chain-item.v1",
                evidence_ref_id=evidence_ref_id,
                sequence=sequence,
                evidence_sha256=digest,
                previous_chain_sha256=previous_hash,
                chain_sha256=chain_sha256,
            )
        )
        previous_hash = chain_sha256

    manifest_seed = canonical_sha256(
        {
            "verification_id": str(verification_id),
            "report_id": str(report_id),
            "root_chain_sha256": previous_hash,
        }
    )
    return build_topic4_record(
        EvidenceChainManifestV1,
        trace_id=trace_id,
        tenant_id=tenant_id,
        version_cas=1,
        created_at=created_at,
        immutable=True,
        schema_version="evidence-chain-manifest.v1",
        evidence_chain_manifest_id=uuid5(
            NAMESPACE_URL,
            f"liyans:topic4:evidence-chain:{tenant_id}:{manifest_seed}",
        ),
        verification_id=verification_id,
        report_id=report_id,
        items=items,
        root_chain_sha256=previous_hash,
    )
