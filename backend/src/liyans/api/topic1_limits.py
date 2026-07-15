from __future__ import annotations

import secrets
from datetime import UTC, datetime

from liyans_contracts.envelope import ErrorReceiptV1, ErrorSeverity
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from liyans.api.middleware import TRACE_PATTERN
from liyans.core.errors import ErrorCategory, ErrorCode


class Topic1ImportBodyLimitMiddleware:
    """Buffers only the Topic 1 import body and rejects it before model parsing."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self._app = app
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_topic1_import(scope):
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = self._content_length(headers.get("content-length"))
        if content_length is not None and content_length > self._max_body_bytes:
            await self._reject(scope, receive, send, headers)
            return
        if content_length is not None:
            await self._app(scope, receive, send)
            return

        messages: list[Message] = []
        total_bytes = 0
        terminal_message: Message = {"type": "http.request", "body": b"", "more_body": False}
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                terminal_message = message
                break
            if message["type"] != "http.request":
                continue
            total_bytes += len(message.get("body", b""))
            if total_bytes > self._max_body_bytes:
                await self._reject(scope, receive, send, headers)
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay_receive() -> Message:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return terminal_message

        await self._app(scope, replay_receive, send)

    @staticmethod
    def _is_topic1_import(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/internal/topic1/imports"
        )

    @staticmethod
    def _content_length(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        headers: Headers,
    ) -> None:
        trace_id = headers.get("x-trace-id", "")
        if not TRACE_PATTERN.fullmatch(trace_id):
            trace_id = secrets.token_hex(16)
        receipt = ErrorReceiptV1(
            schema_version="topic3.error-receipt.v1",
            error_code=ErrorCode.TOPIC1_IMPORT_LIMIT.value,
            category=ErrorCategory.CONTRACT.value,
            severity=ErrorSeverity.ERROR,
            retriable=False,
            safe_message="The Topic 1 import exceeds the accepted size limit.",
            details_ref={"max_body_bytes": self._max_body_bytes},
            occurred_at=datetime.now(UTC),
        )
        response = JSONResponse(
            status_code=413,
            content={
                "error": receipt.model_dump(mode="json"),
                "trace_id": trace_id,
            },
            headers={"x-trace-id": trace_id},
        )
        await response(scope, receive, send)
