# Topic4 PowerShell API Examples

## 1. Environment

```powershell
# Use an OIDC access token issued for the required Topic4 scopes.
$BaseUrl = "http://localhost:8000"
$Token = $env:LIYAN_ACCESS_TOKEN
$Headers = @{
    Authorization = "Bearer $Token"
    "Content-Type" = "application/json"
}
```

Do not place tokens, tenant IDs, or private Candidate payloads in tracked files.
Tenant identity is derived from the token and is not supplied by a client
header.

## 2. Health

```powershell
Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/internal/topic4/health" `
    -Headers $Headers
```

## 3. Query a Verification

```powershell
$VerificationId = "00000000-0000-0000-0000-000000000000"

Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/internal/topic4/verifications/$VerificationId" `
    -Headers $Headers

Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/internal/topic4/verifications/$VerificationId/report" `
    -Headers $Headers
```

## 4. Query Claims and Evidence

```powershell
$Claims = Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/internal/topic4/verifications/$VerificationId/claims" `
    -Headers $Headers

$ClaimId = $Claims.payload.claims[0].claim_id
Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/internal/topic4/claims/$ClaimId/evidence" `
    -Headers $Headers
```

## 5. Trace Query

```powershell
$TraceId = "replace-with-an-authenticated-trace-id"
Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/internal/topic4/traces/$TraceId?limit=500" `
    -Headers $Headers
```

## 6. SSE Replay

```powershell
Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/internal/topic4/sse/replay?after_sequence=-1" `
    -Headers $Headers
```

Live SSE clients should send the last signed cursor in `Last-Event-ID` after a
disconnect. The cursor is tenant bound and cannot be replayed for another
tenant.
