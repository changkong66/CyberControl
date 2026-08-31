from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests
from sseclient import SSEClient

ROOT = Path(__file__).resolve().parents[2]
LOAD_ROOT = ROOT / "tests" / "load"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LOAD_ROOT) not in sys.path:
    sys.path.insert(0, str(LOAD_ROOT))

from gate_c.config import (  # noqa: E402
    Credential,
    Thresholds,
    Workload,
    credentials_for_worker,
    is_duplicate_replay_client,
    is_slow_consumer,
)
from gate_c.finalize import _formal_execution_metadata  # noqa: E402
from gate_c.jemalloc_profile_capability import _verify_report  # noqa: E402
from gate_c.monitor import (  # noqa: E402
    _process_memory_metrics,
    _size_bytes,
    _split_stat_bytes,
)
from gate_c.publisher import _http_failure  # noqa: E402
from gate_c.recorder import GateCRecorder  # noqa: E402
from gate_c.runtime_controls import summarize_api_log  # noqa: E402
from gate_c.sse_client import (  # noqa: E402
    FrameActivityScanner,
    TrackingEventSource,
    parse_probe_event,
    redact_sensitive,
)
from gate_c.summarize import _outbox_dead_peak  # noqa: E402
from gate_c.token_provider import TokenProvider  # noqa: E402
from tools.gate_c_image_lock import (  # noqa: E402
    BUILD_RECEIPT_SCHEMA,
    IMAGE_LOCK_SCHEMA,
    PROCESS_VERSION,
    _validate_inputs,
)


def test_gate_c_thresholds_are_frozen_and_final_stage_is_2000() -> None:
    thresholds = Thresholds.load(LOAD_ROOT / "gate-c-thresholds.v1.json")

    assert thresholds.document["frozen_before_execution"] is True
    assert thresholds.stages[-1].users == 2000
    assert thresholds.stages[-1].sustain_seconds == 1800
    assert thresholds.document["maximum_database_pool_acquisition_timeouts"] == 0
    assert thresholds.document["minimum_monitor_sample_success_rate"] == 0.95


def test_gate_c_workload_has_two_tenants_and_topic4_projection() -> None:
    workload = Workload.load(LOAD_ROOT / "gate-c-workload.v1.json")

    assert len(workload.tenant_ids) >= 2
    assert workload.stream_path == "/internal/topic4/sse/stream"
    assert workload.event_type.startswith("topic4.")
    assert workload.integer("duplicate_replay_percent") == 5
    assert workload.integer("forced_disconnect_after_sustain_seconds") == 5


def test_gate_c_monitor_parses_process_memory_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        stdout = """\
VmRSS:       100 kB
RssAnon:      60 kB
RssFile:      40 kB
VmData:      120 kB
__SMAPS_ROLLUP__
Pss:          90 kB
Private_Clean: 10 kB
Private_Dirty: 70 kB
Private_Hugetlb: 2 kB
__MAP_COUNT__
37
"""

    def run(*args, **kwargs):
        assert args[0][:4] == ["docker", "exec", "api-1", "sh"]
        assert kwargs == {
            "check": True,
            "capture_output": True,
            "text": True,
            "timeout": 10,
        }
        return Result()

    monkeypatch.setattr("gate_c.monitor.subprocess.run", run)

    assert _process_memory_metrics("docker", "api-1") == {
        "rss_bytes": 100 * 1024,
        "anonymous_rss_bytes": 60 * 1024,
        "file_rss_bytes": 40 * 1024,
        "data_bytes": 120 * 1024,
        "pss_bytes": 90 * 1024,
        "uss_bytes": 82 * 1024,
        "map_count": 37,
    }


def test_gate_c_monitor_rejects_incomplete_process_memory_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        stdout = "VmRSS: 100 kB\n__SMAPS_ROLLUP__\n__MAP_COUNT__\n4\n"

    monkeypatch.setattr("gate_c.monitor.subprocess.run", lambda *args, **kwargs: Result())

    with pytest.raises(RuntimeError, match="incomplete"):
        _process_memory_metrics("docker", "api-1")


