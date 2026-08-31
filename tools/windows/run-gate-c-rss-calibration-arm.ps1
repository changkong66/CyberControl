[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "Measurement", "APrime")]
    [string]$Arm,

    [Parameter(Mandatory = $true)]
    [ValidateSet("S", "R", "P", "F")]
    [string]$Variable,

    [Parameter(Mandatory = $true)]
    [string]$ImageLockPath,

    [Parameter(Mandatory = $true)]
    [string]$TlsBundlePath,

    [string]$ResultsRoot = "D:\CyberControlAcceptance\phase7\gate-c\diagnostics\adr0032",

    [string]$DockerDataRoot = "F:\Docker\DockerDesktopWSL",

    [string]$DockerInternalRoot = "/mnt/docker-desktop-disk",

    [ValidateRange(0, 2)]
    [int]$InfraRetryAttempt = 0,

    [string]$RetryOfRunId,

    [string]$PriorArmResult
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "gate-c-capacity.ps1")

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$composePath = Join-Path $root "tests\load\docker-compose.gate-c-rss-calibration.yml"
$imageLockTool = Join-Path $root "tools\gate_c_image_lock.py"
$packageTool = Join-Path $root "tests\load\gate_c\diagnostic_evidence_package.py"
$capacityMonitorPath = Join-Path $root "tools\windows\watch-gate-c-capacity.ps1"
$processVersion = "Gate-C-12-v1.0"
$capacityPolicyRevision = "Gate-C-12-capacity-v1.1"
[double]$capacityAdmissionGiB = 15.0
[double]$capacityWarningGiB = 8.0
[double]$capacityStopGiB = 5.0
$thresholdPath = Join-Path $root "tests\load\gate-c-thresholds.v1.json"
$workloadPath = Join-Path $root "tests\load\gate-c-workload.v1.json"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$runId = "adr0032-$($Variable.ToLowerInvariant())-$($Arm.ToLowerInvariant())-$timestamp-$suffix"
$projectName = "cc-gc12-$($Variable.ToLowerInvariant())-$($Arm.ToLowerInvariant())-$suffix"
$volumeName = "cc_gc12_${suffix}_postgres"
$runDirectory = [IO.Path]::GetFullPath((Join-Path $ResultsRoot $runId))
$evidenceDirectory = Join-Path $runDirectory "evidence"
$secretsDirectory = Join-Path $runDirectory "secrets"
$tlsDirectory = Join-Path $secretsDirectory "tls"
$passwordPath = Join-Path $secretsDirectory "postgres-password"
$resultPath = Join-Path $evidenceDirectory "calibration-arm.json"
$packagePath = Join-Path $runDirectory "evidence.zip"
$manifestPath = Join-Path $runDirectory "evidence-manifest.json"
$cleanupReceiptPath = Join-Path $runDirectory "cleanup-receipt.json"
$packageReferencePath = Join-Path $runDirectory "package-reference.json"
$runSummaryPath = Join-Path $runDirectory "run-summary.json"
$stopFile = Join-Path $evidenceDirectory "capacity-monitor.stop"
$composeArguments = @("-p", $projectName, "-f", $composePath)
$capacityMonitor = $null
$archiveVerified = $false
$volumeCreated = $false
$classification = "NON_ACCEPTANCE_DIAGNOSTIC"
$failureReason = $null
$composeExitCode = $null

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-NewJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    if (Test-Path -LiteralPath $Path) {
        throw "Immutable JSON output already exists: $Path"
    }
    [IO.File]::WriteAllText(
        $Path,
        (($Value | ConvertTo-Json -Depth 12) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
}

function Get-CapacitySnapshot {
    return Get-GateCMultiRootCapacitySnapshot `
        -ResultsRoot $ResultsRoot `
        -DockerDataRoot $DockerDataRoot `
        -DockerInternalRoot $DockerInternalRoot `
        -PolicyRevision $capacityPolicyRevision `
        -AdmissionGiB $capacityAdmissionGiB `
        -WarningGiB $capacityWarningGiB `
        -StopGiB $capacityStopGiB `
        -ProjectName $projectName
}

function Assert-CapacityAdmission {
    $snapshot = Get-CapacitySnapshot
    if ($snapshot.admission_ready -ne $true) {
        throw "Gate C capacity admission failed: $($snapshot.limiting_target) has $($snapshot.free_gib) GiB available."
    }
    return $snapshot
}

function Assert-PriorArm {
    $expected = switch ($Arm) {
        "A" { $null }
        "Measurement" { "A" }
        "APrime" { "Measurement" }
    }
    if ($null -eq $expected) {
        if (-not [string]::IsNullOrWhiteSpace($PriorArmResult)) {
            throw "A control arm cannot consume a prior arm result."
        }
        return
    }
    if ([string]::IsNullOrWhiteSpace($PriorArmResult)) {
        throw "$Arm requires -PriorArmResult for the immediately preceding $expected arm."
    }
    $resolved = [IO.Path]::GetFullPath($PriorArmResult)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "Prior arm result does not exist: $resolved"
    }
    $prior = Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        $prior.schema_version -ne "cybercontrol.gate-c-rss-calibration-arm.v1" -or
        $prior.process_version -ne $processVersion -or
        $prior.classification -ne "NON_ACCEPTANCE_DIAGNOSTIC" -or
        $prior.formal_gate_attempt -ne $false -or
        $prior.acceptance_claim -ne $false -or
        $prior.arm -ne $expected -or
        $prior.variable -ne $Variable -or
        $prior.source.source_sha -ne $sourceCommit -or
        $prior.source.source_tree -ne $sourceTree -or
        $prior.source.product_source_sha -ne [string]$imageLock.source.product_source_sha -or
        $prior.source.engineering_baseline_sha -ne
            [string]$imageLock.source.engineering_baseline_sha -or
        $prior.source.image_id -ne [string]$diagnostic.image_id -or
        $prior.source.image_lock_sha256 -ne (Get-FileSha256 $resolvedLockPath) -or
        $prior.source.build_receipt_sha256 -ne (Get-FileSha256 $receiptPath) -or
        $prior.passed -ne $true
    ) {
        throw "Prior arm result is not eligible for $Arm."
    }
    foreach ($control in $prior.zero_tolerance.PSObject.Properties) {
        if ($control.Value -ne $true) {
            throw "$Arm is prohibited after zero-tolerance failure $($control.Name)."
        }
    }
}

