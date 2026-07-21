from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError


@dataclass(frozen=True, slots=True)
class KeycloakUser:
    user_id: str
    username: str
    email: str | None
    enabled: bool
    attributes: dict[str, tuple[str, ...]]
    display_name: str | None = None
    last_name: str | None = None
    email_verified: bool = False


class KeycloakAdminClient:
    def __init__(
        self,
        *,
        base_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        timeout_seconds: float,
        max_response_bytes: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Keycloak Admin API base URL is invalid")
        if not realm or not client_id or not client_secret:
            raise ValueError("Keycloak Admin API credentials are required")
        if timeout_seconds <= 0 or max_response_bytes < 16_384:
            raise ValueError("Keycloak Admin API limits are invalid")
        self._base_url = base_url.rstrip("/")
        self._realm = quote(realm, safe="")
        self._client_id = client_id
        self._client_secret = client_secret
        self._max_response_bytes = max_response_bytes
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"Accept": "application/json"},
        )
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owned_client:
            await self._client.aclose()

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
        existing = await self.find_by_registration_id(registration_id)
        if existing is not None:
            return existing
        attributes: dict[str, list[str]] = {
            "tenant_id": [tenant_id],
            "permissions": [learner_permissions],
            "registration_id": [str(registration_id)],
            "preferred_locale": [preferred_locale],
            "login_channel": [channel],
        }
        payload: dict[str, Any] = {
            "username": identifier,
            "enabled": True,
            "firstName": display_name,
            "groups": ["/learners"],
            "attributes": attributes,
            "credentials": [
                {
                    "type": "password",
                    "value": password,
                    "temporary": False,
                }
            ],
        }
        if channel == "EMAIL":
            payload["email"] = identifier
            payload["emailVerified"] = True
        else:
            attributes["phone_number"] = [identifier]
        response = await self._admin_request("POST", "/users", json=payload)
        if response.status_code == 409:
            existing = await self.find_by_registration_id(registration_id)
            if existing is not None:
                return existing
            raise LiyanError(
                ErrorCode.IDENTITY_ACCOUNT_CONFLICT,
                "The account registration could not be completed.",
                category=ErrorCategory.AUTH,
                status_code=409,
            )
        self._require_status(response, {201})
        location = response.headers.get("location", "")
        user_id = location.rstrip("/").rsplit("/", 1)[-1]
        if not user_id or len(user_id) > 256:
            created = await self.find_by_registration_id(registration_id)
            if created is None:
                raise self._unavailable()
            return created
        return await self.get_user(user_id)

    async def find_by_registration_id(self, registration_id: UUID) -> KeycloakUser | None:
        response = await self._admin_request(
            "GET",
            "/users",
            params={
                "q": f"registration_id:{registration_id}",
                "briefRepresentation": "false",
                "max": "20",
            },
        )
        self._require_status(response, {200})
        document = self._json(response)
        if not isinstance(document, list) or len(document) > 20:
            raise self._unavailable()
        expected = str(registration_id)
        for raw_user in document:
            user = self._parse_user(raw_user)
            if expected in user.attributes.get("registration_id", ()):
                return user
        return None

    async def get_user(self, user_id: str) -> KeycloakUser:
        response = await self._admin_request("GET", f"/users/{quote(user_id, safe='')}")
        if response.status_code == 404:
            raise LiyanError(
                ErrorCode.IDENTITY_ACCOUNT_NOT_FOUND,
                "The account does not exist.",
                category=ErrorCategory.AUTH,
                status_code=404,
            )
        self._require_status(response, {200})
        return self._parse_user(self._json(response))

    async def update_profile(
        self,
        user_id: str,
        *,
        display_name: str,
        preferred_locale: str,
        current_user: KeycloakUser | None = None,
    ) -> None:
        user = current_user or await self.get_user(user_id)
        attributes = {key: list(values) for key, values in user.attributes.items()}
        attributes["preferred_locale"] = [preferred_locale]
        payload = self._user_update_document(user)
        payload["firstName"] = display_name
        payload["attributes"] = attributes
        response = await self._admin_request(
            "PUT",
            f"/users/{quote(user_id, safe='')}",
            json=payload,
        )
        self._require_status(response, {204})

    async def update_contact(
        self,
        user_id: str,
        *,
        channel: str,
        identifier: str,
        current_user: KeycloakUser | None = None,
    ) -> None:
        user = current_user or await self.get_user(user_id)
        attributes = {key: list(values) for key, values in user.attributes.items()}
        login_channel = next(iter(attributes.get("login_channel", ())), None)
        payload = self._user_update_document(user)
        payload["username"] = identifier if login_channel == channel else user.username
        payload["attributes"] = attributes
        if channel == "EMAIL":
            payload["email"] = identifier
            payload["emailVerified"] = True
        else:
            attributes["phone_number"] = [identifier]
        response = await self._admin_request(
            "PUT",
            f"/users/{quote(user_id, safe='')}",
            json=payload,
        )
        self._require_status(response, {204})

    async def set_enabled(
        self,
        user_id: str,
        *,
        enabled: bool,
        current_user: KeycloakUser | None = None,
    ) -> None:
        user = current_user or await self.get_user(user_id)
        payload = self._user_update_document(user)
        payload["enabled"] = enabled
        response = await self._admin_request(
            "PUT",
            f"/users/{quote(user_id, safe='')}",
            json=payload,
        )
        self._require_status(response, {204})

    async def restore_user(self, user: KeycloakUser) -> None:
        response = await self._admin_request(
            "PUT",
            f"/users/{quote(user.user_id, safe='')}",
            json=self._user_update_document(user),
        )
        self._require_status(response, {204})

    async def delete_user(self, user_id: str) -> None:
        response = await self._admin_request("DELETE", f"/users/{quote(user_id, safe='')}")
        self._require_status(response, {204, 404})

    async def _admin_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._access_token()
        response = await self._request(
            method,
            f"{self._base_url}/admin/realms/{self._realm}{path}",
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
        if response.status_code == 401:
            self._token = None
            self._token_expires_at = 0.0
            token = await self._access_token()
            response = await self._request(
                method,
                f"{self._base_url}/admin/realms/{self._realm}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
        return response

    async def _access_token(self) -> str:
        if self._token is not None and monotonic() < self._token_expires_at:
            return self._token
        async with self._token_lock:
            if self._token is not None and monotonic() < self._token_expires_at:
                return self._token
            response = await self._request(
                "POST",
                f"{self._base_url}/realms/{self._realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            self._require_status(response, {200})
            document = self._json(response)
            token = document.get("access_token") if isinstance(document, dict) else None
            expires_in = document.get("expires_in") if isinstance(document, dict) else None
            if (
                not isinstance(token, str)
                or not 32 <= len(token) <= 16_384
                or not isinstance(expires_in, int)
                or not 1 <= expires_in <= 86_400
            ):
                raise self._unavailable()
            self._token = token
            self._token_expires_at = monotonic() + max(1, expires_in - 30)
            return token

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise self._unavailable() from exc
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_response_bytes:
                    raise self._unavailable()
            except ValueError as exc:
                raise self._unavailable() from exc
        if len(response.content) > self._max_response_bytes:
            raise self._unavailable()
        return response

    def _json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise self._unavailable() from exc

    def _parse_user(self, value: Any) -> KeycloakUser:
        if not isinstance(value, dict):
            raise self._unavailable()
        user_id = value.get("id")
        username = value.get("username")
        email = value.get("email")
        display_name = value.get("firstName")
        last_name = value.get("lastName")
        email_verified = value.get("emailVerified", False)
        enabled = value.get("enabled")
        raw_attributes = value.get("attributes", {})
        if (
            not isinstance(user_id, str)
            or not 1 <= len(user_id) <= 256
            or not isinstance(username, str)
            or not 1 <= len(username) <= 320
            or (email is not None and not isinstance(email, str))
            or (isinstance(email, str) and len(email) > 320)
            or (display_name is not None and not isinstance(display_name, str))
            or (isinstance(display_name, str) and len(display_name) > 255)
            or (last_name is not None and not isinstance(last_name, str))
            or (isinstance(last_name, str) and len(last_name) > 255)
            or not isinstance(email_verified, bool)
            or not isinstance(enabled, bool)
            or not isinstance(raw_attributes, dict)
        ):
            raise self._unavailable()
        attributes: dict[str, tuple[str, ...]] = {}
        for key, raw_values in raw_attributes.items():
            if (
                not isinstance(key, str)
                or not 1 <= len(key) <= 255
                or not isinstance(raw_values, list)
                or not all(isinstance(item, str) for item in raw_values)
                or len(raw_values) > 32
                or any(len(item) > 4096 for item in raw_values)
            ):
                raise self._unavailable()
            attributes[key] = tuple(raw_values)
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

    @staticmethod
    def _user_update_document(user: KeycloakUser) -> dict[str, Any]:
        document: dict[str, Any] = {
            "username": user.username,
            "email": user.email,
            "emailVerified": user.email_verified,
            "enabled": user.enabled,
            "attributes": {key: list(values) for key, values in user.attributes.items()},
        }
        if user.display_name is not None:
            document["firstName"] = user.display_name
        if user.last_name is not None:
            document["lastName"] = user.last_name
        return document

    def _require_status(self, response: httpx.Response, expected: set[int]) -> None:
        if response.status_code in expected:
            return
        if response.status_code in {400, 403, 404, 409, 422}:
            raise LiyanError(
                ErrorCode.IDENTITY_ACCOUNT_CONFLICT,
                "The identity provider rejected the account operation.",
                category=ErrorCategory.AUTH,
                status_code=409,
            )
        raise self._unavailable()

    @staticmethod
    def _unavailable() -> LiyanError:
        return LiyanError(
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
            "The identity provider is temporarily unavailable.",
            category=ErrorCategory.AUTH,
            retriable=True,
            status_code=503,
        )
