from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from .common import FROZEN_MODEL_CONFIG

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
LOCALE_PATTERN = re.compile(r"^(zh-CN|zh-TW|en-US)$")


class IdentityContactChannel(StrEnum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"


class IdentityChallengePurpose(StrEnum):
    REGISTER = "REGISTER"
    CHANGE_EMAIL = "CHANGE_EMAIL"
    CHANGE_PHONE = "CHANGE_PHONE"
    RECOVERY = "RECOVERY"


class IdentityChallengeState(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"


class IdentityAccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class IdentityRegistrationState(StrEnum):
    KEYCLOAK_PENDING = "KEYCLOAK_PENDING"
    PROJECTION_PENDING = "PROJECTION_PENDING"
    COMPLETED = "COMPLETED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    FAILED = "FAILED"


class IdentityApiEnvelopeV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["identity.api-envelope.v1"] = "identity.api-envelope.v1"
    request_id: UUID
    trace_id: str = Field(min_length=16, max_length=64, pattern=r"^[a-fA-F0-9]+$")
    data: dict[str, Any]


class VerificationChallengeRequestV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["verification-challenge.request.v1"] = (
        "verification-challenge.request.v1"
    )
    channel: IdentityContactChannel
    purpose: IdentityChallengePurpose
    identifier: str = Field(min_length=3, max_length=320)
    invitation_token: str | None = Field(default=None, min_length=32, max_length=4096)

    @model_validator(mode="after")
    def validate_channel_purpose(self) -> VerificationChallengeRequestV1:
        expected = {
            IdentityChallengePurpose.CHANGE_EMAIL: IdentityContactChannel.EMAIL,
            IdentityChallengePurpose.CHANGE_PHONE: IdentityContactChannel.PHONE,
        }.get(self.purpose)
        if expected is not None and self.channel != expected:
            raise ValueError("challenge purpose does not match the contact channel")
        return self


class VerificationChallengeVerifyV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["verification-challenge.verify.v1"] = "verification-challenge.verify.v1"
    challenge_id: UUID
    code: SecretStr = Field(json_schema_extra={"writeOnly": True})
    invitation_token: str | None = Field(default=None, min_length=32, max_length=4096)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"^[0-9]{6}$", value.get_secret_value()):
            raise ValueError("verification code must contain exactly six digits")
        return value


class VerificationChallengeReceiptV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["verification-challenge.receipt.v1"] = (
        "verification-challenge.receipt.v1"
    )
    challenge_id: UUID
    channel: IdentityContactChannel
    purpose: IdentityChallengePurpose
    state: IdentityChallengeState
    delivery_hint: str = Field(min_length=1, max_length=320)
    expires_at: datetime
    resend_after_seconds: int = Field(ge=1, le=3600)


class RegistrationConsentV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    privacy_policy_version: str = Field(min_length=1, max_length=64)
    terms_of_service_version: str = Field(min_length=1, max_length=64)
    privacy_policy_accepted: Literal[True]
    terms_of_service_accepted: Literal[True]


class UserRegisterByEmailCommandV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["user-register-by-email.command.v1"] = (
        "user-register-by-email.command.v1"
    )
    challenge_id: UUID
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(json_schema_extra={"writeOnly": True})
    display_name: str = Field(min_length=1, max_length=255)
    preferred_locale: str = Field(default="zh-CN", pattern=LOCALE_PATTERN.pattern)
    consent: RegistrationConsentV1
    invitation_token: str | None = Field(default=None, min_length=32, max_length=4096)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("email is invalid")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not 8 <= len(value.get_secret_value()) <= 128:
            raise ValueError("password length is invalid")
        return value


class UserRegisterByPhoneCommandV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["user-register-by-phone.command.v1"] = (
        "user-register-by-phone.command.v1"
    )
    challenge_id: UUID
    phone: str = Field(min_length=8, max_length=32)
    password: SecretStr = Field(json_schema_extra={"writeOnly": True})
    display_name: str = Field(min_length=1, max_length=255)
    preferred_locale: str = Field(default="zh-CN", pattern=LOCALE_PATTERN.pattern)
    consent: RegistrationConsentV1
    invitation_token: str | None = Field(default=None, min_length=32, max_length=4096)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        compact = re.sub(r"[\s().-]", "", value)
        if not PHONE_PATTERN.fullmatch(compact):
            raise ValueError("phone must use E.164 format")
        return compact

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not 8 <= len(value.get_secret_value()) <= 128:
            raise ValueError("password length is invalid")
        return value


class RegistrationReceiptV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["registration.receipt.v1"] = "registration.receipt.v1"
    registration_id: UUID
    account_id: UUID
    state: Literal["COMPLETED"] = "COMPLETED"
    preferred_locale: str = Field(pattern=LOCALE_PATTERN.pattern)
    login_required: Literal[True] = True
    created_at: datetime


class RegistrationStatusV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["registration.status.v1"] = "registration.status.v1"
    registration_id: UUID
    registration_version: int = Field(ge=1)
    state: IdentityRegistrationState
    channel: IdentityContactChannel
    account_id: UUID | None = None
    failure_code: str | None = Field(default=None, max_length=128)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class AccountProfileV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["account.profile.v1"] = "account.profile.v1"
    account_id: UUID
    tenant_id: str = Field(min_length=3, max_length=128)
    subject_ref: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=255)
    preferred_locale: str = Field(pattern=LOCALE_PATTERN.pattern)
    email_hint: str | None = Field(default=None, max_length=320)
    email_verified: bool
    phone_hint: str | None = Field(default=None, max_length=32)
    phone_verified: bool
    status: IdentityAccountStatus
    profile_version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class AccountAdminViewV1(AccountProfileV1):
    schema_version: Literal["account.admin-view.v1"] = "account.admin-view.v1"
    disabled_reason_code: str | None = Field(default=None, max_length=128)


class IdentityAuditEntryV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["identity.audit-entry.v1"] = "identity.audit-entry.v1"
    event_id: UUID
    sequence: int = Field(ge=0)
    action: str = Field(min_length=1, max_length=128)
    outcome: str = Field(min_length=1, max_length=64)
    actor_ref: str = Field(min_length=1, max_length=256)
    target_ref: str | None = Field(default=None, max_length=512)
    trace_id: str | None = Field(
        default=None,
        min_length=16,
        max_length=64,
        pattern=r"^[a-fA-F0-9]+$",
    )
    metadata: dict[str, Any]
    occurred_at: datetime
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_algorithm: Literal["SHA-256"] = "SHA-256"
