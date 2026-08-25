from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from liyans.infrastructure.observability.jemalloc_profiles import (
    JemallocProfileController,
    JemallocProfileRejected,
)
from liyans.infrastructure.observability.metrics import PlatformMetrics

SOURCE = {
    "source_sha": "a" * 40,
    "source_tree": "b" * 40,
    "product_source_sha": "c" * 40,
    "engineering_baseline_sha": "d" * 40,
    "process_version": "Gate-C-12-v1.0",
    "library_sha256": "e" * 64,
    "library_build_id": "f" * 40,
    "image_id": "sha256:" + "1" * 64,
    "image_digest": "sha256:" + "2" * 64,
}


class FakeMallctl:
    def __init__(self) -> None:
        self.values = {
            "config.prof": True,
            "config.stats": True,
            "opt.prof": True,
            "prof.active": False,
        }
        self.calls: list[tuple[str, object]] = []
        self.reset_result = 0
        self.write_results: dict[bool, int] = {}
        self.dump_result = 0

    def read_bool(self, name: str) -> bool | None:
        self.calls.append(("read", name))
        return self.values.get(name)

    def reset(self) -> int:
        self.calls.append(("reset", None))
        return self.reset_result

    def write_bool(self, name: str, value: bool) -> int:
        self.calls.append(("write", (name, value)))
        result = self.write_results.get(value, 0)
        if result == 0:
            self.values[name] = value
        return result

    def dump(self, path: Path) -> int:
        self.calls.append(("dump", path.name))
        if self.dump_result == 0:
            path.write_bytes(b"heap-profile-fixture")
        return self.dump_result


def _controller(
    directory: Path | None,
    mallctl: FakeMallctl | None = None,
) -> JemallocProfileController:
    return JemallocProfileController(
        directory=directory,
        source_metadata=SOURCE if directory is not None else {},
        mallctl=mallctl or FakeMallctl(),  # type: ignore[arg-type]
        signal_number=12,
    )


def _install_signal_stubs(monkeypatch) -> dict[object, object]:
    loop = asyncio.get_running_loop()
    handlers: dict[object, object] = {}
    monkeypatch.setattr(
        loop,
        "add_signal_handler",
        lambda key, value: handlers.update({key: value}),
    )
    monkeypatch.setattr(
        loop,
        "remove_signal_handler",
        lambda key: handlers.pop(key, None) is not None,
    )
    return handlers


@pytest.mark.asyncio
async def test_disabled_controller_registers_no_signal_or_transition(monkeypatch) -> None:
    loop = asyncio.get_running_loop()
    signal_calls = 0

    def reject_signal(*_args) -> None:
        nonlocal signal_calls
        signal_calls += 1

    monkeypatch.setattr(loop, "add_signal_handler", reject_signal)
    controller = _controller(None)

    await controller.start()
    await controller.close()

    assert controller.enabled is False
    assert controller.transition_task is None
    assert controller.state == "inactive"
    assert signal_calls == 0


