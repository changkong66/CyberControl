[CmdletBinding()]
param(
    [ValidateSet("HarnessSmoke", "Full")]
    [string]$Mode = "Full",

    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,62}$')]
    [string]$ProjectName = "cybercontrol-gate-c",

    [string]$ResultsRoot = "D:\CyberControlAcceptance\phase7\gate-c",

    [switch]$SkipBuild,

    [switch]$KeepEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$baseCompose = Join-Path $root "infra\docker-compose.yml"
$gateCompose = Join-Path $root "tests\load\docker-compose.gate-c.yml"
$thresholdPath = Join-Path $root "tests\load\gate-c-thresholds.v1.json"
$workloadPath = Join-Path $root "tests\load\gate-c-workload.v1.json"
$monitorPath = Join-Path $root "tests\load\gate_c\monitor.py"
$runtimeControlsPath = Join-Path $root "tests\load\gate_c\runtime_controls.py"
$runId = "gate-c-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
$sourceCommit = (& git -C $root rev-parse HEAD).Trim()
$sourceTree = (& git -C $root rev-parse "HEAD^{tree}").Trim()
$branch = (& git -C $root branch --show-current).Trim()
$status = @(& git -C $root status --porcelain=v1 --untracked-files=all)
$volumeName = if ($Mode -eq "Full") {
    "cybercontrol_gate_c_postgres"
}
else {
    "cybercontrol_gate_c_smoke_postgres"
}
$runDirectory = Join-Path $ResultsRoot "$runId-$($sourceCommit.Substring(0, 12))"
$runDirectory = [IO.Path]::GetFullPath($runDirectory)
$secretsDirectory = Join-Path $runDirectory "secrets"
$credentialsPath = Join-Path $secretsDirectory "credentials.json"
$composeArguments = @("-p", $ProjectName, "-f", $baseCompose, "-f", $gateCompose)
$monitorProcesses = @()

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
        "postgresql://liyans_bootstrap:liyans-bootstrap-local-only@127.0.0.1:5432/liyans",
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
        source_commit = $sourceCommit
        source_tree = $sourceTree
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

if ($Mode -eq "Full") {
    if ($branch -ne "main") {
        throw "Full Gate C acceptance must run from main; current branch is $branch."
    }
    if ($status.Count -ne 0) {
        throw "Full Gate C acceptance requires a clean source tree."
    }
    $remoteMain = (Invoke-RestMethod `
        -Headers @{ Accept = "application/vnd.github+json"; "User-Agent" = "CyberControl-Gate-C" } `
        -Uri "https://api.github.com/repos/changkong66/CyberControl/branches/main" `
        -TimeoutSec 30).commit.sha
    if ($sourceCommit -ne $remoteMain) {
        throw "Local main does not match the protected remote main."
    }
}

New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $secretsDirectory -Force | Out-Null
$env:GATE_C_RESULTS_DIR = $runDirectory
$env:GATE_C_POSTGRES_VOLUME = $volumeName
$env:PYTHONPATH = Join-Path $root "tests\load"

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
$selectedStages = if ($Mode -eq "Full") {
    @($thresholds.stages)
}
else {
    @($thresholds.stages | Select-Object -First 1)
}

try {
    Invoke-Compose @("config", "--quiet")
    $composeConfig = (& docker compose @composeArguments config | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to render the Gate C Compose configuration."
    }
    $upArguments = @("up", "--detach", "--wait")
    if (-not $SkipBuild) {
        $upArguments += "--build"
    }
    $upArguments += "api"
    Invoke-Compose $upArguments
    if (-not $SkipBuild) {
        Invoke-Compose @("build", "gate-c-load")
    }

    $apiContainer = (& docker compose @composeArguments ps -q api).Trim()
    $postgresContainer = (& docker compose @composeArguments ps -q postgres).Trim()
    $keycloakContainer = (& docker compose @composeArguments ps -q keycloak).Trim()
    $environmentEvidence = [ordered]@{
        schema_version = "cybercontrol.gate-c-environment.v1"
        mode = $Mode
        run_id = $runId
        source_commit = $sourceCommit
        source_tree = $sourceTree
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
        volume = (& docker volume inspect $volumeName | ConvertFrom-Json)[0]
        runtime_images = [ordered]@{
            api = (& docker inspect --format "{{.Image}}" $apiContainer).Trim()
            postgres = (& docker inspect --format "{{.Image}}" $postgresContainer).Trim()
            keycloak = (& docker inspect --format "{{.Image}}" $keycloakContainer).Trim()
        }
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
        }
        finally {
            Stop-GateMonitor -Process $monitor
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
        & uv run --frozen python tests/load/gate_c/summarize.py `
            --stage $stageName `
            --stage-dir $stageDirectory `
            --thresholds $thresholdPath `
            --workload $workloadPath `
            --output (Join-Path $stageDirectory "stage-summary.json")
        if ($LASTEXITCODE -ne 0) {
            throw "Gate C stage $stageName failed its frozen thresholds."
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
    if (-not $KeepEnvironment) {
        try {
            Invoke-Compose @("down", "--remove-orphans")
        }
        catch {
            Write-Warning $_
        }
    }
    $resolvedSecrets = [IO.Path]::GetFullPath($secretsDirectory)
    if (-not $resolvedSecrets.StartsWith($runDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Gate C secrets path escaped the run directory."
    }
    if (Test-Path -LiteralPath $resolvedSecrets) {
        Remove-Item -LiteralPath $resolvedSecrets -Recurse -Force
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
    mode = $Mode
    run_id = $runId
    source_commit = $sourceCommit
    result_directory = $runDirectory
    volume = $volumeName
} | ConvertTo-Json -Depth 4