function Get-JemallocBinding {
    param([Parameter(Mandatory = $true)][string]$ImageReference)
    $values = @(& docker run --rm --entrypoint /bin/sh $ImageReference -c `
        'set -eu; p=/opt/cybercontrol/jemalloc-prof/lib/libjemalloc.so.2; sha256sum "$p" | cut -d" " -f1; readelf -n "$p" | awk ''/Build ID:/ {print $3}''')
    if ($LASTEXITCODE -ne 0 -or $values.Count -ne 2) {
        throw "Unable to read the diagnostic jemalloc binding."
    }
    if ($values[0] -notmatch '^[0-9a-f]{64}$' -or $values[1] -notmatch '^[0-9a-f]{40}$') {
        throw "Diagnostic jemalloc binding is invalid."
    }
    return [ordered]@{ sha256 = $values[0]; build_id = $values[1] }
}

function Start-CapacityMonitor {
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $arguments = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $capacityMonitorPath,
        "-ResultsRoot", $ResultsRoot,
        "-DockerDataRoot", $DockerDataRoot,
        "-DockerInternalRoot", $DockerInternalRoot,
        "-RunDirectory", $evidenceDirectory,
        "-ProjectName", $projectName,
        "-StopFile", $stopFile,
        "-ParentProcessId", [string]$PID,
        "-PolicyRevision", $capacityPolicyRevision,
        "-AdmissionGiB", [string]$capacityAdmissionGiB,
        "-WarningGiB", [string]$capacityWarningGiB,
        "-StopGiB", [string]$capacityStopGiB,
        "-SampleIntervalSeconds", "5"
    )
    $script:capacityMonitor = Start-Process -FilePath $pwsh -ArgumentList $arguments `
        -WorkingDirectory $root `
        -RedirectStandardOutput (Join-Path $evidenceDirectory "capacity-monitor.stdout.log") `
        -RedirectStandardError (Join-Path $evidenceDirectory "capacity-monitor.stderr.log") `
        -WindowStyle Hidden -PassThru
    $null = $script:capacityMonitor.Handle
}

function Stop-CapacityMonitor {
    if ($null -eq $script:capacityMonitor) {
        return
    }
    if (-not $script:capacityMonitor.HasExited) {
        New-Item -ItemType File -Path $stopFile -Force | Out-Null
        if (-not $script:capacityMonitor.WaitForExit(30000)) {
            $script:capacityMonitor.Kill($true)
            throw "Capacity monitor did not stop cleanly."
        }
    }
    $script:capacityMonitor.Refresh()
    Write-NewJson -Path (Join-Path $evidenceDirectory "capacity-monitor-exit.json") -Value ([ordered]@{
        schema_version = "cybercontrol.gate-c-capacity-monitor-exit.v1"
        process_version = $processVersion
        captured_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        exit_code = $script:capacityMonitor.ExitCode
        hard_stop = (Test-Path -LiteralPath (Join-Path $evidenceDirectory "capacity-hard-stop.json"))
    })
    $script:capacityMonitor = $null
}

function Remove-ArmResources {
    & docker compose @composeArguments down --remove-orphans --volumes 2>&1 |
        Set-Content -LiteralPath (Join-Path $runDirectory "cleanup-compose.log") -Encoding UTF8
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to stop calibration Compose resources."
    }
    $containers = @(& docker ps --all --filter "label=com.docker.compose.project=$projectName" --format "{{.ID}}")
    $networks = @(& docker network ls --filter "label=com.docker.compose.project=$projectName" --format "{{.ID}}")
    $projectVolumes = @(& docker volume ls --filter "label=com.docker.compose.project=$projectName" --format "{{.Name}}")
    $namedVolume = @(& docker volume ls --filter "name=^${volumeName}$" --format "{{.Name}}")
    if ($namedVolume -contains $volumeName) {
        & docker volume rm $volumeName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to remove the current arm PostgreSQL volume."
        }
    }
    $remainingVolume = @(& docker volume ls --filter "name=^${volumeName}$" --format "{{.Name}}")
    if ($containers.Count -ne 0 -or $networks.Count -ne 0 -or $projectVolumes.Count -ne 0 -or $remainingVolume.Count -ne 0) {
        throw "Calibration arm cleanup left project resources behind."
    }
    $resolvedSecrets = [IO.Path]::GetFullPath($secretsDirectory)
    $resolvedRun = [IO.Path]::GetFullPath($runDirectory).TrimEnd('\') + '\'
    if (-not $resolvedSecrets.StartsWith($resolvedRun, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a secrets path outside the current arm directory."
    }
    if (Test-Path -LiteralPath $resolvedSecrets) {
        Remove-Item -LiteralPath $resolvedSecrets -Recurse -Force
    }
    $resolvedEvidence = [IO.Path]::GetFullPath($evidenceDirectory)
    if (-not $resolvedEvidence.StartsWith($resolvedRun, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove evidence intermediates outside the current arm directory."
    }
    if (Test-Path -LiteralPath $resolvedEvidence) {
        Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
    }
    $capacity = Get-CapacitySnapshot
    Write-NewJson -Path $cleanupReceiptPath -Value ([ordered]@{
        schema_version = "cybercontrol.gate-c-diagnostic-cleanup-receipt.v1"
        process_version = $processVersion
        classification = "NON_ACCEPTANCE_DIAGNOSTIC"
        run_id = $runId
        project_name = $projectName
        postgres_volume = $volumeName
        zero_containers = $true
        zero_networks = $true
        zero_project_volumes = $true
        postgres_volume_removed = $true
        secrets_removed = (-not (Test-Path -LiteralPath $resolvedSecrets))
        archived_intermediates_removed = (-not (Test-Path -LiteralPath $resolvedEvidence))
        capacity_after_cleanup = $capacity
        next_arm_admission_ready = [bool]$capacity.admission_ready
        completed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    })
}

if ($InfraRetryAttempt -eq 0 -and -not [string]::IsNullOrWhiteSpace($RetryOfRunId)) {
    throw "-RetryOfRunId is valid only when -InfraRetryAttempt is 1 or 2."
}
if ($InfraRetryAttempt -gt 0 -and [string]::IsNullOrWhiteSpace($RetryOfRunId)) {
    throw "An infrastructure retry requires -RetryOfRunId."
}
$sourceCommit = (& git -C $root rev-parse HEAD).Trim()
$sourceTree = (& git -C $root rev-parse "HEAD^{tree}").Trim()
$originMain = (& git -C $root rev-parse origin/main).Trim()
$status = @(& git -C $root status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $sourceCommit -ne $originMain -or $status.Count -ne 0) {
    throw "Calibration requires a clean exact origin/main worktree."
}
$runningContainers = @(& docker ps --format "{{.ID}}")
if ($LASTEXITCODE -ne 0 -or $runningContainers.Count -ne 0) {
    throw "Calibration requires Docker Server availability and zero running containers."
}
$capacityAtStart = Assert-CapacityAdmission

$resolvedLockPath = [IO.Path]::GetFullPath($ImageLockPath)
& uv run --frozen python $imageLockTool --root $root verify --image-lock $resolvedLockPath
if ($LASTEXITCODE -ne 0) {
    throw "INFRA_ABORTED: diagnostic image-lock verification failed."
}
$imageLock = Get-Content -LiteralPath $resolvedLockPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($imageLock.source.commit -ne $sourceCommit -or $imageLock.source.tree -ne $sourceTree) {
    throw "INFRA_ABORTED: image lock does not bind exact origin/main."
}
$diagnostic = $imageLock.diagnostic_images.'rss-calibration'
if ($null -eq $diagnostic -or $diagnostic.role -ne "NON_ACCEPTANCE_DIAGNOSTIC") {
    throw "INFRA_ABORTED: image lock has no diagnostic-only calibration image."
}
foreach ($service in $imageLock.services.PSObject.Properties) {
    if ($service.Value.image_id -eq $diagnostic.image_id) {
        throw "INFRA_ABORTED: diagnostic image cannot impersonate formal service $($service.Name)."
    }
}
$actualDiagnosticId = (& docker image inspect --format "{{.Id}}" ([string]$diagnostic.reference)).Trim()
if ($LASTEXITCODE -ne 0 -or $actualDiagnosticId -ne [string]$diagnostic.image_id) {
    throw "INFRA_ABORTED: local diagnostic image content differs from the image lock."
}
$jemalloc = Get-JemallocBinding -ImageReference ([string]$diagnostic.reference)

if (Test-Path -LiteralPath $runDirectory) {
    throw "Immutable calibration run directory already exists: $runDirectory"
}
New-Item -ItemType Directory -Path $evidenceDirectory, $tlsDirectory -Force | Out-Null
$passwordBytes = [byte[]]::new(32)
[Security.Cryptography.RandomNumberGenerator]::Fill($passwordBytes)
$password = [Convert]::ToBase64String($passwordBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
$resolvedTlsBundle = [IO.Path]::GetFullPath($TlsBundlePath)
if (-not (Test-Path -LiteralPath $resolvedTlsBundle -PathType Container)) {
    throw "Sequence TLS bundle does not exist: $resolvedTlsBundle"
}
foreach ($name in @("ca.crt", "server.crt", "server.key", "tls-manifest.json")) {
    $source = Join-Path $resolvedTlsBundle $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Sequence TLS bundle is missing $name."
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $tlsDirectory $name)
}
$tlsManifest = Get-Content -LiteralPath (Join-Path $tlsDirectory "tls-manifest.json") `
    -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $tlsManifest.schema_version -ne "cybercontrol.gate-c-calibration-tls.v1" -or
    $tlsManifest.process_version -ne $processVersion -or
    $tlsManifest.classification -ne "NON_ACCEPTANCE_DIAGNOSTIC" -or
    $tlsManifest.server_hostname -ne "postgres" -or
    $tlsManifest.ca_private_key_persisted -ne $false -or
    $tlsManifest.server_private_key_recorded_in_evidence -ne $false
) {
    throw "Sequence TLS bundle manifest is invalid."
}
Copy-Item -LiteralPath (Join-Path $tlsDirectory "tls-manifest.json") `
    -Destination (Join-Path $evidenceDirectory "tls-manifest.json")

$receiptPath = Join-Path (Split-Path -Parent $resolvedLockPath) ([string]$imageLock.build_receipt.path)
Assert-PriorArm
$execution = [ordered]@{
    schema_version = "cybercontrol.gate-c-rss-calibration-execution.v1"
    process_version = $processVersion
    classification = "NON_ACCEPTANCE_DIAGNOSTIC"
    formal_gate_attempt = $false
    acceptance_claim = $false
    run_id = $runId
    arm = $Arm
    variable = $Variable
    infra_retry_attempt = $InfraRetryAttempt
    retry_of_run_id = $RetryOfRunId
    source_sha = $sourceCommit
    source_tree = $sourceTree
    product_source_sha = [string]$imageLock.source.product_source_sha
    engineering_baseline_sha = [string]$imageLock.source.engineering_baseline_sha
    project_name = $projectName
    postgres_volume = $volumeName
    image_lock_sha256 = Get-FileSha256 $resolvedLockPath
    build_receipt_sha256 = Get-FileSha256 $receiptPath
    diagnostic_image = $diagnostic
    postgres_image = $imageLock.services.postgres
    jemalloc = $jemalloc
    threshold_sha256 = Get-FileSha256 $thresholdPath
    workload_sha256 = Get-FileSha256 $workloadPath
    capacity_at_start = $capacityAtStart
    database_credentials_recorded = $false
    started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
}
Write-NewJson -Path (Join-Path $evidenceDirectory "execution-metadata.json") -Value $execution
Write-NewJson -Path (Join-Path $evidenceDirectory "execution-context.json") -Value $execution

$env:GATE_C_POSTGRES_IMAGE = [string]$imageLock.services.postgres.reference
$env:GATE_C_DIAGNOSTIC_IMAGE_REFERENCE = [string]$diagnostic.reference
$env:GATE_C_TLS_DIR = $tlsDirectory
$env:GATE_C_SECRETS_DIR = $secretsDirectory
$env:GATE_C_RESULTS_DIR = $evidenceDirectory
$env:GATE_C_POSTGRES_VOLUME = $volumeName
$env:GATE_C_CALIBRATION_ARM = $Arm
$env:GATE_C_CALIBRATION_VARIABLE = $Variable
$env:GATE_C_CALIBRATION_RUN_ID = $runId
$env:GATE_C_SOURCE_SHA = $sourceCommit
$env:GATE_C_SOURCE_TREE = $sourceTree
$env:GATE_C_PRODUCT_SOURCE_SHA = [string]$imageLock.source.product_source_sha
$env:GATE_C_ENGINEERING_BASELINE_SHA = [string]$imageLock.source.engineering_baseline_sha
$env:GATE_C_DIAGNOSTIC_IMAGE_ID = [string]$diagnostic.image_id
$env:GATE_C_DIAGNOSTIC_IMAGE_DIGEST = [string]$diagnostic.image_id
$env:GATE_C_IMAGE_LOCK_SHA256 = Get-FileSha256 $resolvedLockPath
$env:GATE_C_BUILD_RECEIPT_SHA256 = Get-FileSha256 $receiptPath
$env:GATE_C_JEMALLOC_PROFILE_LIBRARY_SHA256 = [string]$jemalloc.sha256
$env:GATE_C_JEMALLOC_PROFILE_LIBRARY_BUILD_ID = [string]$jemalloc.build_id

try {
    & docker volume create `
        --label com.cybercontrol.purpose=gate-c-12-adr0032-calibration `
        --label com.cybercontrol.run-id=$runId `
        --label com.cybercontrol.data-class=ephemeral-diagnostic-postgres `
        $volumeName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "INFRA_ABORTED: failed to create the fresh calibration PostgreSQL volume."
    }
    $volumeCreated = $true
    & docker compose @composeArguments config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "INFRA_ABORTED: calibration Compose validation failed."
    }
    $composeImages = @(& docker compose @composeArguments config --images | Sort-Object -Unique)
    $expectedImages = @(
        [string]$imageLock.services.postgres.reference,
        [string]$diagnostic.reference
    ) | Sort-Object -Unique
    if ((Compare-Object $composeImages $expectedImages).Count -ne 0) {
        throw "INFRA_ABORTED: calibration Compose images differ from the locked pair."
    }
    Start-CapacityMonitor
    & docker compose @composeArguments up --abort-on-container-exit --exit-code-from calibration `
        --no-build --pull never 2>&1 |
        Tee-Object -FilePath (Join-Path $evidenceDirectory "compose-up.log")
    $composeExitCode = $LASTEXITCODE
    & docker compose @composeArguments ps --all --format json 2>&1 |
        Set-Content -LiteralPath (Join-Path $evidenceDirectory "compose-ps.jsonl") -Encoding UTF8
    & docker compose @composeArguments logs --no-color --timestamps 2>&1 |
        Set-Content -LiteralPath (Join-Path $evidenceDirectory "compose.log") -Encoding UTF8
    if (Test-Path -LiteralPath (Join-Path $evidenceDirectory "capacity-hard-stop.json")) {
        $classification = "INFRA_ABORTED"
        throw "INFRA_ABORTED: capacity hard stop activated below 5 GiB."
    }
    if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
        $classification = "DESIGN_REJECTED"
        throw "Calibration instrumentation did not produce an arm result."
    }
    $armResult = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        $armResult.process_version -ne $processVersion -or
        $armResult.run_id -ne $runId -or
        $armResult.arm -ne $Arm -or
        $armResult.variable -ne $Variable -or
        $armResult.source.source_sha -ne $sourceCommit -or
        $armResult.source.image_id -ne [string]$diagnostic.image_id
    ) {
        $classification = "DESIGN_REJECTED"
        throw "Calibration result source or variable binding is invalid."
    }
    if ($composeExitCode -ne 0 -or $armResult.passed -ne $true) {
        $classification = "DESIGN_REJECTED"
        throw "Calibration arm failed its zero-tolerance controls."
    }
}
catch {
    $failureReason = $_.Exception.Message
    if ($failureReason.StartsWith("INFRA_ABORTED", [StringComparison]::Ordinal)) {
        $classification = "INFRA_ABORTED"
    }
    Write-NewJson -Path (Join-Path $evidenceDirectory "execution-failure.json") -Value ([ordered]@{
        schema_version = "cybercontrol.gate-c-rss-calibration-failure.v1"
        process_version = $processVersion
        classification = $classification
        formal_gate_attempt = $false
        acceptance_claim = $false
        run_id = $runId
        arm = $Arm
        variable = $Variable
        reason = $failureReason
        failed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    })
}

