from __future__ import annotations

import ipaddress
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, status
from liyans_contracts.identity import (
    IdentityApiEnvelopeV1,
    IdentityChallengePurpose,
    IdentityContactChannel,
    UserRegisterByEmailCommandV1,
    UserRegisterByPhoneCommandV1,
    VerificationChallengeRequestV1,
    VerificationChallengeVerifyV1,
)
from pydantic import BaseModel, ConfigDict, Field

from liyans.api.auth import require_scopes
from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.tenant import current_tenant
from liyans.domains.identity.models import ContactChannel
from liyans.domains.identity.service import (
    IDENTITY_SCOPE_ADMIN_READ,
    IDENTITY_SCOPE_ADMIN_WRITE,
    IDENTITY_SCOPE_CONTACT_WRITE,
    IDENTITY_SCOPE_PROFILE_READ,
    IDENTITY_SCOPE_PROFILE_WRITE,
    IdentityService,
)

public_router = APIRouter(prefix="/api/auth", tags=["identity"])
account_router = APIRouter(prefix="/internal/accounts", tags=["identity"])
tenant_account_router = APIRouter(prefix="/internal/tenant/accounts", tags=["identity"])
tenant_registration_router = APIRouter(prefix="/internal/tenant/registrations", tags=["identity"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=32, max_length=160)]


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=255)
    preferred_locale: Literal["zh-CN", "zh-TW", "en-US"]
    expected_version: int = Field(ge=1)


class ContactChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: IdentityContactChannel
    identifier: str = Field(min_length=3, max_length=320)
    challenge_id: UUID
    expected_version: int = Field(ge=1)


class AccountStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason_code: str | None = Field(default=None, min_length=1, max_length=128)


def identity_service(request: Request) -> IdentityService:
    value = getattr(request.app.state, "identity_service", None)
    if value is None:
        raise LiyanError(
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
            "The identity service is unavailable.",
            category=ErrorCategory.AUTH,
            retriable=True,
            status_code=503,
        )
    return cast(IdentityService, value)


def response_envelope(request: Request, data: dict) -> IdentityApiEnvelopeV1:
    return IdentityApiEnvelopeV1(
        request_id=uuid4(),
        trace_id=request.state.trace_id,
        data=data,
    )


def request_ip(request: Request) -> str:
    value = request.client.host if request.client is not None else "127.0.0.1"
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return "0.0.0.0"


