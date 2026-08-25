[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "Measurement", "APrime")]
    [string]$Arm,

    [Parameter(Mandatory = $true)]
    [string]$ImageLockPath,

    [string]$ResultsRoot = "D:\CyberControlAcceptance\phase7\gate-c\diagnostics\adr0032-l1",

    [ValidateRange(1, 65535)]
    [int]$PostgresHostPort = 55432,

    [ValidateRange(0, 2)]
    [int]$InfraRetryAttempt = 0,

    [string]$RetryOfRunId,

    [string]$PriorArmResult
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$gateRunner = Join-Path $PSScriptRoot "run-phase7-gate-c.ps1"
$comparisonTool = Join-Path $root "tests\load\gate_c\rss_l1_calibration_compare.py"
$packageTool = Join-Path $root "tests\load\gate_c\diagnostic_evidence_package.py"
$imageLockTool = Join-Path $root "tools\gate_c_image_lock.py"
$baseCompose = Join-Path $root "infra\docker-compose.yml"
$gateCompose = Join-Path $root "tests\load\docker-compose.gate-c.yml"
$boundedCompose = Join-Path $root "tests\load\docker-compose.gate-c-bounded-memory-inventory.yml"
$heartbeatCompose = Join-Path $root "tests\load\docker-compose.gate-c-event-loop-heartbeat.yml"
$processVersion = "Gate-C-12-v1.0"
[double]$capacityAdmissionGiB = 15.0
[double]$capacityWarningGiB = 8.0
[double]$capacityStopGiB = 5.0
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$runId = "adr0032-l1-$($Arm.ToLowerInvariant())-$timestamp-$suffix"
$projectName = "cc-gc12-l1-$($Arm.ToLowerInvariant())-$suffix"
$volumeName = "cc_gc12_l1_${suffix}_postgres"
$armDirectory = [IO.Path]::GetFullPath((Join-Path $ResultsRoot $runId))
$rawResultsRoot = Join-Path $armDirectory "runs"
$stdoutPath = Join-Path $armDirectory "runner.stdout.log"
$stderrPath = Join-Path $armDirectory "runner.stderr.log"
$wrapperMetadataPath = Join-Path $armDirectory "wrapper-metadata.json"
$runSummaryPath = Join-Path $armDirectory "run-summary.json"
$outcomePath = Join-Path $armDirectory "outcome.json"
$packagePath = Join-Path $armDirectory "evidence.zip"
$manifestPath = Join-Path $armDirectory "evidence-manifest.json"
$cleanupReceiptPath = Join-Path $armDirectory "cleanup-receipt.json"
$packageReferencePath = Join-Path $armDirectory "package-reference.json"
$archiveVerified = $false
$runDirectory = $null
$failureReason = $null
$classification = "NON_ACCEPTANCE_DIAGNOSTIC"
$runnerExitCode = $null

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
    $driveRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($ResultsRoot))
    $driveName = $driveRoot.TrimEnd('\').TrimEnd(':')
    $freeBytes = [int64](Get-PSDrive -Name $driveName -ErrorAction Stop).Free
    $state = if ($freeBytes -lt [int64]($capacityStopGiB * 1GB)) {
        "HARD_STOP"
    }
    elseif ($freeBytes -lt [int64]($capacityWarningGiB * 1GB)) {
        "WARNING"
    }
    else {
        "NORMAL"
    }
    return [ordered]@{
        free_bytes = $freeBytes
        free_gib = [math]::Round([double]$freeBytes / 1GB, 3)
        admission_gib = $capacityAdmissionGiB
        warning_gib = $capacityWarningGiB
        stop_gib = $capacityStopGiB
        state = $state
        sampled_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    }
}

