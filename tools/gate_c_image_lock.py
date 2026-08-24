from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROCESS_VERSION = "Gate-C-12-v1.0"
IMAGE_LOCK_SCHEMA = "cybercontrol.gate-c-image-lock.v1"
BUILD_RECEIPT_SCHEMA = "cybercontrol.gate-c-build-receipt.v1"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class SourceBinding:
    commit: str
    tree: str
    product_source_sha: str
    engineering_baseline_sha: str
    source_date_epoch: int


@dataclass(frozen=True)
class BuildTarget:
    name: str
    dockerfile: str
    repository: str


TARGETS = (
    BuildTarget("backend", "infra/backend.Dockerfile", "cybercontrol/gate-c-backend"),
    BuildTarget("frontend", "infra/frontend.Dockerfile", "cybercontrol/gate-c-frontend"),
    BuildTarget(
        "mock-provider", "infra/mock-provider.Dockerfile", "cybercontrol/gate-c-mock-provider"
    ),
    BuildTarget("gate-c-load", "tests/load/Dockerfile", "cybercontrol/gate-c-load"),
)


def _run(arguments: Sequence[str], *, cwd: Path, capture: bool = True) -> str:
    completed = subprocess.run(  # noqa: S603 - all callers construct fixed tool arguments.
        list(arguments),
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )
    return completed.stdout.strip() if capture else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _source_binding(
    root: Path, product_source_sha: str, engineering_baseline_sha: str
) -> SourceBinding:
    commit = _run(("git", "rev-parse", "HEAD"), cwd=root)
    tree = _run(("git", "rev-parse", "HEAD^{tree}"), cwd=root)
    status = _run(("git", "status", "--porcelain=v1", "--untracked-files=all"), cwd=root)
    if status:
        raise ValueError("Gate C image builds require a clean source worktree")
    for name, value in (
        ("source commit", commit),
        ("source tree", tree),
        ("product source", product_source_sha),
        ("engineering baseline", engineering_baseline_sha),
    ):
        if GIT_SHA.fullmatch(value) is None:
            raise ValueError(f"{name} is not a full Git SHA")
    if engineering_baseline_sha != commit:
        raise ValueError("engineering baseline must equal the exact build commit")
    epoch = int(_run(("git", "show", "-s", "--format=%ct", "HEAD"), cwd=root))
    return SourceBinding(commit, tree, product_source_sha, engineering_baseline_sha, epoch)


def _validate_inputs(path: Path) -> dict[str, Any]:
    inputs = _read_json(path)
    if inputs.get("schema_version") != "cybercontrol.gate-c-build-inputs.v1":
        raise ValueError("Gate C build inputs have the wrong schema")
    if inputs.get("process_version") != PROCESS_VERSION:
        raise ValueError("Gate C build inputs have the wrong process version")
    buildkit = inputs.get("buildkit")
    if (
        not isinstance(buildkit, dict)
        or SHA256.fullmatch(str(buildkit.get("image_digest"))) is None
    ):
        raise ValueError("Gate C BuildKit image digest is missing or invalid")
    python_image = inputs.get("python_base_image")
    if (
        not isinstance(python_image, dict)
        or SHA256.fullmatch(str(python_image.get("digest"))) is None
        or set(python_image.get("builder_mirrors", {})) != {"a", "b"}
    ):
        raise ValueError("Gate C Python base image mirror binding is invalid")
    alpine = inputs.get("alpine")
    if (
        not isinstance(alpine, dict)
        or re.fullmatch(r"[0-9a-f]{64}", str(alpine.get("apkindex_sha256"))) is None
    ):
        raise ValueError("Gate C APKINDEX content hash is missing or invalid")
    packages = alpine.get("backend_runtime_packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Gate C backend package lock is empty")
    names: set[str] = set()
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("Gate C backend package entry is invalid")
        name = str(package.get("filename"))
        digest = str(package.get("sha256"))
        if name in names or re.fullmatch(r"[A-Za-z0-9+_.-]+\.apk", name) is None:
            raise ValueError("Gate C backend package filename is invalid or duplicated")
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(f"Gate C backend package {name} has an invalid SHA256")
        names.add(name)
    return inputs


