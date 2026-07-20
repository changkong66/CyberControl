from __future__ import annotations

import base64
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from liyans_contracts.identity import (
    IdentityChallengePurpose,
    IdentityContactChannel,
    IdentityRegistrationState,
    UserRegisterByEmailCommandV1,
    UserRegisterByPhoneCommandV1,
    VerificationChallengeRequestV1,
    VerificationChallengeVerifyV1,
)
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from liyans.core.errors import ErrorCode, LiyanError, MessageConflictError, RateLimitExceeded
from liyans.core.settings import Settings
from liyans.core.tenant import tenant_scope
from liyans.domains.identity.keycloak import KeycloakAdminClient, KeycloakUser
from liyans.domains.identity.models import (
    ContactChannel,
    IdentityAccountModel,
    IdentityReconciliationJobModel,
    IdentityRegistrationSnapshotModel,
    IdentityVerificationChallengeModel,
    ReconciliationState,
    RegistrationState,
)
from liyans.domains.identity.service import IdentityService
from liyans.infrastructure.database.context import session_context_from_tenant
from liyans.infrastructure.database.models import (
    AuditEventModel,
    IdempotencyRecordModel,
    OutboxMessageModel,
)
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

pytestmark = pytest.mark.integration

KEYCLOAK_BASE_URL = os.getenv("LIYAN_TEST_KEYCLOAK_BASE_URL")
KEYCLOAK_REALM = os.getenv("LIYAN_TEST_KEYCLOAK_REALM", "cybercontrol")
KEYCLOAK_CLIENT_ID = os.getenv(
    "LIYAN_TEST_KEYCLOAK_ADMIN_CLIENT_ID",
    "cybercontrol-registration-admin",
)
KEYCLOAK_CLIENT_SECRET = os.getenv("LIYAN_TEST_KEYCLOAK_ADMIN_CLIENT_SECRET")


class ReconciliationKeycloak:
    def __init__(self) -> None:
        self.user: KeycloakUser | None = None
        self.fail_reads = False
        self.restore_count = 0

    async def create_learner(
        self,
        *,
        registration_id: UUID,
        tenant_id: str,
        channel: str,
        identifier: str,
        password: str,
        display_name: str,
        preferred_locale: str,
        learner_permissions: str,
    ) -> KeycloakUser:
        del password, display_name
        attributes = {
            "tenant_id": (tenant_id,),
            "registration_id": (str(registration_id),),
            "preferred_locale": (preferred_locale,),
            "login_channel": (channel,),
            "permissions": (learner_permissions,),
        }
        if channel == "PHONE":
            attributes["phone_number"] = (identifier,)
        self.user = KeycloakUser(
            user_id=f"reconcile-{registration_id}",
            username=identifier,
            email=identifier if channel == "EMAIL" else None,
            enabled=True,
            attributes=attributes,
        )
        return self.user

    async def get_user(self, user_id: str) -> KeycloakUser:
        if self.fail_reads:
            raise RuntimeError("injected Keycloak read failure")
        if self.user is None or self.user.user_id != user_id:
            raise RuntimeError("Keycloak user is unavailable")
        return self.user

    async def find_by_registration_id(self, registration_id: UUID) -> KeycloakUser | None:
        if self.fail_reads:
            raise RuntimeError("injected Keycloak lookup failure")
        if self.user is None:
            return None
        registrations = self.user.attributes.get("registration_id", ())
        return self.user if str(registration_id) in registrations else None

    async def update_profile(
        self,
        user_id: str,
        *,
        display_name: str,
        preferred_locale: str,
        current_user: KeycloakUser | None = None,
    ) -> None:
        user = current_user or await self.get_user(user_id)
        attributes = dict(user.attributes)
        attributes["preferred_locale"] = (preferred_locale,)
        self.user = replace(
            user,
            display_name=display_name,
            attributes=attributes,
        )

    async def restore_user(self, user: KeycloakUser) -> None:
        self.restore_count += 1
        self.user = user

    async def close(self) -> None:
        return None


def _jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))


@pytest.mark.asyncio
async def test_postgres_identity_reconciler_role_is_catalog_only(
    postgres_reconciler,
) -> None:
    async with postgres_reconciler.transaction() as session:
        role_name = await session.scalar(text("SELECT current_user"))
        grants = {
            (str(row.column_name), str(row.privilege_type))
            for row in (
                await session.execute(
                    text(
                        "SELECT column_name, privilege_type "
                        "FROM information_schema.column_privileges "
                        "WHERE grantee = current_user "
                        "AND table_schema = 'public' "
                        "AND table_name = 'identity_reconciliation_jobs'"
                    )
                )
            )
        }
        await session.execute(text("SELECT DISTINCT tenant_id FROM identity_reconciliation_jobs"))
    assert role_name == "liyans_identity_reconciler"
    assert grants == {("tenant_id", "SELECT")}

    with pytest.raises(DBAPIError):
        async with postgres_reconciler.transaction() as session:
            await session.execute(
                text("SELECT job_document FROM identity_reconciliation_jobs LIMIT 1")
            )

    with pytest.raises(DBAPIError):
        async with postgres_reconciler.transaction() as session:
            await session.execute(text("SELECT account_id FROM identity_accounts LIMIT 1"))