function Assert-PriorArm {
    param(
        [Parameter(Mandatory = $true)]$ExpectedSource
    )
    $expectedArm = switch ($Arm) {
        "A" { $null }
        "Measurement" { "A" }
        "APrime" { "Measurement" }
    }
    if ($null -eq $expectedArm) {
        if (-not [string]::IsNullOrWhiteSpace($PriorArmResult)) {
            throw "A control arm cannot consume a prior L1 arm result."
        }
        return
    }
    if ([string]::IsNullOrWhiteSpace($PriorArmResult)) {
        throw "$Arm requires the immediately preceding $expectedArm L1 arm result."
    }
    $priorPath = [IO.Path]::GetFullPath($PriorArmResult)
    if (-not (Test-Path -LiteralPath $priorPath -PathType Leaf)) {
        throw "Prior L1 arm result does not exist: $priorPath"
    }
    $prior = Get-Content -LiteralPath $priorPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        $prior.schema_version -ne "cybercontrol.gate-c-rss-l1-calibration-arm.v1" -or
        $prior.process_version -ne $processVersion -or
        $prior.classification -ne "NON_ACCEPTANCE_DIAGNOSTIC" -or
        $prior.formal_gate_attempt -ne $false -or
        $prior.acceptance_claim -ne $false -or
        $prior.arm -ne $expectedArm -or
        $prior.passed -ne $true
    ) {
        throw "Prior L1 arm result is not eligible for $Arm."
    }
    foreach ($binding in $ExpectedSource.GetEnumerator()) {
        $actual = $prior.source.PSObject.Properties[$binding.Key]
        if ($null -eq $actual -or [string]$actual.Value -ne [string]$binding.Value) {
            throw "Prior L1 arm source binding $($binding.Key) does not match the current lock."
        }
    }
}

function Find-RunDirectory {
    $matches = @(
        Get-ChildItem -LiteralPath $rawResultsRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object {
                $metadataPath = Join-Path $_.FullName "execution-metadata.json"
                if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
                    return $false
                }
                $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 |
                    ConvertFrom-Json
                return $metadata.project -eq $projectName
            }
    )
    if ($matches.Count -gt 1) {
        throw "L1 wrapper found multiple run directories for its unique Compose project."
    }
    $result = if ($matches.Count -eq 1) { $matches[0].FullName } else { $null }
    return $result
}

