[CmdletBinding()]
param(
    [ValidatePattern("^[a-z0-9][a-z0-9_-]{2,40}$")]
    [string]$ProjectName = "liyans-topic2-local",

    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 5432,

    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 8000,

    [switch]$NoBuild,
    [switch]$KeepFailedStack
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$startScript = Join-Path $PSScriptRoot "start-local.ps1"
$arguments = @{
    ProjectName = $ProjectName
    PostgresPort = $PostgresPort
    ApiPort = $ApiPort
}
if ($NoBuild) {
    $arguments.NoBuild = $true
}
if ($KeepFailedStack) {
    $arguments.KeepFailedStack = $true
}

& $startScript @arguments
Write-Host "Topic 2 OpenAPI: http://127.0.0.1:$ApiPort/docs" -ForegroundColor Green
Write-Host "Topic 2 API prefix: http://127.0.0.1:$ApiPort/internal/topic2"
