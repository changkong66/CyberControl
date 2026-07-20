from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    CONTRACT = "CONTRACT"
    AUTH = "AUTH"
    TENANT = "TENANT"
    MESSAGING = "MESSAGING"
    TASK = "TASK"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    CIRCUIT = "CIRCUIT"
    PROVIDER = "PROVIDER"
    AUDIT = "AUDIT"
    CONFIG = "CONFIG"
    DATABASE = "DATABASE"
    INTERNAL = "INTERNAL"


class ErrorCode(StrEnum):
    AUTH_REQUIRED = "LIYAN-AUTH-REQUIRED"
    AUTH_TOKEN_INVALID = "LIYAN-AUTH-TOKEN-INVALID"  # noqa: S105
    AUTH_CONFIG_INVALID = "LIYAN-AUTH-CONFIG-INVALID"
    AUTH_FORBIDDEN = "LIYAN-AUTH-FORBIDDEN"
    AUTH_IDENTITY_HEADER_FORBIDDEN = "LIYAN-AUTH-IDENTITY-HEADER-FORBIDDEN"
    IDENTITY_INVITATION_INVALID = "LIYAN-IDENTITY-INVITATION-INVALID"
    IDENTITY_CHALLENGE_INVALID = "LIYAN-IDENTITY-CHALLENGE-INVALID"
    IDENTITY_CHALLENGE_EXPIRED = "LIYAN-IDENTITY-CHALLENGE-EXPIRED"
    IDENTITY_REGISTRATION_UNAVAILABLE = "LIYAN-IDENTITY-REGISTRATION-UNAVAILABLE"
    IDENTITY_REGISTRATION_NOT_FOUND = "LIYAN-IDENTITY-REGISTRATION-NOT-FOUND"
    IDENTITY_ACCOUNT_NOT_FOUND = "LIYAN-IDENTITY-ACCOUNT-NOT-FOUND"
    IDENTITY_ACCOUNT_CONFLICT = "LIYAN-IDENTITY-ACCOUNT-CONFLICT"
    IDENTITY_INTEGRITY_FAILED = "LIYAN-IDENTITY-INTEGRITY-FAILED"
    TENANT_INACTIVE = "LIYAN-TENANT-INACTIVE"
    TENANT_IDENTITY_UNBOUND = "LIYAN-TENANT-IDENTITY-UNBOUND"
    CONTRACT_INVALID = "LIYAN-CONTRACT-INVALID"
    CONTRACT_UNSUPPORTED_VERSION = "LIYAN-CONTRACT-UNSUPPORTED-VERSION"
    TENANT_CONTEXT_MISSING = "LIYAN-TENANT-CONTEXT-MISSING"
    TENANT_MISMATCH = "LIYAN-TENANT-MISMATCH"
    MESSAGE_DUPLICATE_CONFLICT = "LIYAN-MESSAGE-DUPLICATE-CONFLICT"
    MESSAGE_SEQUENCE_GAP = "LIYAN-MESSAGE-SEQUENCE-GAP"
    MESSAGE_SEQUENCE_STALE = "LIYAN-MESSAGE-SEQUENCE-STALE"
    MESSAGE_HANDLER_MISSING = "LIYAN-MESSAGE-HANDLER-MISSING"
    MESSAGE_EXPIRED = "LIYAN-MESSAGE-EXPIRED"
    MESSAGE_BUFFER_FULL = "LIYAN-MESSAGE-BUFFER-FULL"
    SSE_FRAGMENT_CONFLICT = "LIYAN-SSE-FRAGMENT-CONFLICT"
    SSE_STREAM_CLOSED = "LIYAN-SSE-STREAM-CLOSED"
    SSE_REPLAY_CURSOR_INVALID = "LIYAN-SSE-REPLAY-CURSOR-INVALID"
    SSE_EVENT_INVALID = "LIYAN-SSE-EVENT-INVALID"
    SSE_EVENT_INTEGRITY_FAILED = "LIYAN-SSE-EVENT-INTEGRITY-FAILED"
    TASK_HANDLER_MISSING = "LIYAN-TASK-HANDLER-MISSING"
    TASK_QUEUE_CLOSED = "LIYAN-TASK-QUEUE-CLOSED"
    TASK_FAILED = "LIYAN-TASK-FAILED"
    TIMEOUT = "LIYAN-TIMEOUT"
    RATE_LIMITED = "LIYAN-RATE-LIMITED"
    CIRCUIT_OPEN = "LIYAN-CIRCUIT-OPEN"
    PROVIDER_DISABLED = "LIYAN-PROVIDER-DISABLED"
    PROVIDER_PROHIBITED = "LIYAN-PROVIDER-PROHIBITED"
    AUDIT_WRITE_FAILED = "LIYAN-AUDIT-WRITE-FAILED"
    CONFIG_INVALID = "LIYAN-CONFIG-INVALID"
    DATABASE_UNAVAILABLE = "LIYAN-DATABASE-UNAVAILABLE"
    DATABASE_SERIALIZATION_FAILURE = "LIYAN-DATABASE-SERIALIZATION-FAILURE"
    DATABASE_TRANSACTION_STATE = "LIYAN-DATABASE-TRANSACTION-STATE"
    ARTIFACT_NOT_FOUND = "LIYAN-ARTIFACT-NOT-FOUND"
    ARTIFACT_CONFLICT = "LIYAN-ARTIFACT-CONFLICT"
    ARTIFACT_INTEGRITY_FAILED = "LIYAN-ARTIFACT-INTEGRITY-FAILED"
    ARTIFACT_PATH_INVALID = "LIYAN-ARTIFACT-PATH-INVALID"
    TOPIC1_NOT_FOUND = "LIYAN-TOPIC1-NOT-FOUND"
    TOPIC1_CONFLICT = "LIYAN-TOPIC1-CONFLICT"
    TOPIC1_CYCLE = "LIYAN-TOPIC1-CYCLE"
    TOPIC1_IMPORT_LIMIT = "LIYAN-TOPIC1-IMPORT-LIMIT"
    TOPIC2_NOT_FOUND = "LIYAN-TOPIC2-NOT-FOUND"
    TOPIC2_CONFLICT = "LIYAN-TOPIC2-CONFLICT"
    TOPIC2_BATCH_LIMIT = "LIYAN-TOPIC2-BATCH-LIMIT"
    TOPIC2_VERSION_CONFLICT = "LIYAN-TOPIC2-VERSION-CONFLICT"
    TOPIC3_NOT_FOUND = "LIYAN-TOPIC3-NOT-FOUND"
    TOPIC3_CONFLICT = "LIYAN-TOPIC3-CONFLICT"
    TOPIC3_VERSION_CONFLICT = "LIYAN-TOPIC3-VERSION-CONFLICT"
    TOPIC3_PROVIDER_UNAVAILABLE = "LIYAN-TOPIC3-PROVIDER-UNAVAILABLE"
    TOPIC3_AGENT_OUTPUT_INVALID = "LIYAN-TOPIC3-AGENT-OUTPUT-INVALID"
    TOPIC3_GENERATION_FAILED = "LIYAN-TOPIC3-GENERATION-FAILED"
    TOPIC3_BATCH_LIMIT = "LIYAN-TOPIC3-BATCH-LIMIT"
    TOPIC4_NOT_FOUND = "LIYAN-TOPIC4-NOT-FOUND"
    TOPIC4_CONFLICT = "LIYAN-TOPIC4-CONFLICT"
    TOPIC4_VERSION_CONFLICT = "LIYAN-TOPIC4-VERSION-CONFLICT"
    TOPIC4_STATE_TRANSITION_INVALID = "LIYAN-TOPIC4-STATE-TRANSITION-INVALID"
    TOPIC4_INTEGRITY_FAILED = "LIYAN-TOPIC4-INTEGRITY-FAILED"
    TOPIC4_DEADLINE_EXPIRED = "LIYAN-TOPIC4-DEADLINE-EXPIRED"
    TOPIC4_RELEASE_DENIED = "LIYAN-TOPIC4-RELEASE-DENIED"
    INTERNAL = "LIYAN-INTERNAL"


