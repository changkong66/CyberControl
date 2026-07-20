from __future__ import annotations

import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_REQUEST_BYTES = 2 * 1024 * 1024
EXPECTED_TOKEN = os.environ.get("FIXTURE_PROVIDER_TOKEN", "local-fixture-provider-only")


def _segments(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw = document.get("input")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _segment(document: dict[str, Any], segment_type: str) -> dict[str, Any]:
    return next(
        (item for item in _segments(document) if item.get("segment_type") == segment_type),
        {},
    )


def _generation_context(document: dict[str, Any]) -> tuple[list[str], str, str]:
    command = _segment(document, "generation_command").get("command")
    command = command if isinstance(command, dict) else {}
    target_ids = command.get("target_kp_ids")
    targets = [str(value) for value in target_ids] if isinstance(target_ids, list) else []
    if not targets:
        raise ValueError("The fixture request has no target knowledge point.")
    depth = str(command.get("lecturer_depth") or "FOUNDATION")

    authoritative = _segment(document, "authoritative_topic1")
    points = authoritative.get("knowledge_points")
    point_documents = points if isinstance(points, list) else []
    point_by_id = {
        str(item.get("kp_id")): item
        for item in point_documents
        if isinstance(item, dict) and item.get("kp_id")
    }
    first = point_by_id.get(targets[0], {})
    title = str(first.get("title") or targets[0])
    return targets, title, depth


def _lecturer(targets: list[str], title: str, depth: str) -> dict[str, Any]:
    return {
        "schema_version": "topic3.lecturer-content.v1",
        "title": f"Local fixture lesson: {title}",
        "learning_objectives": [f"Explain the core definition and boundary of {title}."],
        "sections": [
            {
                "section_id": "fixture_foundation",
                "title": "Authoritative foundation",
                "depth": depth,
                "markdown": (
                    f"# {title}\n\n"
                    "This deterministic local fixture uses only the frozen Topic1 input segment. "
                    "It demonstrates the complete generation, verification, and release pipeline "
                    "through the configured local fixture provider."
                ),
                "target_kp_ids": targets,
            }
        ],
        "summary": [f"Review the Topic1 evidence bound to {', '.join(targets)}."],
        "misconception_alerts": [],
        "personalization_notes": [],
    }


def _tester(targets: list[str], title: str) -> dict[str, Any]:
    return {
        "schema_version": "topic3.tester-content.v1",
        "title": f"Local diagnostic: {title}",
        "total_score": 100.0,
        "questions": [
            {
                "question_id": "fixture-question-1",
                "question_type": "CONCEPT",
                "difficulty": 0.35,
                "target_kp_ids": targets,
                "prompt_markdown": f"State the authoritative definition of **{title}**.",
                "standard_answer": "Use the definition provided by the frozen Topic1 snapshot.",
                "solution_steps": [
                    "Locate the matching Topic1 knowledge point.",
                    "State its definition without adding external claims.",
                ],
                "misconception_diagnostics": ["Reject unsupported extensions or invented sources."],
                "score": 100.0,
            }
        ],
        "diagnostic_dimensions": ["evidence-grounding", "concept-accuracy"],
    }


def _code(title: str) -> dict[str, Any]:
    return {
        "schema_version": "topic3.code-sandbox-content.v1",
        "title": f"Deterministic control response for {title}",
        "objective": "Simulate a bounded first-order response using only Python arithmetic.",
        "files": [
            {
                "path": "control_demo.py",
                "language": "python",
                "entrypoint": True,
                "content": (
                    "dt = 0.1\n"
                    "gain = 0.8\n"
                    "state = 0.0\n"
                    "samples = []\n"
                    "for step in range(40):\n"
                    "    state += dt * (-state + gain)\n"
                    "    samples.append(round(state, 6))\n"
                    "print(samples[-1])\n"
                ),
            }
        ],
        "parameters": {"dt": "0.1", "gain": "0.8", "steps": "40"},
        "expected_observations": ["The bounded response converges toward the configured gain."],
        "result_analysis": (
            "The fixture is deterministic and performs no network or filesystem operation."
        ),
        "safety_notes": ["Run only in the project sandbox and keep the finite iteration bound."],
    }


def _extension(targets: list[str], title: str) -> dict[str, Any]:
    resource_id = "fixture-engineering-context"
    return {
        "schema_version": "topic3.extension-content.v1",
        "title": f"Local engineering context: {title}",
        "resources": [
            {
                "resource_id": resource_id,
                "resource_kind": "ENGINEERING",
                "title": f"Evidence-bound application of {title}",
                "summary": (
                    "A deterministic local extension that remains within the supplied Topic1 "
                    "knowledge-point boundary."
                ),
                "relevance_to_kp_ids": targets,
                "citation_text": f"CyberControl frozen Topic1 snapshot for {', '.join(targets)}.",
                "source_url": None,
            }
        ],
        "recommended_sequence": [resource_id],
    }


def fixture_output(document: dict[str, Any]) -> dict[str, Any]:
    tools = document.get("tools")
    tool = tools[0] if isinstance(tools, list) and tools and isinstance(tools[0], dict) else {}
    tool_name = str(tool.get("name") or "")
    targets, title, depth = _generation_context(document)
    if tool_name == "submit_lecturer_result":
        return _lecturer(targets, title, depth)
    if tool_name == "submit_tester_result":
        return _tester(targets, title)
    if tool_name == "submit_codesandbox_result":
        return _code(title)
    if tool_name == "submit_extension_result":
        return _extension(targets, title)
    raise ValueError(f"Unsupported fixture tool: {tool_name or 'missing'}")


class FixtureProviderHandler(BaseHTTPRequestHandler):
    server_version = "CyberControlFixtureProvider/1"

    def do_GET(self) -> None:
        if self.path != "/health/ready":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._json(HTTPStatus.OK, {"status": "ready", "network_access": False})

    def do_POST(self) -> None:
        if self.path != "/v1/responses":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        provided = self.headers.get("Authorization", "")
        if not hmac.compare_digest(provided, f"Bearer {EXPECTED_TOKEN}"):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_fixture_token"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "invalid_request_size"})
            return
        try:
            document = json.loads(self.rfile.read(length))
            if not isinstance(document, dict):
                raise ValueError("Request body must be an object.")
            output = fixture_output(document)
        except (json.JSONDecodeError, ValueError) as exc:
            self._json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error": "invalid_fixture_request", "message": str(exc)},
            )
            return
        self._json(
            HTTPStatus.OK,
            {
                "request_id": str(document.get("request_id") or "fixture-request"),
                "structured_output": output,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        print(f"fixture-provider {self.address_string()} {format % args}", flush=True)

    def _json(self, status: HTTPStatus, document: dict[str, Any]) -> None:
        payload = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    port = int(os.environ.get("PORT", "8090"))
    server = ThreadingHTTPServer(
        ("0.0.0.0", port),  # noqa: S104 - required for container bridge traffic.
        FixtureProviderHandler,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