@public_router.post(
    "/verification-challenges",
    response_model=IdentityApiEnvelopeV1,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_public_challenge(
    request: Request,
    body: VerificationChallengeRequestV1,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    receipt = await identity_service(request).request_challenge(
        body,
        idempotency_key=idempotency_key,
        trace_id=request.state.trace_id,
        client_ip=request_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    return response_envelope(request, {"challenge": receipt.model_dump(mode="json")})


@public_router.post(
    "/verification-challenges/verify",
    response_model=IdentityApiEnvelopeV1,
)
async def verify_public_challenge(
    request: Request,
    body: VerificationChallengeVerifyV1,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    receipt = await identity_service(request).verify_challenge(
        body,
        idempotency_key=idempotency_key,
        invitation_token=body.invitation_token,
        trace_id=request.state.trace_id,
    )
    return response_envelope(request, {"challenge": receipt.model_dump(mode="json")})


@public_router.get(
    "/dev/verification-codes/{challenge_id}",
    response_model=IdentityApiEnvelopeV1,
)
async def read_fixture_verification_code(
    request: Request,
    challenge_id: UUID,
) -> IdentityApiEnvelopeV1:
    settings = request.app.state.settings
    source_ip = ipaddress.ip_address(request_ip(request))
    request_host = (request.url.hostname or "").casefold()
    if (
        settings.environment == "production"
        or not settings.registration_fixture_inbox_enabled
        or request_host not in {"localhost", "127.0.0.1", "::1", "testserver"}
        or not source_ip.is_loopback
    ):
        raise LiyanError(
            ErrorCode.AUTH_FORBIDDEN,
            "The development verification inbox is unavailable.",
            category=ErrorCategory.AUTH,
            status_code=403,
        )
    message = await identity_service(request).fixture_inbox.read(challenge_id)
    if message is None:
        raise LiyanError(
            ErrorCode.IDENTITY_CHALLENGE_INVALID,
            "The verification message is unavailable.",
            category=ErrorCategory.AUTH,
            status_code=404,
        )
    return response_envelope(
        request,
        {
            "challenge_id": str(message.challenge_id),
            "code": message.code,
            "delivery_hint": message.delivery_hint,
            "expires_at": message.expires_at.isoformat(),
        },
    )


@public_router.post(
    "/register/email",
    response_model=IdentityApiEnvelopeV1,
    status_code=status.HTTP_201_CREATED,
)
async def register_by_email(
    request: Request,
    body: UserRegisterByEmailCommandV1,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    receipt = await identity_service(request).register_email(
        body,
        idempotency_key=idempotency_key,
        trace_id=request.state.trace_id,
    )
    return response_envelope(request, {"registration": receipt.model_dump(mode="json")})


@public_router.post(
    "/register/phone",
    response_model=IdentityApiEnvelopeV1,
    status_code=status.HTTP_201_CREATED,
)
async def register_by_phone(
    request: Request,
    body: UserRegisterByPhoneCommandV1,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    receipt = await identity_service(request).register_phone(
        body,
        idempotency_key=idempotency_key,
        trace_id=request.state.trace_id,
    )
    return response_envelope(request, {"registration": receipt.model_dump(mode="json")})


@account_router.get(
    "/me",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_PROFILE_READ))],
)
async def get_profile(request: Request) -> IdentityApiEnvelopeV1:
    profile = await identity_service(request).get_profile()
    return response_envelope(request, {"profile": profile.model_dump(mode="json")})


@account_router.patch(
    "/me",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_PROFILE_WRITE))],
)
async def update_profile(
    request: Request,
    body: ProfileUpdateRequest,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    profile = await identity_service(request).update_profile(
        display_name=body.display_name,
        preferred_locale=body.preferred_locale,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return response_envelope(request, {"profile": profile.model_dump(mode="json")})


@account_router.post(
    "/me/verification-challenges",
    response_model=IdentityApiEnvelopeV1,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_CONTACT_WRITE))],
)
async def request_contact_challenge(
    request: Request,
    body: VerificationChallengeRequestV1,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    if (
        body.purpose
        not in {
            IdentityChallengePurpose.CHANGE_EMAIL,
            IdentityChallengePurpose.CHANGE_PHONE,
        }
        or body.invitation_token is not None
    ):
        raise LiyanError(
            ErrorCode.CONTRACT_INVALID,
            "The authenticated contact challenge purpose is invalid.",
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )
    receipt = await identity_service(request).request_challenge(
        body,
        idempotency_key=idempotency_key,
        trace_id=request.state.trace_id,
        client_ip=request_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        context=current_tenant(),
    )
    return response_envelope(request, {"challenge": receipt.model_dump(mode="json")})


@account_router.post(
    "/me/verification-challenges/verify",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_CONTACT_WRITE))],
)
async def verify_contact_challenge(
    request: Request,
    body: VerificationChallengeVerifyV1,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    if body.invitation_token is not None:
        raise LiyanError(
            ErrorCode.CONTRACT_INVALID,
            "Authenticated verification cannot include an invitation.",
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )
    receipt = await identity_service(request).verify_challenge(
        body,
        idempotency_key=idempotency_key,
        invitation_token=None,
        trace_id=request.state.trace_id,
        context=current_tenant(),
    )
    return response_envelope(request, {"challenge": receipt.model_dump(mode="json")})


@account_router.post(
    "/me/contact",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_CONTACT_WRITE))],
)
async def change_contact(
    request: Request,
    body: ContactChangeRequest,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    profile = await identity_service(request).change_contact(
        channel=ContactChannel(body.channel.value),
        identifier=body.identifier,
        challenge_id=body.challenge_id,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return response_envelope(request, {"profile": profile.model_dump(mode="json")})


@tenant_account_router.get(
    "",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_ADMIN_READ))],
)
async def list_tenant_accounts(
    request: Request,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> IdentityApiEnvelopeV1:
    accounts = await identity_service(request).list_accounts(offset=offset, limit=limit)
    return response_envelope(
        request,
        {"accounts": [account.model_dump(mode="json") for account in accounts]},
    )


@tenant_account_router.get(
    "/{account_id}/audit",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_ADMIN_READ))],
)
async def list_tenant_account_audit(
    request: Request,
    account_id: UUID,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> IdentityApiEnvelopeV1:
    entries = await identity_service(request).list_account_audit(
        account_id,
        offset=offset,
        limit=limit,
    )
    return response_envelope(
        request,
        {"audit_entries": [entry.model_dump(mode="json") for entry in entries]},
    )


@tenant_account_router.get(
    "/{account_id}",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_ADMIN_READ))],
)
async def get_tenant_account(request: Request, account_id: UUID) -> IdentityApiEnvelopeV1:
    account = await identity_service(request).get_account(account_id)
    return response_envelope(request, {"account": account.model_dump(mode="json")})


@tenant_account_router.post(
    "/{account_id}/disable",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_ADMIN_WRITE))],
)
async def disable_tenant_account(
    request: Request,
    account_id: UUID,
    body: AccountStatusRequest,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    account = await identity_service(request).set_account_enabled(
        account_id,
        enabled=False,
        reason_code=body.reason_code,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return response_envelope(request, {"account": account.model_dump(mode="json")})


@tenant_account_router.post(
    "/{account_id}/restore",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_ADMIN_WRITE))],
)
async def restore_tenant_account(
    request: Request,
    account_id: UUID,
    body: AccountStatusRequest,
    idempotency_key: IdempotencyKey,
) -> IdentityApiEnvelopeV1:
    account = await identity_service(request).set_account_enabled(
        account_id,
        enabled=True,
        reason_code=None,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return response_envelope(request, {"account": account.model_dump(mode="json")})


@tenant_registration_router.get(
    "/{registration_id}",
    response_model=IdentityApiEnvelopeV1,
    dependencies=[Depends(require_scopes(IDENTITY_SCOPE_ADMIN_READ))],
)
async def get_tenant_registration_status(
    request: Request,
    registration_id: UUID,
) -> IdentityApiEnvelopeV1:
    registration = await identity_service(request).get_registration_status(registration_id)
    return response_envelope(
        request,
        {"registration": registration.model_dump(mode="json")},
    )
