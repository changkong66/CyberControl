[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("calibration")]
    [string]$Kind,

    [ValidateSet("D")]
    [string]$Variable,

    [Parameter(Mandatory = $true)]
    [string]$ImageLockPath,

    [string]$ResultsRoot = "D:\CyberControlAcceptance\phase7\gate-c\diagnostics\adr0033-reproduction",

    [ValidateRange(0, 2)]
    [int]$InfraRetryAttempt = 0,

    [string]$RetryOfRunId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sequenceRunner = Join-Path $PSScriptRoot "run-gate-c-rss-calibration-sequence.ps1"
$comparisonTool = Join-Path $root "tests\load\gate_c\rss_reproduction_compare.py"
$packageTool = Join-Path $root "tests\load\gate_c\diagnostic_evidence_package.py"
$processVersion = "Gate-C-12-v2.0"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
if ($Kind -eq "calibration" -and [string]::IsNullOrWhiteSpace($Variable)) {
    throw "INFRA_ABORTED: calibration reproduction requires -Variable."
}
$variableName = $Variable.ToLowerInvariant()
$reproductionId = "adr0033-$Kind-$variableName-reproduction-$timestamp-$suffix"
$reproductionDirectory = [IO.Path]::GetFullPath((Join-Path $ResultsRoot $reproductionId))
$sequencesDirectory = Join-Path $reproductionDirectory "sequences"
$evidenceDirectory = Join-Path $reproductionDirectory "evidence"
$packagePath = Join-Path $reproductionDirectory "evidence.zip"
$manifestPath = Join-Path $reproductionDirectory "evidence-manifest.json"
$runSummaryPath = Join-Path $reproductionDirectory "run-summary.json"
$cleanupReceiptPath = Join-Path $reproductionDirectory "cleanup-receipt.json"
$packageReferencePath = Join-Path $reproductionDirectory "package-reference.json"
$classification = "NON_ACCEPTANCE_DIAGNOSTIC"
$failureReason = $null
$references = [ordered]@{}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-NewJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    if (Test-Path -LiteralPath $Path) {
        throw "Immutable JSON output already exists: $Path"
    }
    [IO.File]::WriteAllText(
        $Path,
        (($Value | ConvertTo-Json -Depth 12) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
}

function Invoke-Sequence {
    param([Parameter(Mandatory = $true)][ValidateSet(1, 2)][int]$Number)

    $stdout = Join-Path $evidenceDirectory "sequence-$Number.stdout.log"
    $stderr = Join-Path $evidenceDirectory "sequence-$Number.stderr.log"
    $arguments = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $sequenceRunner,
        "-ImageLockPath", [IO.Path]::GetFullPath($ImageLockPath),
        "-ResultsRoot", $sequencesDirectory,
        "-InfraRetryAttempt", [string]$InfraRetryAttempt
    )
    if (-not [string]::IsNullOrWhiteSpace($RetryOfRunId)) {
        $arguments += @("-RetryOfRunId", $RetryOfRunId)
    }
    if ($Kind -eq "calibration") {
        $arguments += @("-Variable", $Variable)
    }
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $process = Start-Process -FilePath $pwsh -ArgumentList $arguments -WorkingDirectory $root `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -WindowStyle Hidden -PassThru -Wait
    $referencePath = @(
        Get-Content -LiteralPath $stdout -Encoding UTF8 |
            Where-Object { $_.Trim().EndsWith("package-reference.json") } |
            ForEach-Object { $_.Trim() }
    ) | Select-Object -Last 1
    if (
        [string]::IsNullOrWhiteSpace($referencePath) -or
        -not (Test-Path -LiteralPath $referencePath -PathType Leaf)
    ) {
        $childError = if (Test-Path -LiteralPath $stderr -PathType Leaf) {
            Get-Content -LiteralPath $stderr -Raw -Encoding UTF8
        }
        else {
            ""
        }
        $childClassification = if ($childError -match "INFRA_ABORTED:") {
            "INFRA_ABORTED"
        }
        else {
            "DESIGN_REJECTED"
        }
        throw "$childClassification`: sequence $Number returned no immutable package reference."
    }
    $reference = Get-Content -LiteralPath $referencePath -Raw -Encoding UTF8 | ConvertFrom-Json
    return [ordered]@{
        reference_path = $referencePath
        reference_sha256 = Get-FileSha256 $referencePath
        run_id = [string]$reference.run_id
        classification = [string]$reference.classification
        process_exit_code = $process.ExitCode
        eligible_for_reproduction = (
            $process.ExitCode -eq 0 -and
            $reference.process_version -eq $processVersion -and
            $reference.classification -eq "NON_ACCEPTANCE_DIAGNOSTIC" -and
            $reference.formal_gate_attempt -eq $false -and
            $reference.acceptance_claim -eq $false
        )
    }
}