def test_backend_runtime_uses_process_start_allocator_configuration() -> None:
    dockerfile = (Path(__file__).resolve().parents[2] / "infra" / "backend.Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "jemalloc-5.3.0-r6.apk" in dockerfile
    assert "PYTHONMALLOC=malloc" in dockerfile
    assert "LD_PRELOAD=/usr/lib/libjemalloc.so.2" in dockerfile
    assert "dirty_decay_ms:1000" in dockerfile
    assert "muzzy_decay_ms:1000" in dockerfile
    assert "narenas:1" in dockerfile
    assert "retain:false" in dockerfile
    assert "malloc_trim" not in dockerfile
    assert "gc.collect" not in dockerfile


def test_frame_activity_scanner_handles_fragmented_heartbeat_and_event() -> None:
    activity: list[bool] = []
    scanner = FrameActivityScanner(activity.append)
    scanner.feed(b": heart")
    scanner.feed(b"beat\r\n\r\n")
    scanner.feed(b"id: cursor\n")
    scanner.feed(b"event: topic4.gate-c.probe\n")
    scanner.feed(b'data: {"value":1}\n\n')

    assert activity == [True, False]


def test_sse_client_parses_multiline_data_through_tracking_source() -> None:
    class Response:
        def __init__(self) -> None:
            self.closed = False

        def iter_content(self, *, chunk_size: int):
            del chunk_size
            yield b'id: cursor\r\nevent: topic4.gate-c.probe\r\ndata: {"a":\n'
            yield b"data: 1}\r\n\r\n"

        def close(self) -> None:
            self.closed = True

    activity: list[bool] = []
    response = Response()
    source = TrackingEventSource(response, activity_callback=activity.append)
    events = list(SSEClient(source).events())

    assert len(events) == 1
    assert events[0].id == "cursor"
    assert events[0].event == "topic4.gate-c.probe"
    assert json.loads(events[0].data) == {"a": 1}
    assert response.closed is False
    assert activity == [False]


def test_probe_parser_rejects_incomplete_identity() -> None:
    with pytest.raises(ValueError, match="identity"):
        parse_probe_event(json.dumps({"gate_c_run_id": "run"}))


def test_recorder_deduplicates_and_detects_cross_tenant_events(tmp_path: Path) -> None:
    recorder = GateCRecorder(run_id="run-1", stage="smoke", output_dir=tmp_path)
    recorder.register_client(
        "client-a",
        "tenant-a",
        principal_fingerprint="principal-a",
        slow_consumer=False,
        duplicate_replay_client=True,
    )
    first = parse_probe_event(
        json.dumps(
            {
                "gate_c_run_id": "run-1",
                "gate_c_tenant_id": "tenant-a",
                "gate_c_probe_id": "p-0",
                "gate_c_probe_ordinal": 0,
                "gate_c_producer_started_ns": 1,
            }
        )
    )
    assert recorder.record_probe("client-a", first) is True
    assert recorder.record_probe("client-a", first) is False
    foreign = parse_probe_event(
        json.dumps(
            {
                "gate_c_run_id": "run-1",
                "gate_c_tenant_id": "tenant-b",
                "gate_c_probe_id": "p-1",
                "gate_c_probe_ordinal": 1,
                "gate_c_producer_started_ns": 1,
            }
        )
    )
    assert recorder.record_probe("client-a", foreign) is False
    result = json.loads(recorder.write_summary().read_text(encoding="utf-8"))

    assert result["counters"]["duplicate_received"] == 1
    assert result["counters"]["cross_tenant_leakage"] == 1
    assert result["clients"]["client-a"]["duplicate_rendered"] == 0
    assert result["clients"]["client-a"]["principal_fingerprint"] == "principal-a"
    assert result["clients"]["client-a"]["slow_consumer"] is False
    assert result["clients"]["client-a"]["duplicate_replay_client"] is True


def test_duplicate_replay_is_balanced_and_distinct_from_slow_slots() -> None:
    duplicates = [index for index in range(2000) if is_duplicate_replay_client(index, 5)]
    slow = [index for index in range(2000) if is_slow_consumer(index, 5)]

    assert len(duplicates) == 100
    assert len(set(duplicates).intersection(slow)) == 0


def test_gate_c_summary_detects_peak_outbox_dead(tmp_path: Path) -> None:
    monitor = tmp_path / "monitor.jsonl"
    monitor.write_text(
        "\n".join(
            (
                json.dumps({"database": {"outbox_states": {"PUBLISHED": 4}}}),
                json.dumps({"database": {"outbox_states": {"DEAD": 2}}}),
                json.dumps({"database_error": "ConnectionError"}),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assert _outbox_dead_peak(monitor) == 2


def test_redaction_removes_tokens_and_codes() -> None:
    value = 'Authorization: Bearer abc.def.ghi password="secret" verification_code=123456'

    redacted = redact_sensitive(value)

    assert "abc.def.ghi" not in redacted
    assert "secret" not in redacted
    assert "123456" not in redacted


def test_runtime_controls_only_records_pool_timeout_fingerprints(tmp_path: Path) -> None:
    log = tmp_path / "api.log"
    log.write_text(
        "INFO normal request\nQueuePool limit of size 10 overflow 20 reached, "
        "connection timed out, timeout 10.00\n",
        encoding="utf-8",
    )

    result = summarize_api_log(log)

    assert result["database_pool_acquisition_timeout_count"] == 1
    assert result["passed"] is False
    assert "QueuePool" not in json.dumps(result)


def test_runtime_controls_fail_closed_on_bad_address_without_raw_log_leak(
    tmp_path: Path,
) -> None:
    log = tmp_path / "api.log"
    log.write_text("ssl operation failed: Bad address for internal endpoint\n", encoding="utf-8")

    result = summarize_api_log(log)

    assert result["bad_address_count"] == 1
    assert result["passed"] is False
    assert "Bad address" not in json.dumps(result)


def test_gate_c_runner_preserves_volume_and_identity_boundaries() -> None:
    runner = (
        Path(__file__).resolve().parents[2] / "tools" / "windows" / "run-phase7-gate-c.ps1"
    ).read_text(encoding="utf-8")

    assert '"--processes", [string]$workload.worker_processes' in runner
    assert "GATE_C_FAULT_AT_SECONDS" in runner
    assert 'Invoke-Compose @("down", "--remove-orphans")' in runner
    assert '"--no-deps"' in runner
    assert "down -v" not in runner
    assert "X-Tenant-ID" not in runner
    assert "[string]$PostgresVolumeName" in runner
    assert "Full Gate C acceptance requires an explicit fresh -PostgresVolumeName" in runner
    assert "$env:GATE_C_POSTGRES_VOLUME = $volumeName" in runner
    assert '"cybercontrol_gate_c_postgres"' not in runner


def test_gate_c_runner_separates_diagnostic_preflight_and_formal_modes() -> None:
    runner = (
        Path(__file__).resolve().parents[2] / "tools" / "windows" / "run-phase7-gate-c.ps1"
    ).read_text(encoding="utf-8")

    assert '[ValidateSet("HarnessSmoke", "DiagnosticStages", "PreflightSmoke", "Full")]' in runner
    assert '$processVersion = "Gate-C-12-v1.0"' in runner
    assert "classification = $executionClassification" in runner
    assert "process_version = $processVersion" in runner
    assert 'formal_gate_attempt = ($Mode -eq "Full")' in runner
    assert "acceptance_claim = $false" in runner
    assert "diagnostic_stage_names = @($DiagnosticStageNames)" in runner
    assert "[int]$DiagnosticIdleSeconds = 0" in runner
    assert 'if ($Mode -ne "DiagnosticStages" -and $DiagnosticIdleSeconds -ne 0)' in runner
    assert 'Join-Path $runDirectory "diagnostic-baseline"' in runner
    assert "Wait-WithCapacityGuard -Seconds $DiagnosticIdleSeconds" in runner
    assert 'if ($Mode -in @("Full", "PreflightSmoke"))' in runner
    assert '$Mode -ne "HarnessSmoke" -and -not $LockedImages' in runner
    assert "$Mode requires a complete locked image receipt." in runner
    assert "-LockedImages cannot be combined with -SkipBuild or -NoCacheBuild." in runner
    assert "Gate C image lock source binding is invalid." in runner
    assert "Assert-LockedComposeImages" in runner
    assert '$service -eq "api" -and $JemallocProfileArm -ne "None"' in runner
    assert "Gate C profiling API image binding is missing." in runner
    assert "Gate C Compose profiling API image reference does not match its binding." in runner
    assert "Gate C local profiling API image content does not match its binding." in runner
    assert "$actualProfileImageId" in runner
    assert "DiagnosticStages requires explicit -DiagnosticStageNames." in runner
    assert "PreflightSmoke cannot retain its environment." in runner
    assert "Remove-EphemeralResources" in runner
    assert "& docker volume rm $volumeName" in runner
    assert "Ephemeral cleanup left PostgreSQL volume $volumeName behind." in runner
    assert '$Mode -eq "DiagnosticStages"' in runner
    assert "(Test-Path -LiteralPath $stageSummaryPath)" in runner
    assert "Diagnostic stage $stageName retained a non-passing threshold summary." in runner
    assert "[int]$DiagnosticRecoverySeconds = 0" in runner
    assert "[switch]$MemoryCheckpoints" in runner
    assert "[switch]$NoCacheBuild" in runner
    assert "if ($NoCacheBuild) {" in runner
    assert '$buildArguments += "--no-cache"' in runner
    assert "Wait-WithCapacityGuard -Seconds $DiagnosticRecoverySeconds" in runner
    assert 'Invoke-MemoryCheckpoint -ContainerId $apiContainer -Label "baseline"' in runner
    assert 'Invoke-MemoryCheckpoint -ContainerId $apiContainer -Label "recovery"' in runner
    assert "Memory checkpoints require only ramp-200" in runner
    assert "memory_checkpoint_compare.py" in runner
    assert "[double]$metadata.duration_seconds -gt 30.0" in runner
    assert "$checkpointTimer.Elapsed.TotalSeconds -gt 30.0" in runner
    assert "did not complete within 30 seconds" in runner

    checkpoint_compose = (LOAD_ROOT / "docker-compose.gate-c-memory-checkpoints.yml").read_text(
        encoding="utf-8"
    )
    assert 'LIYAN_MEMORY_DIAGNOSTICS: "false"' in checkpoint_compose
    assert "LIYAN_MEMORY_CHECKPOINT_DIR: /gate-c-results/memory-checkpoints" in checkpoint_compose
    assert "LIYAN_MEMORY_CHECKPOINT_SOURCE_SHA" in checkpoint_compose
    assert "X-Tenant-ID" not in checkpoint_compose

    finalizer = (LOAD_ROOT / "gate_c" / "finalize.py").read_text(encoding="utf-8")
    assert "execution = _formal_execution_metadata(args.run_dir)" in finalizer
    assert '"process_version": execution["process_version"]' in finalizer
    assert '"classification": execution["classification"]' in finalizer


def test_gate_c_finalizer_requires_bound_formal_process_metadata(tmp_path: Path) -> None:
    execution = {
        "process_version": "Gate-C-12-v1.0",
        "classification": "FORMAL_GATE_C_ATTEMPT",
        "formal_gate_attempt": True,
        "run_id": "gate-c-run",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "product_source_sha": "a" * 40,
        "engineering_baseline_sha": "a" * 40,
    }
    (tmp_path / "execution-metadata.json").write_text(
        json.dumps(execution),
        encoding="utf-8",
    )

    assert _formal_execution_metadata(tmp_path) == execution

    execution["classification"] = "PREFLIGHT_CHECK"
    (tmp_path / "execution-metadata.json").write_text(
        json.dumps(execution),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-formal"):
        _formal_execution_metadata(tmp_path)


def test_gate_c_source_built_images_have_bound_provenance_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfiles = (
        root / "infra" / "backend.Dockerfile",
        root / "infra" / "frontend.Dockerfile",
        root / "infra" / "mock-provider.Dockerfile",
        root / "tests" / "load" / "Dockerfile",
        root / "tests" / "load" / "jemalloc-profile.Dockerfile",
    )
    expected_labels = (
        "org.opencontainers.image.revision=${CYBERCONTROL_SOURCE_SHA}",
        "com.cybercontrol.source-tree=${CYBERCONTROL_SOURCE_TREE}",
        "com.cybercontrol.product-source=${CYBERCONTROL_PRODUCT_SOURCE_SHA}",
        "com.cybercontrol.engineering-baseline=${CYBERCONTROL_ENGINEERING_BASELINE_SHA}",
        "com.cybercontrol.process-version=${CYBERCONTROL_PROCESS_VERSION}",
    )
    for path in dockerfiles:
        source = path.read_text(encoding="utf-8")
        assert all(label in source for label in expected_labels), path

    runner = (root / "tools" / "windows" / "run-phase7-gate-c.ps1").read_text(encoding="utf-8")
    assert "$env:GATE_C_SOURCE_SHA = $sourceCommit" in runner
    assert "$env:GATE_C_SOURCE_TREE = $sourceTree" in runner
    assert "Assert-ImageProvenance" in runner
    assert '"frontend",' in runner
    assert '"gate-c-load"' in runner


def test_gate_c_build_inputs_lock_builder_packages_and_external_images() -> None:
    root = Path(__file__).resolve().parents[2]
    inputs = _validate_inputs(root / "tests" / "load" / "gate-c-build-inputs.v1.json")
    build_tool = (root / "tools" / "gate_c_image_lock.py").read_text(encoding="utf-8")
    backend_dockerfile = (root / "infra" / "backend.Dockerfile").read_text(encoding="utf-8")

    assert PROCESS_VERSION == "Gate-C-12-v1.0"
    assert IMAGE_LOCK_SCHEMA == "cybercontrol.gate-c-image-lock.v1"
    assert BUILD_RECEIPT_SCHEMA == "cybercontrol.gate-c-build-receipt.v1"
    assert inputs["platform"] == "linux/amd64"
    assert inputs["buildkit"]["image_digest"].startswith("sha256:")
    assert inputs["buildkit"]["source_revision"] == "673b7e0196de0cac83308274b88aaed97a91af74"
    assert {package["filename"] for package in inputs["alpine"]["backend_runtime_packages"]} == {
        "jemalloc-5.3.0-r6.apk",
        "libgcc-15.2.0-r5.apk",
        "libstdc++-15.2.0-r5.apk",
        "libcrypto3-3.5.8-r0.apk",
        "libssl3-3.5.8-r0.apk",
    }
    assert "apkindex_sha256" not in inputs["alpine"]
    assert set(inputs["base_image_roles"]) == {
        "python",
        "node",
        "nginx",
        "postgres",
        "keycloak",
        "buildkit",
    }
    assert "builder_mirrors" not in json.dumps(inputs)
    assert set(inputs["offline_supply_chain"]) == {"manifest", "base_images"}
    for package in inputs["alpine"]["backend_runtime_packages"]:
        assert package["filename"] in backend_dockerfile
        assert package["sha256"] in backend_dockerfile
    assert "APKINDEX.tar.gz" not in backend_dockerfile
    assert "apk add --no-network --allow-untrusted" in backend_dockerfile
    assert '"docker", "buildx", "inspect", builder, "--bootstrap"' in build_tool
    assert '"--no-cache"' in build_tool
    assert '"--network"' in build_tool
    assert '"none"' in build_tool
    assert "builder_mirrors" not in build_tool
    assert "normal-image-lock.json" in build_tool
    assert "diagnostic-image-lock.json" in build_tool
    assert "all-service-digest-manifest.json" in build_tool
    assert "rewrite-timestamp=true" in build_tool
    assert '"com.docker.compose.project"' in build_tool


def test_gate_c_candidate_smoke_supports_same_digest_independent_scenarios() -> None:
    root = Path(__file__).resolve().parents[2]
    runner = (root / "tools" / "windows" / "run-phase7-gate-c.ps1").read_text(encoding="utf-8")
    compose = (root / "tests" / "load" / "docker-compose.gate-c.yml").read_text(encoding="utf-8")

    assert '[ValidateSet("ColdDeployment", "ControlledApiRestart", "StableIdle")]' in runner
    assert '[string]$SmokeScenario = "ColdDeployment"' in runner
    assert "$env:GATE_C_IMAGE_TAG = $sourceCommit" in runner
    assert '"--profile", "gate-c-load"' in runner
    assert "smoke_scenario = $SmokeScenario" in runner
    assert '$Mode -in @("DiagnosticStages", "HarnessSmoke")' in runner
    assert '$Mode -in @("PreflightSmoke", "HarnessSmoke")' in runner
    assert 'Invoke-Compose @("down", "--remove-orphans", "--volumes")' in runner
    assert "label=com.docker.compose.project=$ProjectName" in runner
    assert "Ephemeral cleanup left Compose volumes" in runner
    assert '"ControlledApiRestart" {' in runner
    assert 'Invoke-Compose @("restart", "api")' in runner
    assert 'Wait-ComposeServiceHealthy -Service "api"' in runner
    assert '"StableIdle" {' in runner
    assert "Wait-WithCapacityGuard -Seconds 300" in runner
    assert "Get-ComposeImageReference" in runner
    assert 'docker image inspect --format "{{.Id}}" $imageReference' in runner
    assert '$capacityPolicyRevision = "Gate-C-12-capacity-v1.1"' in runner
    assert "[double]$capacityAdmissionGiB = 15.0" in runner
    assert "[double]$capacityWarningGiB = 8.0" in runner
    assert "[double]$capacityStopGiB = 5.0" in runner
    assert "function Assert-CapacityAdmission" in runner
    assert "function Assert-CapacityReserve" in runner
    assert "$capacitySnapshot = Assert-CapacityAdmission" in runner
    assert '$capacityAbort = $Reason.StartsWith("Gate C capacity"' in runner
    assert 'if ($capacityAbort) { "INFRA_ABORTED" }' in runner
    assert "capacity_policy_revision = $capacityPolicyRevision" in runner
    assert "capacity_at_start = $script:capacityAtStart" in runner
    assert "capacity_latest = $script:lastCapacitySnapshot" in runner
    assert "Start-CapacityMonitor" in runner
    assert "Wait-WithCapacityGuard -Seconds 300" in runner

    capacity_monitor = (root / "tools" / "windows" / "watch-gate-c-capacity.ps1").read_text(
        encoding="utf-8"
    )
    assert '"INFRA_CAPACITY_WARNING"' in capacity_monitor
    assert '"INFRA_ABORTED"' in capacity_monitor
    assert '"label=com.docker.compose.project=$ProjectName"' in capacity_monitor
    assert '"label=com.docker.compose.oneoff=True"' not in capacity_monitor
    assert "docker stop --time 30" in capacity_monitor
    assert "project_container_results" in capacity_monitor
    assert "volumes_deleted = $false" in capacity_monitor
    assert "docker volume rm" not in capacity_monitor
    assert "docker system prune" not in capacity_monitor

    capacity_library = (root / "tools" / "windows" / "gate-c-capacity.ps1").read_text(
        encoding="utf-8"
    )
    assert '-Name "results_root"' in capacity_library
    assert '-Name "docker_data_root"' in capacity_library
    assert 'name = "docker_internal_root"' in capacity_library
    assert 'distribution = "docker-desktop"' in capacity_library
    assert 'process_version = "Gate-C-12-v1.0"' in capacity_library
    assert "admission_ready" in capacity_library

    assert compose.count("cybercontrol/gate-c-backend:${GATE_C_IMAGE_TAG:-unknown}") == 2
    assert "cybercontrol/gate-c-mock-provider:${GATE_C_IMAGE_TAG:-unknown}" in compose
    assert "cybercontrol/gate-c-frontend:${GATE_C_IMAGE_TAG:-unknown}" in compose
    assert "cybercontrol/gate-c-load:${GATE_C_IMAGE_TAG:-unknown}" in compose


def test_gate_c_capacity_startup_snapshot_closes_monitor_race(tmp_path: Path) -> None:
    runner = Path(__file__).resolve().parents[2] / "tools" / "windows" / "run-phase7-gate-c.ps1"
    probe = tmp_path / "capacity-startup-race.ps1"
    escaped_runner = str(runner).replace("'", "''")
    probe.write_text(
        f"""\
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    '{escaped_runner}', [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {{ throw "Runner parse failed." }}
$required = @(
    "Get-HostCapacitySnapshot",
    "Get-CapacitySnapshotState",
    "Update-LatestCapacitySnapshot",
    "Assert-CapacityMonitorHealthy"
)
foreach ($name in $required) {{
    $definition = @($ast.FindAll({{
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true))
    if ($definition.Count -ne 1) {{ throw "Expected one function named $name." }}
    Invoke-Expression $definition[0].Extent.Text
}}
function Get-GateCMultiRootCapacitySnapshot {{
    $state = if ($script:testFreeBytes -lt [int64]($capacityStopGiB * 1GB)) {{
        "HARD_STOP"
    }} elseif ($script:testFreeBytes -lt [int64]($capacityWarningGiB * 1GB)) {{
        "WARNING"
    }} else {{
        "NORMAL"
    }}
    return [pscustomobject]@{{
        state = $state
        free_bytes = $script:testFreeBytes
        free_gib = [math]::Round([double]$script:testFreeBytes / 1GB, 3)
        admission_ready = ($script:testFreeBytes -ge [int64]($capacityAdmissionGiB * 1GB))
        limiting_target = "test"
    }}
}}
$probeTempRoot = [IO.Path]::GetTempPath()
if ([string]::IsNullOrWhiteSpace($probeTempRoot)) {{
    throw "PowerShell did not provide a platform temp directory."
}}
$ResultsRoot = $probeTempRoot
$DockerDataRoot = $probeTempRoot
$DockerInternalRoot = "/test"
$ProjectName = "capacity-test"
$capacityPolicyRevision = "Gate-C-12-capacity-v1.1"
[double]$capacityAdmissionGiB = 15.0
[double]$capacityWarningGiB = 8.0
[double]$capacityStopGiB = 5.0
$states = foreach ($freeGiB in @(16.0, 7.0, 4.0)) {{
    $script:testFreeBytes = [int64]($freeGiB * 1GB)
    (Get-HostCapacitySnapshot).state
}}
$script:testFreeBytes = [int64](16.0 * 1GB)
$script:lastCapacitySnapshot = Get-HostCapacitySnapshot
$runDirectory = Join-Path $probeTempRoot "gate-c-capacity-race-not-created"
$script:capacityMonitorProcess = [pscustomobject]@{{ HasExited = $false }}
$script:capacityMonitorProcess | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{}}
Assert-CapacityMonitorHealthy
$missingStateError = $null
try {{
    Get-CapacitySnapshotState -Snapshot ([pscustomobject]@{{ free_bytes = 1 }}) | Out-Null
}}
catch {{
    $missingStateError = $_.Exception.Message
}}
[ordered]@{{
    states = @($states)
    startup_guard_passed = $true
    missing_state_error = $missingStateError
}} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )

    probe_environment = os.environ.copy()
    probe_environment.pop("TEMP", None)
    probe_environment.pop("TMP", None)
    completed = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(probe)],
        check=False,
        capture_output=True,
        text=True,
        env=probe_environment,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["states"] == ["NORMAL", "WARNING", "HARD_STOP"]
    assert result["startup_guard_passed"] is True
    assert result["missing_state_error"] == "Gate C capacity snapshot is missing required state."


def test_jemalloc_profile_image_is_pinned_and_diagnostic_only() -> None:
    root = Path(__file__).resolve().parents[2]
    normal = (root / "infra" / "backend.Dockerfile").read_text(encoding="utf-8")
    profile = (root / "tests" / "load" / "jemalloc-profile.Dockerfile").read_text(encoding="utf-8")

    assert "--enable-prof" in profile
    assert "--enable-prof-libunwind" in profile
    assert "make -j1 EXTRA_CFLAGS=-fno-builtin-aligned_alloc check" in profile
    assert "ccDETERMINISTIC.o" in profile
    assert "reproducibility-normalization.txt" in profile
    assert "upstream-test-compiler-flags.txt" in profile
    assert "2db82d1e7119df3e71b7640219b6dfe84789bc0537983c3b7ac4f7189aecfeaa" in profile
    assert "555b08620f00919e9b99c98a433cfcb755359395d62622cc8ae967d6717d43a0" in profile
    assert "487908875c68b8ceb3fbd2c88f04eb2ddf8dd212272a2b3898e5e4fbd885623d" in profile
    assert "prof:true,prof_active:false,lg_prof_sample:19" in profile
    assert "prof_gdump:false,prof_final:false,prof_leak:false" in profile
    assert "libprofile-cohort.so" in profile
    assert "com.cybercontrol.diagnostic-capability=jemalloc-prof-5.3.0" in profile
    assert "prof:true" not in normal


def test_jemalloc_profile_symbolization_requires_resolved_native_cohort(tmp_path: Path) -> None:
    report = tmp_path / "symbolized.txt"
    output = tmp_path / "validation.json"
    report.write_text(
        "Total: 100663296 B\n"
        " 96636764  96.0%  96.0%  96636764  96.0% cybercontrol_profile_allocate\n",
        encoding="utf-8",
    )

    _verify_report(report, output)

    validation = json.loads(output.read_text(encoding="utf-8"))
    assert validation["passed"] is True
    assert validation["resolved_percentage"] == 96.0

    low_resolution = tmp_path / "low-resolution.txt"
    low_resolution.write_text(
        " 50331648  50.0%  50.0% cybercontrol_profile_allocate\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="below 90%"):
        _verify_report(low_resolution, tmp_path / "must-not-exist.json")

    misleading_cumulative = tmp_path / "misleading-cumulative.txt"
    misleading_cumulative.write_text(
        " 1048576  1.0% 100.0% 93323264 89.0% cybercontrol_profile_allocate\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="below 90%"):
        _verify_report(misleading_cumulative, tmp_path / "also-must-not-exist.json")


def test_gate_c_jemalloc_profile_protocol_is_fixed_and_non_formal() -> None:
    root = Path(__file__).resolve().parents[2]
    runner = (root / "tools" / "windows" / "run-phase7-gate-c.ps1").read_text(encoding="utf-8")
    compose = (root / "tests" / "load" / "docker-compose.gate-c-jemalloc-profile.yml").read_text(
        encoding="utf-8"
    )

    assert '[ValidateSet("None", "A", "Measurement", "APrime")]' in runner
    assert '[string]$JemallocProfileArm = "None"' in runner
    assert "Jemalloc profile arms are valid only with -Mode DiagnosticStages." in runner
    assert "Jemalloc profile arms require only ramp-200, 300 idle seconds" in runner
    assert "Jemalloc profile arms must reuse a prevalidated locked image receipt." in runner
    assert "Profiling image digest does not match -JemallocProfileImageDigest." in runner
    assert "docker kill --signal USR2" in runner
    assert '$JemallocProfileArm -eq "Measurement"' in runner
    assert (
        'Invoke-JemallocProfileTransition -ContainerId $apiContainer -Name "activation"' in runner
    )
    assert (
        'Invoke-JemallocProfileTransition -ContainerId $apiContainer -Name "completion"' in runner
    )
    assert "Jemalloc control arm produced an unauthorized profile artifact." in runner
    assert 'formal_gate_attempt = ($Mode -eq "Full")' in runner

    assert "cybercontrol/gate-c-jemalloc-profile:${GATE_C_IMAGE_TAG:-unknown}" in compose
    assert "dockerfile:" not in compose
    assert "build:" not in compose
    assert 'LIYAN_MEMORY_DIAGNOSTICS: "false"' in compose
    assert 'LIYAN_MEMORY_CHECKPOINT_DIR: ""' in compose
    assert "LIYAN_JEMALLOC_PROFILE_DIR: /gate-c-results/jemalloc-profile" in compose
    assert "GATE_C_JEMALLOC_PROFILE_IMAGE_DIGEST" in compose
    assert "X-Tenant-ID" not in compose
    assert "X-Subject-Ref" not in compose


def test_gate_c_monitor_uses_the_compose_postgres_host_port() -> None:
    runner = (
        Path(__file__).resolve().parents[2] / "tools" / "windows" / "run-phase7-gate-c.ps1"
    ).read_text(encoding="utf-8")

    assert "[int]$PostgresHostPort" in runner
    assert "$env:LIYAN_POSTGRES_HOST_PORT = [string]$PostgresHostPort" in runner
    assert "@127.0.0.1:${PostgresHostPort}/liyans" in runner
    assert "postgres_host_port = $PostgresHostPort" in runner
    assert "@127.0.0.1:5432/liyans" not in runner


def test_gate_c_worker_credentials_are_disjoint_and_complete() -> None:
    credentials = tuple(
        Credential(
            username=f"user-{index}",
            password="password",
            tenant_id="tenant-a" if index % 2 == 0 else "tenant-b",
            subject_ref=f"subject-{index}",
            publisher=index < 2,
            course_id="course-a",
            target_kp_id="kp-a",
        )
        for index in range(20)
    )

    partitions = [
        credentials_for_worker(credentials, worker_index=index, worker_processes=4)
        for index in range(4)
    ]

    assert all(len(partition) == 5 for partition in partitions)
    assert {item.username for partition in partitions for item in partition} == {
        item.username for item in credentials
    }
    assert sum((list(partition) for partition in partitions), []).count(credentials[0]) == 1


def test_gate_c_slow_consumer_schedule_is_deterministic_and_balanced() -> None:
    selected = [index for index in range(2000) if is_slow_consumer(index, 5)]

    assert len(selected) == 100
    assert selected[:5] == [0, 21, 42, 63, 84]
    assert {index % 4 for index in selected} == {0, 1, 2, 3}


def test_gate_c_workload_keeps_slow_consumer_capacity_above_burst_rate() -> None:
    workload = Workload.load(LOAD_ROOT / "gate-c-workload.v1.json")

    assert (
        workload.integer("slow_consumer_delay_ms")
        * workload.number("burst_events_per_second_per_tenant")
        < 1000
    )


def test_gate_c_runtime_metric_size_parsing_is_numeric() -> None:
    assert _size_bytes("1.5MiB") == 1_572_864
    assert _split_stat_bytes("1.5MiB / 2MB") == (1_572_864, 2_000_000)


def test_token_provider_marks_replacement_as_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    credential = Credential(
        username="gate-user",
        password="password",
        tenant_id="tenant-a",
        subject_ref="subject-a",
        publisher=False,
        course_id="course-a",
        target_kp_id="kp-a",
    )
    provider = TokenProvider(
        token_url="http://keycloak.invalid/token",
        client_id="cybercontrol-cli",
        refresh_skew_seconds=60,
    )

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "access_token": (
                    "eyJhbGciOiJSUzI1NiJ9."
                    "eyJ0ZW5hbnRfaWQiOiJ0ZW5hbnQtYSIsInN1YiI6InN1YmplY3QtYSJ9."
                    "signature"
                ),
                "expires_in": 3600,
            }

    calls = 0

    def post(*_args, **_kwargs) -> Response:
        nonlocal calls
        calls += 1
        return Response()

    monkeypatch.setattr(provider._session, "post", post)
    first = provider.get(credential)
    second = provider.get(credential, force_refresh=True)
    cached = provider.get(credential)

    assert calls == 2
    assert first.refreshed is False
    assert second.refreshed is True
    assert cached.from_cache is True
    assert cached.refreshed is False


def test_gate_c_http_failure_records_only_status_and_stable_code() -> None:
    response = requests.Response()
    response.status_code = 404
    response._content = b'{"error":{"code":"TOPIC2_NOT_FOUND","message":"private"}}'
    error = requests.HTTPError(response=response)

    assert _http_failure(error) == {
        "status_code": 404,
        "error_code": "TOPIC2_NOT_FOUND",
    }


def test_gate_c_provision_creates_topic2_learning_path() -> None:
    source = (LOAD_ROOT / "gate_c" / "provision.py").read_text(encoding="utf-8")

    assert "/paths/generate" in source
    assert '"schema_version": "topic2.path-generate-command.v1"' in source


def test_gate_c_real_workflow_uses_frozen_topic4_locale() -> None:
    source = (LOAD_ROOT / "gate_c" / "publisher.py").read_text(encoding="utf-8")

    assert '"locale": "zh-CN"' in source


def test_locust_shutdown_hooks_accept_locust_246_event_shapes() -> None:
    locust_source = (LOAD_ROOT / "locustfile.py").read_text(encoding="utf-8")
    tree = ast.parse(locust_source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("on_test_stop", "on_quitting"):
        function = functions[name]
        assert function.args.kwarg is not None

    runner = (
        Path(__file__).resolve().parents[2] / "tools" / "windows" / "run-phase7-gate-c.ps1"
    ).read_text(encoding="utf-8")
    assert "$Process.Refresh()" in runner
    assert "$null = $process.Handle" in runner
