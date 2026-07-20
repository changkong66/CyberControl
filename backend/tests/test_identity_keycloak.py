from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest

from liyans.core.errors import ErrorCode, LiyanError
from liyans.domains.identity.keycloak import KeycloakAdminClient

BASE_URL = "https://identity.example.test"
REALM = "cybercontrol"
CLIENT_ID = "registration-admin"
CLIENT_SECRET = "test-client-secret"
TOKEN = "t" * 32


def _client(transport: httpx.BaseTransport) -> tuple[KeycloakAdminClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=transport)
    return (
        KeycloakAdminClient(
            base_url=BASE_URL,
            realm=REALM,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            timeout_seconds=1,
            max_response_bytes=16_384,
            client=http_client,
        ),
        http_client,
    )


def _token_response(token: str = TOKEN) -> httpx.Response:
    return httpx.Response(200, json={"access_token": token, "expires_in": 60})


def _user_document(*, registration_id: str | None = None) -> dict[str, object]:
    attributes: dict[str, list[str]] = {
        "tenant_id": ["tenant-a"],
        "login_channel": ["EMAIL"],
    }
    if registration_id is not None:
        attributes["registration_id"] = [registration_id]
    return {
        "id": "user-123",
        "username": "learner@example.test",
        "email": "learner@example.test",
        "emailVerified": True,
        "firstName": "Identity Learner",
        "lastName": "Example",
        "enabled": True,
        "attributes": attributes,
    }


def test_keycloak_client_rejects_unsafe_configuration() -> None:
    common = {
        "realm": REALM,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "timeout_seconds": 1,
        "max_response_bytes": 16_384,
    }
    with pytest.raises(ValueError):
        KeycloakAdminClient(base_url="file:///tmp/keycloak", **common)
    with pytest.raises(ValueError):
        KeycloakAdminClient(base_url=BASE_URL, **{**common, "client_secret": ""})
    with pytest.raises(ValueError):
        KeycloakAdminClient(base_url=BASE_URL, **{**common, "timeout_seconds": 0})


@pytest.mark.asyncio
async def test_keycloak_client_refreshes_token_once_after_unauthorized() -> None:
    token_calls = 0
    admin_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, admin_calls
        if request.url.path.endswith("/protocol/openid-connect/token"):
            token_calls += 1
            return _token_response(str(token_calls) * 32)
        admin_calls += 1
        if admin_calls == 1:
            assert request.headers["authorization"] == f"Bearer {'1' * 32}"
            return httpx.Response(401)
        assert request.headers["authorization"] == f"Bearer {'2' * 32}"
        return httpx.Response(200, json=[])

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        assert await client.find_by_registration_id(uuid4()) is None
        assert token_calls == 2
        assert admin_calls == 2
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_keycloak_create_maps_conflict_and_recovers_missing_location() -> None:
    registration_id = uuid4()
    mode = "conflict"
    find_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal find_calls
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return _token_response()
        if request.method == "GET" and request.url.path.endswith("/users"):
            find_calls += 1
            if mode == "recover" and find_calls == 2:
                return httpx.Response(
                    200,
                    json=[_user_document(registration_id=str(registration_id))],
                )
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.path.endswith("/users"):
            return httpx.Response(409 if mode == "conflict" else 201)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(LiyanError) as raised:
            await client.create_learner(
                registration_id=registration_id,
                tenant_id="tenant-a",
                channel="EMAIL",
                identifier="learner@example.test",
                password="Password123",
                display_name="Learner",
                preferred_locale="zh-CN",
                learner_permissions="topic1:read",
            )
        assert raised.value.code == ErrorCode.IDENTITY_ACCOUNT_CONFLICT

        mode = "recover"
        find_calls = 0
        recovered = await client.create_learner(
            registration_id=registration_id,
            tenant_id="tenant-a",
            channel="PHONE",
            identifier="+14155550123",
            password="Password123",
            display_name="Learner",
            preferred_locale="en-US",
            learner_permissions="topic1:read",
        )
        assert recovered.user_id == "user-123"
        assert recovered.display_name == "Identity Learner"
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_keycloak_profile_contact_status_and_delete_requests() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return _token_response()
        if request.method == "GET":
            return httpx.Response(200, json=_user_document())
        if request.method == "PUT":
            payloads.append(httpx.Response(200, content=request.content).json())
            return httpx.Response(204)
        if request.method == "DELETE":
            return httpx.Response(404)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        await client.update_profile("user-123", display_name="Updated", preferred_locale="zh-TW")
        await client.update_contact("user-123", channel="EMAIL", identifier="updated@example.test")
        await client.update_contact("user-123", channel="PHONE", identifier="+14155550999")
        await client.set_enabled("user-123", enabled=False)
        await client.restore_user(await client.get_user("user-123"))
        await client.delete_user("user-123")
    finally:
        await http_client.aclose()

    assert payloads[0]["firstName"] == "Updated"
    assert payloads[1]["email"] == "updated@example.test"
    assert payloads[1]["emailVerified"] is True
    assert payloads[2]["attributes"]["phone_number"] == ["+14155550999"]
    assert payloads[3]["enabled"] is False
    assert payloads[4]["emailVerified"] is True
    assert payloads[4]["lastName"] == "Example"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_factory", "expected_code"),
    [
        (lambda: httpx.Response(404), ErrorCode.IDENTITY_ACCOUNT_NOT_FOUND),
        (lambda: httpx.Response(403), ErrorCode.IDENTITY_ACCOUNT_CONFLICT),
        (lambda: httpx.Response(500), ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE),
        (
            lambda: httpx.Response(200, content=b"not-json"),
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
        ),
        (
            lambda: httpx.Response(200, content=b"{}", headers={"content-length": "20000"}),
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
        ),
        (
            lambda: httpx.Response(200, content=b"{}", headers={"content-length": "invalid"}),
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
        ),
        (
            lambda: httpx.Response(200, content=b"x" * 16_385),
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
        ),
        (
            lambda: httpx.Response(200, json={"id": "missing-required-fields"}),
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
        ),
        (
            lambda: httpx.Response(
                200,
                json={**_user_document(), "email": "x" * 321},
            ),
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
        ),
        (
            lambda: httpx.Response(
                200,
                json={**_user_document(), "attributes": {"x" * 256: ["value"]}},
            ),
            ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE,
        ),
    ],
)
async def test_keycloak_client_fails_closed_for_invalid_provider_responses(
    response_factory: Callable[[], httpx.Response],
    expected_code: ErrorCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return _token_response()
        return response_factory()

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(LiyanError) as raised:
            await client.get_user("user-123")
        assert raised.value.code == expected_code
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_keycloak_client_maps_transport_and_token_document_failures() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout", request=request)

    client, http_client = _client(httpx.MockTransport(timeout_handler))
    try:
        with pytest.raises(LiyanError) as timeout:
            await client.find_by_registration_id(uuid4())
        assert timeout.value.code == ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE
    finally:
        await http_client.aclose()

    def malformed_token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "short", "expires_in": 0})

    client, http_client = _client(httpx.MockTransport(malformed_token_handler))
    try:
        with pytest.raises(LiyanError) as malformed:
            await client.find_by_registration_id(uuid4())
        assert malformed.value.code == ErrorCode.IDENTITY_REGISTRATION_UNAVAILABLE
    finally:
        await http_client.aclose()
