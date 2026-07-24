from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import asyncpg
import requests

from gate_c.config import Workload
from gate_c.token_provider import decode_unverified_claims

READER_PERMISSIONS = " ".join(
    (
        "topic3:read",
        "topic3:generation:read",
        "topic3:sse:read",
        "topic4:read",
        "topic4:sse:read",
    )
)
PUBLISHER_PERMISSIONS = " ".join(
    (
        READER_PERMISSIONS,
        "topic1:read",
        "topic1:import",
        "topic1:freeze",
        "topic2:read",
        "topic2:profile:read",
        "topic2:profile:write",
        "topic2:memory:read",
        "topic2:memory:write",
        "topic2:path:read",
        "topic2:path:write",
        "topic2:context:read",
        "topic3:generation:write",
        "topic3:generation:retry",
        "topic3:sse:publish",
        "topic4:verification:read",
        "topic4:claim:read",
        "topic4:report:read",
        "topic4:trace:read",
    )
)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


class KeycloakAdmin:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False
        response = self.session.post(
            f"{self.base_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            },
            timeout=30,
            allow_redirects=False,
        )
        response.raise_for_status()
        token = str(response.json().get("access_token", ""))
        if not token:
            raise RuntimeError("Keycloak admin token is missing")
        self.session.headers["Authorization"] = f"Bearer {token}"

    def ensure_user(
        self,
        *,
        username: str,
        password: str,
        tenant_id: str,
        permissions: str,
    ) -> str:
        users_url = f"{self.base_url}/admin/realms/cybercontrol/users"
        response = self.session.get(
            users_url,
            params={"username": username, "exact": "true"},
            timeout=30,
            allow_redirects=False,
        )
        response.raise_for_status()
        existing = response.json()
        document = {
            "username": username,
            "email": f"{username}@example.invalid",
            "emailVerified": True,
            "enabled": True,
            "attributes": {
                "tenant_id": [tenant_id],
                "permissions": [permissions],
            },
            "requiredActions": [],
        }
        if existing:
            user_id = str(existing[0]["id"])
            update = self.session.put(
                f"{users_url}/{user_id}",
                json=document,
                timeout=30,
                allow_redirects=False,
            )
            update.raise_for_status()
        else:
            create = self.session.post(
                users_url,
                json=document,
                timeout=30,
                allow_redirects=False,
            )
            create.raise_for_status()
            location = create.headers.get("Location", "")
            user_id = location.rstrip("/").rsplit("/", 1)[-1]
            if not user_id:
                raise RuntimeError("Keycloak user creation did not return an identifier")
        reset = self.session.put(
            f"{users_url}/{user_id}/reset-password",
            json={"type": "password", "temporary": False, "value": password},
            timeout=30,
            allow_redirects=False,
        )
        reset.raise_for_status()
        role_response = self.session.get(
            f"{self.base_url}/admin/realms/cybercontrol/roles/learner",
            timeout=30,
            allow_redirects=False,
        )
        role_response.raise_for_status()
        role = role_response.json()
        mapping = self.session.post(
            f"{users_url}/{user_id}/role-mappings/realm",
            json=[role],
            timeout=30,
            allow_redirects=False,
        )
        if mapping.status_code not in {204, 409}:
            mapping.raise_for_status()
        return user_id


async def _ensure_tenants(database_url: str, issuer: str, tenant_ids: tuple[str, ...]) -> None:
    connection = await asyncpg.connect(database_url)
    try:
        for tenant_id in tenant_ids:
            await connection.execute(
                """
                INSERT INTO tenants
                    (tenant_id, slug, display_name, oidc_issuer, oidc_tenant_claim)
                VALUES ($1, $1, $2, $3, $1)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    oidc_issuer = EXCLUDED.oidc_issuer,
                    oidc_tenant_claim = EXCLUDED.oidc_tenant_claim,
                    status = 'ACTIVE',
                    updated_at = now()
                """,
                tenant_id,
                f"Gate C {tenant_id}",
                issuer,
            )
    finally:
        await connection.close()


def _user_token(base_url: str, username: str, password: str) -> tuple[str, dict[str, Any]]:
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        f"{base_url.rstrip('/')}/realms/cybercontrol/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "cybercontrol-cli",
            "username": username,
            "password": password,
            "scope": "openid profile email",
        },
        timeout=30,
        allow_redirects=False,
    )
    response.raise_for_status()
    token = str(response.json().get("access_token", ""))
    if not token:
        raise RuntimeError("Keycloak did not issue a Gate C access token")
    return token, decode_unverified_claims(token)


def _api_session(token: str) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


