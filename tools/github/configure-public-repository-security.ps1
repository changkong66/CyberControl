[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($env:GH_TOKEN)) {
    throw "GH_TOKEN with repository administration permission is required."
}

$headers = @{
    Accept = "application/vnd.github+json"
    Authorization = "Bearer $($env:GH_TOKEN)"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "CyberControl-Public-Security"
}
$apiRoot = "https://api.github.com/repos/$Repository"

function Invoke-GitHubJson {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "PATCH", "PUT")]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [hashtable]$Body
    )

    $arguments = @{
        Method = $Method
        Uri = $Uri
        Headers = $headers
        TimeoutSec = 60
    }
    if ($null -ne $Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body | ConvertTo-Json -Depth 10 -Compress
    }
    try {
        return Invoke-RestMethod @arguments
    }
    catch {
        $status = "transport-error"
        $responseProperty = $_.Exception.PSObject.Properties["Response"]
        if ($null -ne $responseProperty -and $null -ne $responseProperty.Value) {
            $statusProperty = $responseProperty.Value.PSObject.Properties["StatusCode"]
            if ($null -ne $statusProperty -and $null -ne $statusProperty.Value) {
                $status = [int]$statusProperty.Value
            }
        }
        $detail = if ($null -eq $_.ErrorDetails) { "" } else { $_.ErrorDetails.Message }
        throw "GitHub API $Method $Uri failed with $status. $($_.Exception.Message) $detail"
    }
}

$repositoryState = Invoke-GitHubJson -Method GET -Uri $apiRoot
if ($repositoryState.visibility -ne "public" -or $repositoryState.private) {
    throw "Public repository security controls cannot be accepted while visibility is not Public."
}
if (-not $repositoryState.permissions.admin) {
    throw "The current GitHub credential does not have repository administration permission."
}

if ($PSCmdlet.ShouldProcess($Repository, "Enable public-repository security controls")) {
    Invoke-GitHubJson -Method PATCH -Uri $apiRoot -Body @{
        security_and_analysis = @{
            secret_scanning = @{ status = "enabled" }
            secret_scanning_push_protection = @{ status = "enabled" }
        }
    } | Out-Null
    Invoke-GitHubJson -Method PUT -Uri "$apiRoot/vulnerability-alerts" | Out-Null
    try {
        Invoke-GitHubJson -Method PUT -Uri "$apiRoot/automated-security-fixes" | Out-Null
    }
    catch {
        Write-Warning (
            "Dependabot automated security fixes could not be enabled. " +
            "The vulnerability-alert gate remains mandatory. $($_.Exception.Message)"
        )
    }
}

$verifiedRepository = Invoke-GitHubJson -Method GET -Uri $apiRoot
$secretScanning = $verifiedRepository.security_and_analysis.secret_scanning.status
$pushProtection = `
    $verifiedRepository.security_and_analysis.secret_scanning_push_protection.status
if ($secretScanning -ne "enabled" -or $pushProtection -ne "enabled") {
    throw "GitHub Secret Scanning or Push Protection is not enabled."
}

$alertResponse = Invoke-GitHubJson `
    -Method GET `
    -Uri "$apiRoot/secret-scanning/alerts?state=open&per_page=100"
$openAlerts = @()
foreach ($candidate in @($alertResponse)) {
    if ($null -ne $candidate.PSObject.Properties["number"]) {
        $openAlerts += $candidate
    }
}
if ($openAlerts.Count -gt 0) {
    throw "GitHub Secret Scanning reports $($openAlerts.Count) open alert(s)."
}

$evidence = [ordered]@{
    schema_version = "phase1.1.github-public-security.v1"
    repository = $Repository
    visibility = $verifiedRepository.visibility
    secret_scanning = $secretScanning
    secret_scanning_push_protection = $pushProtection
    open_secret_scanning_alerts = $openAlerts.Count
    vulnerability_alerts_requested = $true
    automated_security_fixes_requested = $true
    verified_at_utc = [DateTime]::UtcNow.ToString("o")
}
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$evidenceRoot = Join-Path $root "artifacts\quality-gates"
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$evidence | ConvertTo-Json -Depth 6 | Set-Content `
    -LiteralPath (Join-Path $evidenceRoot "github-public-security.json") `
    -Encoding utf8
$evidence | ConvertTo-Json -Depth 6
