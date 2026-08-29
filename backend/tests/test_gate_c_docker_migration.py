from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import gate_c_docker_migration as migration  # noqa: E402


def test_authorized_cleanup_and_recreated_container_are_not_missing() -> None:
    reference = [
        "a" * 64 + "|deleted|image:old",
        "b" * 64 + "|recreated|image:same",
    ]
    current = [{"ID": "c" * 64, "Names": "recreated", "Image": "image:same"}]
    cleanup = {"actions": {"removed_containers": ["a" * 64]}}

    result = migration._container_differences(reference, current, cleanup)

    assert result["unexplained_missing"] == []
    assert {item["classification"] for item in result["classified_missing"]} == {
        "AUTHORIZED_CLEANUP",
        "SAME_NAME_IMAGE_RECREATED",
    }


def test_system_network_id_difference_is_non_blocking() -> None:
    result = migration._network_differences(
        ["old|bridge|bridge"],
        [{"ID": "new", "Name": "bridge", "Driver": "bridge"}],
        {"actions": {"removed_networks": []}},
        {"system_networks": ["bridge", "host", "none"]},
    )

    assert result["unexplained_missing"] == []
    assert result["classified_missing"][0]["classification"] == "SYSTEM_NETWORK_DIFFERENCE"


def test_custom_network_loss_is_blocking() -> None:
    result = migration._network_differences(
        ["old|application_default|bridge"],
        [],
        {"actions": {"removed_networks": []}},
        {"system_networks": ["bridge", "host", "none"]},
    )

    assert result["unexplained_missing"] == ["old|application_default|bridge"]


def test_formal_volume_loss_cannot_be_hidden_by_unrelated_cleanup() -> None:
    result = migration._volume_differences(
        ["formal", "diagnostic"],
        [{"Name": "diagnostic"}],
        {"actions": {"removed_volumes": ["unrelated"]}},
    )

    assert result["unexplained_missing"] == ["formal"]


def test_allowed_transient_image_must_be_explicit() -> None:
    identifier = "sha256:" + "a" * 64
    result = migration._image_differences(
        [f"{identifier}|quality:temp"],
        [],
        {"allowed_missing_image_contents": [{"image_id": identifier, "classification": "TEMP"}]},
    )

    assert result["unexplained_missing"] == []
    assert result["classified_missing"][0]["classification"] == "TEMP"
