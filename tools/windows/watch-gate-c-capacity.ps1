[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ResultsRoot,

    [Parameter(Mandatory = $true)]
    [string]$RunDirectory,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,62}$')]
    [string]$ProjectName,

    [string]$DockerDataRoot = "F:\Docker\DockerDesktopWSL",

    [string]$DockerInternalRoot = "/mnt/docker-desktop-disk",

    [Parameter(Mandatory = $true)]
    [string]$StopFile,

    [Parameter(Mandatory = $true)]
    [int]$ParentProcessId,

    [Parameter(Mandatory = $true)]
    [string]$PolicyRevision,

    [ValidateRange(1.0, 1024.0)]
    [double]$AdmissionGiB = 15.0,

    [ValidateRange(1.0, 1024.0)]
    [double]$WarningGiB = 8.0,

    [ValidateRange(1.0, 1024.0)]
    [double]$StopGiB = 5.0,

    [ValidateRange(1, 60)]
    [int]$SampleIntervalSeconds = 5,

    [ValidatePattern('^Gate-C-12-v[12]\.0$')]
    [string]$ProcessVersion = "Gate-C-12-v1.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "gate-c-capacity.ps1")

if ($StopGiB -ge $WarningGiB) {
    throw "Capacity stop threshold must be lower than the warning threshold."
}

$resolvedRunDirectory = [IO.Path]::GetFullPath($RunDirectory)
$resolvedStopFile = [IO.Path]::GetFullPath($StopFile)
if (-not $resolvedStopFile.StartsWith($resolvedRunDirectory, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Capacity monitor stop file escaped the run directory."
}

$historyPath = Join-Path $resolvedRunDirectory "capacity-history.jsonl"
$latestPath = Join-Path $resolvedRunDirectory "capacity-latest.json"
$warningPath = Join-Path $resolvedRunDirectory "capacity-warning.json"
$hardStopPath = Join-Path $resolvedRunDirectory "capacity-hard-stop.json"

function Write-JsonAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )

    $temporaryPath = "$Path.$PID.tmp"
    $Value | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Get-CapacitySnapshot {
    return Get-GateCMultiRootCapacitySnapshot `
        -ResultsRoot $ResultsRoot `
        -DockerDataRoot $DockerDataRoot `
        -DockerInternalRoot $DockerInternalRoot `
        -PolicyRevision $PolicyRevision `
        -AdmissionGiB $AdmissionGiB `
        -WarningGiB $WarningGiB `
        -StopGiB $StopGiB `
        -ProcessVersion $ProcessVersion `
        -ProjectName $ProjectName
}

while ($true) {
    if (Test-Path -LiteralPath $resolvedStopFile -PathType Leaf) {
        exit 0
    }
    if ($null -eq (Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue)) {
        exit 0
    }

    $snapshot = Get-CapacitySnapshot
    Add-Content -LiteralPath $historyPath `
        -Value ($snapshot | ConvertTo-Json -Depth 12 -Compress) -Encoding UTF8
    Write-JsonAtomically -Path $latestPath -Value $snapshot

    if ($snapshot.state -eq "WARNING" -and -not (Test-Path -LiteralPath $warningPath)) {
        $warning = [ordered]@{
            schema_version = "cybercontrol.gate-c-capacity-warning.v1"
            process_version = $ProcessVersion
            policy_revision = $PolicyRevision
            classification = "INFRA_CAPACITY_WARNING"
            acceptance_claim = $false
            action = "BLOCK_STAGE_ESCALATION_AND_REVIEW_NON_DESTRUCTIVE_TEMPORARY_CLEANUP"
            snapshot = $snapshot
        }
        Write-JsonAtomically -Path $warningPath -Value $warning
    }

    if ($snapshot.state -eq "HARD_STOP") {
        $containerResults = @()
        $containerIds = @(& docker ps `
            --filter "label=com.docker.compose.project=$ProjectName" `
            --format "{{.ID}}")
        $enumerationExitCode = $LASTEXITCODE
        if ($enumerationExitCode -eq 0) {
            foreach ($containerId in $containerIds) {
                if ([string]::IsNullOrWhiteSpace($containerId)) {
                    continue
                }
                & docker stop --time 30 $containerId | Out-Null
                $containerResults += [ordered]@{
                    container_id = $containerId
                    graceful_stop_exit_code = $LASTEXITCODE
                }
            }
        }
        $hardStop = [ordered]@{
            schema_version = "cybercontrol.gate-c-capacity-hard-stop.v1"
            process_version = $ProcessVersion
            policy_revision = $PolicyRevision
            classification = "INFRA_ABORTED"
            formal_gate_attempt = $false
            acceptance_claim = $false
            snapshot = $snapshot
            project_container_enumeration_exit_code = $enumerationExitCode
            project_container_results = $containerResults
            volumes_deleted = $false
        }
        Write-JsonAtomically -Path $hardStopPath -Value $hardStop
        exit 42
    }

    Start-Sleep -Seconds $SampleIntervalSeconds
}
