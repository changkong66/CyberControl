[CmdletBinding()]
param(
    [switch]$SkipFullRegression
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $env:LIYAN_TEST_DATABASE_URL) {
    throw "LIYAN_TEST_DATABASE_URL is required."
}
if (-not $env:LIYAN_TEST_MIGRATION_DATABASE_URL) {
    throw "LIYAN_TEST_MIGRATION_DATABASE_URL is required."
}

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Resolve-UvExecutable {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidates = @(
        (Join-Path $env:APPDATA "Python\Python311\Scripts\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    throw "uv is unavailable. Run tools/windows/sync-python-environment.ps1 first."
}

$UvExecutable = Resolve-UvExecutable

$env:LIYAN_DATABASE_URL = $env:LIYAN_TEST_DATABASE_URL
$env:LIYAN_DATABASE_MIGRATION_URL = $env:LIYAN_TEST_MIGRATION_DATABASE_URL

Push-Location $RepositoryRoot
try {
    & $UvExecutable run --frozen alembic -c backend/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic upgrade failed with exit code $LASTEXITCODE."
    }

    & $UvExecutable run --frozen alembic -c backend/alembic.ini current --check-heads
    if ($LASTEXITCODE -ne 0) {
        throw "The database is not at the Alembic head."
    }

    & $UvExecutable run --frozen pytest backend/tests/integration -q -rs
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL integration tests failed with exit code $LASTEXITCODE."
    }

    if (-not $SkipFullRegression) {
        & $UvExecutable run --frozen pytest -q
        if ($LASTEXITCODE -ne 0) {
            throw "Full regression failed with exit code $LASTEXITCODE."
        }
    }
}
finally {
    Pop-Location
}