@pytest.mark.asyncio
async def test_fixed_profile_sequence_writes_source_bound_manifests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mallctl = FakeMallctl()
    controller = _controller(tmp_path, mallctl)
    handlers = _install_signal_stubs(monkeypatch)

    await controller.start()
    assert controller.state == "inactive"
    assert mallctl.calls[:4] == [
        ("read", "config.prof"),
        ("read", "config.stats"),
        ("read", "opt.prof"),
        ("read", "prof.active"),
    ]

    await controller.activate()
    assert controller.state == "sampling"
    assert mallctl.values["prof.active"] is True
    profile = await controller.complete()

    assert controller.state == "complete"
    assert controller.active is False
    assert mallctl.values["prof.active"] is False
    assert profile.read_bytes() == b"heap-profile-fixture"
    assert mallctl.calls[4:] == [
        ("reset", None),
        ("write", ("prof.active", True)),
        ("write", ("prof.active", False)),
        ("dump", "profile.heap"),
    ]

    activation = json.loads((tmp_path / "activation.manifest.json").read_text("utf-8"))
    completion = json.loads((tmp_path / "completion.manifest.json").read_text("utf-8"))
    assert activation["source"] == SOURCE
    assert activation["previous_state"] == "inactive"
    assert activation["final_state"] == "sampling"
    assert activation["files"] == []
    assert activation["completed_monotonic_seconds"] >= activation["started_monotonic_seconds"]
    assert completion["source"] == SOURCE
    assert completion["previous_state"] == "sampling"
    assert completion["final_state"] == "complete"
    assert completion["mallctl"] == {"prof.active=false": 0, "prof.dump": 0}
    assert completion["files"] == [
        {
            "path": "profile.heap",
            "size_bytes": profile.stat().st_size,
            "sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        }
    ]

    with pytest.raises(JemallocProfileRejected, match="sequence"):
        await controller.complete()
    await controller.close()
    assert handlers == {}


@pytest.mark.asyncio
async def test_start_rejects_missing_capability_and_active_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    handlers = _install_signal_stubs(monkeypatch)
    mallctl = FakeMallctl()
    mallctl.values["config.prof"] = False
    controller = _controller(tmp_path, mallctl)

    with pytest.raises(JemallocProfileRejected, match="not enabled"):
        await controller.start()
    assert handlers == {}

    mallctl.values["config.prof"] = True
    mallctl.values["prof.active"] = True
    with pytest.raises(JemallocProfileRejected, match="start inactive"):
        await controller.start()
    assert handlers == {}


@pytest.mark.asyncio
async def test_concurrent_transition_is_rejected_and_close_waits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller = _controller(tmp_path)
    _install_signal_stubs(monkeypatch)
    started = asyncio.Event()
    release = asyncio.Event()
    original_activate = controller._activate

    async def controlled_activate() -> None:
        started.set()
        await release.wait()
        await original_activate()

    monkeypatch.setattr(controller, "_activate", controlled_activate)
    await controller.start()
    transition = controller._schedule_next()
    await started.wait()

    with pytest.raises(JemallocProfileRejected, match="already running"):
        controller._schedule_next()
    close_task = asyncio.create_task(controller.close())
    await asyncio.sleep(0)
    assert close_task.done() is False

    release.set()
    await close_task
    assert transition.done()
    assert controller.state == "sampling"


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_owner_is_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller = _controller(tmp_path)
    _install_signal_stubs(monkeypatch)
    await controller.start()
    await controller._transition_lock.acquire()
    transition = controller._schedule_next()
    await asyncio.sleep(0)

    transition.cancel()
    with pytest.raises(asyncio.CancelledError):
        await transition
    controller._transition_lock.release()

    assert controller.state == "failed"
    with pytest.raises(JemallocProfileRejected, match="terminally failed"):
        controller._schedule_next()
    await controller.close()


@pytest.mark.asyncio
async def test_dump_failure_preserves_error_and_terminal_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mallctl = FakeMallctl()
    controller = _controller(tmp_path, mallctl)
    _install_signal_stubs(monkeypatch)
    await controller.start()
    await controller.activate()
    mallctl.dump_result = 5

    with pytest.raises(JemallocProfileRejected, match="prof.dump failed.*5"):
        await controller.complete()

    assert controller.state == "failed"
    assert mallctl.values["prof.active"] is False
    assert not (tmp_path / "completion.manifest.json").exists()
    await controller.close()


@pytest.mark.asyncio
async def test_preexisting_artifact_and_path_escape_fail_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller = _controller(tmp_path)
    _install_signal_stubs(monkeypatch)
    await controller.start()
    (tmp_path / "activation.manifest.json").write_text("preserve", encoding="ascii")

    with pytest.raises(JemallocProfileRejected, match="already exist"):
        await controller.activate()
    assert (tmp_path / "activation.manifest.json").read_text("ascii") == "preserve"
    assert controller.state == "failed"
    with pytest.raises(JemallocProfileRejected, match="escapes"):
        controller._contained("../outside.heap")
    await controller.close()


def test_environment_requires_complete_source_and_runtime_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIYAN_JEMALLOC_PROFILE_DIR", str(tmp_path))
    for name, value in SOURCE.items():
        monkeypatch.setenv(f"LIYAN_JEMALLOC_PROFILE_{name.upper()}", value)

    controller = JemallocProfileController.from_environment()

    assert controller.enabled is True
    assert controller.state == "inactive"

    monkeypatch.setenv("LIYAN_JEMALLOC_PROFILE_SOURCE_SHA", "not-a-sha")
    with pytest.raises(ValueError, match="source_sha"):
        JemallocProfileController.from_environment()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("LIBRARY_SHA256", "e" * 63, "library SHA256"),
        ("LIBRARY_BUILD_ID", "f" * 39, "library build ID"),
        ("IMAGE_ID", "sha256:" + "1" * 63, "image ID"),
        ("IMAGE_DIGEST", "sha512:" + "2" * 64, "image digest"),
    ),
)
def test_environment_rejects_imprecise_runtime_fingerprints(
    tmp_path: Path,
    monkeypatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv("LIYAN_JEMALLOC_PROFILE_DIR", str(tmp_path))
    for source_name, source_value in SOURCE.items():
        monkeypatch.setenv(f"LIYAN_JEMALLOC_PROFILE_{source_name.upper()}", source_value)
    monkeypatch.setenv(f"LIYAN_JEMALLOC_PROFILE_{name}", value)

    with pytest.raises(ValueError, match=message):
        JemallocProfileController.from_environment()


def test_platform_metrics_keeps_all_diagnostic_owners_mutually_exclusive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIYAN_JEMALLOC_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("LIYAN_MEMORY_DIAGNOSTICS", "true")

    with pytest.raises(ValueError, match="mutually exclusive"):
        PlatformMetrics()

    monkeypatch.delenv("LIYAN_MEMORY_DIAGNOSTICS")
    monkeypatch.setenv("LIYAN_MEMORY_CHECKPOINT_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="mutually exclusive"):
        PlatformMetrics()
