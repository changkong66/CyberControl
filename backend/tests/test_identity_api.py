from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from liyans_contracts.identity import (
    AccountAdminViewV1,
    AccountProfileV1,
    IdentityAccountStatus,
    IdentityAuditEntryV1,
    IdentityChallengePurpose,
    IdentityChallengeState,
    IdentityContactChannel,
    IdentityRegistrationState,
    RegistrationReceiptV1,
    RegistrationStatusV1,
    VerificationChallengeReceiptV1,
)

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.settings import get_settings
from liyans.core.tenant import TenantContext
from liyans.domains.identity.crypto import FixtureInboxMessage
from liyans.infrastructure.security import AuthenticatedPrincipal
from liyans.main import create_app

TRACE_ID = "a" * 32
ACCOUNT_ID = uuid4()
CHALLENGE_ID = uuid4()
REGISTRATION_ID = uuid4()


class StubTokenVerifier:
    def __init__(self, scopes: frozenset[str]) -> None:
        self.scopes = scopes

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        if token != "identity-token":
            raise LiyanError(
                ErrorCode.AUTH_TOKEN_INVALID,
                "The bearer token is invalid or expired.",
                category=ErrorCategory.AUTH,
                status_code=401,
            )
        now = datetime.now(UTC)
        return AuthenticatedPrincipal(
            issuer="https://issuer.test",
            subject="subject:identity-api",
            tenant_id="tenant-a",
            roles=frozenset({"learner"}),
            scopes=self.scopes,
            token_id="identity-jti",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )


class StubTenantAuthorizer:
    async def authorize(
        self,
        principal: AuthenticatedPrincipal,
        *,
        trace_id: str,
    ) -> TenantContext:
        return TenantContext(
            tenant_id=principal.tenant_id,
            subject_ref=principal.subject,
            roles=principal.roles,
            scopes=principal.scopes,
            trace_id=trace_id,
        )


