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

if (-not $env:LIYAN_DATABASE_MIGRATION_URL) {
    throw "LIYAN_DATABASE_MIGRATION_URL must contain the privileged migration connection URL."
}

if ($Action -eq "DowngradeOne" -and -not $AllowDestructiveDowngrade) {
    throw "DowngradeOne requires -AllowDestructiveDowngrade."
}

$UvExecutable = Resolve-UvExecutable

Push-Location $RepositoryRoot
try {
    switch ($Action) {
        "Upgrade" {
            & $UvExecutable run --frozen alembic -c $AlembicConfig upgrade head
        }
        "DowngradeOne" {
            & $UvExecutable run --frozen alembic -c $AlembicConfig downgrade -1
        }
        "Current" {
            & $UvExecutable run --frozen alembic -c $AlembicConfig current --check-heads
        }
        "Check" {
            & $UvExecutable run --frozen alembic -c $AlembicConfig check
        }
        "Sql" {
            & $UvExecutable run --frozen alembic -c $AlembicConfig upgrade head --sql
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