function Remove-ArmResources {
    $env:GATE_C_RESULTS_DIR = if ($null -ne $runDirectory) { $runDirectory } else { $armDirectory }
    $env:GATE_C_POSTGRES_VOLUME = $volumeName
    $env:GATE_C_IMAGE_TAG = [string]$expectedSource.source_commit
    $env:GATE_C_SOURCE_SHA = [string]$expectedSource.source_commit
    $env:GATE_C_SOURCE_TREE = [string]$expectedSource.source_tree
    $env:GATE_C_PRODUCT_SOURCE_SHA = [string]$expectedSource.product_source_sha
    $env:GATE_C_ENGINEERING_BASELINE_SHA = [string]$expectedSource.engineering_baseline_sha
    $env:GATE_C_PROCESS_VERSION = $processVersion
    $composeArguments = @("-p", $projectName, "-f", $baseCompose, "-f", $gateCompose)
    if ($Arm -eq "Measurement") {
        $composeArguments += @("-f", $boundedCompose)
    }
    $composeArguments += @("-f", $heartbeatCompose, "--profile", "gate-c-load")
    $cleanupLogPath = Join-Path $armDirectory "cleanup-compose.log"
    & docker compose @composeArguments down --remove-orphans --volumes 2>&1 |
        Set-Content -LiteralPath $cleanupLogPath -Encoding UTF8
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to stop L1 calibration Compose resources."
    }
    $containers = @(& docker ps --all `
        --filter "label=com.docker.compose.project=$projectName" --format "{{.ID}}")
    $networks = @(& docker network ls `
        --filter "label=com.docker.compose.project=$projectName" --format "{{.ID}}")
    $projectVolumes = @(& docker volume ls `
        --filter "label=com.docker.compose.project=$projectName" --format "{{.Name}}")
    $namedVolume = @(& docker volume ls --filter "name=^${volumeName}$" --format "{{.Name}}")
    if ($namedVolume -contains $volumeName) {
        & docker volume rm $volumeName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to remove the current L1 PostgreSQL volume."
        }
    }
    $remainingVolume = @(& docker volume ls `
        --filter "name=^${volumeName}$" --format "{{.Name}}")
    if (
        $containers.Count -ne 0 -or
        $networks.Count -ne 0 -or
        $projectVolumes.Count -ne 0 -or
        $remainingVolume.Count -ne 0
    ) {
        throw "L1 arm cleanup left temporary project resources behind."
    }
    if ($null -ne $runDirectory) {
        $resolvedRun = [IO.Path]::GetFullPath($runDirectory)
        $resolvedArm = [IO.Path]::GetFullPath($armDirectory).TrimEnd('\') + '\'
        if (-not $resolvedRun.StartsWith($resolvedArm, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove an L1 run directory outside the current arm archive."
        }
        Remove-Item -LiteralPath $resolvedRun -Recurse -Force
    }
    if ((Test-Path -LiteralPath $rawResultsRoot) -and -not (Get-ChildItem $rawResultsRoot -Force)) {
        Remove-Item -LiteralPath $rawResultsRoot -Force
    }
    $cleanupLogSha256 = Get-FileSha256 $cleanupLogPath
    foreach ($path in @(
        $stdoutPath,
        $stderrPath,
        (Join-Path $armDirectory "image-lock-verification.log"),
        $cleanupLogPath
    )) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    $capacity = Get-CapacitySnapshot
    Write-NewJson -Path $cleanupReceiptPath -Value ([ordered]@{
        schema_version = "cybercontrol.gate-c-rss-l1-cleanup.v1"
        process_version = $processVersion
        classification = "NON_ACCEPTANCE_DIAGNOSTIC"
        run_id = $runId
        project_name = $projectName
        postgres_volume = $volumeName
        zero_containers = $true
        zero_networks = $true
        zero_project_volumes = $true
        postgres_volume_removed = $true
        archived_intermediates_removed = $true
        cleanup_compose_log_sha256 = $cleanupLogSha256
        capacity_after_cleanup = $capacity
        next_arm_admission_ready = (
            [int64]$capacity.free_bytes -ge [int64]($capacityAdmissionGiB * 1GB)
        )
        completed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    })
}

if ($InfraRetryAttempt -eq 0 -and -not [string]::IsNullOrWhiteSpace($RetryOfRunId)) {
    throw "-RetryOfRunId is valid only for infrastructure retry attempts 1 or 2."
}
if ($InfraRetryAttempt -gt 0 -and [string]::IsNullOrWhiteSpace($RetryOfRunId)) {
    throw "An infrastructure retry requires -RetryOfRunId."
}
if (Test-Path -LiteralPath $armDirectory) {
    throw "Immutable L1 arm directory already exists: $armDirectory"
}
New-Item -ItemType Directory -Path $rawResultsRoot -Force | Out-Null

$sourceCommit = (& git -C $root rev-parse HEAD).Trim()
$sourceTree = (& git -C $root rev-parse "HEAD^{tree}").Trim()
$originMain = (& git -C $root rev-parse origin/main).Trim()
$status = @(& git -C $root status --porcelain=v1 --untracked-files=all)
$capacityAtStart = Get-CapacitySnapshot
$resolvedLockPath = [IO.Path]::GetFullPath($ImageLockPath)
& uv run --frozen python $imageLockTool --root $root verify --image-lock $resolvedLockPath `
    *> (Join-Path $armDirectory "image-lock-verification.log")
if ($LASTEXITCODE -ne 0) {
    throw "INFRA_ABORTED: L1 image-lock verification failed."
}
$imageLock = Get-Content -LiteralPath $resolvedLockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$receiptPath = Join-Path (Split-Path -Parent $resolvedLockPath) ([string]$imageLock.build_receipt.path)
$expectedSource = [ordered]@{
    source_commit = $sourceCommit
    source_tree = $sourceTree
    product_source_sha = [string]$imageLock.source.product_source_sha
    engineering_baseline_sha = [string]$imageLock.source.engineering_baseline_sha
    image_lock_sha256 = Get-FileSha256 $resolvedLockPath
    build_receipt_sha256 = Get-FileSha256 $receiptPath
}
Assert-PriorArm -ExpectedSource $expectedSource
if ($sourceCommit -ne $originMain -or $status.Count -ne 0) {
    throw "L1 calibration requires a clean exact origin/main worktree."
}
if (
    $imageLock.source.commit -ne $sourceCommit -or
    $imageLock.source.tree -ne $sourceTree -or
    [int64]$capacityAtStart.free_bytes -lt [int64]($capacityAdmissionGiB * 1GB)
) {
    throw "INFRA_ABORTED: L1 source, image lock or 15 GiB capacity admission failed."
}
$runningContainers = @(& docker ps --format "{{.ID}}")
if ($LASTEXITCODE -ne 0 -or $runningContainers.Count -ne 0) {
    throw "INFRA_ABORTED: L1 calibration requires Docker and zero running containers."
}

Write-NewJson -Path $wrapperMetadataPath -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-rss-l1-wrapper.v1"
    process_version = $processVersion
    classification = "NON_ACCEPTANCE_DIAGNOSTIC"
    formal_gate_attempt = $false
    acceptance_claim = $false
    run_id = $runId
    arm = $Arm
    infra_retry_attempt = $InfraRetryAttempt
    retry_of_run_id = $RetryOfRunId
    source = $expectedSource
    project_name = $projectName
    postgres_volume = $volumeName
    capacity_at_start = $capacityAtStart
    started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
})

$runnerArguments = @(
    "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $gateRunner,
    "-Mode", "DiagnosticStages",
    "-ProjectName", $projectName,
    "-ResultsRoot", $rawResultsRoot,
    "-PostgresVolumeName", $volumeName,
    "-PostgresHostPort", [string]$PostgresHostPort,
    "-DiagnosticStageNames", "ramp-200",
    "-DiagnosticIdleSeconds", "300",
    "-DiagnosticRecoverySeconds", "600",
    "-BoundedMemoryInventoryArm", $Arm,
    "-ProductSourceSha", [string]$imageLock.source.product_source_sha,
    "-EngineeringBaselineSha", [string]$imageLock.source.engineering_baseline_sha,
    "-LockedImages",
    "-ImageLockPath", $resolvedLockPath,
    "-KeepEnvironment"
)
try {
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $process = Start-Process -FilePath $pwsh -ArgumentList $runnerArguments -WorkingDirectory $root `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
        -WindowStyle Hidden -PassThru -Wait
    $runnerExitCode = $process.ExitCode
    $runDirectory = Find-RunDirectory

    if ($runnerExitCode -eq 0 -and $null -ne $runDirectory) {
        & uv run --frozen python $comparisonTool summarize `
            --run-directory $runDirectory --arm $Arm --output $runSummaryPath
        if ($LASTEXITCODE -ne 0) {
            $classification = "DESIGN_REJECTED"
            $failureReason = "L1 arm evidence failed its zero-tolerance or integrity controls."
        }
    }
    else {
        $classification = "DESIGN_REJECTED"
        $failureReason = "L1 Gate C runner failed with exit code $runnerExitCode."
        if ($null -ne $runDirectory) {
            $failurePath = Join-Path $runDirectory "diagnostics\failure.json"
            if (Test-Path -LiteralPath $failurePath -PathType Leaf) {
                $failure = Get-Content -LiteralPath $failurePath -Raw -Encoding UTF8 |
                    ConvertFrom-Json
                if ($failure.classification -eq "INFRA_ABORTED") {
                    $classification = "INFRA_ABORTED"
                }
                $failureReason = [string]$failure.reason
            }
        }
    }
}
catch {
    $classification = "DESIGN_REJECTED"
    $failureReason = "L1 wrapper execution failed: $($_.Exception.Message)"
    if ($null -eq $runDirectory) {
        try {
            $runDirectory = Find-RunDirectory
        }
        catch {
            $failureReason += "; run directory discovery also failed"
        }
    }
}
Write-NewJson -Path $outcomePath -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-rss-l1-outcome.v1"
    process_version = $processVersion
    classification = $classification
    formal_gate_attempt = $false
    acceptance_claim = $false
    run_id = $runId
    arm = $Arm
    runner_exit_code = $runnerExitCode
    passed = ($null -eq $failureReason)
    reason = $failureReason
    completed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
})
if (-not (Test-Path -LiteralPath $runSummaryPath -PathType Leaf)) {
    Copy-Item -LiteralPath $outcomePath -Destination $runSummaryPath
}

try {
    & uv run --frozen python $packageTool `
        --evidence-directory $armDirectory `
        --package $packagePath `
        --manifest $manifestPath `
        --run-id $runId
    if ($LASTEXITCODE -ne 0) {
        throw "L1 evidence package creation or verification failed."
    }
    $archiveVerified = $true
}
finally {
    if ($archiveVerified) {
        Remove-ArmResources
        $cleanup = Get-Content -LiteralPath $cleanupReceiptPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if ($cleanup.next_arm_admission_ready -ne $true -and $null -eq $failureReason) {
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
            arm = $Arm
            source = $expectedSource
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
            run_summary = if (Test-Path -LiteralPath $runSummaryPath -PathType Leaf) {
                [ordered]@{ path = $runSummaryPath; sha256 = Get-FileSha256 $runSummaryPath }
            }
            else { $null }
        })
    }
}

foreach ($name in @(
    "GATE_C_RESULTS_DIR", "GATE_C_POSTGRES_VOLUME", "GATE_C_IMAGE_TAG", "GATE_C_SOURCE_SHA",
    "GATE_C_SOURCE_TREE", "GATE_C_PRODUCT_SOURCE_SHA", "GATE_C_ENGINEERING_BASELINE_SHA",
    "GATE_C_PROCESS_VERSION"
)) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
if ($null -ne $failureReason) {
    Write-Output $packageReferencePath
    throw "$classification`: $failureReason; immutable evidence: $packageReferencePath"
}
Write-Output $packageReferencePath
