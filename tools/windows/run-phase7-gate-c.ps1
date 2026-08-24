[CmdletBinding()]
param(
    [ValidateSet("HarnessSmoke", "DiagnosticStages", "PreflightSmoke", "Full")]
    [string]$Mode = "Full",

    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,62}$')]
    [string]$ProjectName = "cybercontrol-gate-c",

    [string]$ResultsRoot = "D:\CyberControlAcceptance\phase7\gate-c",

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$')]
    [string]$PostgresVolumeName,

    [ValidateRange(1, 65535)]
    [int]$PostgresHostPort = 5432,

    [ValidateSet("smoke-20", "ramp-200", "ramp-500", "ramp-1000", "gate-2000")]
    [string[]]$DiagnosticStageNames = @(),

    [ValidateRange(0, 900)]
    [int]$DiagnosticIdleSeconds = 0,

    [ValidateRange(0, 900)]
    [int]$DiagnosticRecoverySeconds = 0,

    [switch]$MemoryCheckpoints,

    [ValidateSet("None", "A", "Measurement", "APrime")]
    [string]$JemallocProfileArm = "None",

    [ValidatePattern('^sha256:[0-9a-f]{64}$')]
    [string]$JemallocProfileImageDigest,

    [ValidateSet("ColdDeployment", "ControlledApiRestart", "StableIdle")]
    [string]$SmokeScenario = "ColdDeployment",

    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ProductSourceSha,

    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$EngineeringBaselineSha,

    [switch]$SkipBuild,

    [switch]$NoCacheBuild,

    [switch]$LockedImages,

    [string]$ImageLockPath,

    [switch]$KeepEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$baseCompose = Join-Path $root "infra\docker-compose.yml"
$gateCompose = Join-Path $root "tests\load\docker-compose.gate-c.yml"
$memoryCheckpointCompose = Join-Path $root "tests\load\docker-compose.gate-c-memory-checkpoints.yml"
$jemallocProfileCompose = Join-Path $root "tests\load\docker-compose.gate-c-jemalloc-profile.yml"
$thresholdPath = Join-Path $root "tests\load\gate-c-thresholds.v1.json"
$workloadPath = Join-Path $root "tests\load\gate-c-workload.v1.json"
$monitorPath = Join-Path $root "tests\load\gate_c\monitor.py"
$runtimeControlsPath = Join-Path $root "tests\load\gate_c\runtime_controls.py"
$imageLockToolPath = Join-Path $root "tools\gate_c_image_lock.py"
$processVersion = "Gate-C-12-v1.0"
$executionClassification = switch ($Mode) {
    "DiagnosticStages" { "DIAGNOSTIC" }
    "PreflightSmoke" { "PREFLIGHT_CHECK" }
    "Full" { "FORMAL_GATE_C_ATTEMPT" }
    default { "HARNESS_SMOKE" }
}
$runIdPrefix = switch ($Mode) {
    "DiagnosticStages" { "gate-c-diagnostic" }
    "PreflightSmoke" { "gate-c-preflight" }
    "HarnessSmoke" { "gate-c-harness" }
    default { "gate-c" }
}
$runId = "$runIdPrefix-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
$sourceCommit = (& git -C $root rev-parse HEAD).Trim()
$sourceTree = (& git -C $root rev-parse "HEAD^{tree}").Trim()
$branch = (& git -C $root branch --show-current).Trim()
$status = @(& git -C $root status --porcelain=v1 --untracked-files=all)
$resolvedProductSourceSha = if ([string]::IsNullOrWhiteSpace($ProductSourceSha)) {
    $sourceCommit
}
else {
    $ProductSourceSha
}
$resolvedEngineeringBaselineSha = if ([string]::IsNullOrWhiteSpace($EngineeringBaselineSha)) {
    $sourceCommit
}
else {
    $EngineeringBaselineSha
}
$volumeName = if (-not [string]::IsNullOrWhiteSpace($PostgresVolumeName)) {
    $PostgresVolumeName
}
else {
    "cybercontrol_gate_c_smoke_postgres"
}
$runDirectory = Join-Path $ResultsRoot "$runId-$($sourceCommit.Substring(0, 12))"
$runDirectory = [IO.Path]::GetFullPath($runDirectory)
$secretsDirectory = Join-Path $runDirectory "secrets"
$credentialsPath = Join-Path $secretsDirectory "credentials.json"
$composeArguments = @(
    "-p", $ProjectName,
    "-f", $baseCompose,
    "-f", $gateCompose,
    "--profile", "gate-c-load"
)
if ($MemoryCheckpoints) {
    $composeArguments = @($composeArguments + @("-f", $memoryCheckpointCompose))
}
if ($JemallocProfileArm -ne "None") {
    $composeArguments = @($composeArguments + @("-f", $jemallocProfileCompose))
}
$monitorProcesses = @()
$script:jemallocProfileBinding = $null
$script:imageLock = $null
$script:imageLockSha256 = $null
$script:buildReceiptSha256 = $null

function Invoke-Compose {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & docker compose @composeArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text.Replace("`r`n", "`n"))
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
    }
}

function Initialize-LockedImages {
    if (-not $LockedImages) {
        return
    }
    if ([string]::IsNullOrWhiteSpace($ImageLockPath)) {
        throw "-LockedImages requires -ImageLockPath."
    }
    $resolvedLockPath = [IO.Path]::GetFullPath($ImageLockPath)
    if (-not (Test-Path -LiteralPath $resolvedLockPath -PathType Leaf)) {
        throw "Gate C image lock does not exist: $resolvedLockPath"
    }
    & uv run --frozen python $imageLockToolPath `
        --root $root verify --image-lock $resolvedLockPath
    if ($LASTEXITCODE -ne 0) {
        throw "Gate C locked image verification failed."
    }
    $lock = Get-Content -LiteralPath $resolvedLockPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if (
        $lock.schema_version -ne "cybercontrol.gate-c-image-lock.v1" -or
        $lock.process_version -ne $processVersion -or
        $lock.source.commit -ne $sourceCommit -or
        $lock.source.tree -ne $sourceTree -or
        $lock.source.product_source_sha -ne $resolvedProductSourceSha -or
        $lock.source.engineering_baseline_sha -ne $resolvedEngineeringBaselineSha
    ) {
        throw "Gate C image lock source binding is invalid."
    }
    $receiptPath = Join-Path (Split-Path -Parent $resolvedLockPath) `
        ([string]$lock.build_receipt.path)
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw "Gate C image lock build receipt is missing."
    }
    $script:imageLock = $lock
    $script:imageLockSha256 = Get-FileSha256 $resolvedLockPath
    $script:buildReceiptSha256 = Get-FileSha256 $receiptPath
}

