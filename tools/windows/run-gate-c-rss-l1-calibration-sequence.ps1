[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ImageLockPath,

    [string]$ResultsRoot = "D:\CyberControlAcceptance\phase7\gate-c\diagnostics\adr0032-l1"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$armRunner = Join-Path $PSScriptRoot "run-gate-c-rss-l1-calibration-arm.ps1"
$comparisonTool = Join-Path $root "tests\load\gate_c\rss_l1_calibration_compare.py"
$packageTool = Join-Path $root "tests\load\gate_c\diagnostic_evidence_package.py"
$processVersion = "Gate-C-12-v1.0"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$sequenceId = "adr0032-l1-sequence-$timestamp-$suffix"
$sequenceDirectory = [IO.Path]::GetFullPath((Join-Path $ResultsRoot $sequenceId))
$armResultsRoot = Join-Path $sequenceDirectory "arms"
$evidenceDirectory = Join-Path $sequenceDirectory "evidence"
$packagePath = Join-Path $sequenceDirectory "evidence.zip"
$manifestPath = Join-Path $sequenceDirectory "evidence-manifest.json"
$runSummaryPath = Join-Path $sequenceDirectory "run-summary.json"
$cleanupReceiptPath = Join-Path $sequenceDirectory "cleanup-receipt.json"
$packageReferencePath = Join-Path $sequenceDirectory "package-reference.json"
$failureReason = $null
$classification = "NON_ACCEPTANCE_DIAGNOSTIC"
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

function Invoke-Arm {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("A", "Measurement", "APrime")]
        [string]$Arm,
        [string]$PriorArmResult
    )
    $stdout = Join-Path $evidenceDirectory "$($Arm.ToLowerInvariant()).stdout.log"
    $stderr = Join-Path $evidenceDirectory "$($Arm.ToLowerInvariant()).stderr.log"
    $arguments = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $armRunner,
        "-Arm", $Arm,
        "-ImageLockPath", [IO.Path]::GetFullPath($ImageLockPath),
        "-ResultsRoot", $armResultsRoot
    )
    if (-not [string]::IsNullOrWhiteSpace($PriorArmResult)) {
        $arguments += @("-PriorArmResult", $PriorArmResult)
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
        throw "$childClassification`: $Arm L1 arm did not return an immutable package reference."
    }
    $reference = Get-Content -LiteralPath $referencePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $summaryPath = [string]$reference.run_summary.path
    if (
        $reference.schema_version -ne "cybercontrol.gate-c-diagnostic-package-reference.v1" -or
        $reference.process_version -ne $processVersion -or
        $reference.classification -notin @(
            "NON_ACCEPTANCE_DIAGNOSTIC", "DESIGN_REJECTED", "INFRA_ABORTED"
        ) -or
        $reference.formal_gate_attempt -ne $false -or
        $reference.acceptance_claim -ne $false -or
        $reference.arm -ne $Arm -or
        -not (Test-Path -LiteralPath $summaryPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath ([string]$reference.evidence_package.path) -PathType Leaf) -or
        -not (Test-Path -LiteralPath ([string]$reference.evidence_manifest.path) -PathType Leaf) -or
        $reference.run_summary.sha256 -ne (Get-FileSha256 $summaryPath) -or
        $reference.evidence_package.sha256 -ne
            (Get-FileSha256 ([string]$reference.evidence_package.path)) -or
        $reference.evidence_manifest.sha256 -ne
            (Get-FileSha256 ([string]$reference.evidence_manifest.path)) -or
        $reference.cleanup_receipt.sha256 -ne
            (Get-FileSha256 ([string]$reference.cleanup_receipt.path))
    ) {
        throw "$Arm L1 package reference failed verification."
    }
    $summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $eligibleForContinuation = (
        $process.ExitCode -eq 0 -and
        $reference.classification -eq "NON_ACCEPTANCE_DIAGNOSTIC" -and
        $summary.arm -eq $Arm -and
        $summary.passed -eq $true
    )
    return [ordered]@{
        reference_path = $referencePath
        reference_sha256 = Get-FileSha256 $referencePath
        run_id = [string]$reference.run_id
        classification = [string]$reference.classification
        process_exit_code = $process.ExitCode
        eligible_for_continuation = $eligibleForContinuation
        failure_reason = if ($eligibleForContinuation) { $null } else { [string]$summary.reason }
        summary_path = $summaryPath
        summary_sha256 = [string]$reference.run_summary.sha256
        package_sha256 = [string]$reference.evidence_package.sha256
        cleanup_receipt_path = [string]$reference.cleanup_receipt.path
        cleanup_receipt_sha256 = [string]$reference.cleanup_receipt.sha256
        source = $reference.source
    }
}

