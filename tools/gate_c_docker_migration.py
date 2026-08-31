from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROCESS_VERSION = "Gate-C-12-v1.0"
REPORT_SCHEMA = "cybercontrol.docker-migration-validation.v1"
POLICY_SCHEMA = "cybercontrol.docker-migration-policy.v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} must contain a JSON object")
        values.append(value)
    return values


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(arguments: Sequence[str]) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed local CLI arguments only.
        list(arguments), check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _validate_document(value: dict[str, Any], schema: str, label: str) -> None:
    if value.get("schema_version") != schema:
        raise ValueError(f"{label} has the wrong schema")
    if value.get("process_version") != PROCESS_VERSION:
        raise ValueError(f"{label} has the wrong process version")


def _reference_inventory(path: Path) -> dict[str, list[str]]:
    value = _read_json(path)
    for key in ("containers", "images", "volumes", "networks"):
        if not isinstance(value.get(key), list) or not all(
            isinstance(item, str) for item in value[key]
        ):
            raise ValueError(f"reference inventory {key} is invalid")
    return {key: list(value[key]) for key in ("containers", "images", "volumes", "networks")}


def _current_inventory(path: Path) -> dict[str, Any]:
    containers = _read_ndjson(path / "containers.ndjson")
    images = _read_ndjson(path / "images.ndjson")
    volumes = _read_ndjson(path / "volumes.ndjson")
    networks = _read_ndjson(path / "networks.ndjson")
    return {
        "containers": containers,
        "images": images,
        "volumes": volumes,
        "networks": networks,
        "docker_info": _read_json(path / "docker-info.json"),
        "buildx_inspect": (path / "buildx-inspect.txt").read_text(encoding="utf-8-sig"),
    }


def _split_reference(value: str, parts: int) -> tuple[str, ...]:
    result = tuple(value.split("|", parts - 1))
    if len(result) != parts:
        raise ValueError(f"invalid reference inventory entry: {value}")
    return result


def _prefix_matches(identifier: str, candidates: set[str]) -> bool:
    return any(
        identifier.startswith(candidate) or candidate.startswith(identifier)
        for candidate in candidates
    )


def _container_differences(
    reference: list[str], current: list[dict[str, Any]], cleanup: dict[str, Any]
) -> dict[str, Any]:
    current_exact = {f"{item['ID']}|{item['Names']}|{item['Image']}" for item in current}
    current_by_name = {str(item["Names"]): item for item in current}
    authorized = set(map(str, cleanup["actions"]["removed_containers"]))
    entries: list[dict[str, Any]] = []
    unexplained: list[str] = []
    for raw in reference:
        identifier, name, image = _split_reference(raw, 3)
        if raw in current_exact:
            continue
        if identifier in authorized:
            entries.append({"reference": raw, "classification": "AUTHORIZED_CLEANUP"})
            continue
        replacement = current_by_name.get(name)
        if replacement is not None and replacement.get("Image") == image:
            entries.append(
                {
                    "reference": raw,
                    "classification": "SAME_NAME_IMAGE_RECREATED",
                    "current_id": replacement.get("ID"),
                }
            )
            continue
        unexplained.append(raw)
    return {"classified_missing": entries, "unexplained_missing": unexplained}


def _image_differences(
    reference: list[str], current: list[dict[str, Any]], policy: dict[str, Any]
) -> dict[str, Any]:
    current_ids = {str(item["ID"]) for item in current}
    allowed = {str(item["image_id"]): item for item in policy["allowed_missing_image_contents"]}
    classified: list[dict[str, Any]] = []
    unexplained: list[str] = []
    for raw in reference:
        identifier, reference_name = _split_reference(raw, 2)
        if identifier in current_ids:
            continue
        disposition = allowed.get(identifier)
        if disposition is None:
            unexplained.append(raw)
            continue
        classified.append({"reference": raw, "reference_name": reference_name, **disposition})
    return {"classified_missing": classified, "unexplained_missing": unexplained}


def _volume_differences(
    reference: list[str], current: list[dict[str, Any]], cleanup: dict[str, Any]
) -> dict[str, Any]:
    current_names = {str(item["Name"]) for item in current}
    authorized = set(map(str, cleanup["actions"]["removed_volumes"]))
    missing = set(reference) - current_names
    return {
        "authorized_cleanup": sorted(missing & authorized),
        "unexplained_missing": sorted(missing - authorized),
    }