@pytest.mark.asyncio
async def test_real_postgres_keycloak_registration_oidc_rls_and_evidence(
    postgres_runtime,
) -> None:
    if not KEYCLOAK_BASE_URL or not KEYCLOAK_CLIENT_SECRET:
        pytest.skip("real Keycloak integration is not configured")
    database, migrator, context = postgres_runtime
    settings = Settings(
        registration_enabled=True,
        registration_development_tenant_id=context.tenant_id,
        registration_allow_development_fallback=True,
        registration_fixture_inbox_enabled=True,
        keycloak_admin_base_url=KEYCLOAK_BASE_URL,
        keycloak_admin_realm=KEYCLOAK_REALM,
        keycloak_admin_client_id=KEYCLOAK_CLIENT_ID,
        keycloak_admin_client_secret=KEYCLOAK_CLIENT_SECRET,
        identity_encryption_secret="integration-identity-encryption-secret-32-bytes",
        identity_lookup_pepper="integration-identity-lookup-pepper-32-bytes",
        verification_code_pepper="integration-verification-code-pepper-32-bytes",
    )
    keycloak = KeycloakAdminClient(
        base_url=KEYCLOAK_BASE_URL,
        realm=KEYCLOAK_REALM,
        client_id=KEYCLOAK_CLIENT_ID,
        client_secret=KEYCLOAK_CLIENT_SECRET,
        timeout_seconds=5,
        max_response_bytes=512 * 1024,
    )
    service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings,
        keycloak=keycloak,
        instance_id="identity-integration",
    )
    email = f"identity-{uuid4().hex[:16]}@example.invalid"
    password = "StrongPassword123"
    subject = None
    try:
        challenge = await service.request_challenge(
            VerificationChallengeRequestV1(
                channel=IdentityContactChannel.EMAIL,
                purpose=IdentityChallengePurpose.REGISTER,
                identifier=email,
            ),
            idempotency_key=f"identity-challenge-{uuid4().hex}",
            trace_id=context.trace_id,
            client_ip="127.0.0.1",
            user_agent="pytest-keycloak-integration",
        )
        fixture = await service.fixture_inbox.read(challenge.challenge_id)
        assert fixture is not None
        verified = await service.verify_challenge(
            VerificationChallengeVerifyV1(
                challenge_id=challenge.challenge_id,
                code=fixture.code,
            ),
            idempotency_key=f"identity-verify-{uuid4().hex}",
            invitation_token=None,
            trace_id=context.trace_id,
        )
        assert verified.state.value == "VERIFIED"
        command = UserRegisterByEmailCommandV1(
            challenge_id=challenge.challenge_id,
            email=email,
            password=password,
            display_name="Integration Learner",
            preferred_locale="zh-CN",
            consent={
                "privacy_policy_version": "privacy-v1",
                "terms_of_service_version": "terms-v1",
                "privacy_policy_accepted": True,
                "terms_of_service_accepted": True,
            },
        )
        idempotency_key = f"identity-register-{uuid4().hex}"
        receipt = await service.register_email(
            command,
            idempotency_key=idempotency_key,
            trace_id=context.trace_id,
        )
        repeated = await service.register_email(
            command,
            idempotency_key=idempotency_key,
            trace_id=context.trace_id,
        )
        assert repeated == receipt

        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                await session.execute(
                    delete(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.operation == "identity.register"
                    )
                )
        recovered_after_idempotency_purge = await service.register_email(
            command,
            idempotency_key=idempotency_key,
            trace_id=context.trace_id,
        )
        assert recovered_after_idempotency_purge == receipt
        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                await session.execute(
                    delete(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.operation == "identity.register"
                    )
                )
        with pytest.raises(MessageConflictError):
            await service.register_email(
                command.model_copy(update={"email": f"changed-{uuid4().hex[:12]}@example.invalid"}),
                idempotency_key=idempotency_key,
                trace_id=context.trace_id,
            )

        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                account = await session.scalar(
                    select(IdentityAccountModel).where(
                        IdentityAccountModel.account_id == receipt.account_id
                    )
                )
                assert account is not None
                subject = account.oidc_subject
                assert account.email_ciphertext != email
                assert email not in account.email_ciphertext
                assert account.email_lookup_digest and len(account.email_lookup_digest) == 64
                assert account.email_verified is True
                challenge_row = await session.scalar(
                    select(IdentityVerificationChallengeModel).where(
                        IdentityVerificationChallengeModel.challenge_id == challenge.challenge_id
                    )
                )
                assert challenge_row is not None
                assert challenge_row.state == "CONSUMED"
                assert challenge_row.code_digest != fixture.code
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(AuditEventModel.category == "IDENTITY")
                )
                outbox_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessageModel)
                    .where(OutboxMessageModel.event_type == "identity.account.registered")
                )
                assert audit_count >= 3
                assert outbox_count == 1

        user_context = replace(
            context,
            subject_ref=subject,
            roles=frozenset({"learner"}),
            scopes=frozenset(
                {"account:profile:read", "account:profile:write", "account:contact:write"}
            ),
        )
        with tenant_scope(user_context):
            profile = await service.get_profile()
            assert profile.display_name == "Integration Learner"
            profile_expected_version = profile.profile_version
            profile_idempotency_key = f"identity-profile-{uuid4().hex}"
            profile = await service.update_profile(
                display_name="Updated Integration Learner",
                preferred_locale="zh-TW",
                expected_version=profile_expected_version,
                idempotency_key=profile_idempotency_key,
            )
            assert profile.display_name == "Updated Integration Learner"
            assert profile.preferred_locale == "zh-TW"
            replayed_profile = await service.update_profile(
                display_name="Updated Integration Learner",
                preferred_locale="zh-TW",
                expected_version=profile_expected_version,
                idempotency_key=profile_idempotency_key,
            )
            assert replayed_profile == profile
            phone = f"+1415{uuid4().int % 10_000_000:07d}"
            contact_challenge = await service.request_challenge(
                VerificationChallengeRequestV1(
                    channel=IdentityContactChannel.PHONE,
                    purpose=IdentityChallengePurpose.CHANGE_PHONE,
                    identifier=phone,
                ),
                idempotency_key=f"identity-contact-challenge-{uuid4().hex}",
                trace_id=context.trace_id,
                client_ip="127.0.0.3",
                user_agent="pytest-contact-integration",
                context=user_context,
            )
            contact_fixture = await service.fixture_inbox.read(contact_challenge.challenge_id)
            assert contact_fixture is not None
            await service.verify_challenge(
                VerificationChallengeVerifyV1(
                    challenge_id=contact_challenge.challenge_id,
                    code=contact_fixture.code,
                ),
                idempotency_key=f"identity-contact-verify-{uuid4().hex}",
                invitation_token=None,
                trace_id=context.trace_id,
                context=user_context,
            )
            contact_expected_version = profile.profile_version
            contact_idempotency_key = f"identity-contact-change-{uuid4().hex}"
            profile = await service.change_contact(
                channel=ContactChannel.PHONE,
                identifier=phone,
                challenge_id=contact_challenge.challenge_id,
                expected_version=contact_expected_version,
                idempotency_key=contact_idempotency_key,
            )
            assert profile.phone_verified is True
            assert profile.phone_hint and profile.phone_hint.endswith(phone[-4:])
            replayed_contact = await service.change_contact(
                channel=ContactChannel.PHONE,
                identifier=phone,
                challenge_id=contact_challenge.challenge_id,
                expected_version=contact_expected_version,
                idempotency_key=contact_idempotency_key,
            )
            assert replayed_contact == profile

        admin_context = replace(
            context,
            subject_ref="subject:tenant-admin",
            roles=frozenset({"tenant-admin"}),
            scopes=frozenset({"account:admin:read", "account:admin:write"}),
        )
        with tenant_scope(admin_context):
            registration_status = await service.get_registration_status(receipt.registration_id)
            assert registration_status.state == IdentityRegistrationState.COMPLETED
            assert registration_status.account_id == receipt.account_id
            assert len(registration_status.record_sha256) == 64
            accounts = await service.list_accounts(offset=0, limit=200)
            account_view = next(item for item in accounts if item.account_id == receipt.account_id)
            audit_entries = await service.list_account_audit(
                receipt.account_id,
                offset=0,
                limit=200,
            )
            assert any(entry.action == "IDENTITY_ACCOUNT_REGISTERED" for entry in audit_entries)
            assert all(entry.hash_algorithm == "SHA-256" for entry in audit_entries)
            disable_idempotency_key = f"identity-disable-{uuid4().hex}"
            disabled = await service.set_account_enabled(
                receipt.account_id,
                enabled=False,
                reason_code="INTEGRATION_TEST",
                expected_version=account_view.profile_version,
                idempotency_key=disable_idempotency_key,
            )
            assert disabled.status.value == "DISABLED"
            replayed_disabled = await service.set_account_enabled(
                receipt.account_id,
                enabled=False,
                reason_code="INTEGRATION_TEST",
                expected_version=account_view.profile_version,
                idempotency_key=disable_idempotency_key,
            )
            assert replayed_disabled == disabled
        disabled_login = await _password_login(email, password)
        assert disabled_login.status_code in {400, 401}
        assert disabled_login.json()["error"] == "invalid_grant"
        with tenant_scope(admin_context):
            restored = await service.set_account_enabled(
                receipt.account_id,
                enabled=True,
                reason_code=None,
                expected_version=disabled.profile_version,
                idempotency_key=f"identity-restore-{uuid4().hex}",
            )
            assert restored.status.value == "ACTIVE"

        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                account_jobs = list(
                    (
                        await session.scalars(
                            select(IdentityReconciliationJobModel).where(
                                IdentityReconciliationJobModel.account_id == receipt.account_id,
                                IdentityReconciliationJobModel.operation == "UPDATE_KEYCLOAK_USER",
                            )
                        )
                    ).all()
                )
                assert len(account_jobs) == 4
                assert all(job.state == ReconciliationState.COMPLETED.value for job in account_jobs)

        async with database.transaction() as session:
            visible_without_context = await session.scalar(
                select(func.count()).select_from(IdentityAccountModel)
            )
        assert visible_without_context == 0

        other_context = replace(context, tenant_id=f"it-{uuid4().hex[:24]}")
        async with migrator.transaction(
            context=session_context_from_tenant(other_context)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO tenants "
                    "(tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim) "
                    "VALUES (:tenant_id, :slug, 'Other Tenant', 'https://issuer.test', :claim)"
                ),
                {
                    "tenant_id": other_context.tenant_id,
                    "slug": other_context.tenant_id,
                    "claim": other_context.tenant_id,
                },
            )
        async with database.transaction(
            context=session_context_from_tenant(other_context)
        ) as session:
            foreign = await session.scalar(
                select(IdentityAccountModel).where(
                    IdentityAccountModel.account_id == receipt.account_id
                )
            )
        assert foreign is None
        with tenant_scope(other_context):
            with pytest.raises(LiyanError) as hidden_registration:
                await service.get_registration_status(receipt.registration_id)
            assert hidden_registration.value.code == ErrorCode.IDENTITY_REGISTRATION_NOT_FOUND

        snapshot_id = await _snapshot_id(database, context, receipt.registration_id)
        with pytest.raises(DBAPIError):
            async with migrator.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                await session.execute(
                    update(IdentityRegistrationSnapshotModel)
                    .where(
                        IdentityRegistrationSnapshotModel.registration_snapshot_id == snapshot_id
                    )
                    .values(state="FAILED")
                )

        async with httpx.AsyncClient(base_url=KEYCLOAK_BASE_URL, timeout=10) as client:
            token_response = await client.post(
                f"/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "cybercontrol-cli",
                    "username": email,
                    "password": password,
                },
            )
        assert token_response.status_code == 200
        claims = _jwt_claims(token_response.json()["access_token"])
        assert claims["tenant_id"] == context.tenant_id
        assert "learner" in claims["roles"]
        assert "account:profile:read" in claims["permissions"].split()
    finally:
        if subject is not None:
            await keycloak.delete_user(subject)
        await service.close()