class LiyanError(RuntimeError):
    def __init__(
        self,
        code: ErrorCode,
        safe_message: str,
        *,
        category: ErrorCategory,
        retriable: bool = False,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.category = category
        self.retriable = retriable
        self.status_code = status_code
        self.details = details or {}


class ContractError(LiyanError):
    def __init__(self, safe_message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            ErrorCode.CONTRACT_INVALID,
            safe_message,
            category=ErrorCategory.CONTRACT,
            status_code=422,
            details=details,
        )


class TenantIsolationError(LiyanError):
    def __init__(self, safe_message: str = "Tenant isolation policy denied the operation.") -> None:
        super().__init__(
            ErrorCode.TENANT_MISMATCH,
            safe_message,
            category=ErrorCategory.TENANT,
            status_code=403,
        )


class MessageSequenceError(LiyanError):
    def __init__(self, code: ErrorCode, safe_message: str) -> None:
        super().__init__(
            code,
            safe_message,
            category=ErrorCategory.MESSAGING,
            status_code=409,
        )


class MessageConflictError(LiyanError):
    def __init__(self, code: ErrorCode, safe_message: str) -> None:
        super().__init__(
            code,
            safe_message,
            category=ErrorCategory.MESSAGING,
            status_code=409,
        )


class RateLimitExceeded(LiyanError):
    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__(
            ErrorCode.RATE_LIMITED,
            "Rate limit exceeded.",
            category=ErrorCategory.RATE_LIMIT,
            retriable=True,
            status_code=429,
            details={"retry_after_seconds": retry_after_seconds},
        )


class CircuitOpenError(LiyanError):
    def __init__(self, circuit_name: str) -> None:
        super().__init__(
            ErrorCode.CIRCUIT_OPEN,
            "The downstream circuit is open.",
            category=ErrorCategory.CIRCUIT,
            retriable=True,
            status_code=503,
            details={"circuit_name": circuit_name},
        )


class OperationTimeoutError(LiyanError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            ErrorCode.TIMEOUT,
            "The operation exceeded its deadline.",
            category=ErrorCategory.TIMEOUT,
            retriable=True,
            status_code=504,
            details={"operation": operation},
        )
