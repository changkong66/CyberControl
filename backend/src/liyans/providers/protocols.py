from __future__ import annotations

from typing import Protocol

from liyans_contracts.providers import ResponsesLiteRequestV1


class ProviderResponse(Protocol):
    @property
    def request_id(self) -> str: ...

    @property
    def structured_output(self) -> dict: ...


class BusinessAIProvider(Protocol):
    alias: str

    async def execute(self, request: ResponsesLiteRequestV1) -> ProviderResponse: ...
