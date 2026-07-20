from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jwt import InvalidTokenError

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,126}[a-z0-9]$")
VERIFICATION_CODE_PATTERN = re.compile(r"^[0-9]{6}$")


def normalize_email(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if len(normalized.encode("utf-8")) > 320 or not EMAIL_PATTERN.fullmatch(normalized):
        raise identity_contract_error("The email address is invalid.")
    local, domain = normalized.rsplit("@", 1)
    if not local or len(local.encode("utf-8")) > 64 or len(domain) > 255:
        raise identity_contract_error("The email address is invalid.")
    return normalized


def normalize_phone(value: str) -> str:
    normalized = re.sub(r"[\s().-]", "", unicodedata.normalize("NFKC", value))
    if not PHONE_PATTERN.fullmatch(normalized):
        raise identity_contract_error("The phone number must use E.164 format.")
    return normalized


def validate_password(password: str) -> None:
    if (
        not 8 <= len(password) <= 128
        or not any(character.isalpha() for character in password)
        or not any(character.isdigit() for character in password)
        or any(character.isspace() or not character.isprintable() for character in password)
    ):
        raise identity_contract_error(
            "The password must contain 8 to 128 printable characters with letters and digits."
        )


def mask_email(value: str) -> str:
    local, domain = value.rsplit("@", 1)
    visible = local[0] if local else "*"
    return f"{visible}{'*' * min(max(len(local) - 1, 2), 8)}@{domain}"


def mask_phone(value: str) -> str:
    return f"{value[:3]}{'*' * max(4, len(value) - 7)}{value[-4:]}"


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def keyed_digest(value: str, secret: str, *, purpose: str) -> str:
    key = hashlib.sha256(f"cybercontrol:{purpose}:{secret}".encode()).digest()
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def verification_code_digest(challenge_id: UUID, code: str, secret: str) -> str:
    if not VERIFICATION_CODE_PATTERN.fullmatch(code):
        return "0" * 64
    return keyed_digest(f"{challenge_id}:{code}", secret, purpose="verification-code")


def verification_code_matches(
    challenge_id: UUID,
    code: str,
    expected_digest: str,
    secret: str,
) -> bool:
    actual = verification_code_digest(challenge_id, code, secret)
    return hmac.compare_digest(actual, expected_digest)


class IdentityCipher:
    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("identity encryption secret must contain at least 32 bytes")
        self._key = hashlib.sha256(f"cybercontrol:identity:v1:{secret}".encode()).digest()

    def encrypt(self, value: str, *, tenant_id: str, field_name: str) -> str:
        nonce = secrets.token_bytes(12)
        aad = f"identity:v1:{tenant_id}:{field_name}".encode()
        ciphertext = AESGCM(self._key).encrypt(nonce, value.encode("utf-8"), aad)
        return "v1." + _b64(nonce) + "." + _b64(ciphertext)

    def decrypt(self, value: str, *, tenant_id: str, field_name: str) -> str:
        try:
            version, encoded_nonce, encoded_ciphertext = value.split(".", 2)
            if version != "v1":
                raise ValueError("unsupported identity ciphertext version")
            nonce = _unb64(encoded_nonce)
            ciphertext = _unb64(encoded_ciphertext)
            aad = f"identity:v1:{tenant_id}:{field_name}".encode()
            plaintext = AESGCM(self._key).decrypt(nonce, ciphertext, aad)
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise LiyanError(
                ErrorCode.IDENTITY_INTEGRITY_FAILED,
                "The protected account data failed integrity verification.",
                category=ErrorCategory.AUTH,
                status_code=503,
            ) from exc


def verify_registration_invitation(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
) -> str:
    if not 32 <= len(token) <= 4096 or len(secret.encode("utf-8")) < 32:
        raise invitation_error()
    try:
        claims = jwt.decode(
            token,
            key=secret,
            algorithms=["HS256"],
            audience=audience,
            issuer=issuer,
            leeway=30,
            options={
                "require": ["exp", "iat", "iss", "aud", "jti", "tenant_id", "purpose"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise invitation_error() from exc
    tenant_id = claims.get("tenant_id")
    purpose = claims.get("purpose")
    token_id = claims.get("jti")
    if (
        not isinstance(tenant_id, str)
        or not TENANT_ID_PATTERN.fullmatch(tenant_id)
        or purpose != "account-registration"
        or not isinstance(token_id, str)
        or not 1 <= len(token_id) <= 256
    ):
        raise invitation_error()
    return tenant_id


def identity_contract_error(message: str) -> LiyanError:
    return LiyanError(
        ErrorCode.CONTRACT_INVALID,
        message,
        category=ErrorCategory.CONTRACT,
        status_code=422,
    )


def invitation_error() -> LiyanError:
    return LiyanError(
        ErrorCode.IDENTITY_INVITATION_INVALID,
        "The registration invitation is invalid or expired.",
        category=ErrorCategory.AUTH,
        status_code=403,
    )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True, slots=True)
class FixtureInboxMessage:
    challenge_id: UUID
    code: str
    delivery_hint: str
    expires_at: datetime


class VerificationFixtureInbox:
    def __init__(self) -> None:
        self._messages: dict[UUID, FixtureInboxMessage] = {}
        self._lock = asyncio.Lock()

    async def deliver(self, message: FixtureInboxMessage) -> None:
        async with self._lock:
            self._discard_expired(datetime.now(UTC))
            self._messages[message.challenge_id] = message

    async def read(self, challenge_id: UUID) -> FixtureInboxMessage | None:
        async with self._lock:
            now = datetime.now(UTC)
            self._discard_expired(now)
            return self._messages.get(challenge_id)

    async def remove(self, challenge_id: UUID) -> None:
        async with self._lock:
            self._messages.pop(challenge_id, None)

    def _discard_expired(self, now: datetime) -> None:
        expired = [
            challenge_id
            for challenge_id, message in self._messages.items()
            if message.expires_at <= now
        ]
        for challenge_id in expired:
            self._messages.pop(challenge_id, None)
