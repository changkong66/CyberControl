from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import re
import tracemalloc
from pathlib import Path

from liyans.infrastructure.observability.jemalloc_profiles import JemallocProfileController

PROCESS_VERSION = "Gate-C-11-v1.0"
COHORT_LIBRARY = Path("/opt/cybercontrol/jemalloc-prof/lib/libprofile-cohort.so")
SYMBOL = "cybercontrol_profile_allocate"


def _write_json(path: Path, document: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")


async def _exercise(block_size: int, block_count: int) -> None:
    if tracemalloc.is_tracing():
        raise RuntimeError("tracemalloc must remain disabled in jemalloc profile mode")
    if os.getenv("LIYAN_MEMORY_DIAGNOSTICS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise RuntimeError("periodic heavy memory diagnostics must remain disabled")
    if os.getenv("LIYAN_MEMORY_CHECKPOINT_DIR", "").strip():
        raise RuntimeError("memory checkpoint mode must remain disabled")
    controller = JemallocProfileController.from_environment()
    if not controller.enabled:
        raise RuntimeError("jemalloc profile capability is not configured")
    await controller.start()
    try:
        await controller.activate()
        cohort = ctypes.CDLL(str(COHORT_LIBRARY))
        cohort.cybercontrol_profile_allocate.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
        cohort.cybercontrol_profile_allocate.restype = ctypes.c_size_t
        allocated = int(cohort.cybercontrol_profile_allocate(block_size, block_count))
        expected = block_size * block_count
        if allocated != expected:
            raise RuntimeError(
                f"native allocation cohort returned {allocated} bytes; expected {expected}"
            )
        profile_path = await controller.complete()
        result = {
            "schema_version": "cybercontrol.jemalloc-profile-capability.v1",
            "process_version": PROCESS_VERSION,
            "state": controller.state,
            "profiler_active": controller.active,
            "cohort": {
                "symbol": SYMBOL,
                "block_size_bytes": block_size,
                "block_count": block_count,
                "allocated_bytes": allocated,
            },
            "profile": profile_path.name,
            "activation_manifest": "activation.manifest.json",
            "completion_manifest": "completion.manifest.json",
        }
        _write_json(profile_path.parent / "capability-result.json", result)
    finally:
        await controller.close()


def _verify_report(report: Path, output: Path) -> None:
    content = report.read_text(encoding="utf-8")
    matching_lines = [line for line in content.splitlines() if SYMBOL in line]
    if not matching_lines:
        raise ValueError(f"symbolized profile does not contain {SYMBOL}")
    percentages: list[float] = []
    for line in matching_lines:
        values = re.findall(r"([0-9]+(?:\.[0-9]+)?)%", line)
        if values:
            percentages.append(float(values[-1]))
    resolved_percentage = max(percentages, default=0.0)
    if resolved_percentage < 90.0:
        raise ValueError(
            f"native cohort resolved percentage {resolved_percentage:.3f} is below 90%"
        )
    _write_json(
        output,
        {
            "schema_version": "cybercontrol.jemalloc-profile-symbolization.v1",
            "process_version": PROCESS_VERSION,
            "required_symbol": SYMBOL,
            "resolved_percentage": resolved_percentage,
            "minimum_percentage": 90.0,
            "passed": True,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    exercise = subparsers.add_parser("exercise")
    exercise.add_argument("--block-size", type=int, default=1024 * 1024)
    exercise.add_argument("--block-count", type=int, default=96)
    verify = subparsers.add_parser("verify-report")
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "exercise":
        asyncio.run(_exercise(arguments.block_size, arguments.block_count))
    else:
        _verify_report(arguments.report, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
