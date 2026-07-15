[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 55434,

    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,62}$')]
    [string]$ContainerName = "liyans-topic1-postgres",

    [switch]$KeepDatabase
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$PostgresImage = (
    "postgres:16-alpine@sha256:" +
    "57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
)
$BootstrapUser = "liyans_bootstrap"
$BootstrapPassword = "liyans-bootstrap-topic1-local-only"
$DatabaseName = "liyans"
$CreatedContainer = $false

function Resolve-NativeExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [string[]]$Candidates = @()
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "$Name is unavailable. Reproduce the pinned development environment first."
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

$Docker = Resolve-NativeExecutable -Name "docker"
$Uv = Resolve-NativeExecutable -Name "uv" -Candidates @(
    (Join-Path $env:APPDATA "Python\Python311\Scripts\uv.exe"),
    (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
)

Push-Location $RepositoryRoot
try {
    Invoke-Native -Executable $Docker -Arguments @("info", "--format", "{{.ServerVersion}}") `
        -Description "Docker daemon readiness check"

    $existingContainer = (& $Docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}")
    if ($LASTEXITCODE -ne 0) {
        throw "Docker container inventory failed."
    }
    if (-not $existingContainer) {
        $portInUse = Get-NetTCPConnection -State Listen -LocalPort $PostgresPort `
            -ErrorAction SilentlyContinue
        if ($portInUse) {
            throw "TCP port $PostgresPort is already in use by a non-managed process."
        }
        Invoke-Native -Executable $Docker -Arguments @(
            "run", "--detach",
            "--name", $ContainerName,
            "--publish", "${PostgresPort}:5432",
            "--env", "POSTGRES_DB=$DatabaseName",
            "--env", "POSTGRES_USER=$BootstrapUser",
            "--env", "POSTGRES_PASSWORD=$BootstrapPassword",
            "--health-cmd", "pg_isready -U $BootstrapUser -d $DatabaseName",
            "--health-interval", "2s",
            "--health-timeout", "3s",
            "--health-retries", "30",
            $PostgresImage
        ) -Description "Topic 1 PostgreSQL test container creation"
        $CreatedContainer = $true
    }
    else {
        $publishedPort = (& $Docker port $ContainerName "5432/tcp").Trim()
        if ($LASTEXITCODE -ne 0 -or $publishedPort -notmatch ":$PostgresPort$") {
            throw (
                "Existing container $ContainerName is not mapped to host port $PostgresPort. " +
                "Use a matching -PostgresPort or remove the stale test container."
            )
        }
        $running = (& $Docker inspect --format "{{.State.Running}}" $ContainerName).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect existing PostgreSQL test container."
        }
        if ($running -ne "true") {
            Invoke-Native -Executable $Docker -Arguments @("start", $ContainerName) `
                -Description "Topic 1 PostgreSQL test container start"
        }
    }

    $healthy = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $health = (& $Docker inspect --format "{{.State.Health.Status}}" $ContainerName).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect PostgreSQL health status."
        }
        if ($health -eq "healthy") {
            $healthy = $true
            break
        }
        if ($health -eq "unhealthy") {
            & $Docker logs $ContainerName
            throw "The Topic 1 PostgreSQL test container became unhealthy."
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        throw "PostgreSQL did not become healthy within 120 seconds."
    }

    $RoleBootstrap = Get-Content `
        -LiteralPath "infra\postgres\init\001-runtime-role.sql" `
        -Raw `
        -Encoding utf8
    $RoleBootstrap | & $Docker exec -i $ContainerName `
        psql --set ON_ERROR_STOP=1 --username $BootstrapUser --dbname $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "Restricted PostgreSQL role bootstrap failed with exit code $LASTEXITCODE."
    }

    $env:LIYAN_TEST_DATABASE_URL = (
        "postgresql+asyncpg://liyans_app:liyans-app-local-only@" +
        "127.0.0.1:$PostgresPort/$DatabaseName"
    )
    $env:LIYAN_TEST_MIGRATION_DATABASE_URL = (
        "postgresql+asyncpg://liyans_migrator:liyans-migrator-local-only@" +
        "127.0.0.1:$PostgresPort/$DatabaseName"
    )
    $env:LIYAN_TEST_DISPATCHER_DATABASE_URL = (
        "postgresql+asyncpg://liyans_dispatcher:liyans-dispatcher-local-only@" +
        "127.0.0.1:$PostgresPort/$DatabaseName"
    )

    Invoke-Native -Executable $Uv -Arguments @("lock", "--check") `
        -Description "Locked Python environment validation"
    & (Join-Path $PSScriptRoot "run-quality-gates.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "The full Release quality redline failed with exit code $LASTEXITCODE."
    }

    Write-Host "Topic 1 local acceptance passed." -ForegroundColor Green
    Write-Host "Evidence: artifacts/quality-gates, artifacts/coverage, artifacts/test-results"
}
finally {
    Pop-Location
    if ($CreatedContainer -and -not $KeepDatabase) {
        & $Docker rm --force $ContainerName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Unable to remove temporary container $ContainerName."
        }
    }
}
