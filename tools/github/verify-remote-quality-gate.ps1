[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Branch,

    [string]$ExpectedCommit,

    [ValidateRange(60, 7200)]
    [int]$TimeoutSeconds = 3600
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($env:GH_TOKEN)) {
    throw "GH_TOKEN with Actions read permission is required."
}
if ([string]::IsNullOrWhiteSpace($ExpectedCommit)) {
    $ExpectedCommit = (& git rev-parse HEAD).Trim()
}
if ($ExpectedCommit -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedCommit must be a full Git commit SHA."
}

$Headers = @{
    Accept = "application/vnd.github+json"
    Authorization = "Bearer $($env:GH_TOKEN)"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "Liyan-Phase11-CI-Verification"
}
$ApiRoot = "https://api.github.com/repos/$Repository"
$Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$Run = $null

while ([DateTime]::UtcNow -lt $Deadline) {
    $queryBranch = [Uri]::EscapeDataString($Branch)
    $runs = Invoke-RestMethod `
        -Method GET `
        -Uri "$ApiRoot/actions/workflows/quality-gates.yml/runs?branch=$queryBranch&per_page=20" `
        -Headers $Headers `
        -TimeoutSec 60
    $Run = @($runs.workflow_runs) |
        Where-Object { $_.head_sha -eq $ExpectedCommit } |
        Select-Object -First 1
    if ($null -eq $Run) {
        Start-Sleep -Seconds 10
        continue
    }
    if ($Run.status -eq "completed") {
        break
    }
    Start-Sleep -Seconds 15
}

if ($null -eq $Run) {
    throw "No Release Quality Gates run appeared for commit $ExpectedCommit."
}
if ($Run.status -ne "completed") {
    throw "Remote quality workflow did not complete before the timeout."
}
if ($Run.conclusion -ne "success") {
    throw "Remote quality workflow concluded '$($Run.conclusion)': $($Run.html_url)"
}

$jobs = Invoke-RestMethod `
    -Method GET `
    -Uri "$ApiRoot/actions/runs/$($Run.id)/jobs?filter=latest&per_page=100" `
    -Headers $Headers `
    -TimeoutSec 60
$Redline = @($jobs.jobs) |
    Where-Object { $_.name -eq "Release quality redline" } |
    Select-Object -First 1
if ($null -eq $Redline -or $Redline.conclusion -ne "success") {
    throw "The required 'Release quality redline' job did not pass."
}

$EvidenceRoot = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) `
    "artifacts\quality-gates"
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$Evidence = [ordered]@{
    schema_version = "phase1.1.remote-ci.v1"
    repository = $Repository
    branch = $Branch
    commit = $ExpectedCommit
    workflow_run_id = $Run.id
    workflow_url = $Run.html_url
    workflow_conclusion = $Run.conclusion
    redline_job_id = $Redline.id
    redline_conclusion = $Redline.conclusion
    verified_at_utc = [DateTime]::UtcNow.ToString("o")
}
$Evidence | ConvertTo-Json -Depth 5 | Set-Content `
    -LiteralPath (Join-Path $EvidenceRoot "remote-ci.json") `
    -Encoding utf8
$Evidence | ConvertTo-Json -Depth 5