async def _snapshot_id(database, context, registration_id):
    with tenant_scope(context):
        async with database.transaction(context=session_context_from_tenant(context)) as session:
            return await session.scalar(
                select(IdentityRegistrationSnapshotModel.registration_snapshot_id)
                .where(IdentityRegistrationSnapshotModel.registration_id == registration_id)
                .order_by(IdentityRegistrationSnapshotModel.registration_version)
                .limit(1)
            )


async def _password_login(username: str, password: str) -> httpx.Response:
    async with httpx.AsyncClient(base_url=KEYCLOAK_BASE_URL, timeout=10) as client:
        return await client.post(
            f"/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "cybercontrol-cli",
                "username": username,
                "password": password,
            },
        )


@pytest.mark.asyncio
async def test_real_phone_registration_can_login_without_email(postgres_runtime) -> None:
    if not KEYCLOAK_BASE_URL or not KEYCLOAK_CLIENT_SECRET:
        pytest.skip("real Keycloak integration is not configured")
    database, _migrator, context = postgres_runtime
    settings = Settings(
        registration_enabled=True,
        registration_development_tenant_id=context.tenant_id,
        registration_allow_development_fallback=True,
        registration_fixture_inbox_enabled=True,
        keycloak_admin_base_url=KEYCLOAK_BASE_URL,
        keycloak_admin_realm=KEYCLOAK_REALM,
        keycloak_admin_client_id=KEYCLOAK_CLIENT_ID,
        keycloak_admin_client_secret=KEYCLOAK_CLIENT_SECRET,
        identity_encryption_secret="integration-identity-encryption-secret-32-bytes",
        identity_lookup_pepper="integration-identity-lookup-pepper-32-bytes",
        verification_code_pepper="integration-verification-code-pepper-32-bytes",
    )
    keycloak = KeycloakAdminClient(
        base_url=KEYCLOAK_BASE_URL,
        realm=KEYCLOAK_REALM,
        client_id=KEYCLOAK_CLIENT_ID,
        client_secret=KEYCLOAK_CLIENT_SECRET,
        timeout_seconds=5,
        max_response_bytes=512 * 1024,
    )
    service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings,
        keycloak=keycloak,
        instance_id="identity-phone-integration",
    )
    phone = f"+8613{uuid4().int % 10_000_000_000:010d}"
    password = "StrongPhone123"
    subject = None
    try:
        challenge = await service.request_challenge(
            VerificationChallengeRequestV1(
                channel=IdentityContactChannel.PHONE,
                purpose=IdentityChallengePurpose.REGISTER,
                identifier=phone,
            ),
            idempotency_key=f"identity-phone-challenge-{uuid4().hex}",
            trace_id=context.trace_id,
            client_ip="127.0.0.2",
            user_agent="pytest-phone-integration",
        )
        fixture = await service.fixture_inbox.read(challenge.challenge_id)
        assert fixture is not None
        await service.verify_challenge(
            VerificationChallengeVerifyV1(
                challenge_id=challenge.challenge_id,
                code=fixture.code,
            ),
            idempotency_key=f"identity-phone-verify-{uuid4().hex}",
            invitation_token=None,
            trace_id=context.trace_id,
        )
        receipt = await service.register_phone(
            UserRegisterByPhoneCommandV1(
                challenge_id=challenge.challenge_id,
                phone=phone,
                password=password,
                display_name="Phone Learner",
                preferred_locale="en-US",
                consent={
                    "privacy_policy_version": "privacy-v1",
                    "terms_of_service_version": "terms-v1",
                    "privacy_policy_accepted": True,
                    "terms_of_service_accepted": True,
                },
            ),
            idempotency_key=f"identity-phone-register-{uuid4().hex}",
            trace_id=context.trace_id,
        )
        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                account = await session.scalar(
                    select(IdentityAccountModel).where(
                        IdentityAccountModel.account_id == receipt.account_id
                    )
                )
                assert account is not None
                subject = account.oidc_subject
                assert account.email_ciphertext is None
                assert account.phone_ciphertext and phone not in account.phone_ciphertext
                assert account.phone_verified is True
        async with httpx.AsyncClient(base_url=KEYCLOAK_BASE_URL, timeout=10) as client:
            token_response = await client.post(
                f"/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "cybercontrol-cli",
                    "username": phone,
                    "password": password,
                },
            )
        assert token_response.status_code == 200
        claims = _jwt_claims(token_response.json()["access_token"])
        assert claims["tenant_id"] == context.tenant_id
        assert "learner" in claims["roles"]
    finally:
        if subject is not None:
            await keycloak.delete_user(subject)
        await service.close()


