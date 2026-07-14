from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Protocol

import httpx
import jwt
from jwt import PyJWK
from jwt.exceptions import InvalidTokenError

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.settings import Settings

TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
AUTHORITY_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
AUTHORIZATION_VALUE_MAX_BYTES = 16_384
JWKS_DOCUMENT_MAX_BYTES = 1_048_576
JWKS_KEY_LIMIT = 100
ALLOWED_ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384"})


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    issuer: str
    subject: str
    tenant_id: str
    roles: frozenset[str]
    scopes: frozenset[str]
    token_id: str | None
    issued_at: datetime
    expires_at: datetime


class TokenVerifier(Protocol):
    async def initialize(self) -> None: ...

    async def verify(self, token: str) -> AuthenticatedPrincipal: ...

    async def close(self) -> None: ...


class RejectingTokenVerifier:
    async def initialize(self) -> None:
        return None

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        del token
        raise LiyanError(
            ErrorCode.AUTH_CONFIG_INVALID,
            "OIDC authentication is not configured.",
            category=ErrorCategory.AUTH,
            retriable=True,
            status_code=503,
        )

    async def close(self) -> None:
        return None


class OIDCTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        algorithms: tuple[str, ...] = ("RS256",),
        tenant_claim: str = "tenant_id",
        roles_claim: str = "roles",
        scope_claim: str = "scope",
        clock_skew_seconds: float = 30,
        max_token_lifetime_seconds: float = 3600,
        cache_ttl_seconds: float = 300,
        http_timeout_seconds: float = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not issuer or not audience or not jwks_url:
            raise ValueError("issuer, audience, and jwks_url are required")
        if not algorithms or not set(algorithms) <= ALLOWED_ASYMMETRIC_ALGORITHMS:
            raise ValueError("only approved asymmetric JWT algorithms are supported")
        if (
            min(
                clock_skew_seconds,
                max_token_lifetime_seconds,
                cache_ttl_seconds,
                http_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("OIDC timing settings must be positive")
        self._issuer = issuer
        self._audience = audience
        self._jwks_url = jwks_url
        self._algorithms = frozenset(algorithms)
        self._tenant_claim = tenant_claim
        self._roles_claim = roles_claim
        self._scope_claim = scope_claim
        self._clock_skew_seconds = clock_skew_seconds
        self._max_token_lifetime_seconds = max_token_lifetime_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._client_owned = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(http_timeout_seconds),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"Accept": "application/json"},
        )
        self._keys: dict[str, dict[str, Any]] = {}
        self._cache_expires_at = 0.0
        self._refresh_lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._refresh_lock:
            await self._refresh_keys()

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        if not token or len(token.encode("utf-8")) > AUTHORIZATION_VALUE_MAX_BYTES:
            raise self._invalid_token()
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise self._invalid_token() from exc
        algorithm = header.get("alg")
        key_id = header.get("kid")
        token_type = header.get("typ")
        if (
            not isinstance(algorithm, str)
            or algorithm not in self._algorithms
            or not isinstance(key_id, str)
            or not key_id
            or len(key_id) > 256
            or "jku" in header
            or "x5u" in header
            or (token_type is not None and token_type not in {"JWT", "at+jwt"})
        ):
            raise self._invalid_token()

        raw_jwk = await self._key_document(key_id)
        declared_algorithm = raw_jwk.get("alg")
        if declared_algorithm is not None and declared_algorithm != algorithm:
            raise self._invalid_token()
        try:
            signing_key = PyJWK.from_dict(raw_jwk, algorithm=algorithm).key
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew_seconds,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "iss",
                        "aud",
                        "sub",
                        self._tenant_claim,
                    ],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except (InvalidTokenError, ValueError, TypeError) as exc:
            raise self._invalid_token() from exc
        return self._principal_from_claims(claims)

    async def close(self) -> None:
        if self._client_owned:
            await self._client.aclose()

    async def _key_document(self, key_id: str) -> dict[str, Any]:
        now = monotonic()
        if now < self._cache_expires_at and key_id in self._keys:
            return self._keys[key_id]
        async with self._refresh_lock:
            now = monotonic()
            if now < self._cache_expires_at and key_id in self._keys:
                return self._keys[key_id]
            await self._refresh_keys()
            key = self._keys.get(key_id)
            if key is None:
                raise self._invalid_token()
            return key

    async def _refresh_keys(self) -> None:
        try:
            response = await self._client.get(self._jwks_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LiyanError(
                ErrorCode.AUTH_CONFIG_INVALID,
                "The OIDC signing key service is unavailable.",
                category=ErrorCategory.AUTH,
                retriable=True,
                status_code=503,
            ) from exc
        if len(response.content) > JWKS_DOCUMENT_MAX_BYTES:
            raise self._jwks_invalid()
        try:
            document = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise self._jwks_invalid() from exc
        keys = document.get("keys") if isinstance(document, dict) else None
        if not isinstance(keys, list) or not 1 <= len(keys) <= JWKS_KEY_LIMIT:
            raise self._jwks_invalid()
        parsed: dict[str, dict[str, Any]] = {}
        seen_key_ids: set[str] = set()
        for raw_key in keys:
            key_id, usable_key = self._parse_jwks_key(raw_key)
            if key_id in seen_key_ids:
                raise self._jwks_invalid()
            seen_key_ids.add(key_id)
            if usable_key is not None:
                parsed[key_id] = usable_key
        if not parsed:
            raise self._jwks_invalid()
        self._keys = parsed
        self._cache_expires_at = monotonic() + self._cache_ttl_seconds

    def _parse_jwks_key(
        self,
        raw_key: Any,
    ) -> tuple[str, dict[str, Any] | None]:
        if not isinstance(raw_key, dict):
            raise self._jwks_invalid()
        key_id = raw_key.get("kid")
        key_type = raw_key.get("kty")
        key_use = raw_key.get("use")
        key_ops = raw_key.get("key_ops")
        declared_algorithm = raw_key.get("alg")
        if (
            not isinstance(key_id, str)
            or not key_id
            or len(key_id) > 256
            or key_type not in {"RSA", "EC"}
            or (key_ops is not None and not isinstance(key_ops, list))
            or (
                isinstance(key_ops, list)
                and not all(isinstance(operation, str) for operation in key_ops)
            )
            or (declared_algorithm is not None and not isinstance(declared_algorithm, str))
        ):
            raise self._jwks_invalid()
        if key_use not in {None, "sig"}:
            return key_id, None
        if isinstance(key_ops, list) and "verify" not in key_ops:
            return key_id, None
        if declared_algorithm is not None and declared_algorithm not in self._algorithms:
            return key_id, None
        compatible = (
            key_type == "RSA" and any(algorithm.startswith("RS") for algorithm in self._algorithms)
        ) or (
            key_type == "EC" and any(algorithm.startswith("ES") for algorithm in self._algorithms)
        )
        return key_id, dict(raw_key) if compatible else None

    def _principal_from_claims(self, claims: dict[str, Any]) -> AuthenticatedPrincipal:
        subject = claims.get("sub")
        tenant_id = claims.get(self._tenant_claim)
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        token_id = claims.get("jti")
        if (
            not isinstance(subject, str)
            or not 1 <= len(subject) <= 256
            or subject != subject.strip()
            or not subject.isprintable()
            or not isinstance(tenant_id, str)
            or not TENANT_ID_PATTERN.fullmatch(tenant_id)
            or not isinstance(issued_at, int | float)
            or not isinstance(expires_at, int | float)
            or isinstance(issued_at, bool)
            or isinstance(expires_at, bool)
            or expires_at <= issued_at
            or expires_at - issued_at > self._max_token_lifetime_seconds
            or (token_id is not None and not isinstance(token_id, str))
            or (isinstance(token_id, str) and len(token_id) > 256)
        ):
            raise self._invalid_token()
        roles = self._claim_values(claims.get(self._roles_claim), split_spaces=True)
        scopes = self._claim_values(claims.get(self._scope_claim), split_spaces=True)
        scopes |= self._claim_values(claims.get("scp"), split_spaces=True)
        return AuthenticatedPrincipal(
            issuer=self._issuer,
            subject=subject,
            tenant_id=tenant_id,
            roles=frozenset(roles),
            scopes=frozenset(scopes),
            token_id=token_id,
            issued_at=datetime.fromtimestamp(issued_at, UTC),
            expires_at=datetime.fromtimestamp(expires_at, UTC),
        )

    def _claim_values(self, value: Any, *, split_spaces: bool) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            values = value.split() if split_spaces else [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            values = value
        else:
            raise self._invalid_token()
        if len(values) > 128 or any(not AUTHORITY_VALUE_PATTERN.fullmatch(item) for item in values):
            raise self._invalid_token()
        return set(values)

    @staticmethod
    def _invalid_token() -> LiyanError:
        return LiyanError(
            ErrorCode.AUTH_TOKEN_INVALID,
            "The bearer token is invalid or expired.",
            category=ErrorCategory.AUTH,
            status_code=401,
        )

    @staticmethod
    def _jwks_invalid() -> LiyanError:
        return LiyanError(
            ErrorCode.AUTH_CONFIG_INVALID,
            "The OIDC signing key document is invalid.",
            category=ErrorCategory.AUTH,
            status_code=503,
        )


def build_token_verifier(settings: Settings) -> TokenVerifier:
    if not settings.oidc_configured:
        return RejectingTokenVerifier()
    issuer = settings.oidc_issuer
    audience = settings.oidc_audience
    jwks_url = settings.oidc_jwks_url
    if issuer is None or audience is None or jwks_url is None:
        raise LiyanError(
            ErrorCode.AUTH_CONFIG_INVALID,
            "OIDC authentication configuration is incomplete.",
            category=ErrorCategory.AUTH,
            status_code=500,
        )
    return OIDCTokenVerifier(
        issuer=issuer,
        audience=audience,
        jwks_url=jwks_url,
        algorithms=settings.oidc_algorithms,
        tenant_claim=settings.oidc_tenant_claim,
        roles_claim=settings.oidc_roles_claim,
        scope_claim=settings.oidc_scope_claim,
        clock_skew_seconds=settings.oidc_clock_skew_seconds,
        max_token_lifetime_seconds=settings.oidc_max_token_lifetime_seconds,
        cache_ttl_seconds=settings.oidc_jwks_cache_ttl_seconds,
        http_timeout_seconds=settings.oidc_http_timeout_seconds,
    )
