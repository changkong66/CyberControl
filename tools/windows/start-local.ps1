[CmdletBinding()]
param(
    [ValidatePattern("^[a-z0-9][a-z0-9_-]{2,40}$")]
    [string]$ProjectName = "liyans-local",

    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 5432,

    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 8000,

    [ValidateRange(30, 600)]
    [int]$WaitTimeoutSeconds = 240,

    [switch]$NoBuild,
    [switch]$KeepFailedStack
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $RepositoryRoot "infra\docker-compose.yml"

function Invoke-Docker {
    param([string[]]$Arguments, [string]$Description)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Assert-PortAvailable {
    param([int]$Port)
    $listeners = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    if (@($listeners | Where-Object { $_.Port -eq $Port }).Count -gt 0) {
        throw "TCP port $Port is already in use. Select another port."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop and docker.exe are required."
}
Invoke-Docker -Arguments @("info", "--format", "{{.ServerVersion}}") `
    -Description "Docker daemon validation"
Assert-PortAvailable -Port $PostgresPort
Assert-PortAvailable -Port $ApiPort

$previousPostgresPort = $env:LIYAN_POSTGRES_HOST_PORT
$previousApiPort = $env:LIYAN_API_HOST_PORT
$env:LIYAN_POSTGRES_HOST_PORT = [string]$PostgresPort
$env:LIYAN_API_HOST_PORT = [string]$ApiPort

Push-Location $RepositoryRoot
try {
    Invoke-Docker -Arguments @("compose", "-p", $ProjectName, "-f", $ComposeFile, "config", "--quiet") `
        -Description "Compose configuration validation"
    $upArguments = @("compose", "-p", $ProjectName, "-f", $ComposeFile, "up")
    if (-not $NoBuild) { $upArguments += "--build" }
    $upArguments += @("--detach", "--wait", "--wait-timeout", [string]$WaitTimeoutSeconds)
    Invoke-Docker -Arguments $upArguments -Description "local stack startup"

    $live = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$ApiPort/health/live" `
        -TimeoutSec 10
    if ($live.status -ne "live") {
        throw "API liveness returned an unexpected response."
    }

    Write-Host "Liyan local stack is healthy." -ForegroundColor Green
    Write-Host "API: http://127.0.0.1:$ApiPort"
    Write-Host "Liveness: http://127.0.0.1:$ApiPort/health/live"
    Write-Host "Metrics: http://127.0.0.1:$ApiPort/metrics"
    Write-Host (
        "Readiness is expected to return HTTP 503 until a development OIDC provider " +
        "is configured."
    ) -ForegroundColor Yellow
} catch {
    & docker compose -p $ProjectName -f $ComposeFile logs --no-color --tail 200
    if (-not $KeepFailedStack) {
        & docker compose -p $ProjectName -f $ComposeFile down --volumes --remove-orphans
    }
    throw
} finally {
    Pop-Location
    if ($null -eq $previousPostgresPort) {
        Remove-Item Env:LIYAN_POSTGRES_HOST_PORT -ErrorAction SilentlyContinue
    } else {
        $env:LIYAN_POSTGRES_HOST_PORT = $previousPostgresPort
    }
    if ($null -eq $previousApiPort) {
        Remove-Item Env:LIYAN_API_HOST_PORT -ErrorAction SilentlyContinue
    } else {
        $env:LIYAN_API_HOST_PORT = $previousApiPort
    }
}