def _bootstrap_tenant(
    *,
    api_base_url: str,
    token: str,
    tenant_id: str,
    subject_ref: str,
) -> tuple[str, str]:
    session = _api_session(token)
    course_path = Path("/app/data/topic1/automatic-control-principles.v1.json")
    bundle = json.loads(course_path.read_text(encoding="utf-8"))
    course_id = str(bundle["content"]["course"]["course_id"])
    courses = session.get(f"{api_base_url}/internal/topic1/courses", timeout=30)
    courses.raise_for_status()
    existing = courses.json().get("data", {}).get("courses", [])
    if not any(item.get("course_id") == course_id for item in existing):
        response = session.post(
            f"{api_base_url}/internal/topic1/imports",
            json=bundle,
            headers={"Idempotency-Key": f"gate-c:{tenant_id}:topic1-import:v1"},
            timeout=90,
        )
        response.raise_for_status()
    encoded_subject = quote(subject_ref, safe="")
    profile_url = (
        f"{api_base_url}/internal/topic2/learners/{encoded_subject}/courses/"
        f"{course_id}/profiles/latest"
    )
    profile = session.get(profile_url, timeout=30)
    if profile.status_code == 404:
        operation_id = uuid5(NAMESPACE_URL, f"gate-c:{tenant_id}:profile")
        response = session.post(
            f"{api_base_url}/internal/topic2/learners/{encoded_subject}/courses/"
            f"{course_id}/initialize",
            json={
                "schema_version": "topic2.operation-command.v1",
                "operation_id": str(operation_id),
                "requested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
            headers={"Idempotency-Key": f"gate-c:{tenant_id}:topic2-init:v1"},
            timeout=60,
        )
        response.raise_for_status()
    else:
        profile.raise_for_status()
    graph = session.get(
        f"{api_base_url}/internal/topic1/courses/{course_id}/graph",
        timeout=30,
    )
    graph.raise_for_status()
    knowledge_points = graph.json().get("data", {}).get("graph", {}).get("knowledge_points", [])
    if not knowledge_points:
        raise RuntimeError("Gate C Topic 1 graph has no knowledge points")
    target_kp_id = str(knowledge_points[0]["kp_id"])
    path_url = (
        f"{api_base_url}/internal/topic2/learners/{encoded_subject}/courses/"
        f"{course_id}/paths/latest"
    )
    path = session.get(path_url, timeout=30)
    if path.status_code == 404:
        operation_id = uuid5(NAMESPACE_URL, f"gate-c:{tenant_id}:path")
        response = session.post(
            f"{api_base_url}/internal/topic2/learners/{encoded_subject}/courses/"
            f"{course_id}/paths/generate",
            json={
                "schema_version": "topic2.path-generate-command.v1",
                "operation_id": str(operation_id),
                "requested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "target_goal": "Gate C authenticated SSE and Outbox acceptance.",
                "target_kp_ids": [target_kp_id],
            },
            headers={"Idempotency-Key": f"gate-c:{tenant_id}:topic2-path:v1"},
            timeout=60,
        )
        response.raise_for_status()
    else:
        path.raise_for_status()
    return course_id, target_kp_id


def main() -> int:
    workload = Workload.load(Path(_required("GATE_C_WORKLOAD_PATH")))
    credentials_path = Path(_required("GATE_C_CREDENTIALS_PATH"))
    api_base_url = _required("GATE_C_API_BASE_URL").rstrip("/")
    keycloak_base_url = _required("GATE_C_KEYCLOAK_BASE_URL").rstrip("/")
    issuer = _required("GATE_C_KEYCLOAK_ISSUER")
    asyncio.run(
        _ensure_tenants(
            _required("GATE_C_DATABASE_URL"),
            issuer,
            workload.tenant_ids,
        )
    )
    admin = KeycloakAdmin(
        keycloak_base_url,
        _required("GATE_C_KEYCLOAK_ADMIN_USERNAME"),
        _required("GATE_C_KEYCLOAK_ADMIN_PASSWORD"),
    )
    credentials: list[dict[str, Any]] = []
    for tenant_id in workload.tenant_ids:
        tenant_credentials: list[dict[str, Any]] = []
        for ordinal in range(workload.principals_per_tenant):
            username = f"gatec-{tenant_id.removeprefix('gate-c-')}-{ordinal:02d}"
            password = secrets.token_urlsafe(24)
            publisher = ordinal == 0
            subject_ref = admin.ensure_user(
                username=username,
                password=password,
                tenant_id=tenant_id,
                permissions=PUBLISHER_PERMISSIONS if publisher else READER_PERMISSIONS,
            )
            token, claims = _user_token(keycloak_base_url, username, password)
            if claims.get("tenant_id") != tenant_id or claims.get("sub") != subject_ref:
                raise RuntimeError("provisioned Keycloak claims are inconsistent")
            tenant_credentials.append(
                {
                    "username": username,
                    "password": password,
                    "tenant_id": tenant_id,
                    "subject_ref": subject_ref,
                    "publisher": publisher,
                    "course_id": "",
                    "target_kp_id": "",
                }
            )
            del token
        publisher_record = tenant_credentials[0]
        publisher_token, _ = _user_token(
            keycloak_base_url,
            str(publisher_record["username"]),
            str(publisher_record["password"]),
        )
        course_id, target_kp_id = _bootstrap_tenant(
            api_base_url=api_base_url,
            token=publisher_token,
            tenant_id=tenant_id,
            subject_ref=str(publisher_record["subject_ref"]),
        )
        for record in tenant_credentials:
            record["course_id"] = course_id
            record["target_kp_id"] = target_kp_id
        credentials.extend(tenant_credentials)
    document = {
        "schema_version": "cybercontrol.gate-c-credentials.v1",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "tenant_count": len(workload.tenant_ids),
        "principal_count": len(credentials),
        "credentials": credentials,
    }
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    credentials_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    credentials_path.chmod(0o600)
    print(
        json.dumps(
            {
                "tenant_count": len(workload.tenant_ids),
                "principal_count": len(credentials),
                "credentials_path": str(credentials_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
