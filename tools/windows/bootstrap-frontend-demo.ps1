[CmdletBinding()]
param(
    [ValidatePattern('^https?://')]
    [string]$ApiBaseUrl = "http://localhost:8000",

    [ValidatePattern('^https?://')]
    [string]$KeycloakBaseUrl = "http://localhost:8080",

    [string]$Realm = "cybercontrol",

    [string]$ClientId = "cybercontrol-cli",

    [string]$CourseId = "CRS_ATC_001",

    [string]$LearnerUsername = "learner",

    [string]$LearnerPassword = "learner-local-only",

    [string]$ReviewerUsername = "reviewer",

    [string]$ReviewerPassword = "reviewer-local-only",

    [Guid]$GenerationSessionId = [Guid]"f6fe2a67-e592-43b4-baf0-8866e0da40eb",

    [Guid]$GenerationOperationId = [Guid]"9f255e6e-f47a-448a-804d-133e7794f80b",

    [ValidateRange(0, 120)]
    [int]$VerificationWaitSeconds = 30,

    [switch]$SkipGeneration
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$api = $ApiBaseUrl.TrimEnd('/')
$keycloak = $KeycloakBaseUrl.TrimEnd('/')
$courseDataPath = Join-Path $PSScriptRoot "..\..\data\topic1\automatic-control-principles.v1.json"

function Get-AccessToken {
    param(
        [Parameter(Mandatory = $true)][string]$Username,
        [Parameter(Mandatory = $true)][string]$Password
    )

    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$keycloak/realms/$Realm/protocol/openid-connect/token" `
        -ContentType "application/x-www-form-urlencoded" `
        -Body @{
            grant_type = "password"
            client_id = $ClientId
            username = $Username
            password = $Password
            scope = "openid profile email"
        } `
        -TimeoutSec 30
    if ([string]::IsNullOrWhiteSpace($response.access_token)) {
        throw "Keycloak did not issue an access token for $Username."
    }
    return [string]$response.access_token
}

function Get-JwtClaims {
    param([Parameter(Mandatory = $true)][string]$Token)

    $payload = $Token.Split('.')[1].Replace('-', '+').Replace('_', '/')
    switch ($payload.Length % 4) {
        1 { $payload += '===' }
        2 { $payload += '==' }
        3 { $payload += '=' }
    }
    $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload))
    return $json | ConvertFrom-Json
}

function Get-StatusCode {
    param([Parameter(Mandatory = $true)]$ErrorRecord)

    $status = $ErrorRecord.Exception.Response.StatusCode
    if ($null -eq $status) {
        return $null
    }
    return [int]$status
}

function Invoke-OptionalGet {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][hashtable]$Headers
    )

    try {
        return Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 30
    }
    catch {
        if ((Get-StatusCode $_) -eq 404) {
            return $null
        }
        throw
    }
}

function Convert-GuidToNetworkBytes {
    param([Parameter(Mandatory = $true)][Guid]$Value)

    $bytes = $Value.ToByteArray()
    [Array]::Reverse($bytes, 0, 4)
    [Array]::Reverse($bytes, 4, 2)
    [Array]::Reverse($bytes, 6, 2)
    return $bytes
}

function Convert-NetworkBytesToGuid {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    $copy = [byte[]]$Bytes.Clone()
    [Array]::Reverse($copy, 0, 4)
    [Array]::Reverse($copy, 4, 2)
    [Array]::Reverse($copy, 6, 2)
    return [Guid]::new($copy)
}

