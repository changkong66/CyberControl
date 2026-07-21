from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from liyans_contracts.identity import (
    IdentityChallengePurpose,
    IdentityContactChannel,
    UserRegisterByEmailCommandV1,
    VerificationChallengeRequestV1,
)
from pydantic import ValidationError

from liyans.core.errors import ErrorCode, LiyanError
from liyans.domains.identity.crypto import (
    IdentityCipher,
    keyed_digest,
    mask_email,
    mask_phone,
    normalize_email,
    normalize_phone,
    validate_password,
    verify_registration_invitation,
)


def test_contact_normalization_masking_and_keyed_lookup() -> None:
    assert normalize_email("  Teacher@Example.COM ") == "teacher@example.com"
    assert normalize_phone("+86 138-0013-8000") == "+8613800138000"
    assert mask_email("teacher@example.com").endswith("@example.com")
    assert mask_phone("+8613800138000").endswith("8000")
    assert keyed_digest("same", "a" * 32, purpose="email") != keyed_digest(
        "same", "b" * 32, purpose="email"
    )
    with pytest.raises(LiyanError):
        normalize_email("not-an-email")
    with pytest.raises(LiyanError):
        normalize_phone("13800138000")


def test_identity_cipher_is_tenant_bound_and_detects_tampering() -> None:
    cipher = IdentityCipher("identity-test-secret-which-is-at-least-32-bytes")
    encrypted = cipher.encrypt(
        "teacher@example.com",
        tenant_id="tenant-a",
        field_name="email",
    )
    assert "teacher@example.com" not in encrypted
    assert (
        cipher.decrypt(encrypted, tenant_id="tenant-a", field_name="email") == "teacher@example.com"
    )
    with pytest.raises(LiyanError) as wrong_tenant:
        cipher.decrypt(encrypted, tenant_id="tenant-b", field_name="email")
    assert wrong_tenant.value.code == ErrorCode.IDENTITY_INTEGRITY_FAILED
    version, nonce, payload = encrypted.split(".", 2)
    replacement = "A" if payload[0] != "A" else "B"
    tampered = f"{version}.{nonce}.{replacement}{payload[1:]}"
    with pytest.raises(LiyanError):
        cipher.decrypt(tampered, tenant_id="tenant-a", field_name="email")


def test_signed_invitation_is_required_and_tenant_bound() -> None:
    now = datetime.now(UTC)
    secret = "invitation-test-secret-which-is-at-least-32-bytes"
    token = jwt.encode(
        {
            "iss": "cybercontrol-registration",
            "aud": "cybercontrol-registration",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": str(uuid4()),
            "purpose": "account-registration",
            "tenant_id": "demo-academy",
        },
        secret,
        algorithm="HS256",
    )
    assert (
        verify_registration_invitation(
            token,
            secret=secret,
            issuer="cybercontrol-registration",
            audience="cybercontrol-registration",
        )
        == "demo-academy"
    )
    with pytest.raises(LiyanError) as raised:
        verify_registration_invitation(
            token,
            secret="wrong-secret-which-is-also-at-least-32-bytes",
            issuer="cybercontrol-registration",
            audience="cybercontrol-registration",
        )
    assert raised.value.code == ErrorCode.IDENTITY_INVITATION_INVALID


def test_registration_contract_rejects_identity_authority_fields() -> None:
    challenge = VerificationChallengeRequestV1(
        channel=IdentityContactChannel.EMAIL,
        purpose=IdentityChallengePurpose.REGISTER,
        identifier="learner@example.com",
    )
    assert challenge.identifier == "learner@example.com"
    with pytest.raises(ValidationError):
        VerificationChallengeRequestV1.model_validate(
            {
                **challenge.model_dump(mode="json"),
                "tenant_id": "forged-tenant",
            }
        )
    with pytest.raises(ValidationError):
        UserRegisterByEmailCommandV1(
            challenge_id=uuid4(),
            email="learner@example.com",
            password="password1",
            display_name="Learner",
            preferred_locale="fr-FR",
            consent={
                "privacy_policy_version": "privacy-v1",
                "terms_of_service_version": "terms-v1",
                "privacy_policy_accepted": True,
                "terms_of_service_accepted": True,
            },
        )


def test_password_policy_rejects_weak_values_without_persisting_hashes() -> None:
    validate_password("Secure123")
    with pytest.raises(LiyanError):
        validate_password("abcdefgh")
    with pytest.raises(LiyanError):
        validate_password("12345678")
    with pytest.raises(LiyanError):
        validate_password("Secure 123")
