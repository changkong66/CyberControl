from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from gate_c.config import Workload, load_credentials
from gate_c.token_provider import TokenProvider


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _status(
    session: requests.Session,
    url: str,
    *,
    token: str | None,
    cursor: str | None,
) -> int:
    headers = {"Accept": "text/event-stream"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if cursor is not None:
        headers["Last-Event-ID"] = cursor
    response = session.get(
        url,
        headers=headers,
        stream=True,
        timeout=(10, 10),
        allow_redirects=False,
    )
    status = response.status_code
    response.close()
    return status


def main() -> int:
    workload = Workload.load(Path(_required("GATE_C_WORKLOAD_PATH")))
    credentials = load_credentials(Path(_required("GATE_C_CREDENTIALS_PATH")))
    cursors = json.loads(
        Path(_required("GATE_C_BASELINE_CURSOR_PATH")).read_text(encoding="utf-8")
    )["cursors"]
    provider = TokenProvider(
        token_url=(
            f"{_required('GATE_C_KEYCLOAK_BASE_URL').rstrip('/')}/realms/"
            "cybercontrol/protocol/openid-connect/token"
        ),
        client_id="cybercontrol-cli",
        refresh_skew_seconds=60,
    )
    by_tenant = {
        tenant_id: next(value for value in credentials if value.tenant_id == tenant_id)
        for tenant_id in workload.tenant_ids
    }
    first, second = workload.tenant_ids[:2]
    first_token = provider.get(by_tenant[first]).value
    second_token = provider.get(by_tenant[second]).value
    first_cursor = str(cursors[first]["cursor"])
    tampered = first_cursor[:-1] + ("A" if first_cursor[-1] != "A" else "B")
    session = requests.Session()
    session.trust_env = False
    url = f"{_required('GATE_C_API_BASE_URL').rstrip('/')}{workload.stream_path}"
    invalid_token = "invalid" + ".gate-c.token"
    controls: dict[str, Any] = {
        "unauthenticated_status": _status(session, url, token=None, cursor=None),
        "invalid_token_status": _status(session, url, token=invalid_token, cursor=None),
        "tampered_cursor_status": _status(session, url, token=first_token, cursor=tampered),
        "cross_tenant_cursor_status": _status(
            session,
            url,
            token=second_token,
            cursor=first_cursor,
        ),
        "valid_cursor_status": _status(
            session,
            url,
            token=first_token,
            cursor=first_cursor,
        ),
    }
    controls["invalid_cursor_acceptance"] = sum(
        1
        for key in ("tampered_cursor_status", "cross_tenant_cursor_status")
        if controls[key] == 200
    )
    controls["passed"] = (
        controls["unauthenticated_status"] == 401
        and controls["invalid_token_status"] == 401
        and controls["tampered_cursor_status"] == 400
        and controls["cross_tenant_cursor_status"] == 400
        and controls["valid_cursor_status"] == 200
    )
    output = Path(_required("GATE_C_STAGE_RESULTS_DIR")) / "security-controls.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": "cybercontrol.gate-c-security-controls.v1",
                **controls,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(controls, sort_keys=True))
    return 0 if controls["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
