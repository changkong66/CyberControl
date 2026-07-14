from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from liyans.core.provider_policy import ProviderPolicyError, ProviderPolicyRegistry
from liyans_contracts.providers import ResponsesLiteRequestV1
from liyans_contracts.registry import CONTRACT_REGISTRY
from liyans_contracts.verification import ReleaseAuthorizationPayloadV1
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def assert_contract_registry() -> None:
    names = [registration.schema_name for registration in CONTRACT_REGISTRY]
    if len(names) != len(set(names)):
        raise AssertionError("duplicate contract schema names")

    for registration in CONTRACT_REGISTRY:
        config = registration.model.model_config
        if config.get("extra") != "forbid":
            raise AssertionError(f"contract must forbid unknown fields: {registration.schema_name}")


def assert_contract_catalog() -> None:
    catalog_path = ROOT / "config" / "contract-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entries = catalog["entries"]
    names = [entry["schema_name"] for entry in entries]
    if len(names) != len(set(names)):
        raise AssertionError("duplicate schema names in contract catalog")

    registry_names = {registration.schema_name for registration in CONTRACT_REGISTRY}
    catalog_names = set(names)
    if not registry_names <= catalog_names:
        raise AssertionError("coded registry contains uncatalogued schemas")

    coded_names = {
        entry["schema_name"] for entry in entries if entry["status"].startswith("CODED_")
    }
    if coded_names != registry_names:
        raise AssertionError("CODED_BASELINE catalog entries must match registry")

    expected_owners = {
        "c1-verification",
        "c2-knowledge",
        "c3-academic",
        "c4-graph",
        "c5-quiz",
        "c6-code",
        "c7-extension",
        "c8-revision",
        "c9-security",
        "c10-privacy",
        "c11-compliance",
        "c12-qa",
    }
    actual_owners = {entry["owner"] for entry in entries}
    if not expected_owners <= actual_owners:
        raise AssertionError("contract catalog does not cover C1-C12")


def assert_provider_policy() -> None:
    registry = ProviderPolicyRegistry.load(ROOT / "config" / "providers.toml")
    if registry.enabled_external_aliases():
        raise AssertionError("external providers must default to disabled")
    try:
        registry.assert_can_enable("external_embedding")
    except ProviderPolicyError:
        pass
    else:
        raise AssertionError("external embedding must be prohibited")


def assert_responses_lite_guard() -> None:
    try:
        ResponsesLiteRequestV1(
            schema_version="responses.lite.request.v1",
            request_id=uuid4(),
            provider_alias="spark_text",
            model_alias="spark-default",
            instructions=[{"role": "system", "content": "verify"}],
            tools=[],
            input_segments=[{"text": "claim"}],
            response_schema={"type": "object"},
            temperature=0.0,
            max_output_tokens=256,
            timeout_ms=5000,
        )
    except ValidationError:
        return
    raise AssertionError("ResponsesLiteRequestV1 accepted empty tools")


def assert_release_expiry_guard() -> None:
    now = datetime.now(UTC)
    try:
        ReleaseAuthorizationPayloadV1(
            schema_version="release.authorization.v1",
            authorization_id=uuid4(),
            verification_id=uuid4(),
            report_id=uuid4(),
            candidate_id=uuid4(),
            candidate_version=1,
            candidate_sha256="a" * 64,
            release_mode="FULL",
            allowed_block_ids=["block-1"],
            disclosure_codes=[],
            report_sha256="b" * 64,
            issued_at=now,
            expires_at=now - timedelta(seconds=1),
            one_time_use=True,
        )
    except ValidationError:
        return
    raise AssertionError("release authorization accepted invalid expiry")


def assert_generated_artifacts() -> None:
    registry_file = ROOT / "schemas" / "registry.json"
    ts_index = ROOT / "packages" / "contracts-ts" / "src" / "generated" / "index.ts"
    go_contracts = ROOT / "packages" / "contracts-go" / "contracts" / "contracts.go"
    if not registry_file.is_file() or not ts_index.is_file() or not go_contracts.is_file():
        raise AssertionError("contract export artifacts are missing")


def main() -> int:
    checks = (
        assert_contract_registry,
        assert_contract_catalog,
        assert_provider_policy,
        assert_responses_lite_guard,
        assert_release_expiry_guard,
        assert_generated_artifacts,
    )
    for check in checks:
        check()
        print(f"ok: {check.__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
