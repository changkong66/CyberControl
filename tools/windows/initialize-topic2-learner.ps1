[CmdletBinding()]
param(
    [ValidatePattern('^https?://')]
    [string]$BaseUrl = "http://127.0.0.1:8000",

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9:_-]{3,256}$')]
    [string]$LearnerRef,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]{3,64}$')]
    [string]$CourseId,

    [Guid]$OperationId = [Guid]::NewGuid(),

    [datetime]$RequestedAt = [datetime]::UtcNow,

    [string]$AccessToken = $env:LIYAN_ACCESS_TOKEN
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($AccessToken)) {
    throw "Set LIYAN_ACCESS_TOKEN or pass -AccessToken with a trusted OIDC access token."
}

$normalizedBaseUrl = $BaseUrl.TrimEnd('/')
$uri = (
    "$normalizedBaseUrl/internal/topic2/learners/" +
    "$([uri]::EscapeDataString($LearnerRef))/courses/" +
    "$([uri]::EscapeDataString($CourseId))/initialize"
)
$idempotencyKey = "topic2-seed-$($OperationId.ToString('N'))"
$headers = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = $idempotencyKey
}
$body = @{
    schema_version = "topic2.operation-command.v1"
    operation_id = $OperationId.ToString()
    requested_at = $RequestedAt.ToUniversalTime().ToString("o")
} | ConvertTo-Json

$response = Invoke-RestMethod `
    -Method Post `
    -Uri $uri `
    -Headers $headers `
    -ContentType "application/json; charset=utf-8" `
    -Body $body `
    -TimeoutSec 60

if ($response.schema_version -ne "topic3.envelope.v1") {
    throw "Topic 2 initialization returned an unexpected response contract."
}

$response