function Assert-LockedComposeImages {
    if (-not $LockedImages) {
        return
    }
    $composeDocument = & docker compose @composeArguments config --format json |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to render Compose while validating the Gate C image lock."
    }
    foreach ($service in @(
        "api",
        "migrate",
        "mock-provider",
        "frontend",
        "gate-c-load",
        "postgres",
        "postgres-role-bootstrap",
        "tenant-bind",
        "keycloak",
        "keycloak-config"
    )) {
        $binding = $script:imageLock.services.PSObject.Properties[$service]
        $composeService = $composeDocument.services.PSObject.Properties[$service]
        if ($null -eq $binding -or $null -eq $composeService) {
            throw "Gate C image lock or Compose model is missing service $service."
        }
        if ($service -eq "api" -and $JemallocProfileArm -ne "None") {
            if ($null -eq $script:jemallocProfileBinding) {
                throw "Gate C profiling API image binding is missing."
            }
            if (
                [string]$composeService.Value.image -ne
                [string]$script:jemallocProfileBinding.image_reference
            ) {
                throw "Gate C Compose profiling API image reference does not match its binding."
            }
            $actualProfileImageId = (& docker image inspect --format "{{.Id}}" `
                ([string]$script:jemallocProfileBinding.image_reference)).Trim()
            if (
                $LASTEXITCODE -ne 0 -or
                $actualProfileImageId -ne [string]$script:jemallocProfileBinding.image_id
            ) {
                throw "Gate C local profiling API image content does not match its binding."
            }
            continue
        }
        if ([string]$composeService.Value.image -ne [string]$binding.Value.reference) {
            throw "Gate C Compose image reference does not match the lock for $service."
        }
        $actualImageId = (& docker image inspect --format "{{.Id}}" `
            ([string]$binding.Value.reference)).Trim()
        if ($LASTEXITCODE -ne 0 -or $actualImageId -ne [string]$binding.Value.image_id) {
            throw "Gate C local image content does not match the lock for $service."
        }
    }
}

function Invoke-MemoryCheckpoint {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][ValidateSet("baseline", "recovery")][string]$Label
    )

    $checkpointDirectory = Join-Path $runDirectory "memory-checkpoints"
    $manifestPath = Join-Path $checkpointDirectory "$Label.manifest.json"
    if (Test-Path -LiteralPath $manifestPath) {
        throw "Memory checkpoint $Label already exists."
    }
    $checkpointTimer = [Diagnostics.Stopwatch]::StartNew()
    & docker kill --signal USR1 $ContainerId | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to signal API memory checkpoint $Label."
    }
    $deadline = (Get-Date).AddSeconds(31)
    do {
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
                ConvertFrom-Json
            if (
                $manifest.schema_version -ne "cybercontrol.memory-checkpoint-manifest.v1" -or
                $manifest.label -ne $Label -or
                $manifest.source.source_sha -ne $sourceCommit -or
                $manifest.source.source_tree -ne $sourceTree -or
                $manifest.source.product_source_sha -ne $resolvedProductSourceSha -or
                $manifest.source.engineering_baseline_sha -ne $resolvedEngineeringBaselineSha -or
                $manifest.source.process_version -ne $processVersion
            ) {
                throw "Memory checkpoint $Label has invalid source binding."
            }
            $metadataPath = Join-Path $checkpointDirectory "$Label.json"
            if (-not (Test-Path -LiteralPath $metadataPath)) {
                throw "Memory checkpoint $Label metadata is missing."
            }
            $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 |
                ConvertFrom-Json
            if (
                $metadata.schema_version -ne "cybercontrol.memory-checkpoint.v1" -or
                $metadata.label -ne $Label -or
                [double]$metadata.duration_seconds -gt 30.0 -or
                $checkpointTimer.Elapsed.TotalSeconds -gt 30.0
            ) {
                throw "Memory checkpoint $Label exceeded its integrity limits."
            }
            return
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "Memory checkpoint $Label did not complete within 30 seconds."
}

function Test-GateVolumeExists {
    $volumes = @(& docker volume ls --filter "name=^${volumeName}$" --format "{{.Name}}")
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to enumerate Docker volumes during Gate C cleanup."
    }
    return $volumes -contains $volumeName
}

function Remove-EphemeralResources {
    Invoke-Compose @("down", "--remove-orphans", "--volumes")

    $containers = @(& docker ps --all `
        --filter "label=com.docker.compose.project=$ProjectName" --format "{{.ID}}")
    if ($LASTEXITCODE -ne 0 -or $containers.Count -ne 0) {
        throw "Ephemeral cleanup left Compose containers for project $ProjectName behind."
    }
    $networks = @(& docker network ls `
        --filter "label=com.docker.compose.project=$ProjectName" --format "{{.ID}}")
    if ($LASTEXITCODE -ne 0 -or $networks.Count -ne 0) {
        throw "Ephemeral cleanup left Compose networks for project $ProjectName behind."
    }
    $projectVolumes = @(& docker volume ls `
        --filter "label=com.docker.compose.project=$ProjectName" --format "{{.Name}}")
    if ($LASTEXITCODE -ne 0 -or $projectVolumes.Count -ne 0) {
        throw "Ephemeral cleanup left Compose volumes for project $ProjectName behind."
    }
    if (Test-GateVolumeExists) {
        & docker volume rm $volumeName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to remove ephemeral PostgreSQL volume $volumeName."
        }
    }
    if (Test-GateVolumeExists) {
        throw "Ephemeral cleanup left PostgreSQL volume $volumeName behind."
    }
}

function Get-ComposeImageReference {
    param([Parameter(Mandatory = $true)][string]$Service)

    $composeDocument = & docker compose @composeArguments config --format json |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to resolve the Compose model for Gate C service $Service."
    }
    $serviceProperty = $composeDocument.services.PSObject.Properties[$Service]
    if ($null -eq $serviceProperty -or [string]::IsNullOrWhiteSpace($serviceProperty.Value.image)) {
        throw "Gate C service $Service does not define a stable image reference."
    }
    return [string]$serviceProperty.Value.image
}

function Get-ComposeImageId {
    param([Parameter(Mandatory = $true)][string]$Service)

    $imageReference = Get-ComposeImageReference -Service $Service
    $imageId = (& docker image inspect --format "{{.Id}}" $imageReference).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($imageId)) {
        throw "Unable to resolve image $imageReference for Gate C service $Service."
    }
    return $imageId
}

function Get-ImageRepoDigest {
    param([Parameter(Mandatory = $true)][string]$ImageReference)

    $repoDigests = @(& docker image inspect --format "{{range .RepoDigests}}{{println .}}{{end}}" `
        $ImageReference)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect repository digests for $ImageReference."
    }
    $digests = @(
        $repoDigests |
            ForEach-Object { ($_ -split "@")[-1].Trim() } |
            Where-Object { $_ -match '^sha256:[0-9a-f]{64}$' } |
            Sort-Object -Unique
    )
    if ($digests.Count -ne 1) {
        throw "Image $ImageReference does not have exactly one content digest."
    }
    return $digests[0]
}

