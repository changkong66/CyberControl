[CmdletBinding()]
param(
    [ValidatePattern("^[a-z0-9][a-z0-9_-]{2,40}$")]
    [string]$ProjectName = "liyans-local",
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $RepositoryRoot "infra\docker-compose.yml"
$arguments = @("compose", "-p", $ProjectName, "-f", $ComposeFile, "down", "--remove-orphans")
if ($RemoveVolumes) { $arguments += "--volumes" }

& docker @arguments
if ($LASTEXITCODE -ne 0) {
    throw "local stack shutdown failed with exit code $LASTEXITCODE."
}
Write-Host "Compose project '$ProjectName' was stopped." -ForegroundColor Green