def _builder_fingerprint(root: Path, builder: str, inputs: dict[str, Any]) -> dict[str, str]:
    inspect = _run(("docker", "buildx", "inspect", builder, "--bootstrap"), cwd=root)
    expected_version = str(inputs["buildkit"]["version"])
    expected_digest = str(inputs["buildkit"]["image_digest"])
    if "Driver:        docker-container" not in inspect:
        raise ValueError(f"builder {builder} is not using the docker-container driver")
    if f"BuildKit version:      {expected_version}" not in inspect:
        raise ValueError(f"builder {builder} does not use {expected_version}")
    container = f"buildx_buildkit_{builder}0"
    raw = _run(("docker", "inspect", container), cwd=root)
    document = json.loads(raw)
    if not isinstance(document, list) or len(document) != 1:
        raise ValueError(f"builder {builder} container inspection is invalid")
    item = document[0]
    configured_image = str(item.get("Config", {}).get("Image", ""))
    image_id = str(item.get("Image", ""))
    if not configured_image.endswith(f"@{expected_digest}") or image_id != expected_digest:
        raise ValueError(f"builder {builder} is not bound to the locked BuildKit content")
    return {
        "name": builder,
        "driver": "docker-container",
        "buildkit_version": expected_version,
        "buildkit_image": configured_image,
        "buildkit_image_digest": image_id,
    }


def _docker_versions(root: Path, inputs: dict[str, Any]) -> dict[str, str]:
    server = _run(("docker", "version", "--format", "{{.Server.Version}}"), cwd=root)
    buildx = _run(("docker", "buildx", "version"), cwd=root).split()[1]
    if server != inputs["docker_server_version"]:
        raise ValueError(f"Docker Server {server} does not match the locked build environment")
    if buildx != inputs["docker_buildx_version"]:
        raise ValueError(f"Buildx {buildx} does not match the locked build environment")
    return {"docker_server_version": server, "docker_buildx_version": buildx}


def _image_id(root: Path, reference: str) -> str:
    image_id = _run(("docker", "image", "inspect", reference, "--format", "{{.Id}}"), cwd=root)
    if SHA256.fullmatch(image_id) is None:
        raise ValueError(f"image {reference} has an invalid local content ID")
    return image_id


def _assert_image_provenance(root: Path, reference: str, source: SourceBinding) -> None:
    raw = _run(("docker", "image", "inspect", reference), cwd=root)
    document = json.loads(raw)
    labels = document[0].get("Config", {}).get("Labels", {})
    expected = {
        "org.opencontainers.image.revision": source.commit,
        "com.cybercontrol.source-tree": source.tree,
        "com.cybercontrol.product-source": source.product_source_sha,
        "com.cybercontrol.engineering-baseline": source.engineering_baseline_sha,
        "com.cybercontrol.process-version": PROCESS_VERSION,
    }
    for name, value in expected.items():
        if labels.get(name) != value:
            raise ValueError(f"image {reference} has invalid provenance label {name}")
    if "com.docker.compose.project" in labels:
        raise ValueError(f"image {reference} contains a runtime Compose project label")


