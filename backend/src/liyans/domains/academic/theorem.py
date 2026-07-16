from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from liyans_contracts.topic4_c2 import EvidenceRefV1
from liyans_contracts.topic4_c3 import (
    TheoremCheckResultV1,
    TheoremConditionResultV1,
    TheoremConditionV1,
    TheoremRegistryEntryV1,
)
from liyans_contracts.topic4_common import VerificationVerdict

from liyans.domains.verification.records import build_topic4_record

THEOREM_ENGINE_VERSION = "c3-theorem-engine-v1"
_WORD = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_NEGATION = frozenset(
    {
        "no",
        "not",
        "never",
        "without",
        "\u4e0d",
        "\u65e0",
        "\u672a",
        "\u5426",
    }
)
_STOP_WORDS = frozenset(
    {
        "a",
        "all",
        "an",
        "and",
        "are",
        "be",
        "for",
        "in",
        "is",
        "of",
        "or",
        "the",
        "to",
        "with",
    }
)


@dataclass(frozen=True, slots=True)
class TheoremConditionAssessment:
    satisfied: bool | None
    evidence_ref_ids: tuple[UUID, ...]
    reason: str

    def __post_init__(self) -> None:
        if not self.reason or len(self.reason) > 4096:
            raise ValueError("theorem condition reason must contain 1 to 4096 characters")
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("theorem condition evidence references must be unique")


class TheoremRegistry:
    def __init__(self, entries: tuple[TheoremRegistryEntryV1, ...] = ()) -> None:
        self._entries: dict[tuple[str, str], TheoremRegistryEntryV1] = {}
        for entry in entries:
            self.register(entry)

    def register(self, entry: TheoremRegistryEntryV1) -> None:
        key = (entry.tenant_id, entry.theorem_key)
        existing = self._entries.get(key)
        if existing is not None and existing.record_sha256 != entry.record_sha256:
            raise ValueError("theorem registry key is already bound to a different entry")
        self._entries[key] = entry

    def get(self, tenant_id: str, theorem_key: str) -> TheoremRegistryEntryV1 | None:
        if not tenant_id:
            raise ValueError("tenant_id cannot be blank")
        return self._entries.get((tenant_id, theorem_key))

    def list_for_tenant(self, tenant_id: str) -> tuple[TheoremRegistryEntryV1, ...]:
        return tuple(
            sorted(
                (entry for (owner, _), entry in self._entries.items() if owner == tenant_id),
                key=lambda entry: entry.theorem_key,
            )
        )


