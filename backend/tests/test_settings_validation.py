from __future__ import annotations

import pytest
from pydantic import ValidationError

from liyans.core.settings import Settings


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"sse_cursor_secret": "short"}, "at least 32 bytes"),
        ({"database_pool_size": 0}, "pool sizing"),
        ({"database_statement_timeout_ms": 99}, "at least 100"),
        ({"artifact_max_object_bytes": 0}, "must be positive"),
        ({"sse_event_max_bytes": 255}, "between 256 bytes"),
        ({"service_instance_id": ""}, "between one and 128"),
        ({"idempotency_retention_seconds": 0}, "durations must be positive"),
        ({"outbox_publisher_batch_size": 0}, "between one and 1000"),
        ({"outbox_publisher_poll_seconds": 0}, "timing settings must be positive"),
        ({"sse_notification_queue_size": 0}, "between one and 100000"),
        ({"sse_notification_reconnect_base_seconds": 0}, "timing settings must be positive"),
        (
            {
                "sse_notification_reconnect_base_seconds": 2,
                "sse_notification_reconnect_max_seconds": 1,
            },
            "base cannot exceed",
        ),
        ({"outbox_publisher_enabled": True}, "dispatcher database URL"),
        ({"oidc_issuer": "https://issuer.test"}, "configured together"),
        ({"oidc_algorithms": ("HS256",)}, "unsupported signing algorithm"),
        (
            {"spark_text_endpoint": "https://provider.test", "spark_text_api_key": None},
            "configured together",
        ),
        ({"provider_http_timeout_seconds": 0}, "must be positive"),
        ({"provider_max_connections": 0}, "between one and 1024"),
        ({"oidc_clock_skew_seconds": 0}, "OIDC timing settings must be positive"),
        (
            {"keycloak_admin_base_url": "http://localhost:8080"},
            "URL and secret must be configured together",
        ),
        ({"identity_encryption_secret": "short"}, "at least 32 bytes"),
        (
            {"registration_reconciliation_claim_lease_seconds": 0},
            "identity service timing settings must be positive",
        ),
    ],
)
def test_settings_reject_invalid_runtime_boundaries(
    overrides: dict[str, object],
    message: str,
) -> None:
    values = {"sse_cursor_secret": "x" * 32, **overrides}
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **values)


def production_settings(**overrides: object) -> dict[str, object]:
    return {
        "environment": "production",
        "sse_cursor_secret": "x" * 32,
        "oidc_issuer": "https://issuer.test",
        "oidc_audience": "cybercontrol-api",
        "oidc_jwks_url": "https://issuer.test/certs",
        **overrides,
    }


