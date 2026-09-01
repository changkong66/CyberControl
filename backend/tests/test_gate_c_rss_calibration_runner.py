from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_calibration_runner_enforces_non_formal_resource_and_retry_boundaries() -> None:
    runner = (ROOT / "tools" / "windows" / "run-gate-c-rss-calibration-arm.ps1").read_text(
        encoding="utf-8"
    )
    compose = (ROOT / "tests" / "load" / "docker-compose.gate-c-rss-calibration.yml").read_text(
        encoding="utf-8"
    )

    assert "[ValidateRange(0, 2)]" in runner
    assert "[double]$capacityAdmissionGiB = 15.0" in runner
    assert "[double]$capacityWarningGiB = 8.0" in runner
    assert "[double]$capacityStopGiB = 5.0" in runner
    assert 'classification = "NON_ACCEPTANCE_DIAGNOSTIC"' in runner
    assert "formal_gate_attempt = $false" in runner
    assert "acceptance_claim = $false" in runner
    assert "Prior arm result is not eligible" in runner
    assert "prohibited after zero-tolerance failure" in runner
    assert "down --remove-orphans --volumes" in runner
    assert "docker volume rm $volumeName" in runner
    assert "docker system prune" not in runner
    assert "$archiveVerified" in runner
    assert "Remove-ArmResources" in runner
    assert "-----BEGIN PRIVATE KEY-----" not in compose
    assert "POSTGRES_PASSWORD_FILE" in compose
    assert "sslmode=verify-full" in compose
    assert "gate_c_calibration:${GATE_C_POSTGRES_PASSWORD" not in compose
    assert "[IO.File]::WriteAllText(" in runner
    assert "$passwordPath," in runner
    assert "@(Compare-Object $composeImages $expectedImages).Count" in runner
    assert '$classification -ne "DESIGN_REJECTED"' in runner
    assert "orchestration failed before a trusted diagnostic result" in runner
    entrypoint = (
        ROOT / "tests" / "load" / "gate_c" / "postgres_calibration_entrypoint.sh"
    ).read_text(encoding="utf-8")
    assert "tls_runtime_dir=/run/postgresql/gate-c-tls" in entrypoint
    assert '"$PGDATA/' not in entrypoint
    assert "ssl_cert_file=/run/postgresql/gate-c-tls/server.crt" in compose
    assert "ssl_key_file=/run/postgresql/gate-c-tls/server.key" in compose
    assert "ssl_ca_file=/run/postgresql/gate-c-tls/ca.crt" in compose
    assert "--readiness-output" in compose
    assert "/gate-c-results/instrumentation-ready.json" in compose
    assert (
        "GATE_C_IMAGE_LOCK_SHA256: ${GATE_C_IMAGE_LOCK_SHA256:"
        "?GATE_C_IMAGE_LOCK_SHA256 is required}"
    ) in compose
    assert (
        "GATE_C_BUILD_RECEIPT_SHA256: ${GATE_C_BUILD_RECEIPT_SHA256:"
        "?GATE_C_BUILD_RECEIPT_SHA256 is required}"
    ) in compose
    assert '$calibrationContainerState = "absent"' in runner
    assert '$parts[0] -ne "created"' in runner
    assert "$parts[1] -notmatch '^0001-01-01T'" in runner
    assert '$classification = "INFRA_ABORTED"' in runner
    assert "calibration container never started" in runner
    assert "instrumentation did not reach the validated readiness marker" in runner
    assert "instrumentation readiness marker failed source-bound validation" in runner
    assert "instrumentation started but did not produce" in runner
    sequence = (ROOT / "tools" / "windows" / "run-gate-c-rss-calibration-sequence.ps1").read_text(
        encoding="utf-8"
    )
    assert 'Invoke-Arm -Arm "A"' in sequence
    assert '-Arm "Measurement"' in sequence
    assert '-Arm "APrime"' in sequence
    assert "tls_identity_reused_across_arms = $true" in sequence
    assert '--forbidden-value-file (Join-Path $tlsDirectory "server.key")' in sequence


def test_calibration_retry_metadata_propagates_across_all_wrapper_levels() -> None:
    scripts = {
        name: (ROOT / "tools" / "windows" / name).read_text(encoding="utf-8")
        for name in (
            "run-gate-c-rss-calibration-reproduction.ps1",
            "run-gate-c-rss-calibration-sequence.ps1",
            "run-gate-c-rss-l1-calibration-sequence.ps1",
        )
    }

    for script in scripts.values():
        assert "[ValidateRange(0, 2)]" in script
        assert '"-InfraRetryAttempt", [string]$InfraRetryAttempt' in script
        assert '$arguments += @("-RetryOfRunId", $RetryOfRunId)' in script
        assert "-RetryOfRunId is valid only when -InfraRetryAttempt is 1 or 2" in script
        assert "an infrastructure retry requires -RetryOfRunId" in script
        assert "infra_retry_attempt = $InfraRetryAttempt" in script
        assert "retry_of_run_id = $RetryOfRunId" in script


