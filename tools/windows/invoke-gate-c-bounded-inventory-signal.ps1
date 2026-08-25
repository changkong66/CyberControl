[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ContainerId,

    [Parameter(Mandatory = $true)]
    [ValidateRange(0, 86400)]
    [int]$DelaySeconds,

    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (Test-Path -LiteralPath $ManifestPath) {
    throw "Bounded inventory manifest already exists: $ManifestPath"
}
if ($DelaySeconds -gt 0) {
    Start-Sleep -Seconds $DelaySeconds
}
& docker kill --signal USR1 $ContainerId | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Unable to signal the bounded inventory container."
}
$deadline = (Get-Date).AddSeconds(31)
do {
    if (Test-Path -LiteralPath $ManifestPath -PathType Leaf) {
        exit 0
    }
    Start-Sleep -Milliseconds 250
} while ((Get-Date) -lt $deadline)
throw "Bounded inventory manifest was not produced within 31 seconds."
