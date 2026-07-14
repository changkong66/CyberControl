from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.settings import Settings
from liyans.infrastructure.security import OIDCTokenVerifier

ISSUER = "https://issuer.test"
AUDIENCE = "liyans-api"
JWKS_URL = "https://issuer.test/.well-known/jwks.json"


def encode_uint(value: int) -> str:
    payload = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="module")
def rsa_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "test-key-1",
        "use": "sig",
        "alg": "RS256",
        "key_ops": ["verify"],
        "n": encode_uint(numbers.n),
        "e": encode_uint(numbers.e),
    }
    return private_key, jwk


def make_token(private_key, **claim_updates) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "subject-123",
        "tenant_id": "tenant-a",
        "roles": ["student"],
        "scope": "topic3:validate topic3:sse:read",
        "scp": ["profile:read"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "jti": "token-123",
    }
    claims.update(claim_updates)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1", "typ": "at+jwt"},
    )


@pytest.mark.asyncio
async def test_oidc_verifier_validates_signature_claims_and_caches_jwks(rsa_material) -> None:
    private_key, jwk = rsa_material
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert str(request.url) == JWKS_URL
        return httpx.Response(200, json={"keys": [jwk]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = OIDCTokenVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url=JWKS_URL,
            client=client,
        )
        await verifier.initialize()
        token = make_token(private_key)
        first = await verifier.verify(token)
        second = await verifier.verify(token)

    assert first == second
    assert first.tenant_id == "tenant-a"
    assert first.subject == "subject-123"
    assert first.roles == frozenset({"student"})
    assert first.scopes == frozenset({"topic3:validate", "topic3:sse:read", "profile:read"})
    assert requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_updates", "expected_code"),
    [
        ({"aud": "wrong-audience"}, ErrorCode.AUTH_TOKEN_INVALID),
        ({"iss": "https://attacker.invalid"}, ErrorCode.AUTH_TOKEN_INVALID),
        (
            {"exp": int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())},
            ErrorCode.AUTH_TOKEN_INVALID,
        ),
        (
            {"exp": int((datetime.now(UTC) + timedelta(hours=2)).timestamp())},
            ErrorCode.AUTH_TOKEN_INVALID,
        ),
        ({"tenant_id": "tenant with spaces"}, ErrorCode.AUTH_TOKEN_INVALID),
    ],
)
async def test_oidc_verifier_rejects_invalid_claims(
    rsa_material,
    claim_updates,
    expected_code,
) -> None:
    private_key, jwk = rsa_material

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [jwk]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = OIDCTokenVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url=JWKS_URL,
            client=client,
        )
        with pytest.raises(LiyanError) as raised:
            await verifier.verify(make_token(private_key, **claim_updates))
    assert raised.value.code == expected_code


@pytest.mark.asyncio
async def test_oidc_verifier_rejects_token_controlled_key_urls(rsa_material) -> None:
    private_key, jwk = rsa_material
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"keys": [jwk]})

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "subject-123",
            "tenant_id": "tenant-a",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        private_key,
        algorithm="RS256",
        headers={
            "kid": "test-key-1",
            "typ": "at+jwt",
            "jku": "https://attacker.invalid/jwks.json",
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = OIDCTokenVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url=JWKS_URL,
            client=client,
        )
        with pytest.raises(LiyanError) as raised:
            await verifier.verify(token)

    assert raised.value.code == ErrorCode.AUTH_TOKEN_INVALID
    assert requests == 0


@pytest.mark.asyncio
async def test_oidc_verifier_refreshes_jwks_for_a_rotated_key(rsa_material) -> None:
    first_private_key, first_jwk = rsa_material
    second_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second_numbers = second_private_key.public_key().public_numbers()
    second_jwk = {
        "kty": "RSA",
        "kid": "test-key-2",
        "use": "sig",
        "alg": "RS256",
        "key_ops": ["verify"],
        "n": encode_uint(second_numbers.n),
        "e": encode_uint(second_numbers.e),
    }
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        keys = [first_jwk] if requests == 1 else [first_jwk, second_jwk]
        return httpx.Response(200, json={"keys": keys})

    now = datetime.now(UTC)
    second_token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "subject-456",
            "tenant_id": "tenant-a",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        second_private_key,
        algorithm="RS256",
        headers={"kid": "test-key-2", "typ": "at+jwt"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = OIDCTokenVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url=JWKS_URL,
            client=client,
        )
        await verifier.verify(make_token(first_private_key))
        principal = await verifier.verify(second_token)

    assert principal.subject == "subject-456"
    assert requests == 2


def test_production_settings_require_oidc_configuration(monkeypatch) -> None:
    monkeypatch.setenv("LIYAN_SSE_CURSOR_SECRET", "x" * 32)
    with pytest.raises(ValidationError, match="production requires OIDC"):
        Settings(environment="production", sse_cursor_secret="x" * 32)


@pytest.mark.asyncio
async def test_oidc_verifier_rejects_symmetric_algorithms_without_jwks_fetch() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "subject-123",
            "tenant_id": "tenant-a",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        "unit-test-only-secret-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": "attacker-key", "typ": "at+jwt"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = OIDCTokenVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url=JWKS_URL,
            client=client,
        )
        with pytest.raises(LiyanError) as raised:
            await verifier.verify(token)

    assert raised.value.code == ErrorCode.AUTH_TOKEN_INVALID
    assert requests == 0


@pytest.mark.asyncio
async def test_oidc_jwks_warmup_fails_closed_when_provider_is_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injected outage")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = OIDCTokenVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url=JWKS_URL,
            client=client,
        )
        with pytest.raises(LiyanError) as raised:
            await verifier.initialize()

    assert raised.value.code == ErrorCode.AUTH_CONFIG_INVALID
    assert raised.value.status_code == 503