def test_calibration_and_l1_powershell_scripts_parse() -> None:
    scripts = (
        ROOT / "tools" / "windows" / "run-gate-c-rss-calibration-arm.ps1",
        ROOT / "tools" / "windows" / "run-gate-c-rss-calibration-sequence.ps1",
        ROOT / "tools" / "windows" / "run-gate-c-rss-l1-calibration-arm.ps1",
        ROOT / "tools" / "windows" / "run-gate-c-rss-l1-calibration-sequence.ps1",
        ROOT / "tools" / "windows" / "run-gate-c-rss-calibration-reproduction.ps1",
        ROOT / "tools" / "windows" / "invoke-gate-c-bounded-inventory-signal.ps1",
        ROOT / "tools" / "windows" / "run-phase7-gate-c.ps1",
        ROOT / "tools" / "windows" / "watch-gate-c-capacity.ps1",
        ROOT / "tools" / "windows" / "gate-c-capacity.ps1",
    )
    for script in scripts:
        command = (
            "$tokens=$null; $errors=$null; "
            f"[Management.Automation.Language.Parser]::ParseFile('{script}',"
            "[ref]$tokens,[ref]$errors) | Out-Null; "
            "if($errors.Count){$errors | ForEach-Object {$_.Message}; exit 1}"
        )
        completed = subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, f"{script}: {completed.stdout}\n{completed.stderr}"


def test_l1_runner_uses_fixed_windows_and_probe_mutex() -> None:
    runner = (ROOT / "tools" / "windows" / "run-phase7-gate-c.ps1").read_text(encoding="utf-8")
    overlay = (
        ROOT / "tests" / "load" / "docker-compose.gate-c-bounded-memory-inventory.yml"
    ).read_text(encoding="utf-8")

    assert '[string]$BoundedMemoryInventoryArm = "None"' in runner
    assert (
        "Bounded inventory, memory checkpoints and sampled profiling are mutually exclusive."
        in runner
    )
    assert '$DiagnosticStageNames[0] -ne "ramp-200"' in runner
    assert "$DiagnosticIdleSeconds -ne 300" in runner
    assert "$DiagnosticRecoverySeconds -ne 600" in runner
    assert "$peakDelaySeconds = [math]::Max(0, $totalSeconds - 60)" in runner
    assert 'Invoke-BoundedMemoryInventory -ContainerId $apiContainer -Label "baseline"' in runner
    assert 'Assert-BoundedMemoryInventoryManifest -Label "peak"' in runner
    assert 'Invoke-BoundedMemoryInventory -ContainerId $apiContainer -Label "recovery"' in runner
    assert "LIYAN_BOUNDED_MEMORY_INVENTORY_DIR" in overlay
    assert 'LIYAN_MEMORY_CHECKPOINT_DIR: ""' in overlay
    assert 'LIYAN_JEMALLOC_PROFILE_DIR: ""' in overlay
    assert '"DiagnosticStages" { "NON_ACCEPTANCE_DIAGNOSTIC" }' in runner
    heartbeat = (
        ROOT / "tests" / "load" / "docker-compose.gate-c-event-loop-heartbeat.yml"
    ).read_text(encoding="utf-8")
    assert 'LIYAN_EVENT_LOOP_HEARTBEAT_ENABLED: "true"' in heartbeat
    arm_runner = (ROOT / "tools" / "windows" / "run-gate-c-rss-l1-calibration-arm.ps1").read_text(
        encoding="utf-8"
    )
    sequence = (
        ROOT / "tools" / "windows" / "run-gate-c-rss-l1-calibration-sequence.ps1"
    ).read_text(encoding="utf-8")
    assert "[ValidateRange(0, 2)]" in arm_runner
    assert "Prior L1 arm source binding" in arm_runner
    assert "down --remove-orphans --volumes" in arm_runner
    assert "Remove-Item -LiteralPath $resolvedRun -Recurse -Force" in arm_runner
    assert "docker system prune" not in arm_runner
    assert 'Invoke-Arm -Arm "A"' in sequence
    assert '-Arm "Measurement"' in sequence
    assert '-Arm "APrime"' in sequence
    assert "A' is prohibited" in sequence


