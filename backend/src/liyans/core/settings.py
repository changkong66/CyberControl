from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(
    os.getenv("LIYAN_REPOSITORY_ROOT", str(Path(__file__).resolve().parents[4]))
).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LIYAN_",
        env_file=".env",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://liyans_app:liyans-app-local-only@localhost:5432/liyans"
    )
    database_migration_url: str | None = None
    outbox_dispatcher_database_url: str | None = None
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: float = 10.0
    database_pool_recycle_seconds: int = 1800
    database_statement_timeout_ms: int = 30_000
    database_idle_transaction_timeout_ms: int = 60_000
    database_command_timeout_seconds: float = 35.0
    database_health_timeout_seconds: float = 3.0
    service_instance_id: str = "liyans-api-local"
    idempotency_retention_seconds: float = 86_400
    idempotency_processing_lease_seconds: float = 120
    outbox_claim_lease_seconds: float = 30
    outbox_publisher_enabled: bool = False
    outbox_publisher_batch_size: int = 32
    outbox_publisher_poll_seconds: float = 0.5
    outbox_publisher_retry_base_seconds: float = 0.25
    outbox_publisher_retry_max_seconds: float = 30
    sse_event_retention_seconds: float = 86_400
    sse_event_max_bytes: int = 256 * 1024
    sse_notification_enabled: bool = False
    sse_notification_database_url: str | None = None
    sse_notification_queue_size: int = 1024
    sse_notification_reconnect_base_seconds: float = 0.25
    sse_notification_reconnect_max_seconds: float = 10
    sse_notification_startup_timeout_seconds: float = 5
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    oidc_tenant_claim: str = "tenant_id"
    oidc_roles_claim: str = "roles"
    oidc_scope_claim: str = "scope"
    oidc_clock_skew_seconds: float = 30
    oidc_max_token_lifetime_seconds: float = 3600
    oidc_jwks_cache_ttl_seconds: float = 300
    oidc_http_timeout_seconds: float = 3
    artifact_root: Path = REPOSITORY_ROOT / "var" / "artifacts"
    artifact_max_object_bytes: int = 64 * 1024 * 1024
    audit_log_path: Path = REPOSITORY_ROOT / "var" / "audit" / "events.jsonl"
    provider_policy_path: Path = REPOSITORY_ROOT / "config" / "providers.toml"
    provider_policy_poll_seconds: float = 2.0
    task_worker_count: int = 4
    sse_replay_capacity: int = 4096
    sse_subscriber_queue_size: int = 128
    sse_cursor_secret: str = Field(default_factory=lambda: secrets.token_hex(32), repr=False)

    @model_validator(mode="after")
    def validate_environment(self) -> Settings:
        if self.environment == "production" and not os.getenv("LIYAN_SSE_CURSOR_SECRET"):
            raise ValueError("production requires LIYAN_SSE_CURSOR_SECRET")
        if len(self.sse_cursor_secret.encode("utf-8")) < 32:
            raise ValueError("sse_cursor_secret must contain at least 32 bytes")
        if self.database_pool_size < 1 or self.database_max_overflow < 0:
            raise ValueError("database pool sizing is invalid")
        if self.database_statement_timeout_ms < 100:
            raise ValueError("database_statement_timeout_ms must be at least 100")
        if self.artifact_max_object_bytes < 1:
            raise ValueError("artifact_max_object_bytes must be positive")
        if not 256 <= self.sse_event_max_bytes <= 4 * 1024 * 1024:
            raise ValueError("sse_event_max_bytes must be between 256 bytes and 4 MiB")
        if not self.service_instance_id or len(self.service_instance_id) > 128:
            raise ValueError("service_instance_id must contain between one and 128 characters")
        if (
            min(
                self.idempotency_retention_seconds,
                self.idempotency_processing_lease_seconds,
                self.outbox_claim_lease_seconds,
                self.sse_event_retention_seconds,
            )
            <= 0
        ):
            raise ValueError("database retention and lease durations must be positive")
        if not 1 <= self.outbox_publisher_batch_size <= 1000:
            raise ValueError("outbox_publisher_batch_size must be between one and 1000")
        if (
            min(
                self.outbox_publisher_poll_seconds,
                self.outbox_publisher_retry_base_seconds,
                self.outbox_publisher_retry_max_seconds,
            )
            <= 0
        ):
            raise ValueError("outbox publisher timing settings must be positive")
        if not 1 <= self.sse_notification_queue_size <= 100_000:
            raise ValueError("sse_notification_queue_size must be between one and 100000")
        if (
            min(
                self.sse_notification_reconnect_base_seconds,
                self.sse_notification_reconnect_max_seconds,
                self.sse_notification_startup_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("SSE notification timing settings must be positive")
        if (
            self.sse_notification_reconnect_base_seconds
            > self.sse_notification_reconnect_max_seconds
        ):
            raise ValueError("SSE notification reconnect base cannot exceed its maximum")
        if self.outbox_publisher_enabled and not self.outbox_dispatcher_database_url:
            raise ValueError("enabled Outbox publisher requires its dispatcher database URL")
        oidc_values = (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        if any(oidc_values) and not all(oidc_values):
            raise ValueError("OIDC issuer, audience, and JWKS URL must be configured together")
        if self.environment == "production" and not all(oidc_values):
            raise ValueError("production requires OIDC issuer, audience, and JWKS URL")
        allowed_algorithms = {"RS256", "RS384", "RS512", "ES256", "ES384"}
        if not self.oidc_algorithms or not set(self.oidc_algorithms) <= allowed_algorithms:
            raise ValueError("oidc_algorithms contains an unsupported signing algorithm")
        if self.environment == "production" and (
            not self.oidc_issuer.startswith("https://")
            or not self.oidc_jwks_url.startswith("https://")
        ):
            raise ValueError("production OIDC endpoints must use HTTPS")
        if (
            min(
                self.oidc_clock_skew_seconds,
                self.oidc_max_token_lifetime_seconds,
                self.oidc_jwks_cache_ttl_seconds,
                self.oidc_http_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("OIDC timing settings must be positive")
        return self

    @property
    def oidc_configured(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