function Get-JemallocLibraryBinding {
    param([Parameter(Mandatory = $true)][string]$ImageReference)

    $metadata = @(& docker run --rm --entrypoint /bin/sh $ImageReference -c `
        'set -eu; library=/opt/cybercontrol/jemalloc-prof/lib/libjemalloc.so.2; sha256sum "$library" | cut -d" " -f1; readelf -n "$library" | awk ''/Build ID:/ {print $3}''')
    if ($LASTEXITCODE -ne 0 -or $metadata.Count -ne 2) {
        throw "Unable to read the profiling library binding from $ImageReference."
    }
    $librarySha256 = $metadata[0].Trim()
    $libraryBuildId = $metadata[1].Trim()
    if ($librarySha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Profiling library SHA256 is invalid."
    }
    if ($libraryBuildId -notmatch '^[0-9a-f]{40}$') {
        throw "Profiling library build ID is invalid."
    }
    return [pscustomobject]@{
        sha256 = $librarySha256
        build_id = $libraryBuildId
    }
}

function Initialize-JemallocProfileBinding {
    $imageReference = Get-ComposeImageReference -Service "api"
    $imageId = Get-ComposeImageId -Service "api"
    $imageDigest = Get-ImageRepoDigest -ImageReference $imageReference
    if ($imageDigest -ne $JemallocProfileImageDigest) {
        throw "Profiling image digest does not match -JemallocProfileImageDigest."
    }
    $library = Get-JemallocLibraryBinding -ImageReference $imageReference

    $env:GATE_C_JEMALLOC_PROFILE_LIBRARY_SHA256 = $library.sha256
    $env:GATE_C_JEMALLOC_PROFILE_LIBRARY_BUILD_ID = $library.build_id
    $env:GATE_C_JEMALLOC_PROFILE_IMAGE_ID = $imageId
    $env:GATE_C_JEMALLOC_PROFILE_IMAGE_DIGEST = $imageDigest

    return [pscustomobject]@{
        arm = $JemallocProfileArm
        image_reference = $imageReference
        image_id = $imageId
        image_digest = $imageDigest
        library_sha256 = $library.sha256
        library_build_id = $library.build_id
    }
}

function Invoke-JemallocProfileTransition {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][ValidateSet("activation", "completion")][string]$Name
    )

    if ($JemallocProfileArm -ne "Measurement" -or $null -eq $script:jemallocProfileBinding) {
        throw "Only the fixed Measurement arm may transition jemalloc profiling."
    }
    $manifestPath = Join-Path $runDirectory "jemalloc-profile\$Name.manifest.json"
    if (Test-Path -LiteralPath $manifestPath) {
        throw "Jemalloc profile $Name manifest already exists."
    }
    & docker kill --signal USR2 $ContainerId | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to signal the API jemalloc profile $Name transition."
    }
    $deadline = (Get-Date).AddSeconds(61)
    do {
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
                ConvertFrom-Json
            $expectedAction = if ($Name -eq "activation") { "activate" } else { "complete" }
            $expectedPrevious = if ($Name -eq "activation") { "inactive" } else { "sampling" }
            $expectedFinal = if ($Name -eq "activation") { "sampling" } else { "complete" }
            if (
                $manifest.schema_version -ne "cybercontrol.jemalloc-profile-manifest.v1" -or
                $manifest.action -ne $expectedAction -or
                $manifest.previous_state -ne $expectedPrevious -or
                $manifest.final_state -ne $expectedFinal -or
                $manifest.source.source_sha -ne $sourceCommit -or
                $manifest.source.source_tree -ne $sourceTree -or
                $manifest.source.product_source_sha -ne $resolvedProductSourceSha -or
                $manifest.source.engineering_baseline_sha -ne $resolvedEngineeringBaselineSha -or
                $manifest.source.process_version -ne $processVersion -or
                $manifest.source.library_sha256 -ne $script:jemallocProfileBinding.library_sha256 -or
                $manifest.source.library_build_id -ne $script:jemallocProfileBinding.library_build_id -or
                $manifest.source.image_id -ne $script:jemallocProfileBinding.image_id -or
                $manifest.source.image_digest -ne $script:jemallocProfileBinding.image_digest
            ) {
                throw "Jemalloc profile $Name manifest has invalid source or state binding."
            }
            if ($Name -eq "completion") {
                $profilePath = Join-Path $runDirectory "jemalloc-profile\profile.heap"
                if (
                    -not (Test-Path -LiteralPath $profilePath -PathType Leaf) -or
                    $manifest.files.Count -ne 1 -or
                    $manifest.files[0].path -ne "profile.heap" -or
                    [int64]$manifest.files[0].size_bytes -ne (Get-Item -LiteralPath $profilePath).Length -or
                    $manifest.files[0].sha256 -ne (Get-FileSha256 $profilePath)
                ) {
                    throw "Jemalloc profile completion artifact failed integrity validation."
                }
            }
            elseif ($manifest.files.Count -ne 0) {
                throw "Jemalloc profile activation unexpectedly created an artifact."
            }
            return
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "Jemalloc profile $Name transition did not complete within 60 seconds."
}

function Invoke-JemallocProfileSymbolization {
    param([Parameter(Mandatory = $true)][string]$ContainerId)

    & docker exec $ContainerId /bin/sh -ec `
        '/opt/cybercontrol/jemalloc-prof/bin/jeprof --show_bytes --text /usr/local/bin/python /gate-c-results/jemalloc-profile/profile.heap > /gate-c-results/jemalloc-profile/symbolized.txt'
    if ($LASTEXITCODE -ne 0) {
        throw "Jemalloc profile symbolization failed."
    }
    $report = Join-Path $runDirectory "jemalloc-profile\symbolized.txt"
    if (-not (Test-Path -LiteralPath $report -PathType Leaf) -or (Get-Item $report).Length -eq 0) {
        throw "Jemalloc profile symbolization produced no report."
    }
}

function Wait-ComposeServiceHealthy {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSeconds = 180
    )

    $containerId = (& docker compose @composeArguments ps --quiet $Service).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($containerId)) {
        throw "Unable to resolve Gate C container for service $Service."
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $state = & docker inspect --format "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}" `
            $containerId
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect Gate C service $Service after restart."
        }
        if ($state.Trim() -eq "running|healthy") {
            return
        }
        if ($state -match "^(exited|dead)\|") {
            throw "Gate C service $Service stopped while waiting for health."
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Gate C service $Service did not become healthy within $TimeoutSeconds seconds."
}

function Assert-ImageProvenance {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$ImageId
    )

    $labels = & docker image inspect --format "{{json .Config.Labels}}" $ImageId |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $null -eq $labels) {
        throw "Unable to inspect provenance labels for Gate C service $Service."
    }
    $expected = [ordered]@{
        "org.opencontainers.image.revision" = $sourceCommit
        "com.cybercontrol.source-tree" = $sourceTree
        "com.cybercontrol.product-source" = $resolvedProductSourceSha
        "com.cybercontrol.engineering-baseline" = $resolvedEngineeringBaselineSha
        "com.cybercontrol.process-version" = $processVersion
    }
    foreach ($item in $expected.GetEnumerator()) {
        $property = $labels.PSObject.Properties[$item.Key]
        if ($null -eq $property -or [string]$property.Value -ne [string]$item.Value) {
            throw "Gate C image provenance mismatch for $Service label $($item.Key)."
        }
    }
}

function Start-GateMonitor {
    param(
        [Parameter(Mandatory = $true)][string]$StageDirectory,
        [Parameter(Mandatory = $true)][string]$StageName
    )

    $stopFile = Join-Path $StageDirectory "monitor.stop"
    $outputFile = Join-Path $StageDirectory "monitor.jsonl"
    $stdout = Join-Path $StageDirectory "monitor.stdout.log"
    $stderr = Join-Path $StageDirectory "monitor.stderr.log"
    $uv = (Get-Command uv -ErrorAction Stop).Source
    $arguments = @(
        "run",
        "--frozen",
        "python",
        "tests/load/gate_c/monitor.py",
        "--project",
        $ProjectName,
        "--database-url",
        "postgresql://liyans_bootstrap:liyans-bootstrap-local-only@127.0.0.1:${PostgresHostPort}/liyans",
        "--metrics-url",
        "http://127.0.0.1:8000/metrics",
        "--output",
        $outputFile,
        "--stop-file",
        $stopFile,
        "--interval-seconds",
        "5"
    )
    $process = Start-Process `
        -FilePath $uv `
        -ArgumentList $arguments `
        -WorkingDirectory $root `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
    # Retain a process handle so Windows PowerShell exposes ExitCode after waiting.
    $null = $process.Handle
    $script:monitorProcesses += [pscustomobject]@{
        Process = $process
        StopFile = $stopFile
        Stage = $StageName
    }
    return $process
}

function Stop-GateMonitor {
    param([Parameter(Mandatory = $true)]$Process)

    $record = $script:monitorProcesses | Where-Object { $_.Process.Id -eq $Process.Id } |
        Select-Object -First 1
    if ($null -eq $record) {
        throw "Gate C monitor process was not registered."
    }
    New-Item -ItemType File -Path $record.StopFile -Force | Out-Null
    if (-not $Process.WaitForExit(30000)) {
        $Process.Kill($true)
        throw "Gate C monitor for $($record.Stage) did not stop cleanly."
    }
    $Process.Refresh()
    if ($Process.ExitCode -ne 0) {
        throw "Gate C monitor for $($record.Stage) exited with code $($Process.ExitCode)."
    }
    Remove-Item -LiteralPath $record.StopFile -Force
}

function Invoke-GateTool {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$EnvironmentArguments,
        [Parameter(Mandatory = $true)][string[]]$Command
    )

    $arguments = @("run", "--rm", "--no-deps") +
        $EnvironmentArguments + @("gate-c-load") + $Command
    Invoke-Compose -Arguments $arguments
}

function Save-ComposeDiagnostics {
    param([Parameter(Mandatory = $true)][string]$Reason)

    $diagnosticsDirectory = Join-Path $runDirectory "diagnostics"
    New-Item -ItemType Directory -Path $diagnosticsDirectory -Force | Out-Null
    [ordered]@{
        schema_version = "cybercontrol.gate-c-failure.v1"
        captured_at = (Get-Date).ToUniversalTime().ToString("o")
        reason = $Reason
        project = $ProjectName
        process_version = $processVersion
        classification = $executionClassification
        formal_gate_attempt = ($Mode -eq "Full")
        acceptance_claim = $false
        source_commit = $sourceCommit
        source_tree = $sourceTree
        product_source_sha = $resolvedProductSourceSha
        engineering_baseline_sha = $resolvedEngineeringBaselineSha
    } | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath (Join-Path $diagnosticsDirectory "failure.json") -Encoding UTF8

    try {
        & docker compose @composeArguments ps --all --format json 2>&1 |
            Set-Content -LiteralPath (Join-Path $diagnosticsDirectory "compose-ps.json") -Encoding UTF8
    }
    catch {
        Write-Warning "Unable to capture Gate C Compose state: $_"
    }

    foreach ($service in @(
        "postgres",
        "postgres-role-bootstrap",
        "migrate",
        "keycloak",
        "keycloak-config",
        "tenant-bind",
        "mock-provider",
        "api"
    )) {
        try {
            & docker compose @composeArguments logs --no-color --timestamps $service 2>&1 |
                Set-Content -LiteralPath (Join-Path $diagnosticsDirectory "$service.log") -Encoding UTF8
        }
        catch {
            Write-Warning "Unable to capture Gate C logs for ${service}: $_"
        }
    }
}

if ($Mode -eq "Full" -and [string]::IsNullOrWhiteSpace($PostgresVolumeName)) {
    throw "Full Gate C acceptance requires an explicit fresh -PostgresVolumeName."
}
if ($Mode -notin @("HarnessSmoke", "Full") -and [string]::IsNullOrWhiteSpace($PostgresVolumeName)) {
    throw "$Mode requires an explicit fresh -PostgresVolumeName."
}
if ($Mode -eq "DiagnosticStages" -and $DiagnosticStageNames.Count -eq 0) {
    throw "DiagnosticStages requires explicit -DiagnosticStageNames."
}
if (
    $Mode -in @("DiagnosticStages", "HarnessSmoke") -and
    ([string]::IsNullOrWhiteSpace($ProductSourceSha) -or
        [string]::IsNullOrWhiteSpace($EngineeringBaselineSha))
) {
    throw "$Mode requires explicit product and engineering baseline SHAs."
}
if ($Mode -ne "DiagnosticStages" -and $DiagnosticStageNames.Count -ne 0) {
    throw "-DiagnosticStageNames is valid only with -Mode DiagnosticStages."
}
if ($Mode -ne "DiagnosticStages" -and $DiagnosticIdleSeconds -ne 0) {
    throw "-DiagnosticIdleSeconds is valid only with -Mode DiagnosticStages."
}
if ($Mode -ne "DiagnosticStages" -and $DiagnosticRecoverySeconds -ne 0) {
    throw "-DiagnosticRecoverySeconds is valid only with -Mode DiagnosticStages."
}
if ($Mode -ne "DiagnosticStages" -and $MemoryCheckpoints) {
    throw "-MemoryCheckpoints is valid only with -Mode DiagnosticStages."
}
if ($Mode -ne "DiagnosticStages" -and $NoCacheBuild) {
    throw "-NoCacheBuild is valid only with -Mode DiagnosticStages."
}
if ($SkipBuild -and $NoCacheBuild) {
    throw "-SkipBuild and -NoCacheBuild are mutually exclusive."
}
if ($LockedImages -and ($SkipBuild -or $NoCacheBuild)) {
    throw "-LockedImages cannot be combined with -SkipBuild or -NoCacheBuild."
}
if (-not $LockedImages -and -not [string]::IsNullOrWhiteSpace($ImageLockPath)) {
    throw "-ImageLockPath requires -LockedImages."
}
if ($MemoryCheckpoints) {
    if (
        $DiagnosticStageNames.Count -ne 1 -or
        $DiagnosticStageNames[0] -ne "ramp-200" -or
        $DiagnosticIdleSeconds -ne 300 -or
        $DiagnosticRecoverySeconds -ne 600
    ) {
        throw "Memory checkpoints require only ramp-200, 300 idle seconds and 600 recovery seconds."
    }
}
if ($JemallocProfileArm -ne "None") {
    if ($Mode -ne "DiagnosticStages") {
        throw "Jemalloc profile arms are valid only with -Mode DiagnosticStages."
    }
    if (
        $DiagnosticStageNames.Count -ne 1 -or
        $DiagnosticStageNames[0] -ne "ramp-200" -or
        $DiagnosticIdleSeconds -ne 300 -or
        $DiagnosticRecoverySeconds -ne 600
    ) {
        throw "Jemalloc profile arms require only ramp-200, 300 idle seconds and 600 recovery seconds."
    }
    if ($MemoryCheckpoints) {
        throw "Jemalloc profiling and memory checkpoints are mutually exclusive."
    }
    if (-not $LockedImages) {
        throw "Jemalloc profile arms must reuse a prevalidated locked image receipt."
    }
    if ([string]::IsNullOrWhiteSpace($JemallocProfileImageDigest)) {
        throw "Jemalloc profile arms require -JemallocProfileImageDigest."
    }
}
elseif (-not [string]::IsNullOrWhiteSpace($JemallocProfileImageDigest)) {
    throw "-JemallocProfileImageDigest requires a jemalloc profile arm."
}
if ($Mode -ne "HarnessSmoke" -and $SmokeScenario -ne "ColdDeployment") {
    throw "-SmokeScenario is valid only with -Mode HarnessSmoke."
}
if ($Mode -eq "PreflightSmoke" -and $KeepEnvironment) {
    throw "PreflightSmoke cannot retain its environment."
}
if ($Mode -ne "HarnessSmoke" -and -not $LockedImages) {
    throw "$Mode requires a complete locked image receipt."
}
if ($Mode -in @("Full", "PreflightSmoke")) {
    if ($branch -ne "main") {
        throw "$Mode must run from main; current branch is $branch."
    }
    if ($status.Count -ne 0) {
        throw "$Mode requires a clean source tree."
    }
    $remoteMain = (Invoke-RestMethod `
        -Headers @{ Accept = "application/vnd.github+json"; "User-Agent" = "CyberControl-Gate-C" } `
        -Uri "https://api.github.com/repos/changkong66/CyberControl/branches/main" `
        -TimeoutSec 30).commit.sha
    if ($sourceCommit -ne $remoteMain) {
        throw "Local main does not match protected origin/main for $Mode."
    }
}
elseif ($Mode -in @("DiagnosticStages", "HarnessSmoke") -and $status.Count -ne 0) {
    throw "$Mode requires a clean committed candidate tree."
}

