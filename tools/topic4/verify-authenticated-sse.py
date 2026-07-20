from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify one authenticated SSE replay frame.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--publication-batch-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser


def _endpoint(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("--url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise SystemExit("--url must not contain user information")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("--url must target the local acceptance environment")
    return value


def _matches(frame: dict[str, str], event_type: str, batch_id: str) -> bool:
    if frame.get("event") != event_type:
        return False
    try:
        document = json.loads(frame.get("data", ""))
    except json.JSONDecodeError:
        return False
    return batch_id in json.dumps(document, ensure_ascii=False, sort_keys=True)


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        _msg: str,
        headers: object,
        _newurl: str,
    ) -> urllib.request.Request | None:
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            "SSE acceptance endpoint redirects are forbidden",
            headers,
            fp,
        )


def _http_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirects(),
    )


def _read_expected_frame(
    response: object,
    *,
    event_type: str,
    batch_id: str,
    deadline: float,
) -> dict[str, object] | None:
    frame: dict[str, str] = {}
    while time.monotonic() < deadline:
        raw = response.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="strict").rstrip("\r\n")
        if not line:
            if frame and _matches(frame, event_type, batch_id):
                return {
                    "event_id": frame.get("id"),
                    "event_type": frame.get("event"),
                    "publication_batch_id": batch_id,
                    "authenticated": True,
                    "replayed": True,
                }
            frame = {}
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator:
            frame[field] = value.lstrip()
    return None


def _verify(args: argparse.Namespace, token: str) -> dict[str, object]:
    request = urllib.request.Request(  # noqa: S310 - URL is restricted above.
        _endpoint(args.url),
        headers={
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    deadline = time.monotonic() + args.timeout_seconds
    try:
        with _http_opener().open(
            request,
            timeout=args.timeout_seconds,
        ) as response:
            if response.status != 200:
                raise SystemExit(f"SSE endpoint returned HTTP {response.status}")
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                raise SystemExit("SSE endpoint returned an unexpected content type")
            matched = _read_expected_frame(
                response,
                event_type=args.event_type,
                batch_id=args.publication_batch_id,
                deadline=deadline,
            )
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"SSE endpoint returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"SSE endpoint is unavailable: {exc.reason}") from exc
    if matched is not None:
        return matched
    raise SystemExit("Expected authenticated SSE publication frame was not observed")


def main() -> int:
    args = _parser().parse_args()
    if args.timeout_seconds <= 0 or args.timeout_seconds > 120:
        raise SystemExit("--timeout-seconds must be between 0 and 120")
    token = os.getenv("LIYAN_DEMO_TOKEN")
    if not token:
        raise SystemExit("LIYAN_DEMO_TOKEN is required")
    print(json.dumps(_verify(args, token), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