@pytest.mark.asyncio
async def test_postgres_challenge_guards_cooldown_expiry_and_lockout(postgres_runtime) -> None:
    database, _migrator, context = postgres_runtime
    settings = Settings(
        registration_enabled=True,
        registration_development_tenant_id=context.tenant_id,
        registration_allow_development_fallback=True,
        registration_fixture_inbox_enabled=True,
        registration_challenge_max_attempts=2,
        registration_rate_limit_max_requests=50,
        identity_encryption_secret="integration-identity-encryption-secret-32-bytes",
        identity_lookup_pepper="integration-identity-lookup-pepper-32-bytes",
        verification_code_pepper="integration-verification-code-pepper-32-bytes",
    )
    service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings,
        keycloak=None,
        instance_id="identity-challenge-guards",
    )
    command = VerificationChallengeRequestV1(
        channel=IdentityContactChannel.EMAIL,
        purpose=IdentityChallengePurpose.REGISTER,
        identifier=f"guard-{uuid4().hex[:12]}@example.invalid",
    )
    request_key = f"identity-guard-request-{uuid4().hex}"
    try:
        with pytest.raises(LiyanError):
            await service.request_challenge(
                command,
                idempotency_key="short",
                trace_id=context.trace_id,
                client_ip="127.0.0.10",
                user_agent="pytest-identity-guards",
            )
        with pytest.raises(LiyanError) as unauthenticated_contact:
            await service.request_challenge(
                VerificationChallengeRequestV1(
                    channel=IdentityContactChannel.EMAIL,
                    purpose=IdentityChallengePurpose.CHANGE_EMAIL,
                    identifier=command.identifier,
                ),
                idempotency_key=f"identity-guard-contact-{uuid4().hex}",
                trace_id=context.trace_id,
                client_ip="127.0.0.10",
                user_agent="pytest-identity-guards",
            )
        assert unauthenticated_contact.value.code == ErrorCode.IDENTITY_INVITATION_INVALID
        with pytest.raises(LiyanError):
            await service.request_challenge(
                command,
                idempotency_key=f"identity-guard-authenticated-{uuid4().hex}",
                trace_id=context.trace_id,
                client_ip="127.0.0.10",
                user_agent="pytest-identity-guards",
                context=context,
            )

        first = await service.request_challenge(
            command,
            idempotency_key=request_key,
            trace_id=context.trace_id,
            client_ip="127.0.0.10",
            user_agent="pytest-identity-guards",
        )
        repeated = await service.request_challenge(
            command,
            idempotency_key=request_key,
            trace_id=context.trace_id,
            client_ip="127.0.0.10",
            user_agent="pytest-identity-guards",
        )
        assert repeated.challenge_id == first.challenge_id
        with pytest.raises(MessageConflictError):
            await service.request_challenge(
                command.model_copy(
                    update={"identifier": f"other-{uuid4().hex[:12]}@example.invalid"}
                ),
                idempotency_key=request_key,
                trace_id=context.trace_id,
                client_ip="127.0.0.10",
                user_agent="pytest-identity-guards",
            )
        cooldown = await service.request_challenge(
            command,
            idempotency_key=f"identity-guard-cooldown-{uuid4().hex}",
            trace_id=context.trace_id,
            client_ip="127.0.0.10",
            user_agent="pytest-identity-guards",
        )
        assert cooldown.challenge_id == first.challenge_id

        fixture = await service.fixture_inbox.read(first.challenge_id)
        assert fixture is not None
        wrong_code = "000000" if fixture.code != "000000" else "999999"
        for attempt in range(2):
            with pytest.raises(LiyanError) as rejected:
                await service.verify_challenge(
                    VerificationChallengeVerifyV1(
                        challenge_id=first.challenge_id,
                        code=wrong_code,
                    ),
                    idempotency_key=f"identity-guard-wrong-{attempt}-{uuid4().hex}",
                    invitation_token=None,
                    trace_id=context.trace_id,
                )
            assert rejected.value.code == ErrorCode.IDENTITY_CHALLENGE_INVALID
        with pytest.raises(LiyanError) as locked:
            await service.verify_challenge(
                VerificationChallengeVerifyV1(
                    challenge_id=first.challenge_id,
                    code=fixture.code,
                ),
                idempotency_key=f"identity-guard-locked-{uuid4().hex}",
                invitation_token=None,
                trace_id=context.trace_id,
            )
        assert locked.value.code == ErrorCode.IDENTITY_CHALLENGE_INVALID

        expiring = await service.request_challenge(
            command.model_copy(
                update={"identifier": f"expired-{uuid4().hex[:12]}@example.invalid"}
            ),
            idempotency_key=f"identity-guard-expiring-{uuid4().hex}",
            trace_id=context.trace_id,
            client_ip="127.0.0.11",
            user_agent="pytest-identity-expiry",
        )
        expiring_fixture = await service.fixture_inbox.read(expiring.challenge_id)
        assert expiring_fixture is not None
        expired_now = datetime.now(UTC)
        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                await session.execute(
                    update(IdentityVerificationChallengeModel)
                    .where(IdentityVerificationChallengeModel.challenge_id == expiring.challenge_id)
                    .values(
                        created_at=expired_now - timedelta(minutes=10),
                        last_sent_at=expired_now - timedelta(minutes=10),
                        expires_at=expired_now - timedelta(minutes=5),
                        updated_at=expired_now,
                    )
                )
        with pytest.raises(LiyanError) as expired:
            await service.verify_challenge(
                VerificationChallengeVerifyV1(
                    challenge_id=expiring.challenge_id,
                    code=expiring_fixture.code,
                ),
                idempotency_key=f"identity-guard-expired-{uuid4().hex}",
                invitation_token=None,
                trace_id=context.trace_id,
            )
        assert expired.value.code == ErrorCode.IDENTITY_CHALLENGE_EXPIRED

        with pytest.raises(LiyanError) as missing:
            await service.verify_challenge(
                VerificationChallengeVerifyV1(challenge_id=uuid4(), code="123456"),
                idempotency_key=f"identity-guard-missing-{uuid4().hex}",
                invitation_token=None,
                trace_id=context.trace_id,
            )
        assert missing.value.code == ErrorCode.IDENTITY_CHALLENGE_INVALID
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_postgres_registration_rate_limit_and_unconfigured_provider_fail_closed(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    settings = Settings(
        registration_enabled=True,
        registration_development_tenant_id=context.tenant_id,
        registration_allow_development_fallback=True,
        registration_fixture_inbox_enabled=True,
        registration_rate_limit_max_requests=1,
        identity_encryption_secret="integration-identity-encryption-secret-32-bytes",
        identity_lookup_pepper="integration-identity-lookup-pepper-32-bytes",
        verification_code_pepper="integration-verification-code-pepper-32-bytes",
    )
    service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings,
        keycloak=None,
        instance_id="identity-provider-disabled",
    )
    first_command = VerificationChallengeRequestV1(
        channel=IdentityContactChannel.EMAIL,
        purpose=IdentityChallengePurpose.REGISTER,
        identifier=f"disabled-{uuid4().hex[:12]}@example.invalid",
    )
    disabled_service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings.model_copy(update={"registration_enabled": False}),
        keycloak=None,
        instance_id="identity-registration-disabled",
    )
    try:
        with pytest.raises(LiyanError) as disabled:
            await disabled_service.request_challenge(
                first_command,
                idempotency_key=f"identity-disabled-registration-{uuid4().hex}",
                trace_id=context.trace_id,
                client_ip="127.0.0.20",
                user_agent="pytest-registration-disabled",
            )
        assert disabled.value.code == ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE
    finally:
        await disabled_service.close()
    try:
        challenge = await service.request_challenge(
            first_command,
            idempotency_key=f"identity-disabled-challenge-{uuid4().hex}",
            trace_id=context.trace_id,
            client_ip="127.0.0.20",
            user_agent="pytest-rate-limit",
        )
        with pytest.raises(RateLimitExceeded):
            await service.request_challenge(
                first_command.model_copy(
                    update={"identifier": f"limited-{uuid4().hex[:12]}@example.invalid"}
                ),
                idempotency_key=f"identity-limited-challenge-{uuid4().hex}",
                trace_id=context.trace_id,
                client_ip="127.0.0.20",
                user_agent="pytest-rate-limit",
            )
        fixture = await service.fixture_inbox.read(challenge.challenge_id)
        assert fixture is not None
        await service.verify_challenge(
            VerificationChallengeVerifyV1(
                challenge_id=challenge.challenge_id,
                code=fixture.code,
            ),
            idempotency_key=f"identity-disabled-verify-{uuid4().hex}",
            invitation_token=None,
            trace_id=context.trace_id,
        )
        command = UserRegisterByEmailCommandV1(
            challenge_id=challenge.challenge_id,
            email=first_command.identifier,
            password="Password123",
            display_name="Disabled Provider",
            preferred_locale="zh-CN",
            consent={
                "privacy_policy_version": "privacy-v1",
                "terms_of_service_version": "terms-v1",
                "privacy_policy_accepted": True,
                "terms_of_service_accepted": True,
            },
        )
        idempotency_key = f"identity-disabled-register-{uuid4().hex}"
        with pytest.raises(LiyanError) as unavailable:
            await service.register_email(
                command,
                idempotency_key=idempotency_key,
                trace_id=context.trace_id,
            )
        assert unavailable.value.code == ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE
        with pytest.raises(MessageConflictError):
            await service.register_email(
                command.model_copy(update={"display_name": "Changed Content"}),
                idempotency_key=idempotency_key,
                trace_id=context.trace_id,
            )
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_postgres_registration_reconciliation_retries_and_completes(
    postgres_runtime,
    monkeypatch,
) -> None:
    database, _migrator, context = postgres_runtime
    settings = Settings(
        registration_enabled=True,
        registration_development_tenant_id=context.tenant_id,
        registration_allow_development_fallback=True,
        registration_fixture_inbox_enabled=True,
        identity_encryption_secret="integration-identity-encryption-secret-32-bytes",
        identity_lookup_pepper="integration-identity-lookup-pepper-32-bytes",
        verification_code_pepper="integration-verification-code-pepper-32-bytes",
    )
    keycloak = ReconciliationKeycloak()
    service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings,
        keycloak=keycloak,
        instance_id="identity-reconciliation-integration",
    )
    email = f"reconcile-{uuid4().hex[:12]}@example.invalid"
    try:
        challenge = await service.request_challenge(
            VerificationChallengeRequestV1(
                channel=IdentityContactChannel.EMAIL,
                purpose=IdentityChallengePurpose.REGISTER,
                identifier=email,
            ),
            idempotency_key=f"identity-reconcile-challenge-{uuid4().hex}",
            trace_id=context.trace_id,
            client_ip="127.0.0.30",
            user_agent="pytest-reconciliation",
        )
        fixture = await service.fixture_inbox.read(challenge.challenge_id)
        assert fixture is not None
        await service.verify_challenge(
            VerificationChallengeVerifyV1(
                challenge_id=challenge.challenge_id,
                code=fixture.code,
            ),
            idempotency_key=f"identity-reconcile-verify-{uuid4().hex}",
            invitation_token=None,
            trace_id=context.trace_id,
        )
        command = UserRegisterByEmailCommandV1(
            challenge_id=challenge.challenge_id,
            email=email,
            password="Password123",
            display_name="Reconciliation Learner",
            preferred_locale="en-US",
            consent={
                "privacy_policy_version": "privacy-v1",
                "terms_of_service_version": "terms-v1",
                "privacy_policy_accepted": True,
                "terms_of_service_accepted": True,
            },
        )
        registration_key = f"identity-reconcile-register-{uuid4().hex}"
        original_finalize = service._finalize_registration

        async def fail_projection_once(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("injected PostgreSQL projection failure")

        monkeypatch.setattr(service, "_finalize_registration", fail_projection_once)
        with pytest.raises(LiyanError) as unavailable:
            await service.register_email(
                command,
                idempotency_key=registration_key,
                trace_id=context.trace_id,
            )
        assert unavailable.value.code == ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE
        monkeypatch.setattr(service, "_finalize_registration", original_finalize)

        with pytest.raises(LiyanError) as pending_retry:
            await service.register_email(
                command,
                idempotency_key=registration_key,
                trace_id=context.trace_id,
            )
        assert pending_retry.value.code == ErrorCode.IDENTITY_ACCOUNT_CONFLICT

        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                job = await session.scalar(select(IdentityReconciliationJobModel))
                latest = await session.scalar(
                    select(IdentityRegistrationSnapshotModel)
                    .order_by(IdentityRegistrationSnapshotModel.registration_version.desc())
                    .limit(1)
                )
                assert job is not None
                assert job.state == ReconciliationState.PENDING.value
                assert latest is not None
                assert latest.state == RegistrationState.PROJECTION_PENDING.value

        keycloak.fail_reads = True
        assert await service.reconcile_known_tenants(limit_per_tenant=5) == 0
        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                job = await session.scalar(select(IdentityReconciliationJobModel))
                assert job is not None
                assert job.state == ReconciliationState.PENDING.value
                assert job.attempt_count == 1
                job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)

        keycloak.fail_reads = False
        assert await service.reconcile_known_tenants(limit_per_tenant=5) == 1
        with tenant_scope(context):
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                job = await session.scalar(select(IdentityReconciliationJobModel))
                latest = await session.scalar(
                    select(IdentityRegistrationSnapshotModel)
                    .order_by(IdentityRegistrationSnapshotModel.registration_version.desc())
                    .limit(1)
                )
                account = await session.scalar(select(IdentityAccountModel))
                assert job is not None
                assert job.state == ReconciliationState.COMPLETED.value
                assert latest is not None
                assert latest.state == RegistrationState.COMPLETED.value
                assert account is not None
                assert account.oidc_subject == keycloak.user.user_id
        repeated = await service.register_email(
            command,
            idempotency_key=registration_key,
            trace_id=context.trace_id,
        )
        assert repeated.account_id == account.account_id
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_postgres_profile_update_compensates_keycloak_after_projection_failure(
    postgres_runtime,
    postgres_reconciler,
    monkeypatch,
) -> None:
    database, _migrator, context = postgres_runtime
    settings = Settings(
        registration_enabled=True,
        registration_development_tenant_id=context.tenant_id,
        registration_allow_development_fallback=True,
        identity_encryption_secret="integration-identity-encryption-secret-32-bytes",
        identity_lookup_pepper="integration-identity-lookup-pepper-32-bytes",
        verification_code_pepper="integration-verification-code-pepper-32-bytes",
        registration_reconciliation_claim_lease_seconds=1,
    )
    email = f"compensate-{uuid4().hex[:12]}@example.invalid"
    original_user = KeycloakUser(
        user_id=context.subject_ref,
        username=email,
        email=email,
        enabled=True,
        attributes={
            "tenant_id": (context.tenant_id,),
            "login_channel": ("EMAIL",),
            "preferred_locale": ("zh-CN",),
        },
        display_name="Original Learner",
        email_verified=True,
    )
    keycloak = ReconciliationKeycloak()
    keycloak.user = original_user
    service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings,
        keycloak=keycloak,
        instance_id="identity-profile-compensation",
    )
    idempotency_key = f"identity-compensation-{uuid4().hex}"
    restarted_service = None
    stale_claim_token = uuid4()
    try:
        with tenant_scope(context):
            profile = await service.get_profile()
            original_commit = service._commit_profile_update

            async def fail_projection_once(*args, **kwargs):
                del args, kwargs
                raise RuntimeError("injected account projection failure")

            monkeypatch.setattr(service, "_commit_profile_update", fail_projection_once)
            with pytest.raises(RuntimeError, match="injected account projection failure"):
                await service.update_profile(
                    display_name="Uncommitted Learner",
                    preferred_locale="en-US",
                    expected_version=profile.profile_version,
                    idempotency_key=idempotency_key,
                )
            assert keycloak.user is not None
            assert keycloak.user.display_name == "Uncommitted Learner"

            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                account = await session.scalar(select(IdentityAccountModel))
                job = await session.scalar(
                    select(IdentityReconciliationJobModel).where(
                        IdentityReconciliationJobModel.account_id == profile.account_id,
                        IdentityReconciliationJobModel.state == ReconciliationState.PENDING.value,
                    )
                )
                assert account is not None
                assert account.display_name == "Original Learner"
                assert job is not None
                serialized_job = json.dumps(job.job_document, sort_keys=True)
                assert "Original Learner" not in serialized_job
                assert email not in serialized_job

            with pytest.raises(LiyanError) as concurrent_mutation:
                await service.update_profile(
                    display_name="Concurrent Learner",
                    preferred_locale="zh-TW",
                    expected_version=profile.profile_version,
                    idempotency_key=f"identity-concurrent-{uuid4().hex}",
                )
            assert concurrent_mutation.value.code == ErrorCode.IDENTITY_ACCOUNT_CONFLICT

            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                job = await session.scalar(
                    select(IdentityReconciliationJobModel).where(
                        IdentityReconciliationJobModel.account_id == profile.account_id,
                        IdentityReconciliationJobModel.state == ReconciliationState.PENDING.value,
                    )
                )
                assert job is not None
                stale_job_id = job.reconciliation_job_id
                job.state = ReconciliationState.RUNNING.value
                job.claim_token = stale_claim_token
                job.claimed_by = "identity-stale-worker"
                job.attempt_count = 1
                job.updated_at = datetime.now(UTC) - timedelta(seconds=2)

            restarted_service = IdentityService(
                database,
                PostgresOutboxRepository(database),
                settings,
                keycloak=keycloak,
                instance_id="identity-profile-compensation-restarted",
                reconciliation_catalog=postgres_reconciler,
            )
            assert restarted_service._known_tenants == set()
            assert await restarted_service.reconcile_known_tenants(limit_per_tenant=5) >= 1
            assert keycloak.user == original_user
            assert keycloak.restore_count == 1
            assert (
                await service._finish_reconciliation_job(
                    context,
                    stale_job_id,
                    claim_token=stale_claim_token,
                    succeeded=True,
                )
                is False
            )

            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                job = await session.scalar(
                    select(IdentityReconciliationJobModel).where(
                        IdentityReconciliationJobModel.account_id == profile.account_id
                    )
                )
                record = await session.scalar(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.operation == "identity.profile.update"
                    )
                )
                compensated = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessageModel)
                    .where(OutboxMessageModel.event_type == "identity.account.compensated")
                )
                assert job is not None
                assert job.state == ReconciliationState.COMPLETED.value
                assert job.attempt_count == 2
                assert job.claim_token is None
                assert job.claimed_by is None
                assert record is not None
                assert record.lease_expires_at is not None
                assert record.lease_expires_at < datetime.now(UTC)
                assert compensated == 1

            monkeypatch.setattr(service, "_commit_profile_update", original_commit)
            updated = await service.update_profile(
                display_name="Uncommitted Learner",
                preferred_locale="en-US",
                expected_version=profile.profile_version,
                idempotency_key=idempotency_key,
            )
            assert updated.display_name == "Uncommitted Learner"
            assert updated.preferred_locale == "en-US"
    finally:
        if restarted_service is not None:
            await restarted_service.close()
        await service.close()