New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $secretsDirectory -Force | Out-Null
if ($MemoryCheckpoints) {
    New-Item -ItemType Directory -Path (Join-Path $runDirectory "memory-checkpoints") -Force |
        Out-Null
}
if ($JemallocProfileArm -ne "None") {
    New-Item -ItemType Directory -Path (Join-Path $runDirectory "jemalloc-profile") -Force |
        Out-Null
}
$env:GATE_C_RESULTS_DIR = $runDirectory
$env:GATE_C_POSTGRES_VOLUME = $volumeName
$env:LIYAN_POSTGRES_HOST_PORT = [string]$PostgresHostPort
$env:PYTHONPATH = Join-Path $root "tests\load"
$env:GATE_C_SOURCE_SHA = $sourceCommit
$env:GATE_C_SOURCE_TREE = $sourceTree
$env:GATE_C_PRODUCT_SOURCE_SHA = $resolvedProductSourceSha
$env:GATE_C_ENGINEERING_BASELINE_SHA = $resolvedEngineeringBaselineSha
$env:GATE_C_PROCESS_VERSION = $processVersion
$env:GATE_C_IMAGE_TAG = $sourceCommit
Initialize-LockedImages
if ($JemallocProfileArm -ne "None") {
    $script:jemallocProfileBinding = Initialize-JemallocProfileBinding
}

