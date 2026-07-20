from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.identity import (
    AccountAdminViewV1,
    AccountProfileV1,
    IdentityAccountStatus,
    IdentityAuditEntryV1,
    IdentityChallengePurpose,
    IdentityChallengeState,
    IdentityContactChannel,
    IdentityRegistrationState,
    RegistrationConsentV1,
    RegistrationReceiptV1,
    RegistrationStatusV1,
    UserRegisterByEmailCommandV1,
    UserRegisterByPhoneCommandV1,
    VerificationChallengeReceiptV1,
    VerificationChallengeRequestV1,
    VerificationChallengeVerifyV1,
)
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.errors import (
    ErrorCategory,
    ErrorCode,
    LiyanError,
    MessageConflictError,
    RateLimitExceeded,
)
from liyans.core.hashing import sha256_hex
from liyans.core.settings import Settings
from liyans.core.tenant import TenantContext, current_tenant, tenant_scope
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import (
    AuditEventModel,
    IdempotencyRecordModel,
    IdempotencyStatus,
    OutboxMessageModel,
    TenantModel,
)
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    TransactionIsolation,
    TransactionRetryPolicy,
)
from liyans.infrastructure.observability.audit import (
    GENESIS_HASH,
    AuditDraft,
    AuditRecord,
    build_audit_record,
)
from liyans.infrastructure.persistence.outbox import OutboxMessage
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

from .crypto import (
    FixtureInboxMessage,
    IdentityCipher,
    VerificationFixtureInbox,
    generate_verification_code,
    identity_contract_error,
    invitation_error,
    keyed_digest,
    mask_email,
    mask_phone,
    normalize_email,
    normalize_phone,
    validate_password,
    verification_code_digest,
    verification_code_matches,
    verify_registration_invitation,
)
from .keycloak import KeycloakAdminClient, KeycloakUser
from .models import (
    AccountStatus,
    ChallengePurpose,
    ChallengeState,
    ContactChannel,
    IdentityAccountModel,
    IdentityConsentRecordModel,
    IdentityReconciliationJobModel,
    IdentityRegistrationSnapshotModel,
    IdentityVerificationChallengeModel,
    IdentityVerificationRateLimitModel,
    ReconciliationState,
    RegistrationState,
)

logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9:_\-.]{32,160}$")
IDENTITY_SCOPE_PROFILE_READ = "account:profile:read"
IDENTITY_SCOPE_PROFILE_WRITE = "account:profile:write"
IDENTITY_SCOPE_CONTACT_WRITE = "account:contact:write"
IDENTITY_SCOPE_ADMIN_READ = "account:admin:read"
IDENTITY_SCOPE_ADMIN_WRITE = "account:admin:write"
OUTBOX_RETENTION = timedelta(days=7)
LEARNER_PERMISSIONS = (
    "topic1:read topic2:read topic2:profile:read topic2:profile:write "
    "topic2:memory:read topic2:memory:write topic2:path:read topic2:path:write "
    "topic2:context:read topic3:read topic3:write topic3:generation:read "
    "topic3:generation:write topic3:generation:retry topic3:sse:read "
    "topic4:read topic4:verification:read topic4:verification:execute "
    "topic4:claim:read topic4:report:read topic4:rag:read topic4:revision:read "
    "topic4:trace:read topic4:sse:read account:profile:read account:profile:write "
    "account:contact:write"
)


