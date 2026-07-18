from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .artifacts import ArtifactObjectRefV1
from .common import Sha256Hex, VersionString
from .enums import SourceAgent
from .topic4_common import (
    AggregateDecision,
    BlockId,
    ClaimKind,
    ModuleRunState,
    ReasonCode,
    RiskLevel,
    Topic4RecordV1,
    VerificationModule,
    VerificationVerdict,
)
from .verification import VerificationState


class ExtractionMethod(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    SPARK_STRUCTURED = "SPARK_STRUCTURED"
    HYBRID = "HYBRID"


class ReviewTaskState(StrEnum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    DECIDED = "DECIDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    APPROVE_WITH_DISCLOSURE = "APPROVE_WITH_DISCLOSURE"
    REVISE = "REVISE"
    BLOCK = "BLOCK"


class PublicationState(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


class ModuleDispatchItemV1(Topic4RecordV1):
    schema_version: Literal["module-dispatch-item.v1"]
    dispatch_item_id: UUID
    claim_id: UUID
    module: VerificationModule
    required: bool
    priority: int = Field(ge=0, le=1000)
    dependency_item_ids: list[UUID] = Field(default_factory=list, max_length=16)
    timeout_ms: int = Field(ge=100, le=120_000)
    max_attempts: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def validate_dependencies(self) -> ModuleDispatchItemV1:
        if self.dispatch_item_id in self.dependency_item_ids:
            raise ValueError("dispatch item cannot depend on itself")
        if len(self.dependency_item_ids) != len(set(self.dependency_item_ids)):
            raise ValueError("dependency_item_ids must be unique")
        return self


class VerificationProgressV1(Topic4RecordV1):
    schema_version: Literal["verification.progress.v1"]
    verification_id: UUID
    state: VerificationState
    state_version: int = Field(ge=1)
    completed_modules: int = Field(ge=0, le=12)
    total_modules: int = Field(ge=0, le=12)
    progress_percent: float = Field(ge=0.0, le=100.0)
    current_stage: str = Field(min_length=1, max_length=128)
    revision_round: int = Field(ge=0, le=2)
    deadline_at: AwareDatetime

    @model_validator(mode="after")
    def validate_progress(self) -> VerificationProgressV1:
        if self.completed_modules > self.total_modules:
            raise ValueError("completed_modules cannot exceed total_modules")
        if self.deadline_at <= self.created_at:
            raise ValueError("deadline_at must be after created_at")
        return self


class ClaimV1(Topic4RecordV1):
    schema_version: Literal["claim.v1"]
    claim_id: UUID
    verification_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    candidate_sha256: Sha256Hex
    block_id: BlockId
    claim_kind: ClaimKind
    claim_subtype: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=32_768)
    normalized_statement: str = Field(min_length=1, max_length=32_768)
    json_pointer: str = Field(min_length=1, max_length=1024)
    ordinal: int = Field(ge=0)
    source_span_start: int = Field(ge=0)
    source_span_end: int = Field(gt=0)
    claim_sha256: Sha256Hex
    extraction_method: ExtractionMethod
    dependent_claim_ids: list[UUID] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_claim(self) -> ClaimV1:
        if self.source_span_end <= self.source_span_start:
            raise ValueError("source span must be non-empty")
        if self.claim_id in self.dependent_claim_ids:
            raise ValueError("claim cannot depend on itself")
        if len(self.dependent_claim_ids) != len(set(self.dependent_claim_ids)):
            raise ValueError("dependent_claim_ids must be unique")
        return self


class ClaimRiskV1(Topic4RecordV1):
    schema_version: Literal["claim.risk.v1"]
    risk_id: UUID
    verification_id: UUID
    claim_id: UUID
    level: RiskLevel
    score: float = Field(ge=0.0, le=1.0)
    academic_impact: float = Field(ge=0.0, le=1.0)
    learner_harm: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    irreversibility: float = Field(ge=0.0, le=1.0)
    external_action: float = Field(ge=0.0, le=1.0)
    mandatory_modules: list[VerificationModule] = Field(min_length=1, max_length=9)
    reason_codes: list[ReasonCode] = Field(min_length=1, max_length=32)
    policy_version: VersionString

    @model_validator(mode="after")
    def validate_modules(self) -> ClaimRiskV1:
        if len(self.mandatory_modules) != len(set(self.mandatory_modules)):
            raise ValueError("mandatory_modules must be unique")
        if self.level == RiskLevel.CRITICAL and self.score < 0.75:
            raise ValueError("critical risk requires score >= 0.75")
        return self


class ModuleDispatchPlanV1(Topic4RecordV1):
    schema_version: Literal["module-dispatch-plan.v1"]
    dispatch_plan_id: UUID
    verification_id: UUID
    claim_ids: list[UUID] = Field(min_length=1, max_length=4096)
    items: list[ModuleDispatchItemV1] = Field(min_length=1, max_length=36_864)
    max_parallelism: int = Field(ge=1, le=32)
    policy_version: VersionString
    plan_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_plan(self) -> ModuleDispatchPlanV1:
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("claim_ids must be unique")
        item_ids = [item.dispatch_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("dispatch item ids must be unique")
        claim_ids = set(self.claim_ids)
        if any(item.claim_id not in claim_ids for item in self.items):
            raise ValueError("dispatch item references an unknown claim")
        known_items = set(item_ids)
        if any(set(item.dependency_item_ids) - known_items for item in self.items):
            raise ValueError("dispatch dependency references an unknown item")
        return self


class ModuleRunV1(Topic4RecordV1):
    schema_version: Literal["module-run.v1"]
    module_run_id: UUID
    verification_id: UUID
    dispatch_plan_id: UUID
    dispatch_item_id: UUID
    claim_id: UUID
    module: VerificationModule
    state: ModuleRunState
    attempt: int = Field(ge=0, le=5)
    max_attempts: int = Field(ge=1, le=5)
    input_sha256: Sha256Hex
    worker_instance_id: str | None = Field(default=None, min_length=1, max_length=128)
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    error_code: ReasonCode | None = None

    @model_validator(mode="after")
    def validate_run(self) -> ModuleRunV1:
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        terminal = {
            ModuleRunState.SUCCEEDED,
            ModuleRunState.FAILED,
            ModuleRunState.TIMED_OUT,
            ModuleRunState.SKIPPED,
            ModuleRunState.CANCELLED,
        }
        if self.state in terminal and self.completed_at is None:
            raise ValueError("terminal module run requires completed_at")
        if self.completed_at is not None and self.started_at is None:
            raise ValueError("completed module run requires started_at")
        if self.started_at and self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        return self


class ModuleRunResultV1(Topic4RecordV1):
    schema_version: Literal["module-run.result.v1"]
    module_result_id: UUID
    module_run_id: UUID
    verification_id: UUID
    claim_id: UUID
    module: VerificationModule
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ref_ids: list[UUID] = Field(default_factory=list, max_length=512)
    finding_codes: list[ReasonCode] = Field(default_factory=list, max_length=128)
    result_artifact: ArtifactObjectRefV1
    result_sha256: Sha256Hex
    deterministic: bool

    @model_validator(mode="after")
    def require_evidence(self) -> ModuleRunResultV1:
        if self.verdict == VerificationVerdict.SUPPORTED and not self.evidence_ref_ids:
            raise ValueError("supported module result requires evidence")
        return self


class ClaimVerdictV1(Topic4RecordV1):
    schema_version: Literal["claim.verdict.v1"]
    claim_verdict_id: UUID
    verification_id: UUID
    claim_id: UUID
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    module_result_ids: list[UUID] = Field(min_length=1, max_length=32)
    evidence_ref_ids: list[UUID] = Field(default_factory=list, max_length=1024)
    reason_codes: list[ReasonCode] = Field(default_factory=list, max_length=128)
    disclosure_codes: list[ReasonCode] = Field(default_factory=list, max_length=32)
    non_waivable: bool


class AggregationResultV1(Topic4RecordV1):
    schema_version: Literal["aggregation.result.v1"]
    aggregation_result_id: UUID
    verification_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    candidate_sha256: Sha256Hex
    decision: AggregateDecision
    claim_verdict_ids: list[UUID] = Field(min_length=1, max_length=4096)
    supported_count: int = Field(ge=0)
    contradicted_count: int = Field(ge=0)
    insufficient_count: int = Field(ge=0)
    unsafe_count: int = Field(ge=0)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    revision_block_ids: list[BlockId] = Field(default_factory=list, max_length=2048)
    disclosure_codes: list[ReasonCode] = Field(default_factory=list, max_length=32)
    policy_version: VersionString

    @model_validator(mode="after")
    def validate_decision(self) -> AggregationResultV1:
        if self.decision == AggregateDecision.REVISE and not self.revision_block_ids:
            raise ValueError("revision decision requires revision_block_ids")
        if self.decision == AggregateDecision.RELEASE_WITH_DISCLOSURE and not self.disclosure_codes:
            raise ValueError("disclosure release requires disclosure_codes")
        if self.decision == AggregateDecision.RELEASE and self.unsafe_count:
            raise ValueError("unsafe claims cannot be released")
        return self


class RevisionRequestV1(Topic4RecordV1):
    schema_version: Literal["revision.request.v1"]
    revision_request_id: UUID
    verification_id: UUID
    parent_verification_id: UUID
    original_candidate_id: UUID
    original_candidate_version: int = Field(ge=1)
    original_candidate_sha256: Sha256Hex
    target_agent: SourceAgent
    revision_round: int = Field(ge=1, le=2)
    block_ids: list[BlockId] = Field(min_length=1, max_length=2048)
    claim_ids: list[UUID] = Field(min_length=1, max_length=4096)
    instructions_artifact: ArtifactObjectRefV1
    instructions_sha256: Sha256Hex
    deadline_at: AwareDatetime

    @model_validator(mode="after")
    def validate_revision_deadline(self) -> RevisionRequestV1:
        if self.deadline_at <= self.created_at:
            raise ValueError("revision deadline must be after creation")
        return self


class RevisionResponseV1(Topic4RecordV1):
    schema_version: Literal["revision.response.v1"]
    revision_response_id: UUID
    revision_request_id: UUID
    child_verification_id: UUID
    revised_candidate_id: UUID
    revised_candidate_version: int = Field(ge=2)
    revised_candidate_sha256: Sha256Hex
    changed_block_ids: list[BlockId] = Field(min_length=1, max_length=2048)
    response_artifact: ArtifactObjectRefV1
    response_sha256: Sha256Hex
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_completion(self) -> RevisionResponseV1:
        if self.completed_at < self.created_at:
            raise ValueError("completed_at cannot precede created_at")
        return self


class VerificationReportV1(Topic4RecordV1):
    schema_version: Literal["verification.report.v1"]
    report_id: UUID
    verification_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    candidate_sha256: Sha256Hex
    knowledge_base_version: VersionString
    aggregation_result_id: UUID
    decision: AggregateDecision
    claim_verdict_ids: list[UUID] = Field(min_length=1, max_length=4096)
    evidence_chain_manifest_id: UUID
    report_artifact: ArtifactObjectRefV1
    report_sha256: Sha256Hex
    policy_version: VersionString
    completed_at: AwareDatetime


class PublicationBatchV1(Topic4RecordV1):
    schema_version: Literal["publication-batch.v1"]
    publication_batch_id: UUID
    authorization_id: UUID
    verification_id: UUID
    report_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    candidate_sha256: Sha256Hex
    state: PublicationState
    public_artifacts: list[ArtifactObjectRefV1] = Field(default_factory=list, max_length=2048)
    outbox_event_ids: list[UUID] = Field(default_factory=list, max_length=2048)
    public_stream_event_ids: list[UUID] = Field(default_factory=list, max_length=4096)
    committed_at: AwareDatetime | None = None
    failure_code: ReasonCode | None = None

    @model_validator(mode="after")
    def validate_publication(self) -> PublicationBatchV1:
        if self.state == PublicationState.COMMITTED and (
            self.committed_at is None or not self.public_artifacts
        ):
            raise ValueError("committed publication requires time and artifacts")
        if self.state == PublicationState.FAILED and self.failure_code is None:
            raise ValueError("failed publication requires failure_code")
        return self


class PublicStreamEventV1(Topic4RecordV1):
    schema_version: Literal["public.stream.event.v1"]
    public_event_id: UUID
    publication_batch_id: UUID
    authorization_id: UUID
    stream_id: UUID
    sequence: int = Field(ge=0)
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$", min_length=1, max_length=128)
    payload_artifact: ArtifactObjectRefV1
    payload_sha256: Sha256Hex
    emitted_at: AwareDatetime


class AuditEventV1(Topic4RecordV1):
    schema_version: Literal["audit-event.v1"]
    audit_event_id: UUID
    aggregate_type: str = Field(min_length=1, max_length=128)
    aggregate_id: UUID
    action: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$", min_length=1, max_length=128)
    actor_subject_ref: str = Field(min_length=1, max_length=256)
    payload_artifact: ArtifactObjectRefV1
    payload_sha256: Sha256Hex
    previous_audit_event_id: UUID | None = None
    previous_chain_sha256: Sha256Hex | None = None
    chain_sha256: Sha256Hex
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def validate_chain_parent(self) -> AuditEventV1:
        if (self.previous_audit_event_id is None) != (self.previous_chain_sha256 is None):
            raise ValueError("previous audit id and hash must be provided together")
        return self


class EvidenceChainItemV1(Topic4RecordV1):
    schema_version: Literal["evidence-chain-item.v1"]
    evidence_ref_id: UUID
    sequence: int = Field(ge=0)
    evidence_sha256: Sha256Hex
    previous_chain_sha256: Sha256Hex | None = None
    chain_sha256: Sha256Hex


class EvidenceChainManifestV1(Topic4RecordV1):
    schema_version: Literal["evidence-chain-manifest.v1"]
    evidence_chain_manifest_id: UUID
    verification_id: UUID
    report_id: UUID
    items: list[EvidenceChainItemV1] = Field(min_length=1, max_length=16_384)
    root_chain_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_sequence(self) -> EvidenceChainManifestV1:
        sequences = [item.sequence for item in self.items]
        if sequences != list(range(len(self.items))):
            raise ValueError("evidence chain sequence must be contiguous from zero")
        if self.items[-1].chain_sha256 != self.root_chain_sha256:
            raise ValueError("root_chain_sha256 must match the final item")
        return self


class HumanReviewTaskV1(Topic4RecordV1):
    schema_version: Literal["human-review.task.v1"]
    review_task_id: UUID
    verification_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    candidate_sha256: Sha256Hex
    state: ReviewTaskState
    risk_level: RiskLevel
    reason_codes: list[ReasonCode] = Field(min_length=1, max_length=128)
    claim_ids: list[UUID] = Field(min_length=1, max_length=4096)
    assigned_role: str = Field(min_length=1, max_length=128)
    due_at: AwareDatetime
    non_waivable_finding_ids: list[UUID] = Field(default_factory=list, max_length=4096)


class HumanReviewDecisionV1(Topic4RecordV1):
    schema_version: Literal["human-review.decision.v1"]
    review_decision_id: UUID
    review_task_id: UUID
    verification_id: UUID
    decision: ReviewDecision
    reviewer_subject_ref: str = Field(min_length=1, max_length=256)
    rationale_artifact: ArtifactObjectRefV1
    rationale_sha256: Sha256Hex
    disclosure_codes: list[ReasonCode] = Field(default_factory=list, max_length=32)
    waived_finding_ids: list[UUID] = Field(default_factory=list, max_length=4096)
    decided_at: AwareDatetime
    decision_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_review_decision(self) -> HumanReviewDecisionV1:
        if self.decision == ReviewDecision.APPROVE_WITH_DISCLOSURE and not self.disclosure_codes:
            raise ValueError("disclosure approval requires disclosure_codes")
        if self.decided_at < self.created_at:
            raise ValueError("decided_at cannot precede created_at")
        return self
