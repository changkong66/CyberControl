from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .artifacts import ArtifactObjectRefV1
from .common import Sha256Hex, VersionString
from .topic4_common import Topic4RecordV1


class GateStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class AcceptanceDecision(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AcceptanceGateResultV1(Topic4RecordV1):
    schema_version: Literal["acceptance-gate-result.v1"]
    gate_code: str = Field(pattern=r"^G(?:[0-9]|1[0-2])$")
    status: GateStatus
    metric_values: dict[str, float] = Field(default_factory=dict)
    evidence_artifact: ArtifactObjectRefV1
    evidence_sha256: Sha256Hex
    failure_codes: list[str] = Field(default_factory=list, max_length=256)


class SystemAcceptanceReportV1(Topic4RecordV1):
    schema_version: Literal["system-acceptance-report.v1"]
    system_acceptance_report_id: UUID
    build_commit_sha256: Sha256Hex
    build_version: VersionString
    gate_results: list[AcceptanceGateResultV1] = Field(min_length=13, max_length=13)
    python_coverage_percent: float = Field(ge=0.0, le=100.0)
    concurrent_verifications: int = Field(ge=0)
    retrieval_p95_ms: float = Field(ge=0.0)
    publication_p95_ms: float = Field(ge=0.0)
    cross_tenant_leaks: int = Field(ge=0)
    authorization_replay_successes: int = Field(ge=0)
    critical_vulnerabilities: int = Field(ge=0)
    high_vulnerabilities: int = Field(ge=0)
    open_p0_defects: int = Field(ge=0)
    open_p1_defects: int = Field(ge=0)
    flaky_core_tests: int = Field(ge=0)
    decision: AcceptanceDecision
    report_artifact: ArtifactObjectRefV1
    report_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_acceptance(self) -> SystemAcceptanceReportV1:
        gate_codes = [gate.gate_code for gate in self.gate_results]
        if len(gate_codes) != len(set(gate_codes)):
            raise ValueError("acceptance gate codes must be unique")
        expected = {f"G{index}" for index in range(13)}
        if set(gate_codes) != expected:
            raise ValueError("acceptance report requires exactly G0 through G12")
        redlines_pass = (
            all(gate.status == GateStatus.PASSED for gate in self.gate_results)
            and self.python_coverage_percent >= 90.0
            and self.concurrent_verifications >= 200
            and self.retrieval_p95_ms <= 200.0
            and self.publication_p95_ms <= 300.0
            and self.cross_tenant_leaks == 0
            and self.authorization_replay_successes == 0
            and self.critical_vulnerabilities == 0
            and self.high_vulnerabilities == 0
            and self.open_p0_defects == 0
            and self.open_p1_defects == 0
            and self.flaky_core_tests == 0
        )
        if self.decision == AcceptanceDecision.ACCEPTED and not redlines_pass:
            raise ValueError("accepted report does not satisfy Topic 4 redlines")
        return self


class ReleaseDerivationCommandV2(Topic4RecordV1):
    schema_version: Literal["release.derivation.command.v2"]
    derivation_command_id: UUID
    verification_id: UUID
    requested_release_mode: Literal["FULL", "FULL_WITH_DISCLOSURE"]
    requested_block_ids: list[str] = Field(default_factory=list, max_length=2048)
    ttl_seconds: int = Field(ge=1, le=300)
    idempotency_key_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_requested_blocks(self) -> ReleaseDerivationCommandV2:
        if len(self.requested_block_ids) != len(set(self.requested_block_ids)):
            raise ValueError("requested_block_ids must be unique")
        return self


class PublicationCommitCommandV2(Topic4RecordV1):
    schema_version: Literal["publication.commit.command.v2"]
    commit_command_id: UUID
    authorization_id: UUID
    idempotency_key_sha256: Sha256Hex