@pytest.mark.asyncio
async def test_postgres_exhausted_identity_compensation_fails_closed(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    settings = Settings(
        registration_enabled=True,
        registration_development_tenant_id=context.tenant_id,
        registration_allow_development_fallback=True,
        identity_encryption_secret="integration-identity-encryption-secret-32-bytes",
        identity_lookup_pepper="integration-identity-lookup-pepper-32-bytes",
        verification_code_pepper="integration-verification-code-pepper-32-bytes",
    )
    email = f"exhausted-{uuid4().hex[:12]}@example.invalid"
    keycloak = ReconciliationKeycloak()
    keycloak.user = KeycloakUser(
        user_id=context.subject_ref,
        username=email,
        email=email,
        enabled=True,
        attributes={
            "tenant_id": (context.tenant_id,),
            "login_channel": ("EMAIL",),
            "preferred_locale": ("zh-CN",),
        },
        display_name="Exhausted Learner",
        email_verified=True,
    )
    service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings,
        keycloak=keycloak,
        instance_id="identity-exhausted-compensation",
    )
    try:
        with tenant_scope(context):
            profile = await service.get_profile()
            request_document = {
                "account_id": str(profile.account_id),
                "display_name": "Never Committed",
                "preferred_locale": "en-US",
                "expected_version": profile.profile_version,
            }
            storage_key, request_digest, duplicate = await service._begin_authenticated_mutation(
                context,
                operation="identity.profile.update",
                idempotency_key=f"identity-exhausted-{uuid4().hex}",
                request_document=request_document,
                account_id=profile.account_id,
                expected_version=profile.profile_version,
            )
            assert duplicate is None
            assert keycloak.user is not None
            job_id = await service._arm_account_compensation(
                context,
                account_id=profile.account_id,
                expected_version=profile.profile_version,
                storage_key=storage_key,
                request_digest=request_digest,
                user=keycloak.user,
            )
            claim_token = uuid4()
            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                job = await session.scalar(
                    select(IdentityReconciliationJobModel).where(
                        IdentityReconciliationJobModel.reconciliation_job_id == job_id
                    )
                )
                assert job is not None
                job.state = ReconciliationState.RUNNING.value
                job.claim_token = claim_token
                job.claimed_by = "identity-exhaustion-test"
            await service._finish_reconciliation_job(
                context,
                job_id,
                claim_token=claim_token,
                succeeded=False,
                failure_code="InjectedPermanentFailure",
                attempt_count=8,
                max_attempts=8,
            )

            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                account = await session.scalar(select(IdentityAccountModel))
                job = await session.scalar(
                    select(IdentityReconciliationJobModel).where(
                        IdentityReconciliationJobModel.reconciliation_job_id == job_id
                    )
                )
                failure_events = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessageModel)
                    .where(
                        OutboxMessageModel.event_type == "identity.account.reconciliation-required"
                    )
                )
                assert account is not None
                assert account.status == "RECONCILIATION_REQUIRED"
                assert account.disabled_reason_code == "IDENTITY_RECONCILIATION_FAILED"
                assert job is not None
                assert job.state == ReconciliationState.FAILED.value
                assert failure_events == 1

            current_profile = await service.get_profile()
            with pytest.raises(LiyanError) as blocked:
                await service.update_profile(
                    display_name="Blocked Mutation",
                    preferred_locale="zh-TW",
                    expected_version=current_profile.profile_version,
                    idempotency_key=f"identity-blocked-{uuid4().hex}",
                )
            assert blocked.value.code == ErrorCode.IDENTITY_ACCOUNT_CONFLICT
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_postgres_first_login_projects_phone_account_and_rejects_wrong_tenant_binding(
    postgres_runtime,
) -> None:
    database, _migrator, context = postgres_runtime
    settings = Settings(
        registration_enabled=True,
        registration_development_tenant_id=context.tenant_id,
        registration_allow_development_fallback=True,
        identity_encryption_secret="integration-identity-encryption-secret-32-bytes",
        identity_lookup_pepper="integration-identity-lookup-pepper-32-bytes",
        verification_code_pepper="integration-verification-code-pepper-32-bytes",
    )
    phone = f"+1415{uuid4().int % 10_000_000:07d}"
    keycloak = ReconciliationKeycloak()
    keycloak.user = KeycloakUser(
        user_id=context.subject_ref,
        username=phone,
        email=None,
        enabled=True,
        attributes={
            "tenant_id": (context.tenant_id,),
            "login_channel": ("PHONE",),
            "phone_number": (phone,),
            "preferred_locale": ("zh-TW",),
        },
    )
    service = IdentityService(
        database,
        PostgresOutboxRepository(database),
        settings,
        keycloak=keycloak,
        instance_id="identity-first-login-projection",
    )
    try:
        with tenant_scope(context):
            profile = await service.get_profile()
            repeated = await service.get_profile()
            assert repeated == profile
            assert profile.subject_ref == context.subject_ref
            assert profile.phone_verified is True
            assert profile.phone_hint and profile.phone_hint.endswith(phone[-4:])
            assert profile.preferred_locale == "zh-TW"
            with pytest.raises(LiyanError) as stale_profile:
                await service.update_profile(
                    display_name="Stale Update",
                    preferred_locale="en-US",
                    expected_version=profile.profile_version + 1,
                    idempotency_key=f"identity-stale-profile-{uuid4().hex}",
                )
            assert stale_profile.value.code == ErrorCode.IDENTITY_ACCOUNT_CONFLICT
            with pytest.raises(LiyanError) as stale_status:
                await service.set_account_enabled(
                    profile.account_id,
                    enabled=False,
                    reason_code="STALE_REQUEST",
                    expected_version=profile.profile_version + 1,
                    idempotency_key=f"identity-stale-status-{uuid4().hex}",
                )
            assert stale_status.value.code == ErrorCode.IDENTITY_ACCOUNT_CONFLICT

            invalid_contact_key = f"identity-invalid-contact-{uuid4().hex}"
            invalid_contact_identifier = f"contact-{uuid4().hex[:12]}@example.invalid"
            invalid_contact_challenge_id = uuid4()
            for _attempt in range(2):
                with pytest.raises(LiyanError) as invalid_contact:
                    await service.change_contact(
                        channel=ContactChannel.EMAIL,
                        identifier=invalid_contact_identifier,
                        challenge_id=invalid_contact_challenge_id,
                        expected_version=profile.profile_version,
                        idempotency_key=invalid_contact_key,
                    )
                assert invalid_contact.value.code == ErrorCode.IDENTITY_CHALLENGE_INVALID
            with pytest.raises(LiyanError) as missing:
                await service.get_account(uuid4())
            assert missing.value.code == ErrorCode.IDENTITY_ACCOUNT_NOT_FOUND

            async with database.transaction(
                context=session_context_from_tenant(context)
            ) as session:
                projected_audits = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(AuditEventModel.action == "IDENTITY_ACCOUNT_PROJECTED")
                )
                projected_events = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessageModel)
                    .where(OutboxMessageModel.event_type == "identity.account.projected")
                )
            assert projected_audits == 1
            assert projected_events == 1

        wrong_context = replace(context, subject_ref=f"subject:wrong-{uuid4().hex}")
        keycloak.user = KeycloakUser(
            user_id=wrong_context.subject_ref,
            username="wrong@example.invalid",
            email="wrong@example.invalid",
            enabled=True,
            attributes={
                "tenant_id": ("different-tenant",),
                "login_channel": ("EMAIL",),
            },
        )
        with tenant_scope(wrong_context):
            with pytest.raises(LiyanError) as wrong_tenant:
                await service.get_profile()
            assert wrong_tenant.value.code == ErrorCode.IDENTITY_INTEGRITY_FAILED
    finally:
        await service.close()
