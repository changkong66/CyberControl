from __future__ import annotations

import runpy
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

TOOLS_ROOT = Path(__file__).resolve().parents[2] / "tools" / "topic4"
SSE_TOOL = cast(
    dict[str, Any],
    runpy.run_path(
        str(TOOLS_ROOT / "verify-authenticated-sse.py"),
        run_name="verify_authenticated_sse_test",
    ),
)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/internal/topic4/sse/stream",
        "http://127.0.0.1:8000/internal/topic4/sse/stream",
        "http://[::1]:8000/internal/topic4/sse/stream",
    ],
)
def test_sse_acceptance_endpoint_allows_only_loopback(url: str) -> None:
    assert SSE_TOOL["_endpoint"](url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/internal/topic4/sse/stream",
        "http://user:password@localhost:8000/internal/topic4/sse/stream",
        "file:///tmp/token-sink",
    ],
)
def test_sse_acceptance_endpoint_rejects_token_disclosure_targets(url: str) -> None:
    with pytest.raises(SystemExit):
        SSE_TOOL["_endpoint"](url)


def test_sse_acceptance_http_client_disables_proxies_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []
    expected_opener = object()

    def capture_handlers(*handlers: object) -> object:
        captured.extend(handlers)
        return expected_opener

    monkeypatch.setattr(urllib.request, "build_opener", capture_handlers)

    assert SSE_TOOL["_http_opener"]() is expected_opener
    proxy_handler = next(
        handler for handler in captured if isinstance(handler, urllib.request.ProxyHandler)
    )
    redirect_handler = next(
        handler for handler in captured if handler.__class__.__name__ == "_RejectRedirects"
    )
    assert proxy_handler.proxies == {}
    request = urllib.request.Request("http://127.0.0.1:8000/stream")
    with pytest.raises(urllib.error.HTTPError, match="redirects are forbidden"):
        redirect_handler.redirect_request(
            request,
            object(),
            302,
            "Found",
            {},
            "https://example.com/token-sink",
        )