function New-UuidV5 {
    param(
        [Parameter(Mandatory = $true)][Guid]$Namespace,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $namespaceBytes = Convert-GuidToNetworkBytes $Namespace
    $nameBytes = [Text.Encoding]::UTF8.GetBytes($Name)
    $input = New-Object byte[] ($namespaceBytes.Length + $nameBytes.Length)
    [Array]::Copy($namespaceBytes, 0, $input, 0, $namespaceBytes.Length)
    [Array]::Copy($nameBytes, 0, $input, $namespaceBytes.Length, $nameBytes.Length)
    $sha1 = [Security.Cryptography.SHA1]::Create()
    try {
        $hash = $sha1.ComputeHash($input)
    }
    finally {
        $sha1.Dispose()
    }
    $uuidBytes = New-Object byte[] 16
    [Array]::Copy($hash, 0, $uuidBytes, 0, 16)
    $uuidBytes[6] = ($uuidBytes[6] -band 0x0f) -bor 0x50
    $uuidBytes[8] = ($uuidBytes[8] -band 0x3f) -bor 0x80
    return Convert-NetworkBytesToGuid $uuidBytes
}

function New-OperationHeaders {
    param(
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$IdempotencyKey
    )

    return @{
        Authorization = "Bearer $Token"
        "Idempotency-Key" = $IdempotencyKey
    }
}

$learnerToken = Get-AccessToken -Username $LearnerUsername -Password $LearnerPassword
$reviewerToken = Get-AccessToken -Username $ReviewerUsername -Password $ReviewerPassword
$learnerClaims = Get-JwtClaims $learnerToken
$learnerRef = [string]$learnerClaims.sub
if ([string]::IsNullOrWhiteSpace($learnerRef) -or $learnerClaims.tenant_id -ne "demo-academy") {
    throw "The local learner token is not bound to the demo-academy tenant."
}

$learnerReadHeaders = @{ Authorization = "Bearer $learnerToken" }
$reviewerReadHeaders = @{ Authorization = "Bearer $reviewerToken" }
$courses = Invoke-RestMethod -Method Get -Uri "$api/internal/topic1/courses" -Headers $learnerReadHeaders -TimeoutSec 30
$course = @($courses.data.courses) | Where-Object { $_.course_id -eq $CourseId } | Select-Object -First 1
if ($null -eq $course) {
    $bundle = Get-Content -LiteralPath $courseDataPath -Raw -Encoding UTF8
    $importHeaders = New-OperationHeaders -Token $reviewerToken -IdempotencyKey "frontend-demo-topic1-import-v1"
    Invoke-RestMethod `
        -Method Post `
        -Uri "$api/internal/topic1/imports" `
        -Headers $importHeaders `
        -ContentType "application/json; charset=utf-8" `
        -Body $bundle `
        -TimeoutSec 60 | Out-Null
}

$encodedLearner = [Uri]::EscapeDataString($learnerRef)
$profileUri = "$api/internal/topic2/learners/$encodedLearner/courses/$CourseId/profiles/latest"
$profile = Invoke-OptionalGet -Uri $profileUri -Headers $learnerReadHeaders
if ($null -eq $profile) {
    $initializeBody = @{
        schema_version = "topic2.operation-command.v1"
        operation_id = "8f049b7f-5e6f-4e0c-b2be-9d4cd9c8cc11"
        requested_at = "2026-07-19T00:00:00Z"
    } | ConvertTo-Json
    $initializeHeaders = New-OperationHeaders -Token $learnerToken -IdempotencyKey "frontend-demo-topic2-initialize-v1"
    Invoke-RestMethod `
        -Method Post `
        -Uri "$api/internal/topic2/learners/$encodedLearner/courses/$CourseId/initialize" `
        -Headers $initializeHeaders `
        -ContentType "application/json; charset=utf-8" `
        -Body $initializeBody `
        -TimeoutSec 60 | Out-Null
}

$pathUri = "$api/internal/topic2/learners/$encodedLearner/courses/$CourseId/paths/latest"
$learningPath = Invoke-OptionalGet -Uri $pathUri -Headers $learnerReadHeaders
if ($null -eq $learningPath) {
    $pathBody = @{
        schema_version = "topic2.path-generate-command.v1"
        operation_id = "6d8b0e9e-fc76-42be-8d8f-1f15c6f2a2a4"
        requested_at = "2026-07-19T00:00:00Z"
        target_goal = "Master automatic control fundamentals through evidence-bound practice."
        target_kp_ids = @()
        manual_order = @()
        change_type = "MANUAL_OVERRIDE"
        trigger_reason = "frontend-demo-bootstrap"
    } | ConvertTo-Json -Depth 6
    $pathHeaders = New-OperationHeaders -Token $learnerToken -IdempotencyKey "frontend-demo-topic2-path-v1"
    Invoke-RestMethod `
        -Method Post `
        -Uri "$api/internal/topic2/learners/$encodedLearner/courses/$CourseId/paths/generate" `
        -Headers $pathHeaders `
        -ContentType "application/json; charset=utf-8" `
        -Body $pathBody `
        -TimeoutSec 60 | Out-Null
}

$candidateResults = @()
if (-not $SkipGeneration) {
    $graph = Invoke-RestMethod -Method Get -Uri "$api/internal/topic1/courses/$CourseId/graph" -Headers $learnerReadHeaders -TimeoutSec 30
    $targetKpId = [string](@($graph.data.graph.knowledge_points)[0].kp_id)
    if ([string]::IsNullOrWhiteSpace($targetKpId)) {
        throw "The imported Topic1 graph has no active knowledge point."
    }
    $generationBody = @{
        schema_version = "topic3.generation-command.v1"
        operation_id = $GenerationOperationId.ToString()
        generation_session_id = $GenerationSessionId.ToString()
        learner_ref = $learnerRef
        course_id = $CourseId
        target_kp_ids = @($targetKpId)
        requested_resources = @(
            "Lecturer_Doc",
            "MindMap",
            "Gradient_Quiz",
            "Simulation_Code",
            "Extension_Material"
        )
        lecturer_depth = "ENGINEERING"
        learning_goal = "Demonstrate a locally grounded multi-agent learning workflow."
        locale = "zh-CN"
        max_parallelism = 1
        allow_partial = $false
        requested_at = "2026-07-19T00:00:00Z"
    } | ConvertTo-Json -Depth 8
    $generationHeaders = New-OperationHeaders -Token $learnerToken -IdempotencyKey "frontend-demo-topic3-generation-v4"
    Invoke-RestMethod `
        -Method Post `
        -Uri "$api/internal/topic3/generations" `
        -Headers $generationHeaders `
        -ContentType "application/json; charset=utf-8" `
        -Body $generationBody `
        -TimeoutSec 60 | Out-Null

    $terminalStates = @("COMPLETED", "PARTIAL", "FAILED", "CANCELLED")
    $generation = $null
    foreach ($attempt in 1..60) {
        Start-Sleep -Seconds 2
        $generation = Invoke-RestMethod `
            -Method Get `
            -Uri "$api/internal/topic3/generations/$GenerationSessionId" `
            -Headers $learnerReadHeaders `
            -TimeoutSec 30
        if ($generation.payload.session.state -in $terminalStates) {
            break
        }
    }
    if ($null -eq $generation -or $generation.payload.session.state -ne "COMPLETED") {
        throw "The local fixture generation did not complete successfully."
    }

    foreach ($candidate in @($generation.payload.candidates)) {
        $verificationName = "topic4-verification:$($candidate.candidate_version):$($candidate.candidate_sha256)"
        $verificationId = New-UuidV5 -Namespace ([Guid]$candidate.candidate_id) -Name $verificationName
        $candidateResults += [pscustomobject]@{
            resource_type = $candidate.resource_type
            candidate_id = $candidate.candidate_id
            candidate_sha256 = $candidate.candidate_sha256
            verification_id = $verificationId.ToString()
            verification_state = "PENDING_OUTBOX"
        }
    }

    if ($VerificationWaitSeconds -gt 0) {
        foreach ($attempt in 1..$VerificationWaitSeconds) {
            $pending = @($candidateResults | Where-Object { $_.verification_state -eq "PENDING_OUTBOX" })
            if (-not $pending) {
                break
            }
            foreach ($candidateResult in $pending) {
                $verification = Invoke-OptionalGet `
                    -Uri "$api/internal/topic4/verifications/$($candidateResult.verification_id)" `
                    -Headers $learnerReadHeaders
                if ($null -ne $verification) {
                    $candidateResult.verification_state = $verification.payload.state.current_state
                }
            }
            if ($attempt -lt $VerificationWaitSeconds) {
                Start-Sleep -Seconds 1
            }
        }
    }
}

[pscustomobject]@{
    tenant_id = [string]$learnerClaims.tenant_id
    learner_ref = $learnerRef
    course_id = $CourseId
    generation_session_id = if ($SkipGeneration) { $null } else { $GenerationSessionId.ToString() }
    candidates = $candidateResults
} | ConvertTo-Json -Depth 8