try {
    Stop-CapacityMonitor
    if ($volumeCreated) {
        & docker compose @composeArguments ps --all --format json 2>&1 |
            Set-Content -LiteralPath (Join-Path $evidenceDirectory "compose-final-ps.jsonl") -Encoding UTF8
    }
    & uv run --frozen python $packageTool `
        --evidence-directory $evidenceDirectory `
        --package $packagePath `
        --manifest $manifestPath `
        --run-id $runId `
        --forbidden-value-file $passwordPath
    if ($LASTEXITCODE -ne 0) {
        throw "Diagnostic evidence package creation or verification failed."
    }
    $summarySource = if (Test-Path -LiteralPath $resultPath -PathType Leaf) {
        $resultPath
    }
    else {
        Join-Path $evidenceDirectory "execution-failure.json"
    }
    Copy-Item -LiteralPath $summarySource -Destination $runSummaryPath
    $archiveVerified = $true
}
finally {
    if ($archiveVerified) {
        Remove-ArmResources
        $cleanupReceipt = Get-Content -LiteralPath $cleanupReceiptPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if ($cleanupReceipt.next_arm_admission_ready -ne $true -and $null -eq $failureReason) {
            $classification = "INFRA_ABORTED"
            $failureReason = "Capacity did not recover to the 15 GiB next-arm admission floor."
        }
        Write-NewJson -Path $packageReferencePath -Value ([ordered]@{
            schema_version = "cybercontrol.gate-c-diagnostic-package-reference.v1"
            process_version = $processVersion
            classification = $classification
            formal_gate_attempt = $false
            acceptance_claim = $false
            run_id = $runId
            evidence_package = [ordered]@{
                path = $packagePath
                size_bytes = (Get-Item -LiteralPath $packagePath).Length
                sha256 = Get-FileSha256 $packagePath
            }
            evidence_manifest = [ordered]@{
                path = $manifestPath
                sha256 = Get-FileSha256 $manifestPath
            }
            cleanup_receipt = [ordered]@{
                path = $cleanupReceiptPath
                sha256 = Get-FileSha256 $cleanupReceiptPath
            }
            run_summary = [ordered]@{
                path = $runSummaryPath
                sha256 = Get-FileSha256 $runSummaryPath
            }
        })
    }
    foreach ($name in @(
        "GATE_C_POSTGRES_IMAGE", "GATE_C_DIAGNOSTIC_IMAGE_REFERENCE", "GATE_C_TLS_DIR",
        "GATE_C_SECRETS_DIR", "GATE_C_RESULTS_DIR", "GATE_C_POSTGRES_VOLUME",
        "GATE_C_CALIBRATION_ARM", "GATE_C_CALIBRATION_VARIABLE", "GATE_C_CALIBRATION_RUN_ID",
        "GATE_C_SOURCE_SHA", "GATE_C_SOURCE_TREE", "GATE_C_PRODUCT_SOURCE_SHA",
        "GATE_C_ENGINEERING_BASELINE_SHA", "GATE_C_DIAGNOSTIC_IMAGE_ID",
        "GATE_C_DIAGNOSTIC_IMAGE_DIGEST", "GATE_C_IMAGE_LOCK_SHA256",
        "GATE_C_BUILD_RECEIPT_SHA256", "GATE_C_JEMALLOC_PROFILE_LIBRARY_SHA256",
        "GATE_C_JEMALLOC_PROFILE_LIBRARY_BUILD_ID"
    )) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

if ($null -ne $failureReason) {
    Write-Output $packageReferencePath
    throw "$classification`: $failureReason; immutable evidence: $packageReferencePath"
}
Write-Output $packageReferencePath
