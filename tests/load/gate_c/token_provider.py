from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any

import requests

from gate_c.config import Credential


@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str
    expires_at_monotonic: float
    acquisition_ms: float
    claims: dict[str, Any]
    from_cache: bool = False
    refreshed: bool = False


def decode_unverified_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Keycloak access token is not a JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    value = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    if not isinstance(value, dict):
        raise ValueError("Keycloak JWT payload must be an object")
    return value


class TokenProvider:
    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        refresh_skew_seconds: int,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._refresh_skew_seconds = refresh_skew_seconds
        self._session = requests.Session()
        self._session.trust_env = False
        self._cache: dict[str, AccessToken] = {}
        self._lock = Lock()

    def get(self, credential: Credential, *, force_refresh: bool = False) -> AccessToken:
        now = time.monotonic()
        cached = self._cache.get(credential.username)
        if (
            not force_refresh
            and cached is not None
            and cached.expires_at_monotonic - self._refresh_skew_seconds > now
        ):
            return replace(cached, acquisition_ms=0.0, from_cache=True, refreshed=False)
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(credential.username)
            if (
                not force_refresh
                and cached is not None
                and cached.expires_at_monotonic - self._refresh_skew_seconds > now
            ):
                return replace(cached, acquisition_ms=0.0, from_cache=True, refreshed=False)
            refreshed = cached is not None
            started = time.perf_counter()
            response = self._session.post(
                self._token_url,
                data={
                    "grant_type": "password",
                    "client_id": self._client_id,
                    "username": credential.username,
                    "password": credential.password,
                    "scope": "openid profile email",
                },
                timeout=30,
                allow_redirects=False,
            )
            response.raise_for_status()
            document = response.json()
            value = str(document.get("access_token", ""))
            expires_in = int(document.get("expires_in", 0))
            if not value or expires_in <= 0:
                raise RuntimeError("Keycloak token response is incomplete")
            claims = decode_unverified_claims(value)
            if claims.get("tenant_id") != credential.tenant_id:
                raise RuntimeError("Keycloak token tenant claim does not match the credential")
            if claims.get("sub") != credential.subject_ref:
                raise RuntimeError("Keycloak token subject does not match the credential")
            token = AccessToken(
                value=value,
                expires_at_monotonic=time.monotonic() + expires_in,
                acquisition_ms=(time.perf_counter() - started) * 1000,
                claims=claims,
                from_cache=False,
                refreshed=refreshed,
            )
            self._cache[credential.username] = token
            return token