if ($InfraRetryAttempt -eq 0 -and -not [string]::IsNullOrWhiteSpace($RetryOfRunId)) {
    throw "INFRA_ABORTED: -RetryOfRunId is valid only when -InfraRetryAttempt is 1 or 2."
}
if ($InfraRetryAttempt -gt 0 -and [string]::IsNullOrWhiteSpace($RetryOfRunId)) {
    throw "INFRA_ABORTED: an infrastructure retry requires -RetryOfRunId."
}
if (Test-Path -LiteralPath $reproductionDirectory) {
    throw "INFRA_ABORTED: immutable reproduction directory already exists: $reproductionDirectory"
}
New-Item -ItemType Directory -Path $sequencesDirectory, $evidenceDirectory -Force | Out-Null
Write-NewJson -Path (Join-Path $evidenceDirectory "execution-context.json") -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-rss-calibration-reproduction-context.v1"
    process_version = $processVersion
    classification = "NON_ACCEPTANCE_DIAGNOSTIC"
    formal_gate_attempt = $false
    acceptance_claim = $false
    reproduction_id = $reproductionId
    kind = $Kind
    variable = if ($Kind -eq "calibration") { $Variable } else { $null }
    infra_retry_attempt = $InfraRetryAttempt
    retry_of_run_id = $RetryOfRunId
    independent_sequence_count = 2
    started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
})

try {
    $references.first = Invoke-Sequence -Number 1
    if ($references.first.eligible_for_reproduction -ne $true) {
        throw "$($references.first.classification): first sequence is not eligible for reproduction."
    }
    $references.second = Invoke-Sequence -Number 2
    if ($references.second.eligible_for_reproduction -ne $true) {
        throw "$($references.second.classification): second sequence is not eligible for reproduction."
    }
    & uv run --frozen python $comparisonTool `
        --kind $Kind `
        --first-reference ([string]$references.first.reference_path) `
        --second-reference ([string]$references.second.reference_path) `
        --output (Join-Path $evidenceDirectory "reproduction.json")
    if ($LASTEXITCODE -ne 0) {
        throw "DESIGN_REJECTED: two-sequence reproduction verification failed."
    }
}
catch {
    $failureReason = $_.Exception.Message
    $lastReference = @($references.Values) | Select-Object -Last 1
    if ($null -ne $lastReference -and $lastReference.classification -in @(
        "DESIGN_REJECTED", "INFRA_ABORTED"
    )) {
        $classification = [string]$lastReference.classification
    }
    elseif ($failureReason.StartsWith("INFRA_ABORTED", [StringComparison]::Ordinal)) {
        $classification = "INFRA_ABORTED"
    }
    else {
        $classification = "DESIGN_REJECTED"
    }
    Write-NewJson -Path (Join-Path $evidenceDirectory "reproduction-failure.json") -Value ([ordered]@{
        schema_version = "cybercontrol.gate-c-rss-calibration-reproduction-failure.v1"
        process_version = $processVersion
        classification = $classification
        formal_gate_attempt = $false
        acceptance_claim = $false
        reproduction_id = $reproductionId
        kind = $Kind
        variable = if ($Kind -eq "calibration") { $Variable } else { $null }
        reason = $failureReason
        failed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    })
}

Write-NewJson -Path (Join-Path $evidenceDirectory "sequence-index.json") -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-rss-calibration-reproduction-index.v1"
    process_version = $processVersion
    reproduction_id = $reproductionId
    sequences = $references
})
$summarySource = if ($null -eq $failureReason) {
    Join-Path $evidenceDirectory "reproduction.json"
}
else {
    Join-Path $evidenceDirectory "reproduction-failure.json"
}
Copy-Item -LiteralPath $summarySource -Destination $runSummaryPath
& uv run --frozen python $packageTool `
    --evidence-directory $evidenceDirectory `
    --package $packagePath `
    --manifest $manifestPath `
    --run-id $reproductionId `
    --process-version $processVersion
if ($LASTEXITCODE -ne 0) {
    throw "Reproduction evidence package creation or verification failed."
}
$resolvedEvidence = [IO.Path]::GetFullPath($evidenceDirectory)
$resolvedReproduction = [IO.Path]::GetFullPath($reproductionDirectory).TrimEnd('\') + '\'
if (-not $resolvedEvidence.StartsWith($resolvedReproduction, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove reproduction intermediates outside the run directory."
}
Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
Write-NewJson -Path $cleanupReceiptPath -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-rss-calibration-reproduction-cleanup.v1"
    process_version = $processVersion
    reproduction_id = $reproductionId
    archived_intermediates_removed = (-not (Test-Path -LiteralPath $resolvedEvidence))
    completed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
})
Write-NewJson -Path $packageReferencePath -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-diagnostic-package-reference.v1"
    process_version = $processVersion
    classification = $classification
    formal_gate_attempt = $false
    acceptance_claim = $false
    run_id = $reproductionId
    evidence_package = [ordered]@{
        path = $packagePath
        size_bytes = (Get-Item -LiteralPath $packagePath).Length
        sha256 = Get-FileSha256 $packagePath
    }
    evidence_manifest = [ordered]@{
        path = $manifestPath
        sha256 = Get-FileSha256 $manifestPath
    }
    cleanup_receipt = [ordered]@{
        path = $cleanupReceiptPath
        sha256 = Get-FileSha256 $cleanupReceiptPath
    }
    run_summary = [ordered]@{
        path = $runSummaryPath
        sha256 = Get-FileSha256 $runSummaryPath
    }
})

if ($null -ne $failureReason) {
    Write-Output $packageReferencePath
    throw "$classification`: $failureReason; immutable reproduction evidence: $packageReferencePath"
}
Write-Output $packageReferencePath
