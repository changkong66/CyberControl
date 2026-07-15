from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from liyans_contracts.providers import LiteToolDefinitionV1, ResponsesLiteRequestV1

from liyans.core.errors import ErrorCode, LiyanError
from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.core.settings import Settings
from liyans.providers.topic3 import (
    ApprovedHTTPProvider,
    Topic3ProviderRegistry,
    build_topic3_provider_registry,
)

ROOT = Path(__file__).resolve().parents[2]


def request(alias: str = "spark_text") -> ResponsesLiteRequestV1:
    return ResponsesLiteRequestV1(
        schema_version="responses.lite.request.v1",
        request_id=uuid4(),
        provider_alias=alias,
        model_alias="approved-model",
        instructions=[{"stage": "contract", "instruction": "Return JSON."}],
        tools=[
            LiteToolDefinitionV1(
                name="submit_result",
                description="Submit the result.",
                input_schema={"type": "object"},
            )
        ],
        input_segments=[{"segment_type": "test", "value": 1}],
        response_schema={"type": "object"},
        temperature=0.1,
        max_output_tokens=256,
        timeout_ms=5000,
    )


@pytest.mark.asyncio
async def test_approved_http_provider_translates_responses_lite() -> None:
    observed: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        observed["authorization"] = http_request.headers["authorization"]
        observed["request_id"] = http_request.headers["x-liyan-request-id"]
        observed["body"] = json.loads(http_request.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "provider-request-1"},
            json={
                "structured_output": {"title": "result"},
                "usage": {"input_tokens": 11, "output_tokens": 17},
            },
        )

    provider = ApprovedHTTPProvider(
        alias="spark_text",
        endpoint="https://provider.test/responses",
        api_key="test-secret",
        model_alias="spark-approved",
        timeout_seconds=5,
        max_connections=4,
        transport=httpx.MockTransport(handler),
    )
    provider_request = request()
    result = await provider.execute(provider_request)
    await provider.close()

    assert observed["authorization"] == "Bearer test-secret"
    assert observed["request_id"] == str(provider_request.request_id)
    assert observed["body"]["instructions"]
    assert observed["body"]["tools"]
    assert result.request_id == "provider-request-1"
    assert result.structured_output == {"title": "result"}
    assert result.input_tokens == 11
    assert result.output_tokens == 17
    assert len(result.response_sha256) == 64


@pytest.mark.asyncio
async def test_provider_fails_closed_on_alias_network_and_response_errors() -> None:
    success_transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"structured_output": {}})
    )
    provider = ApprovedHTTPProvider(
        alias="spark_text",
        endpoint="https://provider.test/responses",
        api_key="test-secret",
        model_alias="spark-approved",
        timeout_seconds=5,
        max_connections=2,
        transport=success_transport,
    )
    with pytest.raises(LiyanError) as alias_error:
        await provider.execute(request("xfyun_code"))
    assert alias_error.value.code == ErrorCode.TOPIC3_PROVIDER_UNAVAILABLE
    await provider.close()

    malformed = ApprovedHTTPProvider(
        alias="spark_text",
        endpoint="https://provider.test/responses",
        api_key="test-secret",
        model_alias="spark-approved",
        timeout_seconds=5,
        max_connections=2,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"output": []})),
    )
    with pytest.raises(LiyanError, match="structured_output"):
        await malformed.execute(request())
    await malformed.close()

    def network_failure(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    unavailable = ApprovedHTTPProvider(
        alias="spark_text",
        endpoint="https://provider.test/responses",
        api_key="test-secret",
        model_alias="spark-approved",
        timeout_seconds=5,
        max_connections=2,
        transport=httpx.MockTransport(network_failure),
    )
    with pytest.raises(LiyanError) as network_error:
        await unavailable.execute(request())
    assert network_error.value.retriable is True
    await unavailable.close()


@pytest.mark.asyncio
async def test_registry_and_settings_only_build_configured_allowlisted_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = ProviderPolicyRegistry.load(ROOT / "config" / "providers.toml")
    empty = build_topic3_provider_registry(Settings(), policy)
    with pytest.raises(LiyanError) as unavailable:
        empty.require("spark_text")
    assert unavailable.value.code == ErrorCode.TOPIC3_PROVIDER_UNAVAILABLE
    await empty.close()

    configured = build_topic3_provider_registry(
        Settings(
            provider_external_enabled=True,
            spark_text_endpoint="https://provider.test/responses",
            spark_text_api_key="secret",
            spark_text_model_alias="spark-approved",
        ),
        policy,
    )
    assert configured.require("spark_text").model_alias == "spark-approved"
    configured.update_policy(policy)
    await configured.close()

    with pytest.raises(ValueError, match="endpoint and API key"):
        Settings(spark_text_endpoint="https://provider.test/responses")
    with pytest.raises(ValueError, match="unknown approved provider"):
        Settings().provider_credentials("other")
    with pytest.raises(ValueError, match="unapproved"):
        Topic3ProviderRegistry(policy, {"other": object()})

    production = {
        "environment": "production",
        "oidc_issuer": "https://issuer.test",
        "oidc_audience": "liyans",
        "oidc_jwks_url": "https://issuer.test/.well-known/jwks.json",
        "sse_cursor_secret": "topic3-production-cursor-secret-0001",
        "provider_external_enabled": True,
        "spark_text_endpoint": "https://spark.test/responses",
        "spark_text_api_key": "spark-secret",
        "xfyun_code_endpoint": "https://code.test/responses",
        "xfyun_code_api_key": "code-secret",
    }
    monkeypatch.setenv("LIYAN_SSE_CURSOR_SECRET", production["sse_cursor_secret"])
    with pytest.raises(ValueError, match="durable Outbox publisher"):
        Settings(**production)
    with pytest.raises(ValueError, match="PostgreSQL SSE notifications"):
        Settings(
            **production,
            outbox_publisher_enabled=True,
            outbox_dispatcher_database_url=(
                "postgresql+asyncpg://dispatcher:secret@database.test/liyans"
            ),
        )
