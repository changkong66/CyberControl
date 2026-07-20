from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(
    os.getenv("LIYAN_REPOSITORY_ROOT", str(Path(__file__).resolve().parents[4]))
).resolve()
DEVELOPMENT_REGISTRATION_INVITATION_SECRET = "local-registration-invitation-secret-change-me-32"
DEVELOPMENT_IDENTITY_ENCRYPTION_SECRET = "local-identity-encryption-secret-change-me-32"
DEVELOPMENT_IDENTITY_LOOKUP_PEPPER = "local-identity-lookup-pepper-change-me-32"
DEVELOPMENT_VERIFICATION_CODE_PEPPER = "local-verification-code-pepper-change-me-32"


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
    identity_reconciler_database_url: str | None = None
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
    keycloak_admin_base_url: str | None = None
    keycloak_admin_realm: str = "cybercontrol"
    keycloak_admin_client_id: str = "cybercontrol-registration-admin"
    keycloak_admin_client_secret: SecretStr | None = Field(default=None, repr=False)
    keycloak_admin_http_timeout_seconds: float = 5
    keycloak_admin_max_response_bytes: int = 512 * 1024
    registration_enabled: bool = False
    registration_development_tenant_id: str = "demo-academy"
    registration_allow_development_fallback: bool = True
    registration_invitation_secret: SecretStr | None = Field(
        default=SecretStr(DEVELOPMENT_REGISTRATION_INVITATION_SECRET),
        repr=False,
    )
    registration_invitation_issuer: str = "cybercontrol-registration"
    registration_invitation_audience: str = "cybercontrol-registration"
    identity_encryption_secret: SecretStr = Field(
        default=SecretStr(DEVELOPMENT_IDENTITY_ENCRYPTION_SECRET),
        repr=False,
    )
    identity_lookup_pepper: SecretStr = Field(
        default=SecretStr(DEVELOPMENT_IDENTITY_LOOKUP_PEPPER),
        repr=False,
    )
    verification_code_pepper: SecretStr = Field(
        default=SecretStr(DEVELOPMENT_VERIFICATION_CODE_PEPPER),
        repr=False,
    )
    registration_challenge_ttl_seconds: int = 300
    registration_challenge_cooldown_seconds: int = 60
    registration_challenge_max_attempts: int = 5
    registration_rate_limit_window_seconds: int = 3600
    registration_rate_limit_max_requests: int = 10
    registration_fixture_inbox_enabled: bool = True
    registration_reconciliation_interval_seconds: float = 30
    registration_reconciliation_claim_lease_seconds: float = 120
    artifact_root: Path = REPOSITORY_ROOT / "var" / "artifacts"
    artifact_max_object_bytes: int = 64 * 1024 * 1024
    audit_log_path: Path = REPOSITORY_ROOT / "var" / "audit" / "events.jsonl"
    provider_policy_path: Path = REPOSITORY_ROOT / "config" / "providers.toml"
    provider_policy_poll_seconds: float = 2.0
    compliance_builder_policy_path: Path = REPOSITORY_ROOT / "config" / "compliance-builders.toml"
    provider_external_enabled: bool = False
    spark_text_endpoint: str | None = None
    spark_text_api_key: str | None = Field(default=None, repr=False)
    spark_text_model_alias: str = "spark-text-approved"
    xfyun_code_endpoint: str | None = None
    xfyun_code_api_key: str | None = Field(default=None, repr=False)
    xfyun_code_model_alias: str = "xfyun-code-approved"
    seedance_endpoint: str | None = None
    seedance_api_key: str | None = Field(default=None, repr=False)
    seedance_model_alias: str = "seedance-approved"
    provider_http_timeout_seconds: float = 90.0
    provider_max_connections: int = 32
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
        if (
            min(
                self.keycloak_admin_http_timeout_seconds,
                self.registration_reconciliation_interval_seconds,
                self.registration_reconciliation_claim_lease_seconds,
            )
            <= 0
        ):
            raise ValueError("identity service timing settings must be positive")
        if not 16_384 <= self.keycloak_admin_max_response_bytes <= 16 * 1024 * 1024:
            raise ValueError("keycloak_admin_max_response_bytes is outside the safe range")
        if not 30 <= self.registration_challenge_ttl_seconds <= 3600:
            raise ValueError("registration challenge TTL must be between 30 and 3600 seconds")
        if not 1 <= self.registration_challenge_cooldown_seconds <= 3600:
            raise ValueError("registration challenge cooldown is invalid")
        if not 1 <= self.registration_challenge_max_attempts <= 20:
            raise ValueError("registration challenge max attempts is invalid")
        if not 1 <= self.registration_rate_limit_window_seconds <= 86_400:
            raise ValueError("registration rate limit window is invalid")
        if not 1 <= self.registration_rate_limit_max_requests <= 1000:
            raise ValueError("registration rate limit maximum is invalid")
        keycloak_values = (
            self.keycloak_admin_base_url,
            self.keycloak_admin_client_secret,
        )
        if any(keycloak_values) and not all(keycloak_values):
            raise ValueError("Keycloak Admin API URL and secret must be configured together")
        identity_secret_values = (
            self.identity_encryption_secret.get_secret_value(),
            self.identity_lookup_pepper.get_secret_value(),
            self.verification_code_pepper.get_secret_value(),
        )
        if any(len(secret.encode("utf-8")) < 32 for secret in identity_secret_values):
            raise ValueError("identity secrets must contain at least 32 bytes")
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
        identity_runtime_configured = self.registration_enabled or all(keycloak_values)
        if self.environment == "production" and identity_runtime_configured:
            if not all(keycloak_values):
                raise ValueError("production identity runtime requires a Keycloak Admin API secret")
            if not self.keycloak_admin_base_url.startswith("https://"):
                raise ValueError("production Keycloak Admin API must use HTTPS")
            if self.registration_allow_development_fallback:
                raise ValueError("production identity runtime cannot use the development fallback")
            if self.registration_fixture_inbox_enabled:
                raise ValueError("production identity runtime cannot enable the fixture inbox")
            development_identity_secrets = (
                DEVELOPMENT_IDENTITY_ENCRYPTION_SECRET,
                DEVELOPMENT_IDENTITY_LOOKUP_PEPPER,
                DEVELOPMENT_VERIFICATION_CODE_PEPPER,
            )
            if any(
                actual == development
                for actual, development in zip(
                    identity_secret_values,
                    development_identity_secrets,
                    strict=True,
                )
            ):
                raise ValueError("production identity runtime requires external identity secrets")
            if self.registration_enabled:
                invitation_secret = (
                    self.registration_invitation_secret.get_secret_value()
                    if self.registration_invitation_secret is not None
                    else ""
                )
                if (
                    len(invitation_secret.encode("utf-8")) < 32
                    or invitation_secret == DEVELOPMENT_REGISTRATION_INVITATION_SECRET
                ):
                    raise ValueError(
                        "production registration requires an external invitation secret"
                    )
            if not self.identity_reconciler_database_url:
                raise ValueError(
                    "production identity runtime requires the reconciliation catalog URL"
                )
        allowed_algorithms = {"RS256", "RS384", "RS512", "ES256", "ES384"}
        if not self.oidc_algorithms or not set(self.oidc_algorithms) <= allowed_algorithms:
            raise ValueError("oidc_algorithms contains an unsupported signing algorithm")
        if self.environment == "production" and (
            not self.oidc_issuer.startswith("https://")
            or not self.oidc_jwks_url.startswith("https://")
        ):
            raise ValueError("production OIDC endpoints must use HTTPS")
        provider_pairs = (
            ("spark_text", self.spark_text_endpoint, self.spark_text_api_key),
            ("xfyun_code", self.xfyun_code_endpoint, self.xfyun_code_api_key),
            ("seedance", self.seedance_endpoint, self.seedance_api_key),
        )
        for alias, endpoint, api_key in provider_pairs:
            if bool(endpoint) != bool(api_key):
                raise ValueError(f"{alias} endpoint and API key must be configured together")
            if (
                self.environment == "production"
                and endpoint
                and not endpoint.startswith("https://")
            ):
                raise ValueError(f"production {alias} endpoint must use HTTPS")
        if self.environment == "production" and self.provider_external_enabled:
            if not self.outbox_publisher_enabled:
                raise ValueError(
                    "production Topic 3 provider execution requires the durable Outbox publisher"
                )
            if not self.sse_notification_enabled:
                raise ValueError(
                    "production Topic 3 provider execution requires PostgreSQL SSE notifications"
                )
            required_provider_aliases = {
                alias for alias, endpoint, api_key in provider_pairs if endpoint and api_key
            }
            missing = {"spark_text", "xfyun_code"} - required_provider_aliases
            if missing:
                raise ValueError(
                    "production Topic 3 requires configured providers: "
                    + ", ".join(sorted(missing))
                )
        if self.provider_http_timeout_seconds <= 0:
            raise ValueError("provider_http_timeout_seconds must be positive")
        if not 1 <= self.provider_max_connections <= 1024:
            raise ValueError("provider_max_connections must be between one and 1024")
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

    def provider_credentials(self, alias: str) -> tuple[str, str, str] | None:
        values = {
            "spark_text": (
                self.spark_text_endpoint,
                self.spark_text_api_key,
                self.spark_text_model_alias,
            ),
            "xfyun_code": (
                self.xfyun_code_endpoint,
                self.xfyun_code_api_key,
                self.xfyun_code_model_alias,
            ),
            "seedance": (
                self.seedance_endpoint,
                self.seedance_api_key,
                self.seedance_model_alias,
            ),
        }
        try:
            endpoint, api_key, model_alias = values[alias]
        except KeyError as exc:
            raise ValueError(f"unknown approved provider alias: {alias}") from exc
        if endpoint is None or api_key is None:
            return None
        return endpoint, api_key, model_alias


@lru_cache
def get_settings() -> Settings:
    return Settings()
