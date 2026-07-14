[CmdletBinding()]
param(
    [ValidateSet("Upgrade", "DowngradeOne", "Current", "Check", "Sql")]
    [string]$Action = "Upgrade",
    [switch]$AllowDestructiveDowngrade
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AlembicConfig = Join-Path $RepositoryRoot "backend\alembic.ini"

if (-not $env:LIYAN_DATABASE_MIGRATION_URL) {
    throw "LIYAN_DATABASE_MIGRATION_URL must contain the privileged migration connection URL."
}

if ($Action -eq "DowngradeOne" -and -not $AllowDestructiveDowngrade) {
    throw "DowngradeOne requires -AllowDestructiveDowngrade."
}

$UvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $UvCommand) {
    throw "uv is not available on PATH. Run tools/windows/sync-python-environment.ps1 first."
}

Push-Location $RepositoryRoot
try {
    switch ($Action) {
        "Upgrade" {
            & $UvCommand.Source run --frozen alembic -c $AlembicConfig upgrade head
        }
        "DowngradeOne" {
            & $UvCommand.Source run --frozen alembic -c $AlembicConfig downgrade -1
        }
        "Current" {
            & $UvCommand.Source run --frozen alembic -c $AlembicConfig current --check-heads
        }
        "Check" {
            & $UvCommand.Source run --frozen alembic -c $AlembicConfig check
        }
        "Sql" {
            & $UvCommand.Source run --frozen alembic -c $AlembicConfig upgrade head --sql
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