class TheoremRegistryBuilder:
    def build(
        self,
        *,
        theorem_key: str,
        name: str,
        domain: str,
        statement: str,
        conditions: tuple[tuple[str, str, bool], ...],
        conclusion: str,
        source_evidence_ref_ids: tuple[UUID, ...],
        registry_version: str,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> TheoremRegistryEntryV1:
        condition_records = [
            build_topic4_record(
                TheoremConditionV1,
                trace_id=trace_id,
                tenant_id=tenant_id,
                version_cas=1,
                created_at=created_at,
                immutable=True,
                schema_version="theorem-condition.v1",
                condition_id=condition_id,
                statement=condition_statement,
                mandatory=mandatory,
            )
            for condition_id, condition_statement, mandatory in conditions
        ]
        if len({condition.condition_id for condition in condition_records}) != len(
            condition_records
        ):
            raise ValueError("theorem condition identifiers must be unique")
        digest_source = ":".join(str(value) for value in source_evidence_ref_ids)
        entry_id = uuid5(
            NAMESPACE_URL,
            f"liyans:c3:theorem:{tenant_id}:{theorem_key}:{registry_version}:{digest_source}",
        )
        return build_topic4_record(
            TheoremRegistryEntryV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="theorem-registry.entry.v1",
            theorem_registry_entry_id=entry_id,
            theorem_key=theorem_key,
            name=name,
            domain=domain,
            statement=statement,
            conditions=condition_records,
            conclusion=conclusion,
            source_evidence_ref_ids=list(source_evidence_ref_ids),
            registry_version=registry_version,
        )


class EvidenceConditionResolver:
    def resolve(
        self,
        entry: TheoremRegistryEntryV1,
        evidence: tuple[EvidenceRefV1, ...],
        *,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> dict[str, TheoremConditionAssessment]:
        self._validate_evidence(
            evidence,
            tenant_id=tenant_id,
            verification_id=verification_id,
            claim_id=claim_id,
        )
        assessments: dict[str, TheoremConditionAssessment] = {}
        for condition in entry.conditions:
            condition_tokens = self._tokens(condition.statement) - _STOP_WORDS
            positive: list[UUID] = []
            negative: list[UUID] = []
            for ref in evidence:
                evidence_tokens = self._tokens(ref.excerpt)
                if not condition_tokens:
                    continue
                overlap = len(condition_tokens & evidence_tokens) / len(condition_tokens)
                if overlap < 0.55:
                    continue
                if evidence_tokens & _NEGATION:
                    negative.append(ref.evidence_ref_id)
                else:
                    positive.append(ref.evidence_ref_id)
            if positive and negative:
                assessments[condition.condition_id] = TheoremConditionAssessment(
                    satisfied=None,
                    evidence_ref_ids=tuple(sorted(set(positive + negative), key=str)),
                    reason="C3_THEOREM_CONFLICTING_EVIDENCE",
                )
            elif negative:
                assessments[condition.condition_id] = TheoremConditionAssessment(
                    satisfied=False,
                    evidence_ref_ids=tuple(sorted(set(negative), key=str)),
                    reason="C3_THEOREM_CONDITION_CONTRADICTED",
                )
            elif positive:
                assessments[condition.condition_id] = TheoremConditionAssessment(
                    satisfied=True,
                    evidence_ref_ids=tuple(sorted(set(positive), key=str)),
                    reason="C3_THEOREM_CONDITION_SUPPORTED",
                )
            else:
                assessments[condition.condition_id] = TheoremConditionAssessment(
                    satisfied=None,
                    evidence_ref_ids=(),
                    reason="C3_THEOREM_CONDITION_EVIDENCE_MISSING",
                )
        return assessments

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {token.casefold() for token in _WORD.findall(value)}

    @staticmethod
    def _validate_evidence(
        evidence: tuple[EvidenceRefV1, ...],
        *,
        tenant_id: str,
        verification_id: UUID,
        claim_id: UUID,
    ) -> None:
        for ref in evidence:
            if ref.tenant_id != tenant_id:
                raise ValueError("theorem evidence cannot cross tenant boundaries")
            if ref.verification_id != verification_id or ref.claim_id != claim_id:
                raise ValueError("theorem evidence must belong to the verified claim")


class TheoremVerifier:
    def check(
        self,
        entry: TheoremRegistryEntryV1,
        assessments: dict[str, TheoremConditionAssessment],
        *,
        verification_id: UUID,
        claim_id: UUID,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> TheoremCheckResultV1:
        if entry.tenant_id != tenant_id:
            raise ValueError("theorem verification cannot cross tenant boundaries")
        condition_results: list[TheoremConditionResultV1] = []
        mandatory_failed = False
        mandatory_unknown = False
        optional_failed = False
        for condition in entry.conditions:
            assessment = assessments.get(
                condition.condition_id,
                TheoremConditionAssessment(
                    satisfied=None,
                    evidence_ref_ids=(),
                    reason="C3_THEOREM_CONDITION_NOT_ASSESSED",
                ),
            )
            mandatory_failed |= condition.mandatory and assessment.satisfied is False
            mandatory_unknown |= condition.mandatory and assessment.satisfied is None
            optional_failed |= not condition.mandatory and assessment.satisfied is not True
            condition_results.append(
                build_topic4_record(
                    TheoremConditionResultV1,
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    version_cas=1,
                    created_at=created_at,
                    immutable=True,
                    schema_version="theorem-condition-result.v1",
                    condition_id=condition.condition_id,
                    satisfied=assessment.satisfied,
                    evidence_ref_ids=list(assessment.evidence_ref_ids),
                    reason=assessment.reason,
                )
            )
        all_satisfied = all(result.satisfied is True for result in condition_results)
        if mandatory_failed:
            verdict = VerificationVerdict.CONTRADICTED
            confidence = 0.97
        elif mandatory_unknown:
            verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
            confidence = 0.35
        elif optional_failed:
            verdict = VerificationVerdict.PARTIALLY_SUPPORTED
            confidence = 0.78
        else:
            verdict = VerificationVerdict.SUPPORTED
            confidence = 0.98
        result_id = uuid5(
            NAMESPACE_URL,
            (
                f"liyans:c3:theorem-result:{tenant_id}:{claim_id}:"
                f"{entry.theorem_registry_entry_id}:{entry.registry_version}"
            ),
        )
        return build_topic4_record(
            TheoremCheckResultV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="theorem-check.result.v1",
            theorem_check_result_id=result_id,
            verification_id=verification_id,
            claim_id=claim_id,
            theorem_registry_entry_id=entry.theorem_registry_entry_id,
            condition_results=condition_results,
            conclusion_supported=all_satisfied,
            verdict=verdict,
            confidence=confidence,
        )