class IdentityService:
    """Transactional identity projection with an explicit Keycloak saga."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        outbox: PostgresOutboxRepository,
        settings: Settings,
        *,
        keycloak: KeycloakAdminClient | None,
        instance_id: str,
        fixture_inbox: VerificationFixtureInbox | None = None,
        reconciliation_catalog: DatabaseSessionManager | None = None,
    ) -> None:
        self._database = database
        self._outbox = outbox
        self._settings = settings
        self._keycloak = keycloak
        self._instance_id = instance_id
        self._cipher = IdentityCipher(settings.identity_encryption_secret.get_secret_value())
        self._fixture_inbox = fixture_inbox or VerificationFixtureInbox()
        self._reconciliation_catalog = reconciliation_catalog
        self._known_tenants: set[str] = set()

    @property
    def fixture_inbox(self) -> VerificationFixtureInbox:
        return self._fixture_inbox

    async def close(self) -> None:
        if self._keycloak is not None:
            await self._keycloak.close()

    async def request_challenge(
        self,
        command: VerificationChallengeRequestV1,
        *,
        idempotency_key: str,
        trace_id: str,
        client_ip: str,
        user_agent: str,
        device_fingerprint: str | None = None,
        context: TenantContext | None = None,
    ) -> VerificationChallengeReceiptV1:
        if (
            command.purpose == IdentityChallengePurpose.REGISTER
            and not self._settings.registration_enabled
        ):
            raise self._registration_unavailable()
        normalized = self._normalize_identifier(command.channel, command.identifier)
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise identity_contract_error("Idempotency-Key must contain 32 to 160 safe characters.")
        effective_context = await self._registration_context(
            command.invitation_token,
            trace_id=trace_id,
            authenticated_context=context,
        )
        if command.purpose != IdentityChallengePurpose.REGISTER and context is None:
            raise invitation_error()
        if command.purpose == IdentityChallengePurpose.REGISTER and context is not None:
            raise identity_contract_error(
                "Authenticated sessions cannot request registration codes."
            )
        account_id = None
        if context is not None:
            account_id = (await self._ensure_account_projection(context)).account_id
        self._known_tenants.add(effective_context.tenant_id)
        fingerprint = self._request_fingerprint(client_ip, user_agent, device_fingerprint)
        request_digest = canonical_sha256(
            {
                "channel": command.channel.value,
                "purpose": command.purpose.value,
                "identifier_digest": self._identifier_digest(
                    normalized,
                    ContactChannel(command.channel.value),
                ),
                "account_id": str(account_id) if account_id is not None else None,
            }
        )
        storage_key = self._storage_key("identity.challenge.request", idempotency_key)
        with tenant_scope(effective_context):
            result = await self._database.run_transaction(
                lambda session: self._request_challenge_transaction(
                    session,
                    effective_context,
                    command,
                    normalized,
                    account_id=account_id,
                    storage_key=storage_key,
                    request_digest=request_digest,
                    client_ip=client_ip,
                    fingerprint=fingerprint,
                ),
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=8),
            )
        if result["code"] is not None and self._settings.registration_fixture_inbox_enabled:
            await self._fixture_inbox.deliver(
                FixtureInboxMessage(
                    challenge_id=result["receipt"].challenge_id,
                    code=result["code"],
                    delivery_hint=result["receipt"].delivery_hint,
                    expires_at=result["receipt"].expires_at,
                )
            )
        return result["receipt"]

    async def verify_challenge(
        self,
        command: VerificationChallengeVerifyV1,
        *,
        idempotency_key: str,
        invitation_token: str | None,
        trace_id: str,
        context: TenantContext | None = None,
    ) -> VerificationChallengeReceiptV1:
        effective_context = await self._registration_context(
            invitation_token,
            trace_id=trace_id,
            authenticated_context=context,
        )
        self._known_tenants.add(effective_context.tenant_id)
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise identity_contract_error("Idempotency-Key must contain 32 to 160 safe characters.")
        storage_key = self._storage_key("identity.challenge.verify", idempotency_key)
        request_digest = canonical_sha256(
            {
                "challenge_id": str(command.challenge_id),
                "code_digest": verification_code_digest(
                    command.challenge_id,
                    command.code.get_secret_value(),
                    self._verification_pepper,
                ),
            }
        )
        with tenant_scope(effective_context):
            result = await self._database.run_transaction(
                lambda session: self._verify_challenge_idempotent_transaction(
                    session,
                    effective_context,
                    command,
                    storage_key=storage_key,
                    request_digest=request_digest,
                ),
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=8),
            )
        if not result["ok"]:
            raise LiyanError(
                result["error_code"],
                "The verification code is invalid or expired.",
                category=ErrorCategory.AUTH,
                status_code=422,
            )
        return result["receipt"]

    async def register_email(
        self,
        command: UserRegisterByEmailCommandV1,
        *,
        idempotency_key: str,
        trace_id: str,
    ) -> RegistrationReceiptV1:
        return await self._register(
            command=command,
            channel=ContactChannel.EMAIL,
            identifier=normalize_email(command.email),
            password=command.password.get_secret_value(),
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    async def register_phone(
        self,
        command: UserRegisterByPhoneCommandV1,
        *,
        idempotency_key: str,
        trace_id: str,
    ) -> RegistrationReceiptV1:
        return await self._register(
            command=command,
            channel=ContactChannel.PHONE,
            identifier=normalize_phone(command.phone),
            password=command.password.get_secret_value(),
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    async def _register(
        self,
        *,
        command: UserRegisterByEmailCommandV1 | UserRegisterByPhoneCommandV1,
        channel: ContactChannel,
        identifier: str,
        password: str,
        idempotency_key: str,
        trace_id: str,
    ) -> RegistrationReceiptV1:
        if not self._settings.registration_enabled:
            raise self._registration_unavailable()
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise identity_contract_error("Idempotency-Key must contain 32 to 160 safe characters.")
        validate_password(password)
        effective_context = await self._registration_context(
            command.invitation_token,
            trace_id=trace_id,
            authenticated_context=None,
        )
        self._known_tenants.add(effective_context.tenant_id)
        identifier_digest = self._identifier_digest(identifier, channel)
        request_document = {
            "channel": channel.value,
            "identifier_digest": identifier_digest,
            "challenge_id": str(command.challenge_id),
            "display_name": command.display_name,
            "preferred_locale": command.preferred_locale,
            "privacy_policy_version": command.consent.privacy_policy_version,
            "terms_of_service_version": command.consent.terms_of_service_version,
        }
        storage_key = self._storage_key("identity.register", idempotency_key)
        digest = canonical_sha256({"operation": "identity.register", "request": request_document})
        with tenant_scope(effective_context):
            prepared = await self._database.run_transaction(
                lambda session: self._prepare_registration_transaction(
                    session,
                    effective_context,
                    channel,
                    identifier_digest,
                    command,
                    storage_key=storage_key,
                    request_digest=digest,
                ),
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=8),
            )
        if prepared["completed"] is not None:
            return RegistrationReceiptV1.model_validate(prepared["completed"])
        registration_id: UUID = prepared["registration_id"]
        reconciliation_pending = False
        try:
            keycloak = self._require_keycloak()
            user = await keycloak.create_learner(
                registration_id=registration_id,
                tenant_id=effective_context.tenant_id,
                channel=channel.value,
                identifier=identifier,
                password=password,
                display_name=command.display_name,
                preferred_locale=command.preferred_locale,
                learner_permissions=LEARNER_PERMISSIONS,
            )
            try:
                return await self._finalize_registration(
                    effective_context,
                    registration_id=registration_id,
                    channel=channel,
                    identifier=identifier,
                    user=user,
                    challenge_id=command.challenge_id,
                    display_name=command.display_name,
                    preferred_locale=command.preferred_locale,
                    consent=command.consent,
                    storage_key=storage_key,
                    request_digest=digest,
                )
            except Exception as exc:
                reconciliation_pending = await self._schedule_registration_reconciliation(
                    effective_context,
                    registration_id=registration_id,
                    channel=channel,
                    user=user,
                    storage_key=storage_key,
                    request_digest=digest,
                    failure_code=type(exc).__name__,
                )
                if not reconciliation_pending:
                    try:
                        await keycloak.delete_user(user.user_id)
                    except Exception:
                        logger.exception(
                            "Failed to compensate Keycloak user after projection failure"
                        )
                raise
        except LiyanError:
            if not reconciliation_pending:
                await self._release_idempotency(effective_context, storage_key)
            raise
        except Exception as exc:
            if not reconciliation_pending:
                await self._release_idempotency(effective_context, storage_key)
            raise LiyanError(
                ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
                "The registration service is temporarily unavailable.",
                category=ErrorCategory.AUTH,
                retriable=True,
                status_code=503,
            ) from exc

    async def _request_challenge_transaction(
        self,
        session: AsyncSession,
        context: TenantContext,
        command: VerificationChallengeRequestV1,
        normalized: str,
        *,
        account_id: UUID | None,
        storage_key: str,
        request_digest: str,
        client_ip: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        duplicate = await self._reserve_idempotency(
            session,
            context,
            storage_key,
            operation="identity.challenge.request",
            request_digest=request_digest,
        )
        if duplicate is not None:
            receipt = VerificationChallengeReceiptV1.model_validate(duplicate["receipt"])
            return {"code": None, "receipt": receipt}
        identifier_digest = self._identifier_digest(normalized, command.channel)
        latest = await session.scalar(
            select(IdentityVerificationChallengeModel)
            .where(
                IdentityVerificationChallengeModel.tenant_id == context.tenant_id,
                IdentityVerificationChallengeModel.channel == command.channel.value,
                IdentityVerificationChallengeModel.purpose == command.purpose.value,
                IdentityVerificationChallengeModel.identifier_digest == identifier_digest,
                IdentityVerificationChallengeModel.account_id == account_id,
                IdentityVerificationChallengeModel.state.in_(
                    [ChallengeState.PENDING.value, ChallengeState.VERIFIED.value]
                ),
            )
            .order_by(IdentityVerificationChallengeModel.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if latest is not None and latest.expires_at > now:
            cooldown_until = latest.last_sent_at + timedelta(
                seconds=self._settings.registration_challenge_cooldown_seconds
            )
            if cooldown_until > now:
                receipt = self._challenge_receipt(latest, now=now)
                await self._complete_idempotency(
                    session,
                    storage_key,
                    {"receipt": receipt.model_dump(mode="json")},
                )
                return {
                    "code": None,
                    "receipt": receipt,
                }
        await self._enforce_rate_limits(
            session,
            context,
            dimensions=(
                ("IDENTIFIER", identifier_digest),
                ("IP", keyed_digest(client_ip or "unknown", self._lookup_pepper, purpose="ip")),
                ("DEVICE", fingerprint),
            ),
            now=now,
        )
        challenge_id = uuid4()
        code = generate_verification_code()
        expires_at = now + timedelta(seconds=self._settings.registration_challenge_ttl_seconds)
        delivery_hint = (
            mask_email(normalized)
            if command.channel == IdentityContactChannel.EMAIL
            else mask_phone(normalized)
        )
        row = IdentityVerificationChallengeModel(
            challenge_id=challenge_id,
            tenant_id=context.tenant_id,
            account_id=account_id,
            channel=command.channel.value,
            purpose=command.purpose.value,
            identifier_digest=identifier_digest,
            delivery_hint=delivery_hint,
            code_digest=verification_code_digest(
                challenge_id,
                code,
                self._verification_pepper,
            ),
            request_fingerprint_digest=fingerprint,
            state=ChallengeState.PENDING.value,
            attempt_count=0,
            max_attempts=self._settings.registration_challenge_max_attempts,
            send_count=1,
            created_at=now,
            last_sent_at=now,
            expires_at=expires_at,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        await self._append_audit(
            session,
            context,
            action="IDENTITY_CHALLENGE_SENT",
            outcome="SUCCEEDED",
            target_ref=f"identity:challenge:{challenge_id}",
            metadata={
                "channel": command.channel.value,
                "purpose": command.purpose.value,
                "identifier_digest": identifier_digest,
            },
        )
        await self._append_outbox(
            session,
            context,
            event_type="identity.verification-challenge.sent",
            partition_key=f"identity:challenge:{challenge_id}",
            payload={
                "challenge_id": str(challenge_id),
                "channel": command.channel.value,
                "purpose": command.purpose.value,
                "delivery_hint": delivery_hint,
                "expires_at": expires_at.isoformat(),
            },
        )
        receipt = self._challenge_receipt(row, now=now)
        await self._complete_idempotency(
            session,
            storage_key,
            {"receipt": receipt.model_dump(mode="json")},
        )
        return {
            "code": code,
            "receipt": receipt,
        }

    async def _verify_challenge_idempotent_transaction(
        self,
        session: AsyncSession,
        context: TenantContext,
        command: VerificationChallengeVerifyV1,
        *,
        storage_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        duplicate = await self._reserve_idempotency(
            session,
            context,
            storage_key,
            operation="identity.challenge.verify",
            request_digest=request_digest,
        )
        if duplicate is not None:
            if duplicate.get("rejected"):
                return {
                    "ok": False,
                    "error_code": ErrorCode(duplicate["error_code"]),
                }
            return {
                "ok": True,
                "receipt": VerificationChallengeReceiptV1.model_validate(duplicate["receipt"]),
            }
        result = await self._verify_challenge_transaction(session, context, command)
        if result["ok"]:
            await self._complete_idempotency(
                session,
                storage_key,
                {"receipt": result["receipt"].model_dump(mode="json")},
            )
        else:
            await self._complete_idempotency(
                session,
                storage_key,
                {"rejected": True, "error_code": result["error_code"].value},
            )
        return result

    async def _verify_challenge_transaction(
        self,
        session: AsyncSession,
        context: TenantContext,
        command: VerificationChallengeVerifyV1,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = await session.scalar(
            select(IdentityVerificationChallengeModel)
            .where(IdentityVerificationChallengeModel.challenge_id == command.challenge_id)
            .with_for_update()
        )
        if row is None:
            return {"ok": False, "error_code": ErrorCode.IDENTITY_CHALLENGE_INVALID}
        if row.expires_at <= now and row.state in {
            ChallengeState.PENDING.value,
            ChallengeState.VERIFIED.value,
        }:
            row.state = ChallengeState.EXPIRED.value
            row.updated_at = now
            await self._append_audit(
                session,
                context,
                action="IDENTITY_CHALLENGE_EXPIRED",
                outcome="REJECTED",
                target_ref=f"identity:challenge:{row.challenge_id}",
                metadata={},
            )
            return {"ok": False, "error_code": ErrorCode.IDENTITY_CHALLENGE_EXPIRED}
        if row.state != ChallengeState.PENDING.value:
            return {"ok": False, "error_code": ErrorCode.IDENTITY_CHALLENGE_INVALID}
        code = command.code.get_secret_value()
        if not verification_code_matches(
            row.challenge_id,
            code,
            row.code_digest,
            self._verification_pepper,
        ):
            row.attempt_count += 1
            if row.attempt_count >= row.max_attempts:
                row.state = ChallengeState.LOCKED.value
            row.updated_at = now
            await self._append_audit(
                session,
                context,
                action="IDENTITY_CHALLENGE_VERIFY",
                outcome="REJECTED",
                target_ref=f"identity:challenge:{row.challenge_id}",
                metadata={"attempt_count": row.attempt_count},
            )
            return {"ok": False, "error_code": ErrorCode.IDENTITY_CHALLENGE_INVALID}
        row.state = ChallengeState.VERIFIED.value
        row.verified_at = now
        row.updated_at = now
        await self._append_audit(
            session,
            context,
            action="IDENTITY_CHALLENGE_VERIFIED",
            outcome="SUCCEEDED",
            target_ref=f"identity:challenge:{row.challenge_id}",
            metadata={"purpose": row.purpose, "channel": row.channel},
        )
        await self._append_outbox(
            session,
            context,
            event_type="identity.verification-challenge.verified",
            partition_key=f"identity:challenge:{row.challenge_id}",
            payload={"challenge_id": str(row.challenge_id), "state": row.state},
        )
        return {"ok": True, "receipt": self._challenge_receipt(row, now=now)}

    async def _prepare_registration_transaction(
        self,
        session: AsyncSession,
        context: TenantContext,
        channel: ContactChannel,
        identifier_digest: str,
        command: UserRegisterByEmailCommandV1 | UserRegisterByPhoneCommandV1,
        *,
        storage_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        duplicate = await self._reserve_idempotency(
            session,
            context,
            storage_key,
            operation="identity.register",
            request_digest=request_digest,
        )
        if duplicate is not None:
            return {"completed": duplicate, "registration_id": None}
        idempotency_digest = sha256_hex(storage_key)
        latest = await session.scalar(
            select(IdentityRegistrationSnapshotModel)
            .where(
                IdentityRegistrationSnapshotModel.tenant_id == context.tenant_id,
                IdentityRegistrationSnapshotModel.idempotency_key_digest == idempotency_digest,
            )
            .order_by(IdentityRegistrationSnapshotModel.registration_version.desc())
            .limit(1)
        )
        if latest is not None:
            if latest.identifier_digest != identifier_digest or latest.channel != channel.value:
                raise MessageConflictError(
                    ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                    "The idempotency key was reused for different registration content.",
                )
            if latest.state == RegistrationState.COMPLETED.value:
                account = await session.scalar(
                    select(IdentityAccountModel).where(
                        IdentityAccountModel.account_id == latest.account_id
                    )
                )
                if account is None:
                    raise self._registration_unavailable()
                receipt = RegistrationReceiptV1(
                    registration_id=latest.registration_id,
                    account_id=account.account_id,
                    preferred_locale=account.preferred_locale,
                    created_at=account.created_at,
                )
                document = receipt.model_dump(mode="json")
                await self._complete_idempotency(session, storage_key, document)
                return {"completed": document, "registration_id": latest.registration_id}
            registration_id = latest.registration_id
            version = latest.registration_version + 1
        else:
            registration_id = uuid4()
            version = 1
        challenge = await session.scalar(
            select(IdentityVerificationChallengeModel)
            .where(
                IdentityVerificationChallengeModel.challenge_id == command.challenge_id,
                IdentityVerificationChallengeModel.channel == channel.value,
                IdentityVerificationChallengeModel.purpose == ChallengePurpose.REGISTER.value,
                IdentityVerificationChallengeModel.identifier_digest == identifier_digest,
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        if (
            challenge is None
            or challenge.state != ChallengeState.VERIFIED.value
            or challenge.expires_at <= now
            or (
                challenge.registration_id is not None
                and challenge.registration_id != registration_id
            )
        ):
            raise LiyanError(
                ErrorCode.IDENTITY_CHALLENGE_INVALID,
                "A valid verified registration challenge is required.",
                category=ErrorCategory.AUTH,
                status_code=422,
            )
        challenge.registration_id = registration_id
        challenge.updated_at = now
        await self._append_registration_snapshot(
            session,
            context,
            registration_id=registration_id,
            version=version,
            account_id=None,
            channel=channel,
            identifier_digest=identifier_digest,
            idempotency_key_digest=idempotency_digest,
            state=RegistrationState.KEYCLOAK_PENDING,
            keycloak_user_id=None,
            failure_code=None,
            state_document={
                "challenge_id": str(command.challenge_id),
                "display_name": command.display_name,
                "preferred_locale": command.preferred_locale,
                "privacy_policy_version": command.consent.privacy_policy_version,
                "terms_of_service_version": command.consent.terms_of_service_version,
            },
            created_at=now,
        )
        return {"completed": None, "registration_id": registration_id}

    async def _finalize_registration(
        self,
        context: TenantContext,
        *,
        registration_id: UUID,
        channel: ContactChannel,
        identifier: str,
        user: KeycloakUser,
        challenge_id: UUID,
        display_name: str,
        preferred_locale: str,
        consent: RegistrationConsentV1,
        storage_key: str,
        request_digest: str,
    ) -> RegistrationReceiptV1:
        tenant_values = user.attributes.get("tenant_id", ())
        registration_values = user.attributes.get("registration_id", ())
        if tenant_values != (context.tenant_id,) or str(registration_id) not in registration_values:
            raise LiyanError(
                ErrorCode.IDENTITY_INTEGRITY_FAILED,
                "The identity provider returned an invalid tenant binding.",
                category=ErrorCategory.AUTH,
                status_code=503,
            )

        async def operation(session: AsyncSession) -> RegistrationReceiptV1:
            await self._lock(
                session, f"identity:registration:{context.tenant_id}:{registration_id}"
            )
            record = await session.scalar(
                select(IdempotencyRecordModel)
                .where(
                    IdempotencyRecordModel.tenant_id == context.tenant_id,
                    IdempotencyRecordModel.idempotency_key == storage_key,
                )
                .with_for_update()
            )
            if record is None or record.request_digest != request_digest:
                raise self._registration_unavailable()
            if record.state == IdempotencyStatus.COMPLETED.value:
                return RegistrationReceiptV1.model_validate(record.result_payload)
            latest = await session.scalar(
                select(IdentityRegistrationSnapshotModel)
                .where(
                    IdentityRegistrationSnapshotModel.tenant_id == context.tenant_id,
                    IdentityRegistrationSnapshotModel.registration_id == registration_id,
                )
                .order_by(IdentityRegistrationSnapshotModel.registration_version.desc())
                .limit(1)
            )
            if latest is None:
                raise self._registration_unavailable()
            account = await session.scalar(
                select(IdentityAccountModel)
                .where(
                    IdentityAccountModel.tenant_id == context.tenant_id,
                    IdentityAccountModel.oidc_subject == user.user_id,
                )
                .with_for_update()
            )
            now = datetime.now(UTC)
            if account is None:
                account = self._new_account(
                    context,
                    user=user,
                    channel=channel,
                    identifier=identifier,
                    display_name=display_name,
                    preferred_locale=preferred_locale,
                    now=now,
                )
                session.add(account)
                await session.flush()
            challenge = await session.scalar(
                select(IdentityVerificationChallengeModel)
                .where(
                    IdentityVerificationChallengeModel.challenge_id == challenge_id,
                    IdentityVerificationChallengeModel.registration_id == registration_id,
                )
                .with_for_update()
            )
            if challenge is None or challenge.state not in {
                ChallengeState.VERIFIED.value,
                ChallengeState.CONSUMED.value,
            }:
                raise LiyanError(
                    ErrorCode.IDENTITY_CHALLENGE_INVALID,
                    "The verified registration challenge is unavailable.",
                    category=ErrorCategory.AUTH,
                    status_code=422,
                )
            challenge.account_id = account.account_id
            challenge.state = ChallengeState.CONSUMED.value
            challenge.consumed_at = challenge.consumed_at or now
            challenge.updated_at = now
            await self._append_consents(
                session,
                context,
                account=account,
                registration_id=registration_id,
                consent=consent,
                accepted_at=now,
            )
            if latest.state != RegistrationState.COMPLETED.value:
                await self._append_registration_snapshot(
                    session,
                    context,
                    registration_id=registration_id,
                    version=latest.registration_version + 1,
                    account_id=account.account_id,
                    channel=channel,
                    identifier_digest=self._identifier_digest(identifier, channel),
                    idempotency_key_digest=sha256_hex(storage_key),
                    state=RegistrationState.COMPLETED,
                    keycloak_user_id=user.user_id,
                    failure_code=None,
                    state_document={
                        "challenge_id": str(challenge_id),
                        "account_id": str(account.account_id),
                    },
                    created_at=now,
                )
                await self._append_audit(
                    session,
                    context,
                    action="IDENTITY_ACCOUNT_REGISTERED",
                    outcome="SUCCEEDED",
                    target_ref=f"identity:account:{account.account_id}",
                    metadata={
                        "registration_id": str(registration_id),
                        "channel": channel.value,
                        "oidc_subject": user.user_id,
                    },
                )
                await self._append_outbox(
                    session,
                    context,
                    event_type="identity.account.registered",
                    partition_key=f"identity:account:{account.account_id}",
                    payload={
                        "registration_id": str(registration_id),
                        "account_id": str(account.account_id),
                        "status": account.status,
                    },
                )
            receipt = RegistrationReceiptV1(
                registration_id=registration_id,
                account_id=account.account_id,
                preferred_locale=account.preferred_locale,
                created_at=account.created_at,
            )
            await self._complete_idempotency(
                session,
                storage_key,
                receipt.model_dump(mode="json"),
            )
            return receipt

        try:
            with tenant_scope(context):
                return await self._database.run_transaction(
                    operation,
                    context=current_session_context(),
                    isolation=TransactionIsolation.SERIALIZABLE,
                    retry_policy=TransactionRetryPolicy(max_attempts=8),
                )
        except IntegrityError as exc:
            raise LiyanError(
                ErrorCode.IDENTITY_ACCOUNT_CONFLICT,
                "The account registration could not be completed.",
                category=ErrorCategory.AUTH,
                status_code=409,
            ) from exc

    async def reconcile_known_tenants(self, *, limit_per_tenant: int = 20) -> int:
        completed = 0
        for tenant_id in sorted(await self._reconciliation_tenant_ids()):
            context = TenantContext(
                tenant_id=tenant_id,
                subject_ref="system:identity-reconciler",
                roles=frozenset(),
                scopes=frozenset(),
                trace_id=sha256_hex(f"identity-reconcile:{tenant_id}")[:32],
            )
            completed += await self._reconcile_tenant(context, limit=limit_per_tenant)
        return completed

    async def _reconciliation_tenant_ids(self) -> set[str]:
        tenant_ids = set(self._known_tenants)
        if self._reconciliation_catalog is None:
            return tenant_ids

        async def discover(session: AsyncSession) -> set[str]:
            rows = await session.scalars(
                text("SELECT DISTINCT tenant_id FROM identity_reconciliation_jobs")
            )
            return {str(tenant_id) for tenant_id in rows if tenant_id}

        discovered = await self._reconciliation_catalog.run_transaction(
            discover,
            isolation=TransactionIsolation.READ_COMMITTED,
            retry_policy=TransactionRetryPolicy(max_attempts=3),
        )
        tenant_ids.update(discovered)
        return tenant_ids

    async def _reconcile_tenant(self, context: TenantContext, *, limit: int) -> int:
        now = datetime.now(UTC)
        stale_before = now - timedelta(
            seconds=self._settings.registration_reconciliation_claim_lease_seconds
        )

        async def claim(session: AsyncSession) -> list[dict[str, Any]]:
            rows = list(
                (
                    await session.scalars(
                        select(IdentityReconciliationJobModel)
                        .where(
                            IdentityReconciliationJobModel.tenant_id == context.tenant_id,
                            or_(
                                and_(
                                    IdentityReconciliationJobModel.state
                                    == ReconciliationState.PENDING.value,
                                    IdentityReconciliationJobModel.next_attempt_at <= now,
                                    IdentityReconciliationJobModel.attempt_count
                                    < IdentityReconciliationJobModel.max_attempts,
                                ),
                                and_(
                                    IdentityReconciliationJobModel.state
                                    == ReconciliationState.RUNNING.value,
                                    IdentityReconciliationJobModel.updated_at <= stale_before,
                                ),
                            ),
                        )
                        .order_by(
                            IdentityReconciliationJobModel.next_attempt_at,
                            IdentityReconciliationJobModel.updated_at,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            claimed: list[dict[str, Any]] = []
            for row in rows:
                lease_exhausted = row.attempt_count >= row.max_attempts
                claim_token = uuid4()
                row.state = ReconciliationState.RUNNING.value
                row.claim_token = claim_token
                row.claimed_by = self._instance_id
                if not lease_exhausted:
                    row.attempt_count += 1
                row.updated_at = now
                claimed.append(
                    {
                        "job_id": row.reconciliation_job_id,
                        "registration_id": row.registration_id,
                        "account_id": row.account_id,
                        "keycloak_user_id": row.keycloak_user_id,
                        "operation": row.operation,
                        "attempt_count": row.attempt_count,
                        "max_attempts": row.max_attempts,
                        "lease_exhausted": lease_exhausted,
                        "claim_token": claim_token,
                        "job_document": dict(row.job_document),
                    }
                )
            return claimed

        with tenant_scope(context):
            jobs = await self._database.run_transaction(
                claim,
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=8),
            )
        completed = 0
        for job in jobs:
            if job["lease_exhausted"]:
                await self._finish_reconciliation_job(
                    context,
                    job["job_id"],
                    claim_token=job["claim_token"],
                    succeeded=False,
                    failure_code="RECONCILIATION_CLAIM_LEASE_EXPIRED",
                    attempt_count=job["attempt_count"],
                    max_attempts=job["max_attempts"],
                )
                continue
            try:
                if job["operation"] == "FINALIZE_PROJECTION":
                    registration_id = job["registration_id"]
                    if registration_id is None:
                        raise self._registration_unavailable()
                    user = (
                        await self._require_keycloak().get_user(job["keycloak_user_id"])
                        if job["keycloak_user_id"]
                        else await self._require_keycloak().find_by_registration_id(registration_id)
                    )
                    if user is None:
                        raise self._registration_unavailable()
                    initial = await self._registration_initial_snapshot(
                        context,
                        registration_id,
                    )
                    channel, identifier = self._user_contact(user)
                    consent = RegistrationConsentV1(
                        privacy_policy_version=initial.state_document["privacy_policy_version"],
                        terms_of_service_version=initial.state_document["terms_of_service_version"],
                        privacy_policy_accepted=True,
                        terms_of_service_accepted=True,
                    )
                    await self._finalize_registration(
                        context,
                        registration_id=registration_id,
                        channel=channel,
                        identifier=identifier,
                        user=user,
                        challenge_id=UUID(initial.state_document["challenge_id"]),
                        display_name=initial.state_document["display_name"],
                        preferred_locale=initial.state_document["preferred_locale"],
                        consent=consent,
                        storage_key=job["job_document"]["storage_key"],
                        request_digest=job["job_document"]["request_digest"],
                    )
                elif job["operation"] in {
                    "UPDATE_KEYCLOAK_USER",
                    "SET_KEYCLOAK_STATUS",
                }:
                    account_id = job["account_id"]
                    if account_id is None:
                        raise self._registration_unavailable()
                    user = self._decode_keycloak_snapshot(
                        context,
                        account_id=account_id,
                        ciphertext=job["job_document"].get("compensation_snapshot"),
                    )
                    if user.user_id != job["keycloak_user_id"]:
                        raise self._registration_unavailable()
                    await self._require_keycloak().restore_user(user)
                else:
                    raise self._registration_unavailable()
                if await self._finish_reconciliation_job(
                    context,
                    job["job_id"],
                    claim_token=job["claim_token"],
                    succeeded=True,
                ):
                    completed += 1
            except Exception as exc:
                await self._finish_reconciliation_job(
                    context,
                    job["job_id"],
                    claim_token=job["claim_token"],
                    succeeded=False,
                    failure_code=type(exc).__name__,
                    attempt_count=job["attempt_count"],
                    max_attempts=job["max_attempts"],
                )
        return completed

    async def _schedule_registration_reconciliation(
        self,
        context: TenantContext,
        *,
        registration_id: UUID,
        channel: ContactChannel,
        user: KeycloakUser,
        storage_key: str,
        request_digest: str,
        failure_code: str,
    ) -> bool:
        try:
            with tenant_scope(context):

                async def operation(session: AsyncSession) -> None:
                    latest = await session.scalar(
                        select(IdentityRegistrationSnapshotModel)
                        .where(
                            IdentityRegistrationSnapshotModel.tenant_id == context.tenant_id,
                            IdentityRegistrationSnapshotModel.registration_id == registration_id,
                        )
                        .order_by(IdentityRegistrationSnapshotModel.registration_version.desc())
                        .limit(1)
                    )
                    if latest is None or latest.state == RegistrationState.COMPLETED.value:
                        return
                    now = datetime.now(UTC)
                    await self._append_registration_snapshot(
                        session,
                        context,
                        registration_id=registration_id,
                        version=latest.registration_version + 1,
                        account_id=latest.account_id,
                        channel=channel,
                        identifier_digest=latest.identifier_digest,
                        idempotency_key_digest=latest.idempotency_key_digest,
                        state=RegistrationState.PROJECTION_PENDING,
                        keycloak_user_id=user.user_id,
                        failure_code=failure_code[:128],
                        state_document={
                            "reconciliation_operation": "FINALIZE_PROJECTION",
                            "keycloak_user_id": user.user_id,
                        },
                        created_at=now,
                    )
                    statement = (
                        insert(IdentityReconciliationJobModel)
                        .values(
                            reconciliation_job_id=uuid4(),
                            tenant_id=context.tenant_id,
                            correlation_id=registration_id,
                            registration_id=registration_id,
                            account_id=latest.account_id,
                            keycloak_user_id=user.user_id,
                            operation="FINALIZE_PROJECTION",
                            state=ReconciliationState.PENDING.value,
                            attempt_count=0,
                            max_attempts=8,
                            next_attempt_at=now,
                            last_error_code=failure_code[:128],
                            job_document={
                                "storage_key": storage_key,
                                "request_digest": request_digest,
                            },
                            created_at=now,
                            updated_at=now,
                        )
                        .on_conflict_do_update(
                            index_elements=[
                                IdentityReconciliationJobModel.tenant_id,
                                IdentityReconciliationJobModel.correlation_id,
                                IdentityReconciliationJobModel.operation,
                            ],
                            set_={
                                "state": ReconciliationState.PENDING.value,
                                "keycloak_user_id": user.user_id,
                                "next_attempt_at": now,
                                "last_error_code": failure_code[:128],
                                "job_document": {
                                    "storage_key": storage_key,
                                    "request_digest": request_digest,
                                },
                                "updated_at": now,
                            },
                        )
                    )
                    await session.execute(statement)
                    await self._append_audit(
                        session,
                        context,
                        action="IDENTITY_RECONCILIATION_SCHEDULED",
                        outcome="PENDING",
                        target_ref=f"identity:registration:{registration_id}",
                        metadata={"failure_code": failure_code[:128]},
                    )

                await self._database.run_transaction(
                    operation,
                    context=current_session_context(),
                    isolation=TransactionIsolation.SERIALIZABLE,
                    retry_policy=TransactionRetryPolicy(max_attempts=8),
                )
            return True
        except Exception:
            logger.exception("Failed to persist identity reconciliation evidence")
            return False

    async def _registration_initial_snapshot(
        self,
        context: TenantContext,
        registration_id: UUID,
    ) -> IdentityRegistrationSnapshotModel:
        with tenant_scope(context):
            async with self._database.transaction(context=current_session_context()) as session:
                snapshot = await session.scalar(
                    select(IdentityRegistrationSnapshotModel)
                    .where(
                        IdentityRegistrationSnapshotModel.tenant_id == context.tenant_id,
                        IdentityRegistrationSnapshotModel.registration_id == registration_id,
                    )
                    .order_by(IdentityRegistrationSnapshotModel.registration_version)
                    .limit(1)
                )
        if snapshot is None:
            raise self._registration_unavailable()
        return snapshot

    async def _finish_reconciliation_job(
        self,
        context: TenantContext,
        job_id: UUID,
        *,
        claim_token: UUID,
        succeeded: bool,
        failure_code: str | None = None,
        attempt_count: int = 0,
        max_attempts: int = 8,
    ) -> bool:
        async def operation(session: AsyncSession) -> bool:
            row = await session.scalar(
                select(IdentityReconciliationJobModel)
                .where(
                    IdentityReconciliationJobModel.tenant_id == context.tenant_id,
                    IdentityReconciliationJobModel.reconciliation_job_id == job_id,
                    IdentityReconciliationJobModel.state == ReconciliationState.RUNNING.value,
                    IdentityReconciliationJobModel.claim_token == claim_token,
                )
                .with_for_update()
            )
            if row is None:
                return False
            now = datetime.now(UTC)
            is_account_compensation = row.operation in {
                "UPDATE_KEYCLOAK_USER",
                "SET_KEYCLOAK_STATUS",
            }
            row.claim_token = None
            row.claimed_by = None
            if succeeded:
                row.state = ReconciliationState.COMPLETED.value
                row.completed_at = now
                row.last_error_code = None
                if is_account_compensation and row.account_id is not None:
                    await self._release_idempotency_in_transaction(
                        session,
                        context,
                        row.job_document.get("storage_key"),
                    )
                    await self._append_audit(
                        session,
                        context,
                        action="IDENTITY_COMPENSATION_COMPLETED",
                        outcome="SUCCEEDED",
                        target_ref=f"identity:account:{row.account_id}",
                        metadata={"reconciliation_job_id": str(job_id)},
                    )
                    await self._append_outbox(
                        session,
                        context,
                        event_type="identity.account.compensated",
                        partition_key=f"identity:account:{row.account_id}",
                        payload={
                            "account_id": str(row.account_id),
                            "reconciliation_job_id": str(job_id),
                        },
                    )
            else:
                exhausted = attempt_count >= max_attempts
                row.state = (
                    ReconciliationState.FAILED.value
                    if exhausted
                    else ReconciliationState.PENDING.value
                )
                row.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(attempt_count, 8)))
                row.last_error_code = (failure_code or "UNKNOWN")[:128]
                if exhausted and is_account_compensation and row.account_id is not None:
                    account = await self._locked_account(session, context, row.account_id)
                    if account.status != AccountStatus.RECONCILIATION_REQUIRED.value:
                        account.status = AccountStatus.RECONCILIATION_REQUIRED.value
                        account.disabled_reason_code = "IDENTITY_RECONCILIATION_FAILED"
                        account.profile_version += 1
                        account.updated_at = now
                        await self._append_audit(
                            session,
                            context,
                            action="IDENTITY_RECONCILIATION_EXHAUSTED",
                            outcome="FAILED",
                            target_ref=f"identity:account:{row.account_id}",
                            metadata={
                                "failure_code": row.last_error_code,
                                "reconciliation_job_id": str(job_id),
                            },
                        )
                        await self._append_outbox(
                            session,
                            context,
                            event_type="identity.account.reconciliation-required",
                            partition_key=f"identity:account:{row.account_id}",
                            payload={
                                "account_id": str(row.account_id),
                                "profile_version": account.profile_version,
                            },
                        )
            row.updated_at = now
            return True

        with tenant_scope(context):
            return await self._database.run_transaction(
                operation,
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=8),
            )

    async def get_profile(self) -> AccountProfileV1:
        context = current_tenant()
        account = await self._ensure_account_projection(context)
        return self._profile(account)

    async def update_profile(
        self,
        *,
        display_name: str,
        preferred_locale: str,
        expected_version: int,
        idempotency_key: str,
    ) -> AccountProfileV1:
        context = current_tenant()
        account = await self._ensure_account_projection(context)
        request_document = {
            "account_id": str(account.account_id),
            "display_name": display_name,
            "preferred_locale": preferred_locale,
            "expected_version": expected_version,
        }
        storage_key, digest, duplicate = await self._begin_authenticated_mutation(
            context,
            operation="identity.profile.update",
            idempotency_key=idempotency_key,
            request_document=request_document,
            account_id=account.account_id,
            expected_version=expected_version,
        )
        if duplicate is not None:
            return AccountProfileV1.model_validate(duplicate)
        keycloak = self._require_keycloak()
        try:
            current_user = await keycloak.get_user(account.oidc_subject)
            reconciliation_job_id = await self._arm_account_compensation(
                context,
                account_id=account.account_id,
                expected_version=expected_version,
                storage_key=storage_key,
                request_digest=digest,
                user=current_user,
            )
        except Exception:
            await self._release_idempotency(context, storage_key)
            raise
        try:
            await keycloak.update_profile(
                account.oidc_subject,
                display_name=display_name,
                preferred_locale=preferred_locale,
                current_user=current_user,
            )
            return await self._commit_profile_update(
                context,
                account_id=account.account_id,
                display_name=display_name,
                preferred_locale=preferred_locale,
                expected_version=expected_version,
                storage_key=storage_key,
                request_digest=digest,
                reconciliation_job_id=reconciliation_job_id,
            )
        except Exception as exc:
            await self._queue_account_compensation(
                context,
                reconciliation_job_id,
                failure_code=type(exc).__name__,
            )
            raise

    async def change_contact(
        self,
        *,
        channel: ContactChannel,
        identifier: str,
        challenge_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> AccountProfileV1:
        context = current_tenant()
        account = await self._ensure_account_projection(context)
        normalized = self._normalize_identifier(channel, identifier)
        identifier_digest = self._identifier_digest(normalized, channel)
        request_document = {
            "account_id": str(account.account_id),
            "channel": channel.value,
            "identifier_digest": identifier_digest,
            "challenge_id": str(challenge_id),
            "expected_version": expected_version,
        }
        storage_key, digest, duplicate = await self._begin_authenticated_mutation(
            context,
            operation="identity.contact.change",
            idempotency_key=idempotency_key,
            request_document=request_document,
            account_id=account.account_id,
            expected_version=expected_version,
        )
        if duplicate is not None:
            return AccountProfileV1.model_validate(duplicate)
        keycloak = self._require_keycloak()
        try:
            await self._assert_contact_challenge(
                context,
                account_id=account.account_id,
                challenge_id=challenge_id,
                channel=channel,
                identifier_digest=identifier_digest,
            )
            current_user = await keycloak.get_user(account.oidc_subject)
            reconciliation_job_id = await self._arm_account_compensation(
                context,
                account_id=account.account_id,
                expected_version=expected_version,
                storage_key=storage_key,
                request_digest=digest,
                user=current_user,
            )
        except Exception:
            await self._release_idempotency(context, storage_key)
            raise
        try:
            await keycloak.update_contact(
                account.oidc_subject,
                channel=channel.value,
                identifier=normalized,
                current_user=current_user,
            )
            return await self._commit_contact_change(
                context,
                account_id=account.account_id,
                channel=channel,
                identifier=normalized,
                challenge_id=challenge_id,
                expected_version=expected_version,
                storage_key=storage_key,
                request_digest=digest,
                reconciliation_job_id=reconciliation_job_id,
            )
        except Exception as exc:
            await self._queue_account_compensation(
                context,
                reconciliation_job_id,
                failure_code=type(exc).__name__,
            )
            raise

    async def list_accounts(self, *, offset: int, limit: int) -> list[AccountAdminViewV1]:
        context = current_tenant()
        self._known_tenants.add(context.tenant_id)
        async with self._database.transaction(context=current_session_context()) as session:
            rows = list(
                (
                    await session.scalars(
                        select(IdentityAccountModel)
                        .where(IdentityAccountModel.tenant_id == context.tenant_id)
                        .order_by(IdentityAccountModel.created_at, IdentityAccountModel.account_id)
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
        return [self._admin_view(row) for row in rows]

    async def get_account(self, account_id: UUID) -> AccountAdminViewV1:
        account = await self._required_account(account_id)
        return self._admin_view(account)

    async def get_registration_status(self, registration_id: UUID) -> RegistrationStatusV1:
        context = current_tenant()
        self._known_tenants.add(context.tenant_id)
        async with self._database.transaction(context=current_session_context()) as session:
            snapshot = await session.scalar(
                select(IdentityRegistrationSnapshotModel)
                .where(
                    IdentityRegistrationSnapshotModel.tenant_id == context.tenant_id,
                    IdentityRegistrationSnapshotModel.registration_id == registration_id,
                )
                .order_by(IdentityRegistrationSnapshotModel.registration_version.desc())
                .limit(1)
            )
        if snapshot is None:
            raise LiyanError(
                ErrorCode.IDENTITY_REGISTRATION_NOT_FOUND,
                "The registration does not exist.",
                category=ErrorCategory.AUTH,
                status_code=404,
            )
        return self._registration_status(snapshot)

    async def list_account_audit(
        self,
        account_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> list[IdentityAuditEntryV1]:
        context = current_tenant()
        await self._required_account(account_id)
        async with self._database.transaction(context=current_session_context()) as session:
            rows = list(
                (
                    await session.scalars(
                        select(AuditEventModel)
                        .where(
                            AuditEventModel.tenant_id == context.tenant_id,
                            AuditEventModel.category == "IDENTITY",
                            AuditEventModel.target_ref == f"identity:account:{account_id}",
                        )
                        .order_by(AuditEventModel.sequence)
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
        return [self._identity_audit_entry(row) for row in rows]

    async def set_account_enabled(
        self,
        account_id: UUID,
        *,
        enabled: bool,
        reason_code: str | None,
        expected_version: int,
        idempotency_key: str,
    ) -> AccountAdminViewV1:
        context = current_tenant()
        account = await self._required_account(account_id)
        request_document = {
            "account_id": str(account_id),
            "enabled": enabled,
            "reason_code": reason_code,
            "expected_version": expected_version,
        }
        storage_key, digest, duplicate = await self._begin_authenticated_mutation(
            context,
            operation="identity.account.status",
            idempotency_key=idempotency_key,
            request_document=request_document,
            account_id=account_id,
            expected_version=expected_version,
        )
        if duplicate is not None:
            return AccountAdminViewV1.model_validate(duplicate)
        keycloak = self._require_keycloak()
        try:
            current_user = await keycloak.get_user(account.oidc_subject)
            reconciliation_job_id = await self._arm_account_compensation(
                context,
                account_id=account_id,
                expected_version=expected_version,
                storage_key=storage_key,
                request_digest=digest,
                user=current_user,
            )
        except Exception:
            await self._release_idempotency(context, storage_key)
            raise
        try:
            await keycloak.set_enabled(
                account.oidc_subject,
                enabled=enabled,
                current_user=current_user,
            )
            return await self._commit_account_status(
                context,
                account_id=account_id,
                enabled=enabled,
                reason_code=reason_code,
                expected_version=expected_version,
                storage_key=storage_key,
                request_digest=digest,
                reconciliation_job_id=reconciliation_job_id,
            )
        except Exception as exc:
            await self._queue_account_compensation(
                context,
                reconciliation_job_id,
                failure_code=type(exc).__name__,
            )
            raise

    async def _ensure_account_projection(self, context: TenantContext) -> IdentityAccountModel:
        self._known_tenants.add(context.tenant_id)
        with tenant_scope(context):
            async with self._database.transaction(context=current_session_context()) as session:
                account = await session.scalar(
                    select(IdentityAccountModel).where(
                        IdentityAccountModel.tenant_id == context.tenant_id,
                        IdentityAccountModel.oidc_subject == context.subject_ref,
                    )
                )
            if account is not None:
                return account
            user = await self._require_keycloak().get_user(context.subject_ref)
            if user.attributes.get("tenant_id") != (context.tenant_id,):
                raise LiyanError(
                    ErrorCode.IDENTITY_INTEGRITY_FAILED,
                    "The identity provider returned an invalid tenant binding.",
                    category=ErrorCategory.AUTH,
                    status_code=503,
                )
            channel, identifier = self._user_contact(user)
            now = datetime.now(UTC)

            async def operation(session: AsyncSession) -> IdentityAccountModel:
                existing = await session.scalar(
                    select(IdentityAccountModel)
                    .where(
                        IdentityAccountModel.tenant_id == context.tenant_id,
                        IdentityAccountModel.oidc_subject == context.subject_ref,
                    )
                    .with_for_update()
                )
                if existing is not None:
                    return existing
                account = self._new_account(
                    context,
                    user=user,
                    channel=channel,
                    identifier=identifier,
                    display_name=user.display_name or user.username,
                    preferred_locale=(user.attributes.get("preferred_locale", ("zh-CN",))[0]),
                    now=now,
                )
                account.status = (
                    AccountStatus.ACTIVE.value if user.enabled else AccountStatus.DISABLED.value
                )
                session.add(account)
                await session.flush()
                await self._append_audit(
                    session,
                    context,
                    action="IDENTITY_ACCOUNT_PROJECTED",
                    outcome="SUCCEEDED",
                    target_ref=f"identity:account:{account.account_id}",
                    metadata={"oidc_subject": user.user_id},
                )
                await self._append_outbox(
                    session,
                    context,
                    event_type="identity.account.projected",
                    partition_key=f"identity:account:{account.account_id}",
                    payload={"account_id": str(account.account_id), "status": account.status},
                )
                return account

            return await self._database.run_transaction(
                operation,
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=8),
            )

    async def _commit_profile_update(
        self,
        context: TenantContext,
        *,
        account_id: UUID,
        display_name: str,
        preferred_locale: str,
        expected_version: int,
        storage_key: str,
        request_digest: str,
        reconciliation_job_id: UUID,
    ) -> AccountProfileV1:
        async def operation(session: AsyncSession) -> AccountProfileV1:
            await self._assert_idempotency_record(
                session,
                context,
                storage_key,
                request_digest,
            )
            account = await self._locked_account(session, context, account_id)
            if account.profile_version != expected_version:
                raise self._account_conflict(
                    "The account profile changed before this request committed."
                )
            now = datetime.now(UTC)
            account.display_name = display_name
            account.preferred_locale = preferred_locale
            account.profile_version += 1
            account.updated_at = now
            await self._append_audit(
                session,
                context,
                action="IDENTITY_PROFILE_UPDATED",
                outcome="SUCCEEDED",
                target_ref=f"identity:account:{account_id}",
                metadata={"profile_version": account.profile_version},
            )
            await self._append_outbox(
                session,
                context,
                event_type="identity.account.profile-updated",
                partition_key=f"identity:account:{account_id}",
                payload={
                    "account_id": str(account_id),
                    "profile_version": account.profile_version,
                },
            )
            await self._complete_reconciliation_job_in_transaction(
                session,
                context,
                reconciliation_job_id,
            )
            profile = self._profile(account)
            await self._complete_idempotency(
                session,
                storage_key,
                profile.model_dump(mode="json"),
            )
            return profile

        return await self._database.run_transaction(
            operation,
            context=current_session_context(),
            isolation=TransactionIsolation.SERIALIZABLE,
            retry_policy=TransactionRetryPolicy(max_attempts=8),
        )

    async def _commit_contact_change(
        self,
        context: TenantContext,
        *,
        account_id: UUID,
        channel: ContactChannel,
        identifier: str,
        challenge_id: UUID,
        expected_version: int,
        storage_key: str,
        request_digest: str,
        reconciliation_job_id: UUID,
    ) -> AccountProfileV1:
        async def operation(session: AsyncSession) -> AccountProfileV1:
            await self._assert_idempotency_record(
                session,
                context,
                storage_key,
                request_digest,
            )
            account = await self._locked_account(session, context, account_id)
            if account.profile_version != expected_version:
                raise self._account_conflict(
                    "The account profile changed before this request committed."
                )
            challenge = await session.scalar(
                select(IdentityVerificationChallengeModel)
                .where(
                    IdentityVerificationChallengeModel.challenge_id == challenge_id,
                    IdentityVerificationChallengeModel.account_id == account_id,
                    IdentityVerificationChallengeModel.state == ChallengeState.VERIFIED.value,
                )
                .with_for_update()
            )
            if challenge is None or challenge.expires_at <= datetime.now(UTC):
                raise LiyanError(
                    ErrorCode.IDENTITY_CHALLENGE_INVALID,
                    "A valid verified contact challenge is required.",
                    category=ErrorCategory.AUTH,
                    status_code=422,
                )
            now = datetime.now(UTC)
            digest = self._identifier_digest(identifier, channel)
            ciphertext = self._cipher.encrypt(
                identifier,
                tenant_id=context.tenant_id,
                field_name=channel.value.lower(),
            )
            if channel == ContactChannel.EMAIL:
                account.email_ciphertext = ciphertext
                account.email_lookup_digest = digest
                account.email_hint = mask_email(identifier)
                account.email_verified = True
            else:
                account.phone_ciphertext = ciphertext
                account.phone_lookup_digest = digest
                account.phone_hint = mask_phone(identifier)
                account.phone_verified = True
            account.profile_version += 1
            account.updated_at = now
            challenge.state = ChallengeState.CONSUMED.value
            challenge.consumed_at = now
            challenge.updated_at = now
            await self._append_audit(
                session,
                context,
                action="IDENTITY_CONTACT_CHANGED",
                outcome="SUCCEEDED",
                target_ref=f"identity:account:{account_id}",
                metadata={"channel": channel.value, "profile_version": account.profile_version},
            )
            await self._append_outbox(
                session,
                context,
                event_type="identity.account.contact-changed",
                partition_key=f"identity:account:{account_id}",
                payload={"account_id": str(account_id), "channel": channel.value},
            )
            await self._complete_reconciliation_job_in_transaction(
                session,
                context,
                reconciliation_job_id,
            )
            profile = self._profile(account)
            await self._complete_idempotency(
                session,
                storage_key,
                profile.model_dump(mode="json"),
            )
            return profile

        return await self._database.run_transaction(
            operation,
            context=current_session_context(),
            isolation=TransactionIsolation.SERIALIZABLE,
            retry_policy=TransactionRetryPolicy(max_attempts=8),
        )

    async def _commit_account_status(
        self,
        context: TenantContext,
        *,
        account_id: UUID,
        enabled: bool,
        reason_code: str | None,
        expected_version: int,
        storage_key: str,
        request_digest: str,
        reconciliation_job_id: UUID,
    ) -> AccountAdminViewV1:
        async def operation(session: AsyncSession) -> AccountAdminViewV1:
            await self._assert_idempotency_record(
                session,
                context,
                storage_key,
                request_digest,
            )
            account = await self._locked_account(session, context, account_id)
            if account.profile_version != expected_version:
                raise self._account_conflict(
                    "The account status changed before this request committed."
                )
            now = datetime.now(UTC)
            account.status = AccountStatus.ACTIVE.value if enabled else AccountStatus.DISABLED.value
            account.disabled_reason_code = None if enabled else reason_code or "ADMIN_DISABLED"
            account.profile_version += 1
            account.updated_at = now
            await self._append_audit(
                session,
                context,
                action="IDENTITY_ACCOUNT_STATUS_CHANGED",
                outcome="SUCCEEDED",
                target_ref=f"identity:account:{account_id}",
                metadata={"enabled": enabled, "profile_version": account.profile_version},
            )
            await self._append_outbox(
                session,
                context,
                event_type="identity.account.status-changed",
                partition_key=f"identity:account:{account_id}",
                payload={
                    "account_id": str(account_id),
                    "status": account.status,
                    "profile_version": account.profile_version,
                },
            )
            await self._complete_reconciliation_job_in_transaction(
                session,
                context,
                reconciliation_job_id,
            )
            view = self._admin_view(account)
            await self._complete_idempotency(session, storage_key, view.model_dump(mode="json"))
            return view

        return await self._database.run_transaction(
            operation,
            context=current_session_context(),
            isolation=TransactionIsolation.SERIALIZABLE,
            retry_policy=TransactionRetryPolicy(max_attempts=8),
        )

    async def _begin_authenticated_mutation(
        self,
        context: TenantContext,
        *,
        operation: str,
        idempotency_key: str,
        request_document: dict[str, Any],
        account_id: UUID,
        expected_version: int,
    ) -> tuple[str, str, dict[str, Any] | None]:
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise identity_contract_error("Idempotency-Key must contain 32 to 160 safe characters.")
        storage_key = self._storage_key(operation, idempotency_key)
        request_digest = canonical_sha256({"operation": operation, "request": request_document})

        async def operation_callback(session: AsyncSession) -> dict[str, Any] | None:
            duplicate = await self._reserve_idempotency(
                session,
                context,
                storage_key,
                operation=operation,
                request_digest=request_digest,
            )
            if duplicate is not None:
                return duplicate
            account = await self._locked_account(session, context, account_id)
            if account.profile_version != expected_version:
                raise self._account_conflict(
                    "The account changed before the idempotent operation was reserved."
                )
            if account.status == AccountStatus.RECONCILIATION_REQUIRED.value:
                raise self._account_conflict(
                    "The account requires identity-provider reconciliation before further changes."
                )
            return None

        with tenant_scope(context):
            duplicate = await self._database.run_transaction(
                operation_callback,
                context=current_session_context(),
                isolation=TransactionIsolation.SERIALIZABLE,
                retry_policy=TransactionRetryPolicy(max_attempts=8),
            )
        return storage_key, request_digest, duplicate

    async def _arm_account_compensation(
        self,
        context: TenantContext,
        *,
        account_id: UUID,
        expected_version: int,
        storage_key: str,
        request_digest: str,
        user: KeycloakUser,
    ) -> UUID:
        self._known_tenants.add(context.tenant_id)
        reconciliation_job_id = uuid4()
        correlation_id = uuid4()
        compensation_snapshot = self._encode_keycloak_snapshot(
            context,
            account_id=account_id,
            user=user,
        )

        async def operation(session: AsyncSession) -> UUID:
            await self._assert_idempotency_record(
                session,
                context,
                storage_key,
                request_digest,
            )
            account = await self._locked_account(session, context, account_id)
            if account.profile_version != expected_version:
                raise self._account_conflict(
                    "The account changed before the identity-provider operation was armed."
                )
            if account.status == AccountStatus.RECONCILIATION_REQUIRED.value:
                raise self._account_conflict(
                    "The account requires identity-provider reconciliation before further changes."
                )
            if account.oidc_subject != user.user_id:
                raise self._registration_unavailable()
            active_job = await session.scalar(
                select(IdentityReconciliationJobModel)
                .where(
                    IdentityReconciliationJobModel.tenant_id == context.tenant_id,
                    IdentityReconciliationJobModel.account_id == account_id,
                    IdentityReconciliationJobModel.operation != "FINALIZE_PROJECTION",
                    IdentityReconciliationJobModel.state.in_(
                        (
                            ReconciliationState.PENDING.value,
                            ReconciliationState.RUNNING.value,
                        )
                    ),
                )
                .with_for_update()
            )
            if active_job is not None:
                raise self._account_conflict(
                    "Another identity-provider operation is still being reconciled."
                )
            now = datetime.now(UTC)
            session.add(
                IdentityReconciliationJobModel(
                    reconciliation_job_id=reconciliation_job_id,
                    tenant_id=context.tenant_id,
                    correlation_id=correlation_id,
                    registration_id=None,
                    account_id=account_id,
                    keycloak_user_id=user.user_id,
                    operation="UPDATE_KEYCLOAK_USER",
                    state=ReconciliationState.PENDING.value,
                    attempt_count=0,
                    max_attempts=8,
                    next_attempt_at=now
                    + timedelta(
                        seconds=max(
                            15.0,
                            self._settings.keycloak_admin_http_timeout_seconds * 3,
                        )
                    ),
                    last_error_code=None,
                    job_document={
                        "kind": "KEYCLOAK_RESTORE",
                        "storage_key": storage_key,
                        "request_digest": request_digest,
                        "compensation_snapshot": compensation_snapshot,
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            await self._append_audit(
                session,
                context,
                action="IDENTITY_COMPENSATION_ARMED",
                outcome="PENDING",
                target_ref=f"identity:account:{account_id}",
                metadata={"reconciliation_job_id": str(reconciliation_job_id)},
            )
            return reconciliation_job_id

        with tenant_scope(context):
            try:
                return await self._database.run_transaction(
                    operation,
                    context=current_session_context(),
                    isolation=TransactionIsolation.SERIALIZABLE,
                    retry_policy=TransactionRetryPolicy(max_attempts=8),
                )
            except IntegrityError as exc:
                raise self._account_conflict(
                    "Another identity-provider operation is still being reconciled."
                ) from exc

    async def _queue_account_compensation(
        self,
        context: TenantContext,
        reconciliation_job_id: UUID,
        *,
        failure_code: str,
    ) -> None:
        try:
            with tenant_scope(context):

                async def operation(session: AsyncSession) -> None:
                    row = await session.scalar(
                        select(IdentityReconciliationJobModel)
                        .where(
                            IdentityReconciliationJobModel.tenant_id == context.tenant_id,
                            IdentityReconciliationJobModel.reconciliation_job_id
                            == reconciliation_job_id,
                        )
                        .with_for_update()
                    )
                    if row is None or row.state != ReconciliationState.PENDING.value:
                        return
                    now = datetime.now(UTC)
                    row.next_attempt_at = now
                    row.last_error_code = failure_code[:128]
                    row.updated_at = now
                    await self._append_audit(
                        session,
                        context,
                        action="IDENTITY_COMPENSATION_QUEUED",
                        outcome="PENDING",
                        target_ref=f"identity:account:{row.account_id}",
                        metadata={
                            "failure_code": failure_code[:128],
                            "reconciliation_job_id": str(reconciliation_job_id),
                        },
                    )

                await self._database.run_transaction(
                    operation,
                    context=current_session_context(),
                    isolation=TransactionIsolation.SERIALIZABLE,
                    retry_policy=TransactionRetryPolicy(max_attempts=8),
                )
        except Exception:
            logger.exception("Failed to expedite identity-provider compensation")

    async def _complete_reconciliation_job_in_transaction(
        self,
        session: AsyncSession,
        context: TenantContext,
        reconciliation_job_id: UUID,
    ) -> None:
        row = await session.scalar(
            select(IdentityReconciliationJobModel)
            .where(
                IdentityReconciliationJobModel.tenant_id == context.tenant_id,
                IdentityReconciliationJobModel.reconciliation_job_id == reconciliation_job_id,
            )
            .with_for_update()
        )
        if row is None or row.state != ReconciliationState.PENDING.value:
            raise self._registration_unavailable()
        now = datetime.now(UTC)
        row.state = ReconciliationState.COMPLETED.value
        row.completed_at = now
        row.last_error_code = None
        row.updated_at = now

    def _encode_keycloak_snapshot(
        self,
        context: TenantContext,
        *,
        account_id: UUID,
        user: KeycloakUser,
    ) -> str:
        document = {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "email_verified": user.email_verified,
            "enabled": user.enabled,
            "display_name": user.display_name,
            "last_name": user.last_name,
            "attributes": {key: list(values) for key, values in user.attributes.items()},
        }
        ciphertext = self._cipher.encrypt(
            json.dumps(document, sort_keys=True, separators=(",", ":")),
            tenant_id=context.tenant_id,
            field_name=f"keycloak-compensation:{account_id}",
        )
        if len(ciphertext) > 65_536:
            raise self._registration_unavailable()
        return ciphertext

    def _decode_keycloak_snapshot(
        self,
        context: TenantContext,
        *,
        account_id: UUID,
        ciphertext: Any,
    ) -> KeycloakUser:
        if not isinstance(ciphertext, str) or not 32 <= len(ciphertext) <= 65_536:
            raise self._registration_unavailable()
        plaintext = self._cipher.decrypt(
            ciphertext,
            tenant_id=context.tenant_id,
            field_name=f"keycloak-compensation:{account_id}",
        )
        try:
            document = json.loads(plaintext)
        except (TypeError, ValueError) as exc:
            raise self._registration_unavailable() from exc
        if not isinstance(document, dict):
            raise self._registration_unavailable()
        user_id = document.get("user_id")
        username = document.get("username")
        email = document.get("email")
        email_verified = document.get("email_verified")
        enabled = document.get("enabled")
        display_name = document.get("display_name")
        last_name = document.get("last_name")
        raw_attributes = document.get("attributes")
        if (
            not isinstance(user_id, str)
            or not 1 <= len(user_id) <= 256
            or not isinstance(username, str)
            or not 1 <= len(username) <= 320
            or (email is not None and not isinstance(email, str))
            or not isinstance(email_verified, bool)
            or not isinstance(enabled, bool)
            or (display_name is not None and not isinstance(display_name, str))
            or (last_name is not None and not isinstance(last_name, str))
            or not isinstance(raw_attributes, dict)
        ):
            raise self._registration_unavailable()
        attributes: dict[str, tuple[str, ...]] = {}
        for key, raw_values in raw_attributes.items():
            if (
                not isinstance(key, str)
                or not 1 <= len(key) <= 255
                or not isinstance(raw_values, list)
                or len(raw_values) > 32
                or not all(isinstance(value, str) and len(value) <= 4096 for value in raw_values)
            ):
                raise self._registration_unavailable()
            attributes[key] = tuple(raw_values)
        if context.tenant_id not in attributes.get("tenant_id", ()):
            raise self._registration_unavailable()
        return KeycloakUser(
            user_id=user_id,
            username=username,
            email=email,
            enabled=enabled,
            attributes=attributes,
            display_name=display_name,
            last_name=last_name,
            email_verified=email_verified,
        )

    async def _assert_contact_challenge(
        self,
        context: TenantContext,
        *,
        account_id: UUID,
        challenge_id: UUID,
        channel: ContactChannel,
        identifier_digest: str,
    ) -> None:
        async with self._database.transaction(context=current_session_context()) as session:
            challenge = await session.scalar(
                select(IdentityVerificationChallengeModel).where(
                    IdentityVerificationChallengeModel.challenge_id == challenge_id,
                    IdentityVerificationChallengeModel.account_id == account_id,
                    IdentityVerificationChallengeModel.channel == channel.value,
                    IdentityVerificationChallengeModel.purpose
                    == (
                        ChallengePurpose.CHANGE_EMAIL.value
                        if channel == ContactChannel.EMAIL
                        else ChallengePurpose.CHANGE_PHONE.value
                    ),
                    IdentityVerificationChallengeModel.identifier_digest == identifier_digest,
                    IdentityVerificationChallengeModel.state == ChallengeState.VERIFIED.value,
                )
            )
            if challenge is None or challenge.expires_at <= datetime.now(UTC):
                raise LiyanError(
                    ErrorCode.IDENTITY_CHALLENGE_INVALID,
                    "A valid verified contact challenge is required.",
                    category=ErrorCategory.AUTH,
                    status_code=422,
                )

    async def _registration_context(
        self,
        invitation_token: str | None,
        *,
        trace_id: str,
        authenticated_context: TenantContext | None,
    ) -> TenantContext:
        if authenticated_context is not None:
            return authenticated_context
        if invitation_token:
            secret = self._settings.registration_invitation_secret
            if secret is None:
                raise invitation_error()
            tenant_id = verify_registration_invitation(
                invitation_token,
                secret=secret.get_secret_value(),
                issuer=self._settings.registration_invitation_issuer,
                audience=self._settings.registration_invitation_audience,
            )
        elif (
            self._settings.environment != "production"
            and self._settings.registration_allow_development_fallback
        ):
            tenant_id = self._settings.registration_development_tenant_id
        else:
            raise invitation_error()
        if not re.fullmatch(r"^[a-z0-9][a-z0-9_-]{1,126}[a-z0-9]$", tenant_id):
            raise invitation_error()
        context = TenantContext(
            tenant_id=tenant_id,
            subject_ref="anonymous:registration",
            roles=frozenset(),
            scopes=frozenset(),
            trace_id=trace_id,
        )
        with tenant_scope(context):
            async with self._database.transaction(context=current_session_context()) as session:
                tenant = await session.scalar(
                    select(TenantModel).where(TenantModel.tenant_id == tenant_id)
                )
                if tenant is None or tenant.status != "ACTIVE":
                    raise invitation_error()
        return context

    async def _enforce_rate_limits(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        dimensions: Iterable[tuple[str, str]],
        now: datetime,
    ) -> None:
        window_seconds = self._settings.registration_rate_limit_window_seconds
        epoch = int(now.timestamp())
        window_start = datetime.fromtimestamp(
            epoch - (epoch % window_seconds),
            UTC,
        )
        for dimension_kind, digest in dimensions:
            await self._lock(
                session,
                f"identity:rate:{context.tenant_id}:{dimension_kind}:{digest}",
            )
            row = await session.scalar(
                select(IdentityVerificationRateLimitModel)
                .where(
                    IdentityVerificationRateLimitModel.tenant_id == context.tenant_id,
                    IdentityVerificationRateLimitModel.dimension_kind == dimension_kind,
                    IdentityVerificationRateLimitModel.dimension_digest == digest,
                    IdentityVerificationRateLimitModel.window_started_at == window_start,
                )
                .with_for_update()
            )
            if row is None:
                session.add(
                    IdentityVerificationRateLimitModel(
                        rate_limit_id=uuid4(),
                        tenant_id=context.tenant_id,
                        dimension_kind=dimension_kind,
                        dimension_digest=digest,
                        window_started_at=window_start,
                        window_seconds=window_seconds,
                        request_count=1,
                        updated_at=now,
                    )
                )
                continue
            if row.request_count >= self._settings.registration_rate_limit_max_requests:
                retry_after = max(
                    1.0,
                    (window_start + timedelta(seconds=window_seconds) - now).total_seconds(),
                )
                raise RateLimitExceeded(retry_after)
            row.request_count += 1
            row.updated_at = now

    async def _append_registration_snapshot(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        registration_id: UUID,
        version: int,
        account_id: UUID | None,
        channel: ContactChannel,
        identifier_digest: str,
        idempotency_key_digest: str,
        state: RegistrationState,
        keycloak_user_id: str | None,
        failure_code: str | None,
        state_document: dict[str, Any],
        created_at: datetime,
    ) -> None:
        material = {
            "registration_id": str(registration_id),
            "registration_version": version,
            "tenant_id": context.tenant_id,
            "account_id": str(account_id) if account_id is not None else None,
            "channel": channel.value,
            "identifier_digest": identifier_digest,
            "idempotency_key_digest": idempotency_key_digest,
            "state": state.value,
            "keycloak_user_id": keycloak_user_id,
            "failure_code": failure_code,
            "state_document": state_document,
            "created_at": created_at.isoformat(),
        }
        session.add(
            IdentityRegistrationSnapshotModel(
                registration_snapshot_id=uuid4(),
                registration_id=registration_id,
                registration_version=version,
                tenant_id=context.tenant_id,
                account_id=account_id,
                channel=channel.value,
                identifier_digest=identifier_digest,
                idempotency_key_digest=idempotency_key_digest,
                state=state.value,
                keycloak_user_id=keycloak_user_id,
                failure_code=failure_code,
                state_document=state_document,
                record_sha256=canonical_sha256(material),
                immutable=True,
                created_at=created_at,
            )
        )
        await session.flush()

    async def _append_consents(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        account: IdentityAccountModel,
        registration_id: UUID,
        consent: RegistrationConsentV1,
        accepted_at: datetime,
    ) -> None:
        policies = (
            ("PRIVACY_POLICY", consent.privacy_policy_version),
            ("TERMS_OF_SERVICE", consent.terms_of_service_version),
        )
        for policy_type, policy_version in policies:
            consent_id = uuid4()
            document = {
                "consent_id": str(consent_id),
                "tenant_id": context.tenant_id,
                "account_id": str(account.account_id),
                "registration_id": str(registration_id),
                "policy_type": policy_type,
                "policy_version": policy_version,
                "accepted": True,
                "accepted_at": accepted_at.isoformat(),
            }
            session.add(
                IdentityConsentRecordModel(
                    consent_record_id=uuid4(),
                    consent_id=consent_id,
                    tenant_id=context.tenant_id,
                    account_id=account.account_id,
                    registration_id=registration_id,
                    policy_type=policy_type,
                    policy_version=policy_version,
                    accepted=True,
                    actor_ref=f"registration:{registration_id}",
                    accepted_at=accepted_at,
                    consent_document=document,
                    record_sha256=canonical_sha256(document),
                    immutable=True,
                )
            )
        await session.flush()

    async def _append_audit(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        action: str,
        outcome: str,
        target_ref: str,
        metadata: dict[str, Any],
    ) -> AuditRecord:
        await self._lock(session, f"audit:{context.tenant_id}")
        previous = await session.scalar(
            select(AuditEventModel)
            .where(AuditEventModel.tenant_id == context.tenant_id)
            .order_by(AuditEventModel.sequence.desc())
            .limit(1)
        )
        record = build_audit_record(
            AuditDraft(
                tenant_id=context.tenant_id,
                category="IDENTITY",
                action=action,
                outcome=outcome,
                actor_ref=context.subject_ref,
                target_ref=target_ref,
                trace_id=context.trace_id,
                envelope_id=None,
                metadata=metadata,
                occurred_at=datetime.now(UTC),
            ),
            0 if previous is None else previous.sequence + 1,
            GENESIS_HASH if previous is None else previous.event_hash,
        )
        session.add(
            AuditEventModel(
                event_id=record.event_id,
                tenant_id=record.tenant_id,
                sequence=record.sequence,
                category=record.category,
                action=record.action,
                outcome=record.outcome,
                actor_ref=record.actor_ref,
                target_ref=record.target_ref,
                trace_id=record.trace_id,
                envelope_id=None,
                event_metadata=record.metadata,
                occurred_at=record.occurred_at,
                previous_hash=record.previous_hash,
                event_hash=record.event_hash,
            )
        )
        await session.flush()
        return record

    async def _append_outbox(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        event_type: str,
        partition_key: str,
        payload: dict[str, Any],
    ) -> None:
        await self._lock(session, f"outbox:{context.tenant_id}:{partition_key}")
        sequence = int(
            await session.scalar(
                select(func.coalesce(func.max(OutboxMessageModel.sequence) + 1, 0)).where(
                    OutboxMessageModel.tenant_id == context.tenant_id,
                    OutboxMessageModel.partition_key == partition_key,
                )
            )
        )
        now = datetime.now(UTC)
        correlation_id = uuid4()
        envelope = Topic3EnvelopeV1(
            envelope_id=uuid4(),
            event_type=event_type,
            message_kind=MessageKind.EVENT,
            tenant_id=context.tenant_id,
            session_id=context.session_id or correlation_id,
            subject_ref=context.subject_ref,
            correlation_id=correlation_id,
            causation_id=None,
            sequence=sequence,
            partition_key=partition_key,
            producer=ProducerMetadataV1(
                agent=None,
                service="identity-service",
                instance_id=self._instance_id,
                build_version="identity-registration-v1",
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=f"identity:{canonical_sha256(payload)}",
                available_at=now,
                expires_at=now + OUTBOX_RETENTION,
            ),
            resource=None,
            trace_id=context.trace_id,
            span_id=None,
            created_at=now,
            error=None,
            payload=payload,
        )
        await self._outbox.append(
            session,
            OutboxMessage(
                outbox_id=uuid4(),
                tenant_id=context.tenant_id,
                envelope=envelope,
                created_at=now,
                available_at=now,
                published_at=None,
                max_attempts=envelope.delivery.max_attempts,
            ),
        )

    async def _reserve_idempotency(
        self,
        session: AsyncSession,
        context: TenantContext,
        key: str,
        *,
        operation: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        statement = (
            insert(IdempotencyRecordModel)
            .values(
                tenant_id=context.tenant_id,
                idempotency_key=key,
                operation=operation,
                request_digest=request_digest,
                state=IdempotencyStatus.PROCESSING.value,
                lease_owner=self._instance_id,
                lease_expires_at=now
                + timedelta(seconds=self._settings.idempotency_processing_lease_seconds),
                expires_at=now + timedelta(seconds=self._settings.idempotency_retention_seconds),
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyRecordModel.tenant_id,
                    IdempotencyRecordModel.idempotency_key,
                ]
            )
            .returning(IdempotencyRecordModel.idempotency_key)
        )
        if (await session.execute(statement)).scalar_one_or_none() is not None:
            return None
        record = await session.scalar(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        if record is None:
            raise self._registration_unavailable()
        if record.operation != operation or record.request_digest != request_digest:
            raise MessageConflictError(
                ErrorCode.MESSAGE_DUPLICATE_CONFLICT,
                "The idempotency key was reused for different request content.",
            )
        if record.state == IdempotencyStatus.COMPLETED.value:
            if not isinstance(record.result_payload, dict):
                raise self._registration_unavailable()
            return dict(record.result_payload)
        if record.lease_expires_at is not None and record.lease_expires_at > now:
            raise self._account_conflict("The idempotent account operation is still in progress.")
        record.state = IdempotencyStatus.PROCESSING.value
        record.lease_owner = self._instance_id
        record.lease_expires_at = now + timedelta(
            seconds=self._settings.idempotency_processing_lease_seconds
        )
        record.updated_at = now
        return None

    async def _complete_idempotency(
        self,
        session: AsyncSession,
        key: str,
        result: dict[str, Any],
    ) -> None:
        record = await session.scalar(
            select(IdempotencyRecordModel)
            .where(IdempotencyRecordModel.idempotency_key == key)
            .with_for_update()
        )
        if record is None:
            raise self._registration_unavailable()
        record.state = IdempotencyStatus.COMPLETED.value
        record.lease_owner = None
        record.lease_expires_at = None
        record.response_status_code = 200
        record.result_payload = result
        record.updated_at = datetime.now(UTC)

    async def _assert_idempotency_record(
        self,
        session: AsyncSession,
        context: TenantContext,
        key: str,
        request_digest: str,
    ) -> None:
        record = await session.scalar(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        if record is None or record.request_digest != request_digest:
            raise self._registration_unavailable()

    async def _release_idempotency_in_transaction(
        self,
        session: AsyncSession,
        context: TenantContext,
        key: Any,
    ) -> None:
        if not isinstance(key, str) or not key:
            raise self._registration_unavailable()
        record = await session.scalar(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.tenant_id == context.tenant_id,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        if record is not None and record.state != IdempotencyStatus.COMPLETED.value:
            now = datetime.now(UTC)
            record.lease_owner = self._instance_id
            record.lease_expires_at = now - timedelta(seconds=1)
            record.updated_at = now

    async def _release_idempotency(self, context: TenantContext, key: str) -> None:
        try:
            with tenant_scope(context):
                async with self._database.transaction(context=current_session_context()) as session:
                    await self._release_idempotency_in_transaction(
                        session,
                        context,
                        key,
                    )
        except Exception:
            return

    async def _required_account(self, account_id: UUID) -> IdentityAccountModel:
        context = current_tenant()
        self._known_tenants.add(context.tenant_id)
        async with self._database.transaction(context=current_session_context()) as session:
            account = await session.scalar(
                select(IdentityAccountModel).where(
                    IdentityAccountModel.tenant_id == context.tenant_id,
                    IdentityAccountModel.account_id == account_id,
                )
            )
        if account is None:
            raise LiyanError(
                ErrorCode.IDENTITY_ACCOUNT_NOT_FOUND,
                "The account does not exist.",
                category=ErrorCategory.AUTH,
                status_code=404,
            )
        return account

    async def _locked_account(
        self,
        session: AsyncSession,
        context: TenantContext,
        account_id: UUID,
    ) -> IdentityAccountModel:
        account = await session.scalar(
            select(IdentityAccountModel)
            .where(
                IdentityAccountModel.tenant_id == context.tenant_id,
                IdentityAccountModel.account_id == account_id,
            )
            .with_for_update()
        )
        if account is None:
            raise LiyanError(
                ErrorCode.IDENTITY_ACCOUNT_NOT_FOUND,
                "The account does not exist.",
                category=ErrorCategory.AUTH,
                status_code=404,
            )
        return account

    def _new_account(
        self,
        context: TenantContext,
        *,
        user: KeycloakUser,
        channel: ContactChannel,
        identifier: str,
        display_name: str,
        preferred_locale: str,
        now: datetime,
    ) -> IdentityAccountModel:
        email_ciphertext = None
        email_digest = None
        email_hint = None
        phone_ciphertext = None
        phone_digest = None
        phone_hint = None
        if channel == ContactChannel.EMAIL:
            email_ciphertext = self._cipher.encrypt(
                identifier,
                tenant_id=context.tenant_id,
                field_name="email",
            )
            email_digest = self._identifier_digest(identifier, ContactChannel.EMAIL)
            email_hint = mask_email(identifier)
        else:
            phone_ciphertext = self._cipher.encrypt(
                identifier,
                tenant_id=context.tenant_id,
                field_name="phone",
            )
            phone_digest = self._identifier_digest(identifier, ContactChannel.PHONE)
            phone_hint = mask_phone(identifier)
        if preferred_locale not in {"zh-CN", "zh-TW", "en-US"}:
            raise identity_contract_error("The preferred locale is invalid.")
        return IdentityAccountModel(
            account_id=uuid4(),
            tenant_id=context.tenant_id,
            oidc_subject=user.user_id,
            display_name=display_name,
            preferred_locale=preferred_locale,
            email_ciphertext=email_ciphertext,
            email_lookup_digest=email_digest,
            email_hint=email_hint,
            email_verified=channel == ContactChannel.EMAIL,
            phone_ciphertext=phone_ciphertext,
            phone_lookup_digest=phone_digest,
            phone_hint=phone_hint,
            phone_verified=channel == ContactChannel.PHONE,
            status=AccountStatus.ACTIVE.value,
            profile_version=1,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _user_contact(user: KeycloakUser) -> tuple[ContactChannel, str]:
        channel = next(iter(user.attributes.get("login_channel", ())), None)
        if channel == ContactChannel.PHONE.value:
            values = user.attributes.get("phone_number", ())
            if values:
                return ContactChannel.PHONE, normalize_phone(values[0])
        if user.email:
            return ContactChannel.EMAIL, normalize_email(user.email)
        if user.username.startswith("+"):
            return ContactChannel.PHONE, normalize_phone(user.username)
        raise LiyanError(
            ErrorCode.IDENTITY_INTEGRITY_FAILED,
            "The identity provider account has no supported verified contact.",
            category=ErrorCategory.AUTH,
            status_code=503,
        )

    def _profile(self, account: IdentityAccountModel) -> AccountProfileV1:
        return AccountProfileV1(
            account_id=account.account_id,
            tenant_id=account.tenant_id,
            subject_ref=account.oidc_subject,
            display_name=account.display_name,
            preferred_locale=account.preferred_locale,
            email_hint=account.email_hint,
            email_verified=account.email_verified,
            phone_hint=account.phone_hint,
            phone_verified=account.phone_verified,
            status=IdentityAccountStatus(account.status),
            profile_version=account.profile_version,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    def _admin_view(self, account: IdentityAccountModel) -> AccountAdminViewV1:
        profile = self._profile(account).model_dump(exclude={"schema_version"})
        return AccountAdminViewV1(
            **profile,
            disabled_reason_code=account.disabled_reason_code,
        )

    @staticmethod
    def _registration_status(
        snapshot: IdentityRegistrationSnapshotModel,
    ) -> RegistrationStatusV1:
        return RegistrationStatusV1(
            registration_id=snapshot.registration_id,
            registration_version=snapshot.registration_version,
            state=IdentityRegistrationState(snapshot.state),
            channel=IdentityContactChannel(snapshot.channel),
            account_id=snapshot.account_id,
            failure_code=snapshot.failure_code,
            record_sha256=snapshot.record_sha256,
            created_at=snapshot.created_at,
        )

    @staticmethod
    def _identity_audit_entry(row: AuditEventModel) -> IdentityAuditEntryV1:
        return IdentityAuditEntryV1(
            event_id=row.event_id,
            sequence=row.sequence,
            action=row.action,
            outcome=row.outcome,
            actor_ref=row.actor_ref,
            target_ref=row.target_ref,
            trace_id=row.trace_id,
            metadata=dict(row.event_metadata),
            occurred_at=row.occurred_at,
            previous_hash=row.previous_hash,
            event_hash=row.event_hash,
            hash_algorithm="SHA-256",
        )

    def _normalize_identifier(
        self,
        channel: IdentityContactChannel | ContactChannel,
        identifier: str,
    ) -> str:
        if channel == IdentityContactChannel.EMAIL or channel == ContactChannel.EMAIL:
            return normalize_email(identifier)
        return normalize_phone(identifier)

    def _identifier_digest(self, identifier: str, channel: ContactChannel) -> str:
        return keyed_digest(
            identifier,
            self._lookup_pepper,
            purpose=f"contact:{channel.value.lower()}",
        )

    def _request_fingerprint(
        self,
        client_ip: str,
        user_agent: str,
        device_fingerprint: str | None,
    ) -> str:
        value = "|".join(
            (
                client_ip[:128],
                user_agent[:512],
                (device_fingerprint or "unknown")[:256],
            )
        )
        return keyed_digest(value, self._lookup_pepper, purpose="device")

    @property
    def _lookup_pepper(self) -> str:
        return self._settings.identity_lookup_pepper.get_secret_value()

    @property
    def _verification_pepper(self) -> str:
        return self._settings.verification_code_pepper.get_secret_value()

    def _require_keycloak(self) -> KeycloakAdminClient:
        if self._keycloak is None:
            raise LiyanError(
                ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
                "Account registration is not configured.",
                category=ErrorCategory.AUTH,
                status_code=503,
            )
        return self._keycloak

    @staticmethod
    def _storage_key(operation: str, idempotency_key: str) -> str:
        return f"identity:{operation}:{sha256_hex(idempotency_key)[:48]}"

    def _challenge_receipt(
        self,
        row: IdentityVerificationChallengeModel,
        *,
        now: datetime,
    ) -> VerificationChallengeReceiptV1:
        resend_after = max(
            1,
            int(
                (
                    row.last_sent_at
                    + timedelta(seconds=self._settings.registration_challenge_cooldown_seconds)
                    - now
                ).total_seconds()
            ),
        )
        return VerificationChallengeReceiptV1(
            challenge_id=row.challenge_id,
            channel=IdentityContactChannel(row.channel),
            purpose=IdentityChallengePurpose(row.purpose),
            state=IdentityChallengeState(row.state),
            delivery_hint=row.delivery_hint,
            expires_at=row.expires_at,
            resend_after_seconds=resend_after,
        )

    @staticmethod
    async def _lock(session: AsyncSession, key: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": key},
        )

    @staticmethod
    def _account_conflict(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.IDENTITY_ACCOUNT_CONFLICT,
            message,
            category=ErrorCategory.AUTH,
            status_code=409,
        )

    @staticmethod
    def _registration_unavailable() -> LiyanError:
        return LiyanError(
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
            "The identity registration service is temporarily unavailable.",
            category=ErrorCategory.AUTH,
            retriable=True,
            status_code=503,
        )


class IdentityReconciliationWorker:
    def __init__(self, service: IdentityService, *, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("identity reconciliation interval must be positive")
        self._service = service
        self._interval_seconds = interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="identity-reconciliation-worker",
        )

    async def close(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            await task

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._service.reconcile_known_tenants()
            except Exception:
                logger.exception("Identity reconciliation cycle failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue
