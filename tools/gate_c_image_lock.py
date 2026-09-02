from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROCESS_VERSION = "Gate-C-12-v2.0"
SEALED_BUILD_INPUT_PROCESS_VERSION = "Gate-C-12-v1.0"
PRODUCT_SOURCE_SHA = "a57d0ce57427804ede3f3c620fda2a93b3a300ff"
IMAGE_LOCK_SCHEMA = "cybercontrol.gate-c-image-lock.v1"
BUILD_RECEIPT_SCHEMA = "cybercontrol.gate-c-build-receipt.v1"
SERVICE_DIGEST_MANIFEST_SCHEMA = "cybercontrol.gate-c-service-digest-manifest.v1"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
OFFLINE_MANIFEST_SCHEMA = "cybercontrol.gate-c-build-supply-chain.v1"
BASE_IMAGE_SPEC_SCHEMA = "cybercontrol.gate-c-build-base-images.v1"


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
DIAGNOSTIC_TARGET = BuildTarget(
    "rss-calibration",
    "tests/load/jemalloc-profile.Dockerfile",
    "cybercontrol/gate-c-jemalloc-profile",
)
BASE_IMAGE_ROLES = {
    "python": "python-base",
    "node": "node-builder-base",
    "nginx": "nginx-runtime-base",
    "postgres": "postgres-runtime",
    "keycloak": "keycloak-runtime",
    "buildkit": "buildkit-builder",
}


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


def _validate_inputs(path: Path) -> dict[str, Any]:  # noqa: C901, PLR0912
    inputs = _read_json(path)
    if inputs.get("schema_version") != "cybercontrol.gate-c-build-inputs.v1":
        raise ValueError("Gate C build inputs have the wrong schema")
    if inputs.get("process_version") != SEALED_BUILD_INPUT_PROCESS_VERSION:
        raise ValueError("Gate C build inputs have the wrong process version")
    buildkit = inputs.get("buildkit")
    if (
        not isinstance(buildkit, dict)
        or SHA256.fullmatch(str(buildkit.get("image_digest"))) is None
    ):
        raise ValueError("Gate C BuildKit image digest is missing or invalid")
    offline = inputs.get("offline_supply_chain")
    if not isinstance(offline, dict):
        raise ValueError("Gate C offline supply-chain binding is missing")
    for name in ("manifest", "base_images"):
        binding = offline.get(name)
        if not isinstance(binding, dict):
            raise ValueError(f"Gate C offline supply-chain {name} binding is missing")
        relative = binding.get("path")
        digest = binding.get("sha256")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ValueError(f"Gate C offline supply-chain {name} path is invalid")
        if not isinstance(digest, str) or HEX_SHA256.fullmatch(digest) is None:
            raise ValueError(f"Gate C offline supply-chain {name} SHA256 is invalid")
    roles = inputs.get("base_image_roles")
    if not isinstance(roles, dict) or roles != BASE_IMAGE_ROLES:
        raise ValueError("Gate C offline base image roles are incomplete")
    alpine = inputs.get("alpine")
    if not isinstance(alpine, dict):
        raise ValueError("Gate C Alpine runtime package lock is missing")
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