def _build_target(
    root: Path,
    target: BuildTarget,
    builder: str,
    arm: str,
    source: SourceBinding,
    inputs: dict[str, Any],
) -> dict[str, str]:
    reference = f"{target.repository}:{source.commit}-{arm}"
    arguments = [
        "docker",
        "buildx",
        "build",
        "--builder",
        builder,
        "--platform",
        "linux/amd64",
        "--no-cache",
        "--provenance=false",
        "--file",
        target.dockerfile,
        "--tag",
        reference,
        "--output",
        f"type=docker,name={reference},rewrite-timestamp=true",
    ]
    build_arguments = {
        "SOURCE_DATE_EPOCH": str(source.source_date_epoch),
        "CYBERCONTROL_SOURCE_SHA": source.commit,
        "CYBERCONTROL_SOURCE_TREE": source.tree,
        "CYBERCONTROL_PRODUCT_SOURCE_SHA": source.product_source_sha,
        "CYBERCONTROL_ENGINEERING_BASELINE_SHA": source.engineering_baseline_sha,
        "CYBERCONTROL_PROCESS_VERSION": PROCESS_VERSION,
    }
    if target.name in {"backend", "mock-provider", "gate-c-load"}:
        python_image = inputs["python_base_image"]
        mirror = python_image["builder_mirrors"][arm]
        build_arguments["PYTHON_IMAGE"] = (
            f"{mirror}/library/python:{python_image['tag']}@{python_image['digest']}"
        )
    for name, value in build_arguments.items():
        arguments.extend(("--build-arg", f"{name}={value}"))
    arguments.append(".")
    _run(arguments, cwd=root, capture=False)
    _assert_image_provenance(root, reference, source)
    return {"reference": reference, "image_id": _image_id(root, reference)}


def _external_service(root: Path, reference: str) -> dict[str, str]:
    return {"reference": reference, "image_id": _image_id(root, reference)}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    inputs_path = (root / args.inputs).resolve()
    inputs = _validate_inputs(inputs_path)
    source = _source_binding(root, args.product_source_sha, args.engineering_baseline_sha)
    versions = _docker_versions(root, inputs)
    builders = [
        _builder_fingerprint(root, args.builder_a, inputs),
        _builder_fingerprint(root, args.builder_b, inputs),
    ]
    if builders[0]["name"] == builders[1]["name"]:
        raise ValueError("Gate C reproducibility requires two independent builders")

    arms: dict[str, dict[str, dict[str, str]]] = {}
    for arm, builder in (("a", args.builder_a), ("b", args.builder_b)):
        arms[arm] = {
            target.name: _build_target(root, target, builder, arm, source, inputs)
            for target in TARGETS
        }
    for target in TARGETS:
        first = arms["a"][target.name]["image_id"]
        second = arms["b"][target.name]["image_id"]
        if first != second:
            raise ValueError(f"independent builds for {target.name} produced different image IDs")

    canonical: dict[str, dict[str, str]] = {}
    for target in TARGETS:
        reference = f"{target.repository}:{source.commit}"
        _run(("docker", "image", "tag", arms["a"][target.name]["image_id"], reference), cwd=root)
        canonical[target.name] = {"reference": reference, "image_id": _image_id(root, reference)}

    external = inputs["external_images"]
    postgres = _external_service(root, external["postgres"])
    keycloak = _external_service(root, external["keycloak"])
    service_images = {
        "api": canonical["backend"],
        "migrate": canonical["backend"],
        "mock-provider": canonical["mock-provider"],
        "frontend": canonical["frontend"],
        "gate-c-load": canonical["gate-c-load"],
        "postgres": postgres,
        "postgres-role-bootstrap": postgres,
        "tenant-bind": postgres,
        "keycloak": keycloak,
        "keycloak-config": keycloak,
    }
    output = args.output.resolve()
    generated = datetime.now(UTC).isoformat()
    receipt = {
        "schema_version": BUILD_RECEIPT_SCHEMA,
        "process_version": PROCESS_VERSION,
        "generated_at_utc": generated,
        "source": {
            "commit": source.commit,
            "tree": source.tree,
            "product_source_sha": source.product_source_sha,
            "engineering_baseline_sha": source.engineering_baseline_sha,
            "source_date_epoch": source.source_date_epoch,
        },
        "environment": {**versions, "platform": inputs["platform"], "builders": builders},
        "inputs": {
            "path": str(inputs_path.relative_to(root)).replace("\\", "/"),
            "sha256": _sha256(inputs_path),
            "document": inputs,
        },
        "independent_builds": arms,
        "reproducible": True,
    }
    receipt_path = output / "build-receipt.json"
    _write_json(receipt_path, receipt)
    lock = {
        "schema_version": IMAGE_LOCK_SCHEMA,
        "process_version": PROCESS_VERSION,
        "generated_at_utc": generated,
        "source": receipt["source"],
        "build_receipt": {
            "path": "build-receipt.json",
            "sha256": _sha256(receipt_path),
        },
        "compose_inputs": {
            "infra/docker-compose.yml": _sha256(root / "infra/docker-compose.yml"),
            "tests/load/docker-compose.gate-c.yml": _sha256(
                root / "tests/load/docker-compose.gate-c.yml"
            ),
        },
        "threshold_sha256": _sha256(root / "tests/load/gate-c-thresholds.v1.json"),
        "workload_sha256": _sha256(root / "tests/load/gate-c-workload.v1.json"),
        "services": service_images,
    }
    _write_json(output / "image-lock.json", lock)