class StubFixtureInbox:
    async def read(self, challenge_id):
        if challenge_id != CHALLENGE_ID:
            return None
        return FixtureInboxMessage(
            challenge_id=CHALLENGE_ID,
            code="123456",
            delivery_hint="u***@example.invalid",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


class StubIdentityService:
    def __init__(self) -> None:
        self.fixture_inbox = StubFixtureInbox()
        self.calls: list[str] = []

    @staticmethod
    def challenge() -> VerificationChallengeReceiptV1:
        return VerificationChallengeReceiptV1(
            challenge_id=CHALLENGE_ID,
            channel=IdentityContactChannel.EMAIL,
            purpose=IdentityChallengePurpose.REGISTER,
            state=IdentityChallengeState.PENDING,
            delivery_hint="u***@example.invalid",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            resend_after_seconds=60,
        )

    @staticmethod
    def profile(*, version: int = 1) -> AccountProfileV1:
        now = datetime.now(UTC)
        return AccountProfileV1(
            account_id=ACCOUNT_ID,
            tenant_id="tenant-a",
            subject_ref="subject:identity-api",
            display_name="Identity User",
            preferred_locale="zh-CN",
            email_hint="u***@example.invalid",
            email_verified=True,
            phone_hint=None,
            phone_verified=False,
            status=IdentityAccountStatus.ACTIVE,
            profile_version=version,
            created_at=now,
            updated_at=now,
        )

    async def request_challenge(self, *_args, **_kwargs):
        self.calls.append("request_challenge")
        return self.challenge()

    async def verify_challenge(self, *_args, **_kwargs):
        self.calls.append("verify_challenge")
        return self.challenge().model_copy(update={"state": IdentityChallengeState.VERIFIED})

    async def register_email(self, *_args, **_kwargs):
        self.calls.append("register_email")
        return self.registration()

    async def register_phone(self, *_args, **_kwargs):
        self.calls.append("register_phone")
        return self.registration()

    async def get_profile(self):
        self.calls.append("get_profile")
        return self.profile()

    async def update_profile(self, **_kwargs):
        self.calls.append("update_profile")
        return self.profile(version=2)

    async def change_contact(self, **_kwargs):
        self.calls.append("change_contact")
        return self.profile(version=2).model_copy(
            update={"phone_hint": "+1415***1234", "phone_verified": True}
        )

    async def list_accounts(self, **_kwargs):
        self.calls.append("list_accounts")
        return [self.admin_view()]

    async def get_account(self, _account_id):
        self.calls.append("get_account")
        return self.admin_view()

    async def get_registration_status(self, _registration_id):
        self.calls.append("get_registration_status")
        return self.registration_status()

    async def list_account_audit(self, _account_id, **_kwargs):
        self.calls.append("list_account_audit")
        return [self.audit_entry()]

    async def set_account_enabled(self, _account_id, *, enabled, **_kwargs):
        self.calls.append("restore" if enabled else "disable")
        return self.admin_view(enabled=enabled)

    @staticmethod
    def registration() -> RegistrationReceiptV1:
        return RegistrationReceiptV1(
            registration_id=REGISTRATION_ID,
            account_id=ACCOUNT_ID,
            preferred_locale="zh-CN",
            created_at=datetime.now(UTC),
        )

    @classmethod
    def admin_view(cls, *, enabled: bool = True) -> AccountAdminViewV1:
        document = cls.profile(version=2).model_dump(exclude={"schema_version", "status"})
        return AccountAdminViewV1(
            **document,
            status=(IdentityAccountStatus.ACTIVE if enabled else IdentityAccountStatus.DISABLED),
            disabled_reason_code=None if enabled else "ADMIN_DISABLED",
        )

    @staticmethod
    def registration_status() -> RegistrationStatusV1:
        return RegistrationStatusV1(
            registration_id=REGISTRATION_ID,
            registration_version=2,
            state=IdentityRegistrationState.COMPLETED,
            channel=IdentityContactChannel.EMAIL,
            account_id=ACCOUNT_ID,
            record_sha256="1" * 64,
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def audit_entry() -> IdentityAuditEntryV1:
        return IdentityAuditEntryV1(
            event_id=uuid4(),
            sequence=1,
            action="IDENTITY_ACCOUNT_REGISTERED",
            outcome="SUCCEEDED",
            actor_ref="subject:identity-api",
            target_ref=f"identity:account:{ACCOUNT_ID}",
            trace_id=TRACE_ID,
            metadata={"account_id": str(ACCOUNT_ID)},
            occurred_at=datetime.now(UTC),
            previous_hash="0" * 64,
            event_hash="2" * 64,
        )


def install_stubs(app, *, scopes: frozenset[str], service: StubIdentityService) -> None:
    app.state.token_verifier = StubTokenVerifier(scopes)
    app.state.tenant_authorizer = StubTenantAuthorizer()
    app.state.auth_configured = True
    app.state.identity_service = service


@pytest.mark.asyncio
async def test_public_identity_routes_and_fixture_inbox(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    app = create_app()
    service = StubIdentityService()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=("127.0.0.1", 9))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client,
    ):
        app.state.identity_service = service
        headers = {"x-trace-id": TRACE_ID, "idempotency-key": "a" * 32}
        challenge = await client.post(
            "/api/auth/verification-challenges",
            headers=headers,
            json={"channel": "EMAIL", "purpose": "REGISTER", "identifier": "u@example.com"},
        )
        assert challenge.status_code == 202
        assert challenge.json()["data"]["challenge"]["challenge_id"] == str(CHALLENGE_ID)
        inbox = await client.get(
            f"/api/auth/dev/verification-codes/{CHALLENGE_ID}",
            headers={"x-trace-id": TRACE_ID},
        )
        assert inbox.status_code == 200
        assert inbox.json()["data"]["code"] == "123456"
        private_transport = httpx.ASGITransport(
            app=app,
            raise_app_exceptions=False,
            client=("10.23.45.67", 9),
        )
        async with httpx.AsyncClient(
            transport=private_transport,
            base_url="http://localhost",
        ) as private_client:
            denied_inbox = await private_client.get(
                f"/api/auth/dev/verification-codes/{CHALLENGE_ID}",
                headers={"x-trace-id": TRACE_ID},
            )
        assert denied_inbox.status_code == 403
        verify = await client.post(
            "/api/auth/verification-challenges/verify",
            headers={"x-trace-id": TRACE_ID, "idempotency-key": "b" * 32},
            json={"challenge_id": str(CHALLENGE_ID), "code": "123456"},
        )
        assert verify.status_code == 200
        common = {
            "challenge_id": str(CHALLENGE_ID),
            "password": "Password123",
            "display_name": "Identity User",
            "preferred_locale": "zh-CN",
            "consent": {
                "privacy_policy_version": "privacy-v1",
                "terms_of_service_version": "terms-v1",
                "privacy_policy_accepted": True,
                "terms_of_service_accepted": True,
            },
        }
        email = await client.post(
            "/api/auth/register/email",
            headers={"x-trace-id": TRACE_ID, "idempotency-key": "c" * 32},
            json={**common, "email": "u@example.com"},
        )
        phone = await client.post(
            "/api/auth/register/phone",
            headers={"x-trace-id": TRACE_ID, "idempotency-key": "d" * 32},
            json={**common, "phone": "+14155551234"},
        )
        forged = await client.post(
            "/api/auth/verification-challenges",
            headers={**headers, "x-tenant-id": "forged"},
            json={"channel": "EMAIL", "purpose": "REGISTER", "identifier": "u@example.com"},
        )
    assert email.status_code == 201
    assert phone.status_code == 201
    assert forged.status_code == 400
    assert set(service.calls) >= {
        "request_challenge",
        "verify_challenge",
        "register_email",
        "register_phone",
    }
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_authenticated_profile_contact_and_admin_routes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LIYAN_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    app = create_app()
    service = StubIdentityService()
    scopes = frozenset(
        {
            "account:profile:read",
            "account:profile:write",
            "account:contact:write",
            "account:admin:read",
            "account:admin:write",
        }
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        install_stubs(app, scopes=scopes, service=service)
        auth = {"authorization": "Bearer identity-token", "x-trace-id": TRACE_ID}
        profile = await client.get("/internal/accounts/me", headers=auth)
        updated = await client.patch(
            "/internal/accounts/me",
            headers={**auth, "idempotency-key": "e" * 32},
            json={
                "display_name": "Updated",
                "preferred_locale": "en-US",
                "expected_version": 1,
            },
        )
        challenge = await client.post(
            "/internal/accounts/me/verification-challenges",
            headers={**auth, "idempotency-key": "f" * 32},
            json={
                "channel": "PHONE",
                "purpose": "CHANGE_PHONE",
                "identifier": "+14155551234",
            },
        )
        verified = await client.post(
            "/internal/accounts/me/verification-challenges/verify",
            headers={**auth, "idempotency-key": "1" * 32},
            json={"challenge_id": str(CHALLENGE_ID), "code": "123456"},
        )
        contact = await client.post(
            "/internal/accounts/me/contact",
            headers={**auth, "idempotency-key": "2" * 32},
            json={
                "channel": "PHONE",
                "identifier": "+14155551234",
                "challenge_id": str(CHALLENGE_ID),
                "expected_version": 2,
            },
        )
        listed = await client.get("/internal/tenant/accounts", headers=auth)
        audit = await client.get(
            f"/internal/tenant/accounts/{ACCOUNT_ID}/audit",
            headers=auth,
        )
        detail = await client.get(f"/internal/tenant/accounts/{ACCOUNT_ID}", headers=auth)
        registration = await client.get(
            f"/internal/tenant/registrations/{REGISTRATION_ID}",
            headers=auth,
        )
        disabled = await client.post(
            f"/internal/tenant/accounts/{ACCOUNT_ID}/disable",
            headers={**auth, "idempotency-key": "3" * 32},
            json={"expected_version": 2, "reason_code": "TEST"},
        )
        restored = await client.post(
            f"/internal/tenant/accounts/{ACCOUNT_ID}/restore",
            headers={**auth, "idempotency-key": "4" * 32},
            json={"expected_version": 3},
        )
        install_stubs(app, scopes=frozenset(), service=service)
        forbidden = await client.get("/internal/tenant/accounts", headers=auth)
    assert challenge.status_code == 202
    assert all(
        response.status_code == 200
        for response in (
            profile,
            updated,
            verified,
            contact,
            listed,
            audit,
            detail,
            registration,
            disabled,
            restored,
        )
    )
    assert forbidden.status_code == 403
    assert set(service.calls) >= {
        "get_profile",
        "update_profile",
        "change_contact",
        "list_accounts",
        "list_account_audit",
        "get_account",
        "get_registration_status",
        "disable",
        "restore",
    }
    get_settings.cache_clear()
