from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

from liyans_contracts.topic4_c11 import ComplianceBuildProvenanceInputV1

ROOT = Path(__file__).resolve().parents[2]
BUILDER_POLICY = ROOT / "config" / "compliance-builders.toml"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _first_allowlisted_builder() -> tuple[str, str, str]:
    with BUILDER_POLICY.open("rb") as handle:
        document = tomllib.load(handle)
    builders = document.get("builders", [])
    if not builders:
        raise RuntimeError("config/compliance-builders.toml does not contain a builder")
    builder = builders[0]
    try:
        return (
            str(builder["builder_id"]),
            str(builder["builder_version"]),
            str(builder["toolchain_manifest_version"]),
        )
    except KeyError as exc:
        raise RuntimeError("the first configured C11 builder is incomplete") from exc


def build_request(
    *,
    verification_id: UUID,
    claim_id: UUID,
    source_sha256: str,
    idempotency_key: str,
) -> dict[str, object]:
    builder_id, builder_version, toolchain_manifest_version = _first_allowlisted_builder()
    provenance = ComplianceBuildProvenanceInputV1(
        builder_id=builder_id,
        builder_version=builder_version,
        toolchain_manifest_version=toolchain_manifest_version,
        source_sha256=source_sha256,
        build_output_document={
            "status": "verified",
            "exit_code": 0,
            "mode": "sample-local-evidence",
        },
        sandbox_policy_id=uuid4(),
        reproducible=True,
        build_command_sha256=_sha256("python -m liyans.sample_control_simulation"),
    )
    return {
        "verification_id": str(verification_id),
        "claim_id": str(claim_id),
        "sbom_document": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "serialNumber": f"urn:uuid:{uuid4()}",
            "version": 1,
            "components": [
                {
                    "bom-ref": "pkg:pypi/numpy@2.1.0",
                    "name": "numpy",
                    "version": "2.1.0",
                    "purl": "pkg:pypi/numpy@2.1.0",
                    "licenses": [{"license": {"id": "BSD-3-Clause"}}],
                }
            ],
        },
        "vulnerability_records": [],
        "provenance_document": provenance.model_dump(mode="json"),
        "_idempotency_key": idempotency_key,
    }


def _parse_uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} must be a UUID") from exc


def _endpoint_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("--base-url must be an absolute http or https URL")
    return f"{base_url.rstrip('/')}/internal/topic4/compliance/packages"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a keyless Topic4 C11 trusted-evidence import request, "
            "or post it to a local API."
        )
    )
    parser.add_argument(
        "--verification-id", required=True, type=lambda value: _parse_uuid(value, "verification-id")
    )
    parser.add_argument(
        "--claim-id", required=True, type=lambda value: _parse_uuid(value, "claim-id")
    )
    parser.add_argument(
        "--source-sha256",
        required=True,
        help="SHA-256 of the persisted C6 source artifact; the server verifies this binding.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, help="Write the JSON request body to this path.")
    parser.add_argument(
        "--post",
        action="store_true",
        help="POST the request to the local API using LIYAN_DEMO_TOKEN.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if len(args.source_sha256) != 64 or any(
        char not in "0123456789abcdefABCDEF" for char in args.source_sha256
    ):
        raise SystemExit("--source-sha256 must be a 64-character hexadecimal SHA-256")
    idempotency_key = f"topic4-c11-sample-{uuid4().hex}"
    request_document = build_request(
        verification_id=args.verification_id,
        claim_id=args.claim_id,
        source_sha256=args.source_sha256.lower(),
        idempotency_key=idempotency_key,
    )
    request_body = {
        key: value for key, value in request_document.items() if key != "_idempotency_key"
    }
    encoded = json.dumps(request_body, ensure_ascii=False, indent=2).encode("utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded + b"\n")
        print(f"Wrote C11 request body to {args.output}")
    else:
        print(encoded.decode("utf-8"))

    if not args.post:
        return 0
    token = os.getenv("LIYAN_DEMO_TOKEN")
    if not token:
        raise SystemExit("--post requires LIYAN_DEMO_TOKEN; no token is stored in this script")
    request = urllib.request.Request(  # noqa: S310 - scheme is restricted by _endpoint_url.
        _endpoint_url(args.base_url),
        data=encoded,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            sys.stdout.write(response.read().decode("utf-8"))
            sys.stdout.write("\n")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"C11 import failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"C11 import endpoint is unavailable: {exc.reason}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
