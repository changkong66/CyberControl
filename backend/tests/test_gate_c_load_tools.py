from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
import requests
from sseclient import SSEClient

LOAD_ROOT = Path(__file__).resolve().parents[2] / "tests" / "load"
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

    assert "jemalloc=5.3.0-r6" in dockerfile
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
    assert '$processVersion = "Gate-C-11-v1.0"' in runner
    assert "classification = $executionClassification" in runner
    assert "process_version = $processVersion" in runner
    assert 'formal_gate_attempt = ($Mode -eq "Full")' in runner
    assert "acceptance_claim = $false" in runner
    assert "diagnostic_stage_names = @($DiagnosticStageNames)" in runner
    assert "[int]$DiagnosticIdleSeconds = 0" in runner
    assert 'if ($Mode -ne "DiagnosticStages" -and $DiagnosticIdleSeconds -ne 0)' in runner
    assert 'Join-Path $runDirectory "diagnostic-baseline"' in runner
    assert "Start-Sleep -Seconds $DiagnosticIdleSeconds" in runner
    assert 'if ($Mode -in @("Full", "PreflightSmoke"))' in runner
    assert "Full Gate C acceptance prohibits -SkipBuild." in runner
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
    assert "Start-Sleep -Seconds $DiagnosticRecoverySeconds" in runner
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
        "process_version": "Gate-C-11-v1.0",
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
    assert "Start-Sleep -Seconds 300" in runner
    assert "Get-ComposeImageReference" in runner
    assert 'docker image inspect --format "{{.Id}}" $imageReference' in runner

    assert compose.count("cybercontrol/gate-c-backend:${GATE_C_IMAGE_TAG:-unknown}") == 2
    assert "cybercontrol/gate-c-mock-provider:${GATE_C_IMAGE_TAG:-unknown}" in compose
    assert "cybercontrol/gate-c-frontend:${GATE_C_IMAGE_TAG:-unknown}" in compose
    assert "cybercontrol/gate-c-load:${GATE_C_IMAGE_TAG:-unknown}" in compose


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