def _network_differences(
    reference: list[str],
    current: list[dict[str, Any]],
    cleanup: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    current_by_name = {str(item["Name"]): item for item in current}
    authorized = set(map(str, cleanup["actions"]["removed_networks"]))
    system = set(map(str, policy["system_networks"]))
    classified: list[dict[str, Any]] = []
    unexplained: list[str] = []
    for raw in reference:
        identifier, name, driver = _split_reference(raw, 3)
        active = current_by_name.get(name)
        if active is not None and active.get("Driver") == driver:
            if name in system and active.get("ID") != identifier:
                classified.append(
                    {
                        "reference": raw,
                        "classification": "SYSTEM_NETWORK_DIFFERENCE",
                        "current_id": active.get("ID"),
                    }
                )
            continue
        if _prefix_matches(identifier, authorized):
            classified.append({"reference": raw, "classification": "AUTHORIZED_CLEANUP"})
            continue
        unexplained.append(raw)
    return {"classified_missing": classified, "unexplained_missing": unexplained}


def _environment(
    current: dict[str, Any], policy: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any]:
    expected = policy["expected_environment"]
    info = current["docker_info"]
    buildx = _run(("docker", "buildx", "version")).split()[1]
    server = _run(("docker", "version", "--format", "{{.Server.Version}}"))
    running = int(_run(("docker", "info", "--format", "{{.ContainersRunning}}")))
    buildkit = str(current["buildx_inspect"])
    checks = {
        "docker_server_version": server == expected["docker_server_version"],
        "docker_buildx_version": buildx == expected["docker_buildx_version"],
        "buildkit_version": expected["buildkit_version"] in buildkit,
        "docker_root": info.get("DockerRootDir") == "/var/lib/docker",
        "containerd_snapshotter": bool(settings.get("UseContainerdSnapshotter"))
        is expected["containerd_snapshotter"],
        "custom_wsl_distro_dir": settings.get("CustomWslDistroDir")
        == expected["custom_wsl_distro_dir"],
        "zero_running_containers": running == 0,
    }
    return {
        "checks": checks,
        "observed": {
            "docker_server_version": server,
            "docker_buildx_version": buildx,
            "docker_root": info.get("DockerRootDir"),
            "storage_driver": info.get("Driver"),
            "running_containers": running,
            "custom_wsl_distro_dir": settings.get("CustomWslDistroDir"),
            "containerd_snapshotter": settings.get("UseContainerdSnapshotter"),
        },
        "passed": all(checks.values()),
    }


def validate(args: argparse.Namespace) -> None:
    policy = _read_json(args.policy)
    _validate_document(policy, POLICY_SCHEMA, "migration policy")
    cleanup = _read_json(args.cleanup_receipt)
    _validate_document(
        cleanup, "cybercontrol.gate-c12-capacity-cleanup-receipt.v1", "cleanup receipt"
    )
    if cleanup.get("actions", {}).get("prune_used") is not False:
        raise ValueError("cleanup receipt does not prove that prune was prohibited")
    if cleanup["actions"].get("formal_volumes_removed") is not False:
        raise ValueError("cleanup receipt reports a formal volume removal")

    checkpoint = _read_json(args.checkpoint_verification)
    if (
        checkpoint.get("process_version") != PROCESS_VERSION
        or checkpoint.get("valid") is not True
        or not all(item.get("sha256_match") is True for item in checkpoint.get("checks", []))
        or not all(
            item.get("is_read_only") is True
            for item in checkpoint.get("post_verification_attributes", [])
        )
    ):
        raise ValueError("recovery checkpoint verification is incomplete")

    volume_copy = _read_json(args.volume_copy_verification)
    _validate_document(
        volume_copy,
        "cybercontrol.docker-migration-volume-copy-verification.v1",
        "volume copy verification",
    )
    if volume_copy.get("result") != "PASS":
        raise ValueError("formal volume copy verification did not pass")

    reference = _reference_inventory(args.reference_inventory)
    current = _current_inventory(args.current_inventory)
    settings = _read_json(args.docker_settings)
    formal = list(map(str, policy["required_formal_volumes"]))
    current_volume_names = {str(item["Name"]) for item in current["volumes"]}
    copied = {str(item["volume"]): item for item in volume_copy.get("volumes", [])}
    formal_checks = {
        name: {
            "present": name in current_volume_names,
            "copy_verification": copied.get(name, {}).get("copy_verification"),
            "content_sha256": copied.get(name, {}).get("source", {}).get("content_sha256"),
        }
        for name in formal
    }
    formal_passed = all(
        item["present"]
        and item["copy_verification"] == "PASS"
        and SHA256.fullmatch(str(item["content_sha256"])) is not None
        for item in formal_checks.values()
    )

    differences = {
        "containers": _container_differences(
            reference["containers"], current["containers"], cleanup
        ),
        "images": _image_differences(reference["images"], current["images"], policy),
        "volumes": _volume_differences(reference["volumes"], current["volumes"], cleanup),
        "networks": _network_differences(
            reference["networks"], current["networks"], cleanup, policy
        ),
    }
    unexplained = {
        name: value["unexplained_missing"]
        for name, value in differences.items()
        if value["unexplained_missing"]
    }
    environment = _environment(current, policy, settings)
    passed = formal_passed and not unexplained and environment["passed"]
    generated = datetime.now(UTC).isoformat()

    common = {
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_INFRASTRUCTURE_VERIFICATION",
        "generated_at_utc": generated,
        "gate_c_attempts_appended": False,
        "formal_state_changed": False,
    }
    source_documents = {
        "reference_inventory": {
            "path": str(args.reference_inventory),
            "sha256": _sha256(args.reference_inventory),
        },
        "cleanup_receipt": {
            "path": str(args.cleanup_receipt),
            "sha256": _sha256(args.cleanup_receipt),
        },
        "checkpoint_verification": {
            "path": str(args.checkpoint_verification),
            "sha256": _sha256(args.checkpoint_verification),
        },
        "volume_copy_verification": {
            "path": str(args.volume_copy_verification),
            "sha256": _sha256(args.volume_copy_verification),
        },
        "policy": {"path": str(args.policy), "sha256": _sha256(args.policy)},
    }
    report = {
        "schema_version": REPORT_SCHEMA,
        **common,
        "source_documents": source_documents,
        "reference_counts": {name: len(items) for name, items in reference.items()},
        "current_counts": {
            name: len(current[name]) for name in ("containers", "images", "volumes", "networks")
        },
        "environment": environment,
        "formal_volume_result": "PASS" if formal_passed else "FAIL",
        "unexplained_differences": unexplained,
        "result": "MIGRATION_VALIDATED" if passed else "MIGRATION_REJECTED",
    }
    difference_report = {
        "schema_version": "cybercontrol.docker-migration-differences.v1",
        **common,
        "rules": {
            "system_network_id_changes": "SYSTEM_NETWORK_DIFFERENCE_NON_BLOCKING",
            "authorized_cleanup": "NON_BLOCKING_WITH_RECEIPT",
            "same_name_image_container_recreation": "NON_BLOCKING",
            "unexplained_custom_network_or_object_loss": "BLOCKING",
        },
        "differences": differences,
        "result": "PASS" if not unexplained else "FAIL",
    }
    formal_report = {
        "schema_version": "cybercontrol.docker-migration-formal-volumes.v1",
        **common,
        "required_count": len(formal),
        "verified_count": sum(
            1 for value in formal_checks.values() if value["copy_verification"] == "PASS"
        ),
        "checks": formal_checks,
        "source_access": "READ_ONLY_VOLUME_MOUNT",
        "temporary_copy_cleanup_verified": volume_copy.get("temporary_volumes_remaining") == [],
        "result": "PASS" if formal_passed else "FAIL",
    }
    rollback = {
        "schema_version": "cybercontrol.docker-migration-rollback-credential.v1",
        **common,
        "checkpoint": source_documents["checkpoint_verification"],
        "checkpoint_valid": True,
        "copy_before_switch": True,
        "preserve_failed_f_drive_scene": True,
        "overwrite_source_prohibited": True,
        "steps": [
            "stop Docker Desktop and terminate WSL",
            "preserve the failed F-drive state without modification",
            "copy each read-only checkpoint VHDX into a new recovery directory",
            "verify copied VHDX length and SHA256 before switching",
            "switch CustomWslDistroDir to the new recovery directory",
            "start Docker and repeat object, environment and formal-volume verification",
        ],
    }

    args.output.mkdir(parents=True, exist_ok=True)
    outputs = {
        "migration-validation-report.json": report,
        "migration-difference-report.json": difference_report,
        "formal-volume-report.json": formal_report,
        "rollback-credential.json": rollback,
    }
    for name, document in outputs.items():
        _write_json(args.output / name, document)
    manifest = {
        "schema_version": "cybercontrol.evidence-content-manifest.v1",
        **common,
        "files": [
            {"path": name, "sha256": _sha256(args.output / name)} for name in sorted(outputs)
        ],
        "result": report["result"],
    }
    _write_json(args.output / "content-manifest.json", manifest)
    if not passed:
        raise ValueError(f"Docker migration rejected: {unexplained or environment['checks']}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Docker Desktop storage migration.")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--reference-inventory", type=Path, required=True)
    parser.add_argument("--current-inventory", type=Path, required=True)
    parser.add_argument("--cleanup-receipt", type=Path, required=True)
    parser.add_argument("--checkpoint-verification", type=Path, required=True)
    parser.add_argument("--volume-copy-verification", type=Path, required=True)
    parser.add_argument("--docker-settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        validate(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Docker migration validation error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
