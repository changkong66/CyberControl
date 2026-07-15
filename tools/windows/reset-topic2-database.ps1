[CmdletBinding()]
param(
    [switch]$ConfirmTopic2Reset
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $ConfirmTopic2Reset) {
    throw "Topic 2 reset requires -ConfirmTopic2Reset. All Topic 2 history will be deleted."
}
if ($env:LIYAN_ENVIRONMENT -eq "production") {
    throw "Topic 2 database reset is forbidden in production."
}
if (-not $env:LIYAN_DATABASE_MIGRATION_URL) {
    throw "LIYAN_DATABASE_MIGRATION_URL must contain the privileged local migration URL."
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$alembicConfig = Join-Path $repositoryRoot "backend\alembic.ini"
$uvCandidates = @(
    (Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    (Join-Path $env:APPDATA "Python\Python311\Scripts\uv.exe"),
    (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
)
$uv = $uvCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $uv) {
    throw "uv is unavailable. Run tools/windows/sync-python-environment.ps1 first."
}

Push-Location $repositoryRoot
try {
    $current = (& $uv run --frozen alembic -c $alembicConfig current --check-heads | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read the current Alembic revision."
    }
    if ($current -notmatch "20260715_0005") {
        throw "The database is not at the frozen Topic 2 head; automatic reset is refused."
    }

    & $uv run --frozen alembic -c $alembicConfig downgrade 20260715_0004
    if ($LASTEXITCODE -ne 0) {
        throw "Topic 2 downgrade failed."
    }
    & $uv run --frozen alembic -c $alembicConfig upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Topic 2 re-creation failed."
    }
    & $uv run --frozen alembic -c $alembicConfig check
    if ($LASTEXITCODE -ne 0) {
        throw "Topic 2 reset left an Alembic model drift."
    }
    Write-Host "Topic 2 tables were recreated; Phase 1.1 and Topic 1 were preserved." `
        -ForegroundColor Green
}
finally {
    Pop-Location
}