def _validated_lock(root: Path, lock_path: Path) -> dict[str, Any]:
    lock = _read_json(lock_path)
    if (
        lock.get("schema_version") != IMAGE_LOCK_SCHEMA
        or lock.get("process_version") != PROCESS_VERSION
    ):
        raise ValueError("Gate C image lock schema or process version is invalid")
    receipt_binding = lock.get("build_receipt")
    if not isinstance(receipt_binding, dict):
        raise ValueError("Gate C image lock does not bind a build receipt")
    receipt_path = lock_path.parent / str(receipt_binding.get("path"))
    if _sha256(receipt_path) != receipt_binding.get("sha256"):
        raise ValueError("Gate C build receipt digest does not match the image lock")
    receipt = _read_json(receipt_path)
    if (
        receipt.get("schema_version") != BUILD_RECEIPT_SCHEMA
        or receipt.get("reproducible") is not True
    ):
        raise ValueError("Gate C build receipt is incomplete")
    source = lock.get("source")
    if not isinstance(source, dict):
        raise ValueError("Gate C image lock source binding is missing")
    current_commit = _run(("git", "rev-parse", "HEAD"), cwd=root)
    current_tree = _run(("git", "rev-parse", "HEAD^{tree}"), cwd=root)
    if source.get("commit") != current_commit or source.get("tree") != current_tree:
        raise ValueError("Gate C image lock does not bind the current source")
    for relative, expected in lock["compose_inputs"].items():
        if _sha256(root / relative) != expected:
            raise ValueError(f"Gate C image lock compose input changed: {relative}")
    if _sha256(root / "tests/load/gate-c-thresholds.v1.json") != lock.get("threshold_sha256"):
        raise ValueError("Gate C frozen thresholds do not match the image lock")
    if _sha256(root / "tests/load/gate-c-workload.v1.json") != lock.get("workload_sha256"):
        raise ValueError("Gate C frozen workload does not match the image lock")
    return lock


def verify(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    lock = _validated_lock(root, args.image_lock.resolve())
    for service, binding in lock["services"].items():
        if _image_id(root, binding["reference"]) != binding["image_id"]:
            raise ValueError(f"Gate C image lock mismatch for service {service}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and verify reproducible Gate C image locks."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument(
        "--inputs",
        type=Path,
        default=Path("tests/load/gate-c-build-inputs.v1.json"),
    )
    build_parser.add_argument("--builder-a", required=True)
    build_parser.add_argument("--builder-b", required=True)
    build_parser.add_argument("--product-source-sha", required=True)
    build_parser.add_argument("--engineering-baseline-sha", required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.set_defaults(handler=build)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--image-lock", type=Path, required=True)
    verify_parser.set_defaults(handler=verify)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Gate C image lock error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