def _supply_chain(  # noqa: C901, PLR0912
    root: Path, inputs: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    offline = inputs["offline_supply_chain"]
    documents: dict[str, dict[str, Any]] = {}
    for name, schema in (
        ("manifest", OFFLINE_MANIFEST_SCHEMA),
        ("base_images", BASE_IMAGE_SPEC_SCHEMA),
    ):
        binding = offline[name]
        path = (root / binding["path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError(f"Gate C offline supply-chain {name} escaped the repository")
        if _sha256(path) != binding["sha256"]:
            raise ValueError(f"Gate C offline supply-chain {name} hash mismatch")
        document = _read_json(path)
        if document.get("schema_version") != schema:
            raise ValueError(f"Gate C offline supply-chain {name} schema is invalid")
        if document.get("process_version") != SEALED_BUILD_INPUT_PROCESS_VERSION:
            raise ValueError(f"Gate C offline supply-chain {name} process version is invalid")
        documents[name] = document
    manifest_images = documents["manifest"].get("base_images")
    specification_images = documents["base_images"].get("base_images")
    if not isinstance(manifest_images, list) or not isinstance(specification_images, list):
        raise ValueError("Gate C offline base image specification is empty")
    manifest_by_role = {
        image.get("role"): image for image in manifest_images if isinstance(image, dict)
    }
    if len(manifest_by_role) != len(manifest_images):
        raise ValueError("Gate C offline base image manifest roles are invalid or duplicated")
    for specification in specification_images:
        if not isinstance(specification, dict):
            raise ValueError("Gate C offline base image specification entry is invalid")
        manifest_image = manifest_by_role.get(specification.get("role"))
        if not isinstance(manifest_image, dict) or any(
            manifest_image.get(name) != value for name, value in specification.items()
        ):
            raise ValueError("Gate C offline base image manifest and specification differ")
    if set(manifest_by_role) != {
        image.get("role") for image in specification_images if isinstance(image, dict)
    }:
        raise ValueError("Gate C offline base image manifest and specification role sets differ")
    roles: dict[str, dict[str, Any]] = {}
    for image in specification_images:
        if not isinstance(image, dict) or not isinstance(image.get("role"), str):
            raise ValueError("Gate C offline base image entry is invalid")
        role = image["role"]
        if role in roles:
            raise ValueError(f"Gate C offline base image role is duplicated: {role}")
        if SHA256.fullmatch(str(image.get("digest"))) is None:
            raise ValueError(f"Gate C offline base image {role} content digest is invalid")
        if SHA256.fullmatch(str(image.get("oci_manifest_digest"))) is None:
            raise ValueError(f"Gate C offline base image {role} OCI digest is invalid")
        if not HEX_SHA256.fullmatch(str(image.get("archive_sha256"))):
            raise ValueError(f"Gate C offline base image {role} archive digest is invalid")
        roles[role] = image
    if set(roles) != set(BASE_IMAGE_ROLES.values()):
        raise ValueError("Gate C offline base image role set is incomplete")
    return documents["manifest"], roles


def _safe_extract_oci(archive_path: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError(f"temporary OCI context already exists: {destination}")
    destination.mkdir(parents=True)
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"OCI archive member escaped extraction root: {member.name}")
        archive.extractall(destination, filter="data")
    for name in ("oci-layout", "index.json"):
        if not (destination / name).is_file():
            raise ValueError(f"extracted OCI context lacks {name}")


def _validate_extracted_oci_context(destination: Path, image: dict[str, Any]) -> None:
    index = _read_json(destination / "index.json")
    manifests = index.get("manifests")
    if not isinstance(manifests, list):
        raise ValueError("extracted OCI context has no manifest index")
    expected_manifest = str(image["oci_manifest_digest"])
    matches = [
        item
        for item in manifests
        if isinstance(item, dict)
        and item.get("digest") == expected_manifest
        and item.get("platform") == {"architecture": "amd64", "os": "linux"}
    ]
    if len(matches) != 1:
        raise ValueError("extracted OCI context manifest binding is missing or ambiguous")
    manifest_path = destination / "blobs" / "sha256" / expected_manifest.split(":", 1)[1]
    if not manifest_path.is_file() or f"sha256:{_sha256(manifest_path)}" != expected_manifest:
        raise ValueError("extracted OCI context manifest blob digest does not match")
    manifest = _read_json(manifest_path)
    config = manifest.get("config")
    expected_config = str(image["config_digest"])
    if not isinstance(config, dict) or config.get("digest") != expected_config:
        raise ValueError("extracted OCI context config binding does not match")
    config_path = destination / "blobs" / "sha256" / expected_config.split(":", 1)[1]
    if not config_path.is_file() or f"sha256:{_sha256(config_path)}" != expected_config:
        raise ValueError("extracted OCI context config blob digest does not match")


def _prepare_oci_contexts(
    root: Path, temporary_root: Path, roles: dict[str, dict[str, Any]]
) -> dict[str, str]:
    contexts: dict[str, str] = {}
    context_roles = (
        ("python_base", "python-base"),
        ("node_base", "node-builder-base"),
        ("nginx_base", "nginx-runtime-base"),
    )
    for context_name, role in context_roles:
        image = roles[role]
        archive = (root / str(image["archive_path"])).resolve()
        if root not in archive.parents or not archive.is_file():
            raise ValueError(f"Gate C offline base image archive escaped repository: {role}")
        if _sha256(archive) != image["archive_sha256"]:
            raise ValueError(f"Gate C offline base image archive hash mismatch: {role}")
        destination = temporary_root / context_name
        _safe_extract_oci(archive, destination)
        _validate_extracted_oci_context(destination, image)
        relative = destination.relative_to(root).as_posix()
        contexts[context_name] = f"oci-layout://./{relative}@{image['oci_manifest_digest']}"
    return contexts


def _oci_context_reference(root: Path, path: Path) -> str:
    index = _read_json(path / "index.json")
    manifests = index.get("manifests")
    if not isinstance(manifests, list):
        raise ValueError(f"OCI context has no manifest index: {path}")
    matches = [
        item
        for item in manifests
        if isinstance(item, dict)
        and item.get("platform") == {"architecture": "amd64", "os": "linux"}
        and SHA256.fullmatch(str(item.get("digest"))) is not None
    ]
    if len(matches) != 1:
        raise ValueError(f"OCI context has an ambiguous linux/amd64 manifest: {path}")
    relative = path.relative_to(root).as_posix()
    return f"oci-layout://./{relative}@{matches[0]['digest']}"


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
    network_mode = str(item.get("HostConfig", {}).get("NetworkMode", ""))
    if not configured_image.endswith(f"@{expected_digest}") or image_id != expected_digest:
        raise ValueError(f"builder {builder} is not bound to the locked BuildKit content")
    if network_mode != "none":
        raise ValueError(f"builder {builder} is not isolated from the network")
    return {
        "name": builder,
        "driver": "docker-container",
        "buildkit_version": expected_version,
        "buildkit_image": configured_image,
        "buildkit_image_digest": image_id,
        "container_network_mode": network_mode,
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
    contexts: dict[str, str],
    backend_context_output: Path | None = None,
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
        "--network",
        "none",
        "--no-cache",
        "--provenance=false",
        "--file",
        target.dockerfile,
        "--tag",
        reference,
    ]
    arguments.extend(("--output", f"type=docker,name={reference},rewrite-timestamp=true"))
    if backend_context_output is not None:
        arguments.extend(
            (
                "--output",
                f"type=oci,dest={backend_context_output},tar=false,rewrite-timestamp=true",
            )
        )
    for name, value in sorted(contexts.items()):
        arguments.extend(("--build-context", f"{name}={value}"))
    build_arguments = {
        "SOURCE_DATE_EPOCH": str(source.source_date_epoch),
        "CYBERCONTROL_SOURCE_SHA": source.commit,
        "CYBERCONTROL_SOURCE_TREE": source.tree,
        "CYBERCONTROL_PRODUCT_SOURCE_SHA": source.product_source_sha,
        "CYBERCONTROL_ENGINEERING_BASELINE_SHA": source.engineering_baseline_sha,
        "CYBERCONTROL_PROCESS_VERSION": PROCESS_VERSION,
    }
    if target.name in {"backend", "mock-provider", "gate-c-load"}:
        build_arguments["PYTHON_IMAGE"] = "python_base"
    if target.name == "frontend":
        build_arguments["NODE_IMAGE"] = "node_base"
        build_arguments["NGINX_IMAGE"] = "nginx_base"
    for name, value in build_arguments.items():
        arguments.extend(("--build-arg", f"{name}={value}"))
    arguments.append(".")
    _run(arguments, cwd=root, capture=False)
    _assert_image_provenance(root, reference, source)
    return {"reference": reference, "image_id": _image_id(root, reference)}


def _build_diagnostic_target(
    root: Path,
    builder: str,
    arm: str,
    source: SourceBinding,
    contexts: dict[str, str],
    backend_context: Path,
) -> dict[str, str]:
    target = DIAGNOSTIC_TARGET
    reference = f"{target.repository}:{source.commit}-{arm}"
    arguments = [
        "docker",
        "buildx",
        "build",
        "--builder",
        builder,
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--no-cache",
        "--provenance=false",
        "--file",
        target.dockerfile,
        "--tag",
        reference,
        "--output",
        f"type=docker,name={reference},rewrite-timestamp=true",
        "--build-context",
        f"backend_image={_oci_context_reference(root, backend_context)}",
    ]
    for name, value in sorted(contexts.items()):
        arguments.extend(("--build-context", f"{name}={value}"))
    build_arguments = {
        "PYTHON_IMAGE": "python_base",
        "SOURCE_DATE_EPOCH": str(source.source_date_epoch),
        "CYBERCONTROL_SOURCE_SHA": source.commit,
        "CYBERCONTROL_SOURCE_TREE": source.tree,
        "CYBERCONTROL_PRODUCT_SOURCE_SHA": source.product_source_sha,
        "CYBERCONTROL_ENGINEERING_BASELINE_SHA": source.engineering_baseline_sha,
        "CYBERCONTROL_PROCESS_VERSION": PROCESS_VERSION,
    }
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


def _bound_image(
    binding: dict[str, str],
    *,
    role: str,
    source: SourceBinding,
    receipt_sha256: str,
) -> dict[str, str]:
    return {
        **binding,
        "source_sha": source.commit,
        "source_tree": source.tree,
        "product_source_sha": source.product_source_sha,
        "engineering_baseline_sha": source.engineering_baseline_sha,
        "process_version": PROCESS_VERSION,
        "image_role": role,
        "build_receipt_sha256": receipt_sha256,
        "content_digest": binding["image_id"],
    }


def build(args: argparse.Namespace) -> None:  # noqa: PLR0915
    root = args.root.resolve()
    inputs_path = (root / args.inputs).resolve()
    inputs = _validate_inputs(inputs_path)
    supply_chain_manifest, base_images = _supply_chain(root, inputs)
    source = _source_binding(root, args.product_source_sha, args.engineering_baseline_sha)
    versions = _docker_versions(root, inputs)
    builders = [
        _builder_fingerprint(root, args.builder_a, inputs),
        _builder_fingerprint(root, args.builder_b, inputs),
    ]
    if builders[0]["name"] == builders[1]["name"]:
        raise ValueError("Gate C reproducibility requires two independent builders")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    offline_context_root = root / "tmp" / f"gate-c-build-contexts-{source.commit}"
    backend_context_root = offline_context_root / "backend"
    if offline_context_root.exists():
        raise ValueError("temporary Gate C build context directory already exists")
    backend_context_root.mkdir(parents=True)
    backend_contexts = {arm: backend_context_root / arm for arm in ("a", "b")}
    arms: dict[str, dict[str, dict[str, str]]] = {}
    try:
        offline_contexts = _prepare_oci_contexts(root, offline_context_root, base_images)
        for arm, builder in (("a", args.builder_a), ("b", args.builder_b)):
            arms[arm] = {
                target.name: _build_target(
                    root,
                    target,
                    builder,
                    arm,
                    source,
                    offline_contexts,
                    backend_contexts[arm] if target.name == "backend" else None,
                )
                for target in TARGETS
            }
        for target in TARGETS:
            first = arms["a"][target.name]["image_id"]
            second = arms["b"][target.name]["image_id"]
            if first != second:
                raise ValueError(
                    f"independent builds for {target.name} produced different image IDs"
                )

        diagnostic_arms = {
            arm: _build_diagnostic_target(
                root,
                builder,
                arm,
                source,
                offline_contexts,
                backend_contexts[arm],
            )
            for arm, builder in (("a", args.builder_a), ("b", args.builder_b))
        }
    finally:
        if offline_context_root.parent != root / "tmp":
            raise RuntimeError("temporary offline OCI context escaped the repository tmp root")
        shutil.rmtree(offline_context_root)
    if diagnostic_arms["a"]["image_id"] != diagnostic_arms["b"]["image_id"]:
        raise ValueError("independent builds for rss-calibration produced different image IDs")

    canonical: dict[str, dict[str, str]] = {}
    for target in TARGETS:
        reference = f"{target.repository}:{source.commit}"
        _run(("docker", "image", "tag", arms["a"][target.name]["image_id"], reference), cwd=root)
        canonical[target.name] = {"reference": reference, "image_id": _image_id(root, reference)}
    diagnostic_reference = f"{DIAGNOSTIC_TARGET.repository}:{source.commit}"
    _run(
        (
            "docker",
            "image",
            "tag",
            diagnostic_arms["a"]["image_id"],
            diagnostic_reference,
        ),
        cwd=root,
    )
    diagnostic_image = {
        "role": "NON_ACCEPTANCE_DIAGNOSTIC",
        "reference": diagnostic_reference,
        "image_id": _image_id(root, diagnostic_reference),
    }

    postgres = _external_service(root, base_images[BASE_IMAGE_ROLES["postgres"]]["local_reference"])
    keycloak = _external_service(root, base_images[BASE_IMAGE_ROLES["keycloak"]]["local_reference"])
    raw_service_images = {
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
            "sealed_input_process_version": SEALED_BUILD_INPUT_PROCESS_VERSION,
        },
        "offline_supply_chain": {
            "sealed_input_process_version": SEALED_BUILD_INPUT_PROCESS_VERSION,
            "manifest": {
                "path": inputs["offline_supply_chain"]["manifest"]["path"],
                "sha256": inputs["offline_supply_chain"]["manifest"]["sha256"],
                "asset_count": sum(
                    len(supply_chain_manifest.get(section, []))
                    for section in (
                        "sources",
                        "patches",
                        "apk",
                        "python_wheels",
                        "pnpm_store",
                        "oci_layouts",
                        "licenses",
                    )
                ),
            },
            "base_images": {
                "path": inputs["offline_supply_chain"]["base_images"]["path"],
                "sha256": inputs["offline_supply_chain"]["base_images"]["sha256"],
                "roles": base_images,
            },
            "network_policy": "BUILDKIT_CONTAINER_NONE_AND_RUN_NETWORK_NONE",
        },
        "independent_builds": arms,
        "diagnostic_independent_builds": {"rss-calibration": diagnostic_arms},
        "reproducible": True,
    }
    receipt_path = output / "build-receipt.json"
    _write_json(receipt_path, receipt)
    receipt_sha256 = _sha256(receipt_path)
    service_images = {
        name: _bound_image(
            binding,
            role=f"FORMAL_SERVICE:{name}",
            source=source,
            receipt_sha256=receipt_sha256,
        )
        for name, binding in raw_service_images.items()
    }
    diagnostic_image = _bound_image(
        diagnostic_image,
        role="NON_ACCEPTANCE_DIAGNOSTIC:rss-calibration",
        source=source,
        receipt_sha256=receipt_sha256,
    )
    common_lock = {
        "schema_version": IMAGE_LOCK_SCHEMA,
        "process_version": PROCESS_VERSION,
        "generated_at_utc": generated,
        "source": receipt["source"],
        "build_receipt": {
            "path": "build-receipt.json",
            "sha256": receipt_sha256,
        },
        "compose_inputs": {
            "infra/docker-compose.yml": _sha256(root / "infra/docker-compose.yml"),
            "tests/load/docker-compose.gate-c.yml": _sha256(
                root / "tests/load/docker-compose.gate-c.yml"
            ),
            "tests/load/docker-compose.gate-c-rss-calibration.yml": _sha256(
                root / "tests/load/docker-compose.gate-c-rss-calibration.yml"
            ),
            "tests/load/docker-compose.gate-c-bounded-memory-inventory.yml": _sha256(
                root / "tests/load/docker-compose.gate-c-bounded-memory-inventory.yml"
            ),
            "tests/load/docker-compose.gate-c-event-loop-heartbeat.yml": _sha256(
                root / "tests/load/docker-compose.gate-c-event-loop-heartbeat.yml"
            ),
            "tests/load/docker-compose.gate-c-memory-checkpoints.yml": _sha256(
                root / "tests/load/docker-compose.gate-c-memory-checkpoints.yml"
            ),
            "tests/load/docker-compose.gate-c-jemalloc-profile.yml": _sha256(
                root / "tests/load/docker-compose.gate-c-jemalloc-profile.yml"
            ),
        },
        "threshold_sha256": _sha256(root / "tests/load/gate-c-thresholds.v1.json"),
        "workload_sha256": _sha256(root / "tests/load/gate-c-workload.v1.json"),
    }
    normal_lock = {
        **common_lock,
        "track": "FORMAL_NORMAL",
        "services": service_images,
        "diagnostic_images": {},
    }
    diagnostic_lock = {
        **common_lock,
        "track": "NON_ACCEPTANCE_DIAGNOSTIC",
        "services": service_images,
        "diagnostic_images": {"rss-calibration": diagnostic_image},
        "diagnostic_roles": {
            "bounded-inventory": {
                **service_images["api"],
                "image_role": "NON_ACCEPTANCE_DIAGNOSTIC_OVERLAY:bounded-inventory",
                "base_service": "api",
            }
        },
    }
    compatibility_lock = {
        **common_lock,
        "track": "COMPATIBILITY_AGGREGATE",
        "services": service_images,
        "diagnostic_images": {"rss-calibration": diagnostic_image},
    }
    _write_json(output / "normal-image-lock.json", normal_lock)
    _write_json(output / "diagnostic-image-lock.json", diagnostic_lock)
    _write_json(output / "image-lock.json", compatibility_lock)
    digest_manifest = {
        "schema_version": SERVICE_DIGEST_MANIFEST_SCHEMA,
        "process_version": PROCESS_VERSION,
        "generated_at_utc": generated,
        "source": receipt["source"],
        "build_receipt": common_lock["build_receipt"],
        "normal_services": service_images,
        "diagnostic_roles": {"rss-calibration": diagnostic_image},
    }
    _write_json(output / "all-service-digest-manifest.json", digest_manifest)


def _validated_lock(root: Path, lock_path: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    root = root.resolve()
    lock_path = lock_path.resolve()
    lock = _read_json(lock_path)
    if (
        lock.get("schema_version") != IMAGE_LOCK_SCHEMA
        or lock.get("process_version") != PROCESS_VERSION
    ):
        raise ValueError("Gate C image lock schema or process version is invalid")
    receipt_binding = lock.get("build_receipt")
    if not isinstance(receipt_binding, dict):
        raise ValueError("Gate C image lock does not bind a build receipt")
    receipt_relative = Path(str(receipt_binding.get("path")))
    if receipt_relative.is_absolute() or ".." in receipt_relative.parts:
        raise ValueError("Gate C build receipt path is invalid")
    receipt_path = (lock_path.parent / receipt_relative).resolve()
    if lock_path.parent not in receipt_path.parents or not receipt_path.is_file():
        raise ValueError("Gate C build receipt escaped the lock directory")
    if _sha256(receipt_path) != receipt_binding.get("sha256"):
        raise ValueError("Gate C build receipt digest does not match the image lock")
    receipt = _read_json(receipt_path)
    if (
        receipt.get("schema_version") != BUILD_RECEIPT_SCHEMA
        or receipt.get("process_version") != PROCESS_VERSION
        or receipt.get("reproducible") is not True
    ):
        raise ValueError("Gate C build receipt is incomplete")
    source = lock.get("source")
    if not isinstance(source, dict):
        raise ValueError("Gate C image lock source binding is missing")
    if receipt.get("source") != source:
        raise ValueError("Gate C build receipt source does not match the image lock")
    expected_source_keys = {
        "commit",
        "tree",
        "product_source_sha",
        "engineering_baseline_sha",
        "source_date_epoch",
    }
    if set(source) != expected_source_keys:
        raise ValueError("Gate C image lock source binding is incomplete")
    if (
        GIT_SHA.fullmatch(str(source.get("commit"))) is None
        or GIT_SHA.fullmatch(str(source.get("tree"))) is None
        or source.get("product_source_sha") != PRODUCT_SOURCE_SHA
        or source.get("engineering_baseline_sha") != source.get("commit")
        or not isinstance(source.get("source_date_epoch"), int)
    ):
        raise ValueError("Gate C image lock source binding is invalid")
    current_commit = _run(("git", "rev-parse", "HEAD"), cwd=root)
    current_tree = _run(("git", "rev-parse", "HEAD^{tree}"), cwd=root)
    if source.get("commit") != current_commit or source.get("tree") != current_tree:
        raise ValueError("Gate C image lock does not bind the current source")

    inputs_binding = receipt.get("inputs")
    if not isinstance(inputs_binding, dict):
        raise ValueError("Gate C build receipt does not bind build inputs")
    inputs_relative = Path(str(inputs_binding.get("path")))
    if inputs_relative.is_absolute() or ".." in inputs_relative.parts:
        raise ValueError("Gate C build input path is invalid")
    inputs_path = (root / inputs_relative).resolve()
    if root not in inputs_path.parents or not inputs_path.is_file():
        raise ValueError("Gate C build input escaped the repository")
    if _sha256(inputs_path) != inputs_binding.get("sha256"):
        raise ValueError("Gate C build input hash does not match the receipt")
    inputs = _validate_inputs(inputs_path)
    if inputs_binding.get("document") != inputs:
        raise ValueError("Gate C build input document does not match the receipt")
    if inputs_binding.get("sealed_input_process_version") != SEALED_BUILD_INPUT_PROCESS_VERSION:
        raise ValueError("Gate C build receipt does not identify its sealed input process version")
    _supply_chain(root, inputs)
    receipt_offline = receipt.get("offline_supply_chain")
    if not isinstance(receipt_offline, dict):
        raise ValueError("Gate C build receipt lacks the offline supply-chain binding")
    if receipt_offline.get("sealed_input_process_version") != SEALED_BUILD_INPUT_PROCESS_VERSION:
        raise ValueError("Gate C receipt offline supply-chain process version is invalid")
    for name in ("manifest", "base_images"):
        recorded = receipt_offline.get(name)
        expected = inputs["offline_supply_chain"][name]
        if not isinstance(recorded, dict):
            raise ValueError(f"Gate C receipt offline {name} binding is missing")
        if recorded.get("path") != expected["path"] or recorded.get("sha256") != expected["sha256"]:
            raise ValueError(f"Gate C receipt offline {name} binding does not match build inputs")
    if receipt_offline.get("network_policy") != "BUILDKIT_CONTAINER_NONE_AND_RUN_NETWORK_NONE":
        raise ValueError("Gate C build receipt network isolation is invalid")

    independent = receipt.get("independent_builds")
    if not isinstance(independent, dict) or set(independent) != {"a", "b"}:
        raise ValueError("Gate C build receipt independent build arms are incomplete")
    if set(independent["a"]) != {target.name for target in TARGETS} or set(independent["b"]) != {
        target.name for target in TARGETS
    }:
        raise ValueError("Gate C build receipt target set is incomplete")
    for target in TARGETS:
        first = independent["a"].get(target.name)
        second = independent["b"].get(target.name)
        if (
            not isinstance(first, dict)
            or not isinstance(second, dict)
            or first.get("image_id") != second.get("image_id")
            or SHA256.fullmatch(str(first.get("image_id"))) is None
        ):
            raise ValueError(f"Gate C build receipt is not reproducible for {target.name}")
    environment = receipt.get("environment")
    builders = environment.get("builders") if isinstance(environment, dict) else None
    if not isinstance(builders, list) or len(builders) != 2:
        raise ValueError("Gate C build receipt builder evidence is incomplete")
    builder_names: set[str] = set()
    for builder in builders:
        if (
            not isinstance(builder, dict)
            or builder.get("driver") != "docker-container"
            or builder.get("container_network_mode") != "none"
            or SHA256.fullmatch(str(builder.get("buildkit_image_digest"))) is None
            or not isinstance(builder.get("name"), str)
            or not builder["name"]
        ):
            raise ValueError("Gate C build receipt builder isolation is invalid")
        builder_names.add(builder["name"])
    if len(builder_names) != 2:
        raise ValueError("Gate C build receipt builders are not independent")
    diagnostic_builds = receipt.get("diagnostic_independent_builds")
    rss_builds = (
        diagnostic_builds.get("rss-calibration") if isinstance(diagnostic_builds, dict) else None
    )
    if (
        not isinstance(rss_builds, dict)
        or set(rss_builds) != {"a", "b"}
        or not isinstance(rss_builds["a"], dict)
        or not isinstance(rss_builds["b"], dict)
        or rss_builds["a"].get("image_id") != rss_builds["b"].get("image_id")
        or SHA256.fullmatch(str(rss_builds["a"].get("image_id"))) is None
    ):
        raise ValueError("Gate C diagnostic build receipt is not reproducible")

    compose_inputs = lock.get("compose_inputs")
    if not isinstance(compose_inputs, dict) or not compose_inputs:
        raise ValueError("Gate C image lock compose inputs are missing")
    for relative, expected in compose_inputs.items():
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ValueError("Gate C image lock compose input path is invalid")
        if _sha256(root / relative) != expected:
            raise ValueError(f"Gate C image lock compose input changed: {relative}")
    if _sha256(root / "tests/load/gate-c-thresholds.v1.json") != lock.get("threshold_sha256"):
        raise ValueError("Gate C frozen thresholds do not match the image lock")
    if _sha256(root / "tests/load/gate-c-workload.v1.json") != lock.get("workload_sha256"):
        raise ValueError("Gate C frozen workload does not match the image lock")

    track = lock.get("track")
    if track not in {"FORMAL_NORMAL", "NON_ACCEPTANCE_DIAGNOSTIC", "COMPATIBILITY_AGGREGATE"}:
        raise ValueError("Gate C image lock track is invalid")
    services = lock.get("services")
    if not isinstance(services, dict) or not services:
        raise ValueError("Gate C image lock services are missing")
    receipt_digest = str(receipt_binding.get("sha256"))
    for service, binding in services.items():
        if not isinstance(binding, dict):
            raise ValueError(f"Gate C image lock service {service} binding is invalid")
        expected = {
            "source_sha": source["commit"],
            "source_tree": source["tree"],
            "product_source_sha": source["product_source_sha"],
            "engineering_baseline_sha": source["engineering_baseline_sha"],
            "process_version": PROCESS_VERSION,
            "build_receipt_sha256": receipt_digest,
        }
        if any(binding.get(name) != value for name, value in expected.items()):
            raise ValueError(
                f"Gate C image lock service {service} source or receipt binding is invalid"
            )
        if binding.get("image_role") != f"FORMAL_SERVICE:{service}":
            raise ValueError(f"Gate C image lock service {service} role is invalid")
        if (
            SHA256.fullmatch(str(binding.get("image_id"))) is None
            or binding.get("content_digest") != binding.get("image_id")
            or not isinstance(binding.get("reference"), str)
        ):
            raise ValueError(f"Gate C image lock service {service} content binding is invalid")

    diagnostic_images = lock.get("diagnostic_images")
    if not isinstance(diagnostic_images, dict):
        raise ValueError("Gate C diagnostic image bindings are invalid")
    if track == "FORMAL_NORMAL" and diagnostic_images:
        raise ValueError("Gate C formal normal lock contains diagnostic images")
    if track == "NON_ACCEPTANCE_DIAGNOSTIC" and not diagnostic_images:
        raise ValueError("Gate C diagnostic lock contains no diagnostic image")
    for role, binding in diagnostic_images.items():
        if not isinstance(binding, dict):
            raise ValueError(f"Gate C diagnostic image {role} binding is invalid")
        expected = {
            "source_sha": source["commit"],
            "source_tree": source["tree"],
            "product_source_sha": source["product_source_sha"],
            "engineering_baseline_sha": source["engineering_baseline_sha"],
            "process_version": PROCESS_VERSION,
            "build_receipt_sha256": receipt_digest,
        }
        if any(binding.get(name) != value for name, value in expected.items()):
            raise ValueError(f"Gate C diagnostic image {role} source or receipt binding is invalid")
        if binding.get("image_role") != f"NON_ACCEPTANCE_DIAGNOSTIC:{role}":
            raise ValueError(f"Gate C diagnostic image {role} has an invalid role")
        if (
            SHA256.fullmatch(str(binding.get("image_id"))) is None
            or binding.get("content_digest") != binding.get("image_id")
            or not isinstance(binding.get("reference"), str)
        ):
            raise ValueError(f"Gate C diagnostic image {role} content binding is invalid")
    return lock


def verify(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    lock = _validated_lock(root, args.image_lock.resolve())
    formal_image_ids: set[str] = set()
    for service, binding in lock["services"].items():
        if _image_id(root, binding["reference"]) != binding["image_id"]:
            raise ValueError(f"Gate C image lock mismatch for service {service}")
        formal_image_ids.add(str(binding["image_id"]))
    for role, binding in lock.get("diagnostic_images", {}).items():
        if binding.get("image_role") != f"NON_ACCEPTANCE_DIAGNOSTIC:{role}":
            raise ValueError(f"Gate C diagnostic image {role} has an invalid role")
        if str(binding.get("image_id")) in formal_image_ids:
            raise ValueError(f"Gate C diagnostic image {role} impersonates a formal service")
        if _image_id(root, binding["reference"]) != binding["image_id"]:
            raise ValueError(f"Gate C image lock mismatch for diagnostic image {role}")


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