[ordered]@{
    schema_version = "cybercontrol.gate-c-execution-metadata.v1"
    process_version = $processVersion
    mode = $Mode
    classification = $executionClassification
    formal_gate_attempt = ($Mode -eq "Full")
    acceptance_claim = $false
    run_id = $runId
    source_commit = $sourceCommit
    source_tree = $sourceTree
    product_source_sha = $resolvedProductSourceSha
    engineering_baseline_sha = $resolvedEngineeringBaselineSha
    branch = $branch
    project = $ProjectName
    postgres_volume = $volumeName
    postgres_host_port = $PostgresHostPort
    diagnostic_stage_names = @($DiagnosticStageNames)
    diagnostic_idle_seconds = $DiagnosticIdleSeconds
    diagnostic_recovery_seconds = $DiagnosticRecoverySeconds
    memory_checkpoints = [bool]$MemoryCheckpoints
    jemalloc_profile_arm = $JemallocProfileArm
    jemalloc_profile_binding = $script:jemallocProfileBinding
    no_cache_build = [bool]$NoCacheBuild
    locked_images = [bool]$LockedImages
    image_lock_sha256 = $script:imageLockSha256
    build_receipt_sha256 = $script:buildReceiptSha256
    smoke_scenario = $SmokeScenario
    thresholds_sha256 = Get-FileSha256 $thresholdPath
    workload_sha256 = Get-FileSha256 $workloadPath
} | ConvertTo-Json -Depth 6 |
    Set-Content -LiteralPath (Join-Path $runDirectory "execution-metadata.json") -Encoding UTF8

