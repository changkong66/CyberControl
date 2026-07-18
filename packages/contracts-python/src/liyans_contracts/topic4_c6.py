from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .artifacts import ArtifactObjectRefV1
from .common import Sha256Hex, VersionString
from .topic4_common import Topic4RecordV1, VerificationVerdict


class CodeLanguage(StrEnum):
    MATLAB = "MATLAB"
    PYTHON = "PYTHON"
    SIMULINK_SCRIPT = "SIMULINK_SCRIPT"
    IEC61131_ST = "IEC61131_ST"
    C_MCU = "C_MCU"


class SandboxExecutionState(StrEnum):
    NOT_RUN = "NOT_RUN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class CodeDependencyV1(Topic4RecordV1):
    schema_version: Literal["code-dependency.v1"]
    name: str = Field(min_length=1, max_length=256)
    version: str | None = Field(default=None, max_length=128)
    package_url: str | None = Field(default=None, max_length=2048)
    declared_license: str | None = Field(default=None, max_length=256)


class CodeArtifactV1(Topic4RecordV1):
    schema_version: Literal["code-artifact.v1"]
    code_artifact_id: UUID
    verification_id: UUID
    claim_id: UUID
    candidate_id: UUID
    candidate_version: int = Field(ge=1)
    block_id: str = Field(min_length=1, max_length=128)
    language: CodeLanguage
    source_artifact: ArtifactObjectRefV1
    source_sha256: Sha256Hex
    entrypoint: str = Field(min_length=1, max_length=512)
    dependencies: list[CodeDependencyV1] = Field(default_factory=list, max_length=1024)
    expected_outputs: list[str] = Field(default_factory=list, max_length=256)


class SandboxPolicyV1(Topic4RecordV1):
    schema_version: Literal["sandbox-policy.v1"]
    sandbox_policy_id: UUID
    language: CodeLanguage
    policy_version: VersionString
    runtime_image_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    network_access: Literal[False]
    root_filesystem_read_only: Literal[True]
    memory_limit_mb: int = Field(ge=16, le=4096)
    cpu_quota_millis: int = Field(ge=10, le=60_000)
    pids_limit: int = Field(ge=1, le=1024)
    timeout_ms: int = Field(ge=100, le=120_000)
    allowed_commands: list[str] = Field(default_factory=list, max_length=256)
    denied_commands: list[str] = Field(default_factory=list, max_length=256)
    syscall_profile_sha256: Sha256Hex


class NumericAssertionResultV1(Topic4RecordV1):
    schema_version: Literal["numeric-assertion-result.v1"]
    assertion_id: str = Field(min_length=1, max_length=128)
    passed: bool
    actual: float | None = None
    expected: float | None = None
    tolerance: float | None = Field(default=None, ge=0.0)


class CodeVerificationResultV1(Topic4RecordV1):
    schema_version: Literal["code-verification.result.v1"]
    code_verification_result_id: UUID
    verification_id: UUID
    claim_id: UUID
    code_artifact_id: UUID
    sandbox_policy_id: UUID
    syntax_valid: bool
    static_analysis_passed: bool
    execution_state: SandboxExecutionState
    exit_code: int | None = None
    stdout_artifact: ArtifactObjectRefV1 | None = None
    stderr_artifact: ArtifactObjectRefV1 | None = None
    stdout_sha256: Sha256Hex | None = None
    stderr_sha256: Sha256Hex | None = None
    numeric_assertions: list[NumericAssertionResultV1] = Field(
        default_factory=list, max_length=4096
    )
    finding_codes: list[str] = Field(default_factory=list, max_length=1024)
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_stream_refs(self) -> CodeVerificationResultV1:
        if (self.stdout_artifact is None) != (self.stdout_sha256 is None):
            raise ValueError("stdout artifact and hash must be provided together")
        if (self.stderr_artifact is None) != (self.stderr_sha256 is None):
            raise ValueError("stderr artifact and hash must be provided together")
        return self