function Assert-ArmContinuation {
    param(
        [Parameter(Mandatory = $true)][string]$Arm,
        [Parameter(Mandatory = $true)]$Reference
    )
    if ($Reference.eligible_for_continuation -ne $true) {
        throw "$Arm L1 arm is not eligible for continuation; A' is prohibited after an A or Measurement failure."
    }
}

if (Test-Path -LiteralPath $sequenceDirectory) {
    throw "INFRA_ABORTED: immutable L1 sequence directory already exists: $sequenceDirectory"
}
New-Item -ItemType Directory -Path $armResultsRoot, $evidenceDirectory -Force | Out-Null
Write-NewJson -Path (Join-Path $evidenceDirectory "sequence-metadata.json") -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-rss-l1-calibration-sequence.v1"
    process_version = $processVersion
    classification = "NON_ACCEPTANCE_DIAGNOSTIC"
    formal_gate_attempt = $false
    acceptance_claim = $false
    sequence_id = $sequenceId
    arm_order = @("A", "Measurement", "APrime")
    started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
})

try {
    $references.A = Invoke-Arm -Arm "A"
    Assert-ArmContinuation -Arm "A" -Reference $references.A
    $references.Measurement = Invoke-Arm `
        -Arm "Measurement" `
        -PriorArmResult ([string]$references.A.summary_path)
    Assert-ArmContinuation -Arm "Measurement" -Reference $references.Measurement
    $references.APrime = Invoke-Arm `
        -Arm "APrime" `
        -PriorArmResult ([string]$references.Measurement.summary_path)
    Assert-ArmContinuation -Arm "APrime" -Reference $references.APrime
    & uv run --frozen python $comparisonTool compare `
        --a ([string]$references.A.summary_path) `
        --measurement ([string]$references.Measurement.summary_path) `
        --a-prime ([string]$references.APrime.summary_path) `
        --output (Join-Path $evidenceDirectory "comparison.json")
    if ($LASTEXITCODE -ne 0) {
        throw "The L1 A/M/A' sequence failed the ADR-0032 interference gate."
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
    Write-NewJson -Path (Join-Path $evidenceDirectory "sequence-failure.json") -Value ([ordered]@{
        schema_version = "cybercontrol.gate-c-rss-l1-sequence-failure.v1"
        process_version = $processVersion
        classification = $classification
        formal_gate_attempt = $false
        acceptance_claim = $false
        sequence_id = $sequenceId
        reason = $failureReason
        failed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    })
}

Write-NewJson -Path (Join-Path $evidenceDirectory "arm-package-index.json") -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-rss-l1-arm-package-index.v1"
    process_version = $processVersion
    sequence_id = $sequenceId
    arms = $references
})
$summarySource = if ($null -eq $failureReason) {
    Join-Path $evidenceDirectory "comparison.json"
}
else {
    Join-Path $evidenceDirectory "sequence-failure.json"
}
Copy-Item -LiteralPath $summarySource -Destination $runSummaryPath
& uv run --frozen python $packageTool `
    --evidence-directory $evidenceDirectory `
    --package $packagePath `
    --manifest $manifestPath `
    --run-id $sequenceId
if ($LASTEXITCODE -ne 0) {
    throw "L1 sequence evidence package creation or verification failed."
}
$resolvedEvidence = [IO.Path]::GetFullPath($evidenceDirectory)
$resolvedSequence = [IO.Path]::GetFullPath($sequenceDirectory).TrimEnd('\') + '\'
if (-not $resolvedEvidence.StartsWith($resolvedSequence, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove L1 sequence intermediates outside the sequence directory."
}
Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
Write-NewJson -Path $cleanupReceiptPath -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-rss-l1-sequence-cleanup.v1"
    process_version = $processVersion
    sequence_id = $sequenceId
    archived_intermediates_removed = (-not (Test-Path -LiteralPath $resolvedEvidence))
    completed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
})
Write-NewJson -Path $packageReferencePath -Value ([ordered]@{
    schema_version = "cybercontrol.gate-c-diagnostic-package-reference.v1"
    process_version = $processVersion
    classification = $classification
    formal_gate_attempt = $false
    acceptance_claim = $false
    run_id = $sequenceId
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
    throw "$failureReason; immutable L1 sequence evidence: $packageReferencePath"
}
Write-Output $packageReferencePath