def test_failed_arm_reference_is_indexed_before_sequence_stops() -> None:
    for name in (
        "run-gate-c-rss-calibration-sequence.ps1",
        "run-gate-c-rss-l1-calibration-sequence.ps1",
    ):
        sequence = (ROOT / "tools" / "windows" / name).read_text(encoding="utf-8")
        invoke_start = sequence.index("function Invoke-Arm")
        continuation_start = sequence.index("function Assert-ArmContinuation")
        invoke_body = sequence[invoke_start:continuation_start]

        assert invoke_body.index("$referencePath = @(") < invoke_body.index(
            "$process.ExitCode -eq 0"
        )
        assert "classification = [string]$reference.classification" in invoke_body
        assert "process_exit_code = $process.ExitCode" in invoke_body
        assert "eligible_for_continuation = $eligibleForContinuation" in invoke_body

        a_assignment = sequence.index('$references.A = Invoke-Arm -Arm "A"')
        a_guard = sequence.index('Assert-ArmContinuation -Arm "A"')
        measurement_assignment = sequence.index("$references.Measurement = Invoke-Arm")
        measurement_guard = sequence.index('Assert-ArmContinuation -Arm "Measurement"')
        a_prime_assignment = sequence.index("$references.APrime = Invoke-Arm")
        assert a_assignment < a_guard < measurement_assignment
        assert measurement_assignment < measurement_guard < a_prime_assignment
        assert "arms = $references" in sequence
        assert '"DESIGN_REJECTED", "INFRA_ABORTED"' in sequence
        assert '$childError -match "INFRA_ABORTED:"' in sequence
        assert '$failureReason.StartsWith("INFRA_ABORTED"' in sequence


def test_reproduction_runner_requires_two_independent_sequences() -> None:
    runner = (ROOT / "tools" / "windows" / "run-gate-c-rss-calibration-reproduction.ps1").read_text(
        encoding="utf-8"
    )

    assert "$references.first = Invoke-Sequence -Number 1" in runner
    assert "$references.second = Invoke-Sequence -Number 2" in runner
    assert "--first-reference ([string]$references.first.reference_path)" in runner
    assert "--second-reference ([string]$references.second.reference_path)" in runner
    assert "formal_gate_attempt = $false" in runner
    assert "acceptance_claim = $false" in runner
    assert '"INFRA_ABORTED", "DESIGN_REJECTED"' not in runner
    assert '"DESIGN_REJECTED", "INFRA_ABORTED"' in runner


def test_adr0032_d0_and_execution_boundaries_are_structured() -> None:
    design = json.loads(
        (
            ROOT
            / "docs"
            / "diagnostics"
            / "phase7-gate-c-twelfth-p2"
            / "adr0032-design-authorization.json"
        ).read_text(encoding="utf-8")
    )

    assert set(design["d0_deliverables"]) == {
        "variable_matrix",
        "interference_formulas_and_zero_tolerance",
        "mutually_exclusive_memory_ledger",
        "attribution_admission_and_multi_owner_cutoff",
        "failure_exit_paths",
        "evidence_image_lock_and_cleanup_contract",
    }
    assert set(design["d0_deliverables"].values()) == {"PRESENT"}
    weak = design["attribution_admission"]["weak"]
    assert weak["minimum_dominant_owner_ratio"] == 0.7
    assert weak["independent_matched_runs"] == 2
    assert "APPEND_ONLY_ADR_0032_WEAK_ADMISSION_ADDENDUM" in weak["approval"]
    assert set(weak["required_evidence"]) >= {
        "residual_categories_bytes_and_ratios",
        "stable_reproduction_and_controls",
        "full_conservative_calculation",
        "two_run_ids",
        "two_package_sha256_values",
    }
    assert design["remediation_validation"]["prediction_deviation_stop_ratio"] == 1.3
    infra = design["outcomes"]["INFRA_ABORTED"]
    assert infra["same_cause_maximum_retries"] == 2
    assert infra["retry_scope"] == "CURRENT_LEVEL_ONLY"
    assert infra["counts_as_design_failure"] is False
    assert infra["gate_c_attempts_appended"] is False


def test_sequence_archives_summary_before_removing_intermediates() -> None:
    sequence = (ROOT / "tools" / "windows" / "run-gate-c-rss-calibration-sequence.ps1").read_text(
        encoding="utf-8"
    )

    assert 'Join-Path $sequenceDirectory "run-summary.json"' in sequence
    assert "Copy-Item -LiteralPath $summarySource -Destination $runSummaryPath" in sequence
    assert "archived_intermediates_removed" in sequence
    assert "Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force" in sequence
    assert "path = $runSummaryPath" in sequence
