[CmdletBinding()]
param(
    [string]$Version = "8.30.1",

    [ValidatePattern('^[a-fA-F0-9]{64}$')]
    [string]$ExpectedArchiveSha256 = `
        "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-WithRetry {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Operation,

        [int]$MaximumAttempts = 3
    )

    for ($attempt = 1; $attempt -le $MaximumAttempts; $attempt++) {
        try {
            return & $Operation
        }
        catch {
            if ($attempt -eq $MaximumAttempts) {
                throw
            }
            Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
        }
    }
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $Executable @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = ($output -join [Environment]::NewLine)
    }
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$gitDirectory = Join-Path $root ".git"
if (-not (Test-Path -LiteralPath $gitDirectory -PathType Container)) {
    throw "The audit must run from the CyberControl Git worktree."
}

$configPath = Join-Path $root ".gitleaks.toml"
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "The repository-owned .gitleaks.toml policy is required."
}

$cacheRoot = Join-Path $root "artifacts\toolchain-cache\gitleaks-$Version"
$securityRoot = Join-Path $root "artifacts\security"
$archiveName = "gitleaks_${Version}_windows_x64.zip"
$archivePath = Join-Path $cacheRoot $archiveName
$gitleaksPath = Join-Path $cacheRoot "gitleaks.exe"
$downloadUri = "https://github.com/gitleaks/gitleaks/releases/download/v$Version/$archiveName"
New-Item -ItemType Directory -Force -Path $cacheRoot, $securityRoot | Out-Null

if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    Invoke-WithRetry -Operation {
        Invoke-WebRequest `
            -UseBasicParsing `
            -Uri $downloadUri `
            -OutFile $archivePath `
            -TimeoutSec 120
    }
}

$actualSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $ExpectedArchiveSha256.ToLowerInvariant()) {
    throw "Gitleaks archive checksum mismatch: expected $ExpectedArchiveSha256, found $actualSha256."
}

if (-not (Test-Path -LiteralPath $gitleaksPath -PathType Leaf)) {
    Expand-Archive -LiteralPath $archivePath -DestinationPath $cacheRoot -Force
}
$versionResult = Invoke-NativeCapture -Executable $gitleaksPath -Arguments @("version")
if ($versionResult.ExitCode -ne 0 -or $versionResult.Output -notmatch [regex]::Escape($Version)) {
    throw "The checksum-verified Gitleaks binary did not report version $Version."
}

$historyReport = Join-Path $securityRoot "gitleaks-public-history.json"
$workingTreeReport = Join-Path $securityRoot "gitleaks-public-working-tree.json"
$historyLog = Join-Path $securityRoot "gitleaks-public-history.log"
$workingTreeLog = Join-Path $securityRoot "gitleaks-public-working-tree.log"

Push-Location $root
try {
    $historyResult = Invoke-NativeCapture -Executable $gitleaksPath -Arguments @(
        "git",
        ".",
        "--config=$configPath",
        "--redact=100",
        "--report-format=json",
        "--report-path=$historyReport",
        "--log-opts=--all"
    )
    [IO.File]::WriteAllText($historyLog, $historyResult.Output, [Text.Encoding]::UTF8)

    $workingTreeResult = Invoke-NativeCapture -Executable $gitleaksPath -Arguments @(
        "dir",
        ".",
        "--config=$configPath",
        "--redact=100",
        "--report-format=json",
        "--report-path=$workingTreeReport"
    )
    [IO.File]::WriteAllText($workingTreeLog, $workingTreeResult.Output, [Text.Encoding]::UTF8)
}
finally {
    Pop-Location
}

function Get-FindingCount {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return 0
    }
    $content = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8).Trim()
    if ([string]::IsNullOrWhiteSpace($content)) {
        return 0
    }
    $parsed = $content | ConvertFrom-Json
    if ($null -eq $parsed) {
        return 0
    }
    return @($parsed).Count
}

$historyFindings = Get-FindingCount -Path $historyReport
$workingTreeFindings = Get-FindingCount -Path $workingTreeReport
$trackedFiles = @(git -C $root ls-files)
$sensitiveNamePattern = `
    '(?i)(^|/)(\.env($|\.)|.*\.(pem|key|p12|pfx|jks)$|id_(rsa|ed25519)|' +
    '.*(secret|credential|password|private-key).*)'
$sensitiveTrackedNames = @($trackedFiles | Where-Object { $_ -match $sensitiveNamePattern })
$allowedTrackedNames = @(".env.example", "tools/github/set-gh-token.ps1")
$unexpectedSensitiveNames = @(
    $sensitiveTrackedNames | Where-Object { $allowedTrackedNames -notcontains $_ }
)

$summary = [ordered]@{
    schema_version = "phase1.1.public-repository-security-audit.v1"
    repository_root = $root.Path
    gitleaks_version = $Version
    gitleaks_archive_sha256 = $actualSha256
    history = [ordered]@{
        exit_code = $historyResult.ExitCode
        findings = $historyFindings
        report = $historyReport
    }
    working_tree = [ordered]@{
        exit_code = $workingTreeResult.ExitCode
        findings = $workingTreeFindings
        report = $workingTreeReport
    }
    tracked_sensitive_name_candidates = $sensitiveTrackedNames
    unexpected_sensitive_tracked_names = $unexpectedSensitiveNames
    passed = (
        $historyResult.ExitCode -eq 0 -and
        $workingTreeResult.ExitCode -eq 0 -and
        $historyFindings -eq 0 -and
        $workingTreeFindings -eq 0 -and
        $unexpectedSensitiveNames.Count -eq 0
    )
    scanned_at_utc = [DateTime]::UtcNow.ToString("o")
}
$summaryPath = Join-Path $securityRoot "public-repository-security-summary.json"
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding utf8
$summary | ConvertTo-Json -Depth 8

if (-not $summary.passed) {
    throw "Public repository security audit failed. Review redacted reports under artifacts/security."
}