$existingVolume = @(& docker volume ls --filter "name=^${volumeName}$" --format "{{.Name}}")
if ($existingVolume -contains $volumeName) {
    throw "Gate C volume $volumeName already exists; a fresh volume is required."
}
& docker volume create `
    --label com.cybercontrol.purpose=phase7-gate-c `
    --label com.cybercontrol.data-class=isolated-clean-postgres `
    $volumeName | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create Gate C PostgreSQL volume."
}

$thresholds = Get-Content -LiteralPath $thresholdPath -Raw -Encoding UTF8 | ConvertFrom-Json
$workload = Get-Content -LiteralPath $workloadPath -Raw -Encoding UTF8 | ConvertFrom-Json
$selectedStages = switch ($Mode) {
    "Full" { @($thresholds.stages) }
    "DiagnosticStages" {
        @(
            foreach ($diagnosticStageName in $DiagnosticStageNames) {
                $selected = @(
                    $thresholds.stages |
                        Where-Object { [string]$_.name -eq $diagnosticStageName }
                )
                if ($selected.Count -ne 1) {
                    throw "Frozen thresholds do not define diagnostic stage $diagnosticStageName."
                }
                $selected[0]
            }
        )
    }
    default { @($thresholds.stages | Select-Object -First 1) }
}

try {
    Invoke-Compose @("config", "--quiet")
    $composeConfig = (& docker compose @composeArguments config | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to render the Gate C Compose configuration."
    }
    if (-not $SkipBuild -and -not $LockedImages) {
        $buildArguments = @("build")
        if ($NoCacheBuild) {
            $buildArguments += "--no-cache"
        }
        $buildArguments += @(
            "api",
            "migrate",
            "mock-provider",
            "frontend",
            "gate-c-load"
        )
        Invoke-Compose $buildArguments
    }
    Assert-LockedComposeImages
    Invoke-Compose @("up", "--detach", "--wait", "api")

    $builtImages = [ordered]@{
        api = Get-ComposeImageId "api"
        migrate = Get-ComposeImageId "migrate"
        mock_provider = Get-ComposeImageId "mock-provider"
        frontend = Get-ComposeImageId "frontend"
        gate_c_load = Get-ComposeImageId "gate-c-load"
    }
    foreach ($image in $builtImages.GetEnumerator()) {
        Assert-ImageProvenance -Service $image.Key -ImageId $image.Value
    }

    switch ($SmokeScenario) {
        "ControlledApiRestart" {
            Invoke-Compose @("restart", "api")
            Wait-ComposeServiceHealthy -Service "api"
        }
        "StableIdle" {
            Start-Sleep -Seconds 300
        }
    }

    $apiContainer = (& docker compose @composeArguments ps -q api).Trim()
    $postgresContainer = (& docker compose @composeArguments ps -q postgres).Trim()
    $keycloakContainer = (& docker compose @composeArguments ps -q keycloak).Trim()
    $environmentEvidence = [ordered]@{
        schema_version = "cybercontrol.gate-c-environment.v1"
        process_version = $processVersion
        mode = $Mode
        smoke_scenario = $SmokeScenario
        classification = $executionClassification
        formal_gate_attempt = ($Mode -eq "Full")
        acceptance_claim = $false
        run_id = $runId
        source_commit = $sourceCommit
        source_tree = $sourceTree
        product_source_sha = $resolvedProductSourceSha
        engineering_baseline_sha = $resolvedEngineeringBaselineSha
        branch = $branch
        clean_source = ($status.Count -eq 0)
        single_host_execution = $true
        production_capacity_claim_permitted = $false
        compose_config_sha256 = Get-TextSha256 $composeConfig
        thresholds_sha256 = Get-FileSha256 $thresholdPath
        workload_sha256 = Get-FileSha256 $workloadPath
        docker_server_version = (& docker version --format "{{.Server.Version}}").Trim()
        docker_cpu_limit = [int](& docker info --format "{{.NCPU}}")
        docker_memory_limit_bytes = [int64](& docker info --format "{{.MemTotal}}")
        postgres_host_port = $PostgresHostPort
        diagnostic_idle_seconds = $DiagnosticIdleSeconds
        diagnostic_recovery_seconds = $DiagnosticRecoverySeconds
        memory_checkpoints = [bool]$MemoryCheckpoints
        jemalloc_profile_arm = $JemallocProfileArm
        jemalloc_profile_binding = $script:jemallocProfileBinding
        no_cache_build = [bool]$NoCacheBuild
        locked_images = [bool]$LockedImages
        image_lock_sha256 = $script:imageLockSha256
        build_receipt_sha256 = $script:buildReceiptSha256
        volume = (& docker volume inspect $volumeName | ConvertFrom-Json)[0]
        runtime_images = [ordered]@{
            api = (& docker inspect --format "{{.Image}}" $apiContainer).Trim()
            postgres = (& docker inspect --format "{{.Image}}" $postgresContainer).Trim()
            keycloak = (& docker inspect --format "{{.Image}}" $keycloakContainer).Trim()
        }
        source_built_images = $builtImages
        tools = [ordered]@{
            locust = (& uv run --frozen locust --version | Out-String).Trim()
            python = (& uv run --frozen python --version | Out-String).Trim()
            uv = (& uv --version | Out-String).Trim()
        }
    }
    $environmentEvidence | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath (Join-Path $runDirectory "environment.json") -Encoding UTF8

    Invoke-GateTool `
        -EnvironmentArguments @() `
        -Command @("python", "-m", "gate_c.provision")

    if ($Mode -eq "DiagnosticStages" -and $DiagnosticIdleSeconds -gt 0) {
        $baselineDirectory = Join-Path $runDirectory "diagnostic-baseline"
        New-Item -ItemType Directory -Path $baselineDirectory -Force | Out-Null
        $baselineMonitor = Start-GateMonitor `
            -StageDirectory $baselineDirectory `
            -StageName "diagnostic-baseline"
        try {
            Start-Sleep -Seconds $DiagnosticIdleSeconds
            if ($MemoryCheckpoints) {
                Invoke-MemoryCheckpoint -ContainerId $apiContainer -Label "baseline"
            }
        }
        finally {
            Stop-GateMonitor -Process $baselineMonitor
        }
        if ($JemallocProfileArm -eq "Measurement") {
            Invoke-JemallocProfileTransition -ContainerId $apiContainer -Name "activation"
        }
    }

    foreach ($stage in $selectedStages) {
        $stageName = [string]$stage.name
        $stageDirectory = Join-Path $runDirectory "stages\$stageName"
        New-Item -ItemType Directory -Path $stageDirectory -Force | Out-Null
        $stageStartedUtc = (Get-Date).ToUniversalTime().ToString("o")
        $stageRunId = "$runId-$stageName"
        $stageContainerDirectory = "/results/stages/$stageName"
        $baselineContainerPath = "$stageContainerDirectory/baseline-cursors.json"
        $spawnSeconds = [Math]::Ceiling([double]$stage.users / [double]$stage.spawn_rate)
        $totalSeconds = [int](
            $spawnSeconds +
            [int]$stage.sustain_seconds +
            [int]$workload.publisher_start_delay_seconds +
            [int]$workload.publisher_drain_seconds
        )
        $faultAtSeconds = [int](
            $spawnSeconds +
            [int]$stage.sustain_seconds +
            [int]$workload.forced_disconnect_after_sustain_seconds
        )
        $stageEnvironment = @(
            "-e", "GATE_C_RUN_ID=$stageRunId",
            "-e", "GATE_C_STAGE=$stageName",
            "-e", "GATE_C_STAGE_RESULTS_DIR=$stageContainerDirectory",
            "-e", "GATE_C_BASELINE_CURSOR_PATH=$baselineContainerPath",
            "-e", "GATE_C_STAGE_TOTAL_SECONDS=$totalSeconds",
            "-e", "GATE_C_FAULT_AT_SECONDS=$faultAtSeconds"
        )
        Invoke-GateTool `
            -EnvironmentArguments $stageEnvironment `
            -Command @("python", "-m", "gate_c.publisher")
        if ($stageName -eq [string]$selectedStages[0].name) {
            Invoke-GateTool `
                -EnvironmentArguments $stageEnvironment `
                -Command @("python", "-m", "gate_c.verify_controls")
        }

        $monitor = Start-GateMonitor -StageDirectory $stageDirectory -StageName $stageName
        try {
            Invoke-GateTool `
                -EnvironmentArguments $stageEnvironment `
                -Command @(
                    "locust",
                    "-f", "/app/tests/load/locustfile.py",
                    "--host", "http://api:8000",
                    "--headless",
                    "--users", [string]$stage.users,
                    "--spawn-rate", [string]$stage.spawn_rate,
                    "--run-time", "${totalSeconds}s",
                    "--processes", [string]$workload.worker_processes,
                    "--csv", "$stageContainerDirectory/locust",
                    "--csv-full-history",
                    "--only-summary"
                )
            if ($Mode -eq "Full" -and $stageName -eq [string]$selectedStages[-1].name) {
                Start-Sleep -Seconds ([int]$thresholds.post_ramp_recovery_seconds)
            }
            if (
                $Mode -eq "DiagnosticStages" -and
                $stageName -eq [string]$selectedStages[-1].name -and
                $DiagnosticRecoverySeconds -gt 0
            ) {
                Start-Sleep -Seconds $DiagnosticRecoverySeconds
                if ($MemoryCheckpoints) {
                    Invoke-MemoryCheckpoint -ContainerId $apiContainer -Label "recovery"
                }
            }
        }
        finally {
            Stop-GateMonitor -Process $monitor
        }
        if (
            $Mode -eq "DiagnosticStages" -and
            $stageName -eq [string]$selectedStages[-1].name -and
            $JemallocProfileArm -eq "Measurement"
        ) {
            Invoke-JemallocProfileTransition -ContainerId $apiContainer -Name "completion"
            Invoke-JemallocProfileSymbolization -ContainerId $apiContainer
        }
        $apiLogPath = Join-Path $stageDirectory "api-runtime.log"
        & docker compose @composeArguments logs --no-color --timestamps --since $stageStartedUtc api 2>&1 |
            Set-Content -LiteralPath $apiLogPath -Encoding UTF8
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to capture API runtime logs for Gate C stage $stageName."
        }
        & uv run --frozen python $runtimeControlsPath `
            --api-log $apiLogPath `
            --output (Join-Path $stageDirectory "runtime-controls.json")
        if ($LASTEXITCODE -ne 0) {
            throw "Gate C runtime control evidence failed for stage $stageName."
        }
        $stageSummaryPath = Join-Path $stageDirectory "stage-summary.json"
        & uv run --frozen python tests/load/gate_c/summarize.py `
            --stage $stageName `
            --stage-dir $stageDirectory `
            --thresholds $thresholdPath `
            --workload $workloadPath `
            --output $stageSummaryPath
        $stageSummaryExitCode = $LASTEXITCODE
        if (
            $stageSummaryExitCode -ne 0 -and
            $Mode -eq "DiagnosticStages" -and
            (Test-Path -LiteralPath $stageSummaryPath)
        ) {
            $diagnosticSummary = Get-Content -LiteralPath $stageSummaryPath -Raw -Encoding UTF8 |
                ConvertFrom-Json
            if (
                $diagnosticSummary.schema_version -ne "cybercontrol.gate-c-stage-summary.v1" -or
                $diagnosticSummary.stage -ne $stageName -or
                $diagnosticSummary.passed -ne $false
            ) {
                throw "Diagnostic stage $stageName returned an invalid threshold summary."
            }
            Write-Warning "Diagnostic stage $stageName retained a non-passing threshold summary."
        }
        elseif ($stageSummaryExitCode -ne 0) {
            throw "Gate C stage $stageName failed its frozen thresholds."
        }
    }

    if ($JemallocProfileArm -in @("A", "APrime")) {
        $profileArtifacts = @(Get-ChildItem -LiteralPath (Join-Path $runDirectory "jemalloc-profile") `
            -Force -File)
        if ($profileArtifacts.Count -ne 0) {
            throw "Jemalloc control arm produced an unauthorized profile artifact."
        }
    }
    elseif ($JemallocProfileArm -eq "Measurement") {
        $profileArtifactNames = @(
            Get-ChildItem -LiteralPath (Join-Path $runDirectory "jemalloc-profile") -Force -File |
                Select-Object -ExpandProperty Name |
                Sort-Object
        )
        $expectedProfileArtifacts = @(
            "activation.manifest.json",
            "completion.manifest.json",
            "profile.heap",
            "symbolized.txt"
        ) | Sort-Object
        if (($profileArtifactNames -join "|") -ne ($expectedProfileArtifacts -join "|")) {
            throw "Jemalloc measurement arm artifacts are incomplete or unexpected."
        }
    }

    if ($MemoryCheckpoints) {
        & uv run --frozen python tests/load/gate_c/memory_checkpoint_compare.py `
            --baseline-manifest (Join-Path $runDirectory "memory-checkpoints\baseline.manifest.json") `
            --recovery-manifest (Join-Path $runDirectory "memory-checkpoints\recovery.manifest.json") `
            --output-dir (Join-Path $runDirectory "memory-comparison")
        if ($LASTEXITCODE -ne 0) {
            throw "Memory checkpoint comparison failed."
        }
    }

    if ($Mode -eq "Full") {
        Invoke-GateTool `
            -EnvironmentArguments @() `
            -Command @(
                "python", "-m", "gate_c.database_evidence",
                "--bootstrap-url", "postgresql://liyans_bootstrap:liyans-bootstrap-local-only@postgres:5432/liyans",
                "--runtime-url", "postgresql://liyans_app:liyans-app-local-only@postgres:5432/liyans",
                "--workload", "/app/tests/load/gate-c-workload.v1.json",
                "--output", "/results/database-evidence.json"
            )
    }
}
catch {
    Save-ComposeDiagnostics -Reason $_.Exception.Message
    throw
}
finally {
    foreach ($record in $monitorProcesses) {
        if (-not $record.Process.HasExited) {
            New-Item -ItemType File -Path $record.StopFile -Force | Out-Null
            $record.Process.WaitForExit(10000) | Out-Null
            if (-not $record.Process.HasExited) {
                $record.Process.Kill($true)
            }
        }
    }
    $cleanupFailure = $null
    try {
        if ($Mode -in @("PreflightSmoke", "HarnessSmoke")) {
            Remove-EphemeralResources
        }
        elseif (-not $KeepEnvironment) {
            Invoke-Compose @("down", "--remove-orphans")
        }
    }
    catch {
        $cleanupFailure = $_
    }
    $resolvedSecrets = [IO.Path]::GetFullPath($secretsDirectory)
    if (-not $resolvedSecrets.StartsWith($runDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Gate C secrets path escaped the run directory."
    }
    if (Test-Path -LiteralPath $resolvedSecrets) {
        Remove-Item -LiteralPath $resolvedSecrets -Recurse -Force
    }
    if ($null -ne $cleanupFailure) {
        throw $cleanupFailure
    }
}

if ($Mode -eq "Full") {
    & uv run --frozen python tests/load/gate_c/finalize.py `
        --run-dir $runDirectory `
        --thresholds $thresholdPath `
        --output (Join-Path $runDirectory "gate-c-summary.json")
    if ($LASTEXITCODE -ne 0) {
        throw "Gate C final evidence did not pass the frozen thresholds."
    }
}

[pscustomobject]@{
    process_version = $processVersion
    mode = $Mode
    smoke_scenario = $SmokeScenario
    classification = $executionClassification
    formal_gate_attempt = ($Mode -eq "Full")
    acceptance_claim = $false
    run_id = $runId
    source_commit = $sourceCommit
    result_directory = $runDirectory
    volume = $volumeName
    diagnostic_idle_seconds = $DiagnosticIdleSeconds
    diagnostic_recovery_seconds = $DiagnosticRecoverySeconds
    memory_checkpoints = [bool]$MemoryCheckpoints
    jemalloc_profile_arm = $JemallocProfileArm
    jemalloc_profile_binding = $script:jemallocProfileBinding
    no_cache_build = [bool]$NoCacheBuild
} | ConvertTo-Json -Depth 4
