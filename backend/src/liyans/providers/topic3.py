from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from liyans_contracts.common import canonical_sha256
from liyans_contracts.providers import ResponsesLiteRequestV1

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.core.settings import Settings


@dataclass(frozen=True, slots=True)
class ProviderExecutionResult:
    request_id: str
    structured_output: dict[str, Any]
    input_tokens: int | None
    output_tokens: int | None
    started_at: datetime
    completed_at: datetime

    @property
    def response_sha256(self) -> str:
        return canonical_sha256(self.structured_output)


class Topic3Provider(Protocol):
    alias: str
    model_alias: str

    async def execute(self, request: ResponsesLiteRequestV1) -> ProviderExecutionResult: ...

    async def close(self) -> None: ...


class ApprovedHTTPProvider:
    """Responses Lite adapter for an explicitly configured approved provider endpoint."""

    def __init__(
        self,
        *,
        alias: str,
        endpoint: str,
        api_key: str,
        model_alias: str,
        timeout_seconds: float,
        max_connections: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.alias = alias
        self.model_alias = model_alias
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_connections,
            ),
            transport=transport,
        )

    async def execute(self, request: ResponsesLiteRequestV1) -> ProviderExecutionResult:
        if request.provider_alias != self.alias:
            raise self._provider_error("Provider request alias does not match the adapter.")
        if not request.instructions or not request.tools:
            raise self._provider_error("Responses Lite requires non-empty instructions and tools.")
        started_at = datetime.now(UTC)
        try:
            response = await self._client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "X-Liyan-Request-ID": str(request.request_id),
                },
                json={
                    "request_id": str(request.request_id),
                    "model": request.model_alias,
                    "instructions": request.instructions,
                    "tools": [tool.model_dump(mode="json") for tool in request.tools],
                    "input": request.input_segments,
                    "response_schema": request.response_schema,
                    "temperature": request.temperature,
                    "max_output_tokens": request.max_output_tokens,
                },
                timeout=min(self._timeout_seconds, request.timeout_ms / 1000),
            )
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._provider_error(
                "The approved provider request failed.",
                retriable=isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)),
            ) from exc
        if not isinstance(document, dict):
            raise self._provider_error("The approved provider returned a non-object response.")
        structured = document.get("structured_output", document.get("output"))
        if not isinstance(structured, dict):
            raise self._provider_error("The approved provider omitted structured_output.")
        usage = document.get("usage") if isinstance(document.get("usage"), dict) else {}
        completed_at = datetime.now(UTC)
        return ProviderExecutionResult(
            request_id=str(
                document.get("request_id")
                or response.headers.get("x-request-id")
                or request.request_id
            ),
            structured_output=structured,
            input_tokens=self._optional_nonnegative_int(usage.get("input_tokens")),
            output_tokens=self._optional_nonnegative_int(usage.get("output_tokens")),
            started_at=started_at,
            completed_at=completed_at,
        )

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _optional_nonnegative_int(value: object) -> int | None:
        if value is None:
            return None
        parsed = int(value)
        if parsed < 0:
            raise ValueError("provider usage values cannot be negative")
        return parsed

    @staticmethod
    def _provider_error(message: str, *, retriable: bool = False) -> LiyanError:
        return LiyanError(
            ErrorCode.TOPIC3_PROVIDER_UNAVAILABLE,
            message,
            category=ErrorCategory.PROVIDER,
            retriable=retriable,
            status_code=503,
        )


class Topic3ProviderRegistry:
    def __init__(
        self,
        policy: ProviderPolicyRegistry,
        providers: dict[str, Topic3Provider],
    ) -> None:
        self._policy = policy
        self._providers = dict(providers)
        prohibited = set(self._providers) - {"spark_text", "xfyun_code", "seedance"}
        if prohibited:
            raise ValueError(f"unapproved provider adapters: {sorted(prohibited)}")
        for alias in self._providers:
            self._policy.assert_can_enable(alias)

    def require(self, alias: str) -> Topic3Provider:
        self._policy.assert_can_enable(alias)
        try:
            return self._providers[alias]
        except KeyError as exc:
            raise LiyanError(
                ErrorCode.TOPIC3_PROVIDER_UNAVAILABLE,
                "The approved provider is not configured for this deployment.",
                category=ErrorCategory.PROVIDER,
                retriable=False,
                status_code=503,
                details={"provider_alias": alias},
            ) from exc

    def update_policy(self, policy: ProviderPolicyRegistry) -> None:
        for alias in self._providers:
            policy.assert_can_enable(alias)
        self._policy = policy

    async def close(self) -> None:
        for provider in self._providers.values():
            await provider.close()


def build_topic3_provider_registry(
    settings: Settings,
    policy: ProviderPolicyRegistry,
) -> Topic3ProviderRegistry:
    providers: dict[str, Topic3Provider] = {}
    if not settings.provider_external_enabled:
        return Topic3ProviderRegistry(policy, providers)
    for alias in ("spark_text", "xfyun_code", "seedance"):
        credentials = settings.provider_credentials(alias)
        if credentials is None:
            continue
        endpoint, api_key, model_alias = credentials
        providers[alias] = ApprovedHTTPProvider(
            alias=alias,
            endpoint=endpoint,
            api_key=api_key,
            model_alias=model_alias,
            timeout_seconds=settings.provider_http_timeout_seconds,
            max_connections=settings.provider_max_connections,
        )
    return Topic3ProviderRegistry(policy, providers)