def test_production_requires_an_external_cursor_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIYAN_SSE_CURSOR_SECRET", raising=False)
    with pytest.raises(ValidationError, match="production requires LIYAN_SSE_CURSOR_SECRET"):
        Settings(_env_file=None, **production_settings())


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"oidc_issuer": None, "oidc_audience": None, "oidc_jwks_url": None},
            "production requires OIDC",
        ),
        (
            {
                "oidc_issuer": "http://issuer.test",
                "oidc_jwks_url": "http://issuer.test/certs",
            },
            "must use HTTPS",
        ),
        (
            {"spark_text_endpoint": "http://provider.test", "spark_text_api_key": "secret"},
            "production spark_text endpoint must use HTTPS",
        ),
        (
            {
                "provider_external_enabled": True,
                "spark_text_endpoint": "https://spark.test",
                "spark_text_api_key": "secret",
                "xfyun_code_endpoint": "https://code.test",
                "xfyun_code_api_key": "secret",
            },
            "requires the durable Outbox publisher",
        ),
        (
            {
                "provider_external_enabled": True,
                "outbox_publisher_enabled": True,
                "outbox_dispatcher_database_url": "postgresql+asyncpg://dispatcher",
                "spark_text_endpoint": "https://spark.test",
                "spark_text_api_key": "secret",
                "xfyun_code_endpoint": "https://code.test",
                "xfyun_code_api_key": "secret",
            },
            "requires PostgreSQL SSE notifications",
        ),
        (
            {
                "provider_external_enabled": True,
                "outbox_publisher_enabled": True,
                "outbox_dispatcher_database_url": "postgresql+asyncpg://dispatcher",
                "sse_notification_enabled": True,
                "spark_text_endpoint": "https://spark.test",
                "spark_text_api_key": "secret",
            },
            "requires configured providers: xfyun_code",
        ),
        (
            {"registration_enabled": True},
            "production identity runtime requires a Keycloak Admin API secret",
        ),
        (
            {
                "registration_enabled": True,
                "keycloak_admin_base_url": "http://identity.test",
                "keycloak_admin_client_secret": "external-admin-secret",
            },
            "Keycloak Admin API must use HTTPS",
        ),
        (
            {
                "registration_enabled": True,
                "keycloak_admin_base_url": "https://identity.test",
                "keycloak_admin_client_secret": "external-admin-secret",
            },
            "cannot use the development fallback",
        ),
        (
            {
                "registration_enabled": True,
                "keycloak_admin_base_url": "https://identity.test",
                "keycloak_admin_client_secret": "external-admin-secret",
                "registration_allow_development_fallback": False,
            },
            "cannot enable the fixture inbox",
        ),
        (
            {
                "registration_enabled": True,
                "keycloak_admin_base_url": "https://identity.test",
                "keycloak_admin_client_secret": "external-admin-secret",
                "registration_allow_development_fallback": False,
                "registration_fixture_inbox_enabled": False,
            },
            "requires external identity secrets",
        ),
        (
            {
                "registration_enabled": True,
                "keycloak_admin_base_url": "https://identity.test",
                "keycloak_admin_client_secret": "external-admin-secret",
                "registration_allow_development_fallback": False,
                "registration_fixture_inbox_enabled": False,
                "identity_encryption_secret": "external-encryption-secret-at-least-32-bytes",
                "identity_lookup_pepper": "external-lookup-pepper-at-least-32-bytes",
                "verification_code_pepper": "external-code-pepper-at-least-32-bytes",
            },
            "requires an external invitation secret",
        ),
        (
            {
                "registration_enabled": True,
                "keycloak_admin_base_url": "https://identity.test",
                "keycloak_admin_client_secret": "external-admin-secret",
                "registration_allow_development_fallback": False,
                "registration_fixture_inbox_enabled": False,
                "registration_invitation_secret": "external-invitation-secret-at-least-32-bytes",
                "identity_encryption_secret": "external-encryption-secret-at-least-32-bytes",
                "identity_lookup_pepper": "external-lookup-pepper-at-least-32-bytes",
                "verification_code_pepper": "external-code-pepper-at-least-32-bytes",
            },
            "requires the reconciliation catalog URL",
        ),
    ],
)
def test_production_security_dependencies_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    message: str,
) -> None:
    monkeypatch.setenv("LIYAN_SSE_CURSOR_SECRET", "x" * 32)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **production_settings(**overrides))


def test_production_identity_runtime_accepts_only_external_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIYAN_SSE_CURSOR_SECRET", "x" * 32)
    settings = Settings(
        _env_file=None,
        **production_settings(
            registration_enabled=True,
            keycloak_admin_base_url="https://identity.test",
            keycloak_admin_client_secret="external-admin-secret",
            registration_allow_development_fallback=False,
            registration_fixture_inbox_enabled=False,
            registration_invitation_secret="external-invitation-secret-at-least-32-bytes",
            identity_encryption_secret="external-encryption-secret-at-least-32-bytes",
            identity_lookup_pepper="external-lookup-pepper-at-least-32-bytes",
            verification_code_pepper="external-code-pepper-at-least-32-bytes",
            identity_reconciler_database_url=(
                "postgresql+asyncpg://identity-reconciler@database/liyans"
            ),
        ),
    )
    assert settings.registration_enabled is True
