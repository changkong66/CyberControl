[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 55436,

    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,62}$')]
    [string]$ContainerName = "liyans-topic2-postgres",

    [switch]$KeepDatabase
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$postgresImage = (
    "postgres:16-alpine@sha256:" +
    "57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
)
$bootstrapUser = "liyans_bootstrap"
$bootstrapPassword = "liyans-bootstrap-topic1-local-only"
$databaseName = "liyans"
$createdContainer = $false

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

$docker = Resolve-NativeExecutable -Name "docker"
$uv = Resolve-NativeExecutable -Name "uv" -Candidates @(
    (Join-Path $env:APPDATA "Python\Python311\Scripts\uv.exe"),
    (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
)

Push-Location $repositoryRoot
try {
    Invoke-Native -Executable $docker -Arguments @("info", "--format", "{{.ServerVersion}}") `
        -Description "Docker daemon readiness check"

    $existing = (& $docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}")
    if ($LASTEXITCODE -ne 0) {
        throw "Docker container inventory failed."
    }
    if (-not $existing) {
        if (Get-NetTCPConnection -State Listen -LocalPort $PostgresPort `
                -ErrorAction SilentlyContinue) {
            throw "TCP port $PostgresPort is already in use."
        }
        Invoke-Native -Executable $docker -Arguments @(
            "run", "--detach",
            "--name", $ContainerName,
            "--publish", "${PostgresPort}:5432",
            "--env", "POSTGRES_DB=$databaseName",
            "--env", "POSTGRES_USER=$bootstrapUser",
            "--env", "POSTGRES_PASSWORD=$bootstrapPassword",
            "--health-cmd", "pg_isready -U $bootstrapUser -d $databaseName",
            "--health-interval", "2s",
            "--health-timeout", "3s",
            "--health-retries", "30",
            $postgresImage
        ) -Description "Topic 2 PostgreSQL test container creation"
        $createdContainer = $true
    }
    else {
        $publishedPort = (& $docker port $ContainerName "5432/tcp").Trim()
        if ($LASTEXITCODE -ne 0 -or $publishedPort -notmatch ":$PostgresPort$") {
            throw "Existing container $ContainerName does not use port $PostgresPort."
        }
        $running = (& $docker inspect --format "{{.State.Running}}" $ContainerName).Trim()
        if ($running -ne "true") {
            Invoke-Native -Executable $docker -Arguments @("start", $ContainerName) `
                -Description "Topic 2 PostgreSQL test container start"
        }
    }

    $healthy = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $health = (& $docker inspect --format "{{.State.Health.Status}}" $ContainerName).Trim()
        if ($health -eq "healthy") {
            $healthy = $true
            break
        }
        if ($health -eq "unhealthy") {
            & $docker logs $ContainerName
            throw "The Topic 2 PostgreSQL container became unhealthy."
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        throw "PostgreSQL did not become healthy within 120 seconds."
    }

    $roleBootstrap = Get-Content `
        -LiteralPath "infra\postgres\init\001-runtime-role.sql" `
        -Raw `
        -Encoding utf8
    $bootstrapSucceeded = $false
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        $roleBootstrap | & $docker exec -i $ContainerName `
            psql --set ON_ERROR_STOP=1 --username $bootstrapUser --dbname $databaseName
        if ($LASTEXITCODE -eq 0) {
            $bootstrapSucceeded = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $bootstrapSucceeded) {
        & $docker logs $ContainerName
        throw "Restricted PostgreSQL role bootstrap failed."
    }

    $env:LIYAN_TEST_DATABASE_URL = (
        "postgresql+asyncpg://liyans_app:liyans-app-local-only@" +
        "127.0.0.1:$PostgresPort/$databaseName"
    )
    $env:LIYAN_TEST_MIGRATION_DATABASE_URL = (
        "postgresql+asyncpg://liyans_migrator:liyans-migrator-local-only@" +
        "127.0.0.1:$PostgresPort/$databaseName"
    )
    $env:LIYAN_TEST_DISPATCHER_DATABASE_URL = (
        "postgresql+asyncpg://liyans_dispatcher:liyans-dispatcher-local-only@" +
        "127.0.0.1:$PostgresPort/$databaseName"
    )

    Invoke-Native -Executable $uv -Arguments @("lock", "--check") `
        -Description "Locked Python environment validation"
    & (Join-Path $PSScriptRoot "run-quality-gates.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "The full Release quality redline failed with exit code $LASTEXITCODE."
    }

    Write-Host "Topic 2 local acceptance passed." -ForegroundColor Green
    Write-Host "Evidence: artifacts/quality-gates, artifacts/coverage, artifacts/test-results"
}
finally {
    Pop-Location
    if ($createdContainer -and -not $KeepDatabase) {
        & $docker rm --force $ContainerName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Unable to remove temporary container $ContainerName."
        }
    }
}
