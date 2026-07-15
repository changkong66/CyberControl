[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Branch = "main",

    [string]$Remote = "origin",

    [string]$ProtectedTag = "phase-1.1-baseline-611375c"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-GitCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [switch]$AllowFailure
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& git @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = ($output -join [Environment]::NewLine)
    }
}

function Assert-ProbeRejected {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Result
    )

    if ($Result.ExitCode -eq 0) {
        throw "Protection probe '$Name' unexpectedly succeeded. Inspect the remote immediately."
    }
    if (
        $Result.Output -notmatch `
            "(GH013|protected branch|repository rule|declined|prohibited|refusing to delete)"
    ) {
        throw "Protection probe '$Name' failed for an unrecognized reason: $($Result.Output)"
    }
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $root
try {
    Invoke-GitCapture -Arguments @("fetch", "--prune", $Remote, $Branch) | Out-Null
    $remoteRef = "refs/remotes/$Remote/$Branch"
    $baseline = (Invoke-GitCapture -Arguments @("rev-parse", $remoteRef)).Output.Trim()
    $tree = (Invoke-GitCapture -Arguments @("rev-parse", "$remoteRef`^{tree}")).Output.Trim()

    $directCandidate = (
        "test(governance): blocked direct-push probe" |
            git commit-tree $tree -p $baseline
    ).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the direct-push probe commit object."
    }
    $directPush = Invoke-GitCapture `
        -Arguments @("push", $Remote, "$directCandidate`:refs/heads/$Branch") `
        -AllowFailure
    Assert-ProbeRejected -Name "direct-push" -Result $directPush

    $forceCandidate = (
        "test(governance): blocked force-push probe" |
            git commit-tree $tree
    ).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the force-push probe commit object."
    }
    $forcePush = Invoke-GitCapture `
        -Arguments @("push", "--force", $Remote, "$forceCandidate`:refs/heads/$Branch") `
        -AllowFailure
    Assert-ProbeRejected -Name "force-push" -Result $forcePush

    $deleteBranch = Invoke-GitCapture `
        -Arguments @("push", $Remote, ":refs/heads/$Branch") `
        -AllowFailure
    Assert-ProbeRejected -Name "delete-branch" -Result $deleteBranch

    $tagRef = "refs/tags/$ProtectedTag"
    $remoteTag = Invoke-GitCapture `
        -Arguments @("ls-remote", "--tags", $Remote, $tagRef)
    if ([string]::IsNullOrWhiteSpace($remoteTag.Output)) {
        Invoke-GitCapture -Arguments @("push", $Remote, "$baseline`:$tagRef") | Out-Null
    }
    $deleteTag = Invoke-GitCapture `
        -Arguments @("push", $Remote, ":$tagRef") `
        -AllowFailure
    Assert-ProbeRejected -Name "delete-tag" -Result $deleteTag

    Invoke-GitCapture -Arguments @("fetch", "--prune", $Remote, $Branch) | Out-Null
    $verifiedBaseline = (Invoke-GitCapture -Arguments @("rev-parse", $remoteRef)).Output.Trim()
    if ($verifiedBaseline -ne $baseline) {
        throw "Remote branch changed during protection probes: $baseline -> $verifiedBaseline"
    }
    $verifiedTag = Invoke-GitCapture `
        -Arguments @("ls-remote", "--tags", $Remote, $tagRef)
    if ([string]::IsNullOrWhiteSpace($verifiedTag.Output)) {
        throw "Protected tag '$ProtectedTag' disappeared during the deletion probe."
    }

    $evidence = [ordered]@{
        schema_version = "phase1.1.repository-protection-probes.v1"
        remote = $Remote
        branch = $Branch
        baseline_sha = $baseline
        protected_tag = $ProtectedTag
        probes = @(
            [ordered]@{ name = "direct-push"; rejected = $true; output = $directPush.Output },
            [ordered]@{ name = "force-push"; rejected = $true; output = $forcePush.Output },
            [ordered]@{ name = "delete-branch"; rejected = $true; output = $deleteBranch.Output },
            [ordered]@{ name = "delete-tag"; rejected = $true; output = $deleteTag.Output }
        )
        remote_unchanged = $true
        verified_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $evidenceRoot = Join-Path $root "artifacts\quality-gates"
    New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
    $evidence | ConvertTo-Json -Depth 8 | Set-Content `
        -LiteralPath (Join-Path $evidenceRoot "repository-protection-probes.json") `
        -Encoding utf8
    $evidence | ConvertTo-Json -Depth 8
}
finally {
    Pop-Location
}
