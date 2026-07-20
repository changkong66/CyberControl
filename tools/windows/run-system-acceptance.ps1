[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,62}$')]
    [string]$ProjectName = "cybercontrol-acceptance",

    [switch]$ResetVolumes,

    [switch]$SkipBuild,

    [switch]$RequireCleanSource,

    [switch]$UseReleasePostgresVolume,

    [ValidatePattern('^https?://')]
    [string]$ApiBaseUrl = "http://localhost:8000",

    [ValidatePattern('^https?://')]
    [string]$FrontendBaseUrl = "http://localhost:5173",

    [ValidatePattern('^https?://')]
    [string]$KeycloakBaseUrl = "http://localhost:8080",

    [string]$EvidencePath = "docs/system-acceptance/evidence/release-eligible.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$composeFile = Join-Path $root "infra\docker-compose.yml"
$releaseComposeFile = Join-Path $root "infra\docker-compose.release.yml"
$composeArguments = @("-p", $ProjectName, "-f", $composeFile)
if ($UseReleasePostgresVolume) {
    $composeArguments += @("-f", $releaseComposeFile)
}
$knowledgeScript = Join-Path $root "tools\topic4\bootstrap-release-eligible-knowledge.py"
$sseVerifier = Join-Path $root "tools\topic4\verify-authenticated-sse.py"
$bootstrapScript = Join-Path $root "tools\windows\bootstrap-frontend-demo.ps1"
$evidenceFile = if ([IO.Path]::IsPathRooted($EvidencePath)) {
    $EvidencePath
}
else {
    Join-Path $root $EvidencePath
}
$api = $ApiBaseUrl.TrimEnd('/')
$frontend = $FrontendBaseUrl.TrimEnd('/')
$keycloak = $KeycloakBaseUrl.TrimEnd('/')

function Invoke-DockerCompose {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & docker compose @composeArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)

    $normalized = $Text.Replace("`r`n", "`n")
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($normalized)
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
    }
}

function Get-AccessToken {
    param(
        [Parameter(Mandatory = $true)][string]$Username,
        [Parameter(Mandatory = $true)][string]$Password
    )

    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$keycloak/realms/cybercontrol/protocol/openid-connect/token" `
        -ContentType "application/x-www-form-urlencoded" `
        -Body @{
            grant_type = "password"
            client_id = "cybercontrol-cli"
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
    while (($payload.Length % 4) -ne 0) {
        $payload += '='
    }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) |
        ConvertFrom-Json
}

function Invoke-Api {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Token,
        [object]$Body,
        [string]$IdempotencyKey
    )

    $headers = @{ Authorization = "Bearer $Token" }
    if (-not [string]::IsNullOrWhiteSpace($IdempotencyKey)) {
        $headers["Idempotency-Key"] = $IdempotencyKey
    }
    $arguments = @{
        Method = $Method
        Uri = $Uri
        Headers = $headers
        TimeoutSec = 60
    }
    if ($null -ne $Body) {
        $arguments["ContentType"] = "application/json; charset=utf-8"
        $arguments["Body"] = $Body | ConvertTo-Json -Depth 40 -Compress
    }
    return Invoke-RestMethod @arguments
}

function Get-HttpStatusCode {
    param([Parameter(Mandatory = $true)]$ErrorRecord)

    $status = $ErrorRecord.Exception.Response.StatusCode
    if ($null -eq $status) {
        return $null
    }
    return [int]$status
}

function Invoke-Psql {
    param([Parameter(Mandatory = $true)][string]$Sql)

    $output = & docker exec $script:postgresContainer `
        psql -v ON_ERROR_STOP=1 -U liyans_bootstrap -d liyans -At -F '|' -c $Sql
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL acceptance query failed."
    }
    return ($output | Out-String).Trim()
}

function Wait-HttpReady {
    $deadline = (Get-Date).AddMinutes(5)
    do {
        try {
            $apiReady = Invoke-RestMethod -Uri "$api/health/ready" -TimeoutSec 5
            $frontendReady = Invoke-RestMethod -Uri "$frontend/healthz" -TimeoutSec 5
            $oidcReady = Invoke-RestMethod `
                -Uri "$keycloak/realms/cybercontrol/.well-known/openid-configuration" `
                -TimeoutSec 5
            if (
                $apiReady.status -eq "ready" -and
                $frontendReady.status -eq "live" -and
                -not [string]::IsNullOrWhiteSpace($oidcReady.jwks_uri)
            ) {
                return [ordered]@{
                    api = $apiReady
                    frontend = $frontendReady
                    oidc_issuer = $oidcReady.issuer
                }
            }
        }
        catch {
            Start-Sleep -Seconds 3
            continue
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    Invoke-DockerCompose -Arguments @("ps", "-a")
    throw "The clean acceptance stack did not become ready within five minutes."
}

function Assert-ModuleResults {
    param([Parameter(Mandatory = $true)]$Snapshot)

    $results = @($Snapshot.module_results)
    if (-not $results) {
        throw "Topic4 returned no module results."
    }
    $invalid = @(
        $results |
            Where-Object {
                $_.verdict -notin @("SUPPORTED", "NOT_APPLICABLE") -or
                ($_.module -eq "C11_COMPLIANCE" -and $_.verdict -ne "NOT_APPLICABLE") -or
                ($_.module -ne "C11_COMPLIANCE" -and $_.verdict -ne "SUPPORTED")
            }
    )
    if ($invalid) {
        throw "Topic4 contains non-release-eligible module verdicts: $($invalid | ConvertTo-Json -Depth 8 -Compress)"
    }
    return @(
        $results |
            Group-Object module, verdict |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    module = [string]$_.Group[0].module
                    verdict = [string]$_.Group[0].verdict
                    count = $_.Count
                }
            }
    )
}

Push-Location $root
try {
    $sourceBranch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sourceBranch)) {
        throw "System acceptance requires a named Git branch. Detached HEAD is not eligible."
    }
    $sourceCommit = (& git rev-parse --verify HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^[0-9a-f]{40}$') {
        throw "Unable to resolve the immutable source commit for system acceptance."
    }
    $sourceTree = (& git show -s --format=%T HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $sourceTree -notmatch '^[0-9a-f]{40}$') {
        throw "Unable to resolve the immutable source tree for system acceptance."
    }
    $sourceStatus = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the source worktree before system acceptance."
    }
    $sourceClean = $sourceStatus.Count -eq 0
    if ($RequireCleanSource -and -not $sourceClean) {
        $dirtySummary = ($sourceStatus | Select-Object -First 20) -join '; '
        throw (
            "System acceptance requires an immutable clean source tree. " +
            "Commit or remove all tracked and untracked changes first. " +
            "Detected: $dirtySummary"
        )
    }

    if ($UseReleasePostgresVolume) {
        if ($ResetVolumes) {
            throw "ResetVolumes cannot be used with the protected external release PostgreSQL volume."
        }
        $releaseVolume = @(& docker volume inspect cybercontrol_release_postgres | ConvertFrom-Json)
        if ($LASTEXITCODE -ne 0 -or $releaseVolume.Count -ne 1) {
            throw "The external cybercontrol_release_postgres volume is unavailable."
        }
        $purpose = $releaseVolume[0].Labels.'com.cybercontrol.purpose'
        $dataClass = $releaseVolume[0].Labels.'com.cybercontrol.data-class'
        if ($purpose -ne "release-acceptance" -or $dataClass -ne "isolated-clean-postgres") {
            throw "The external release PostgreSQL volume labels do not match the acceptance policy."
        }
    }

    $composeConfig = (& docker compose @composeArguments config | Out-String)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($composeConfig)) {
        throw "Unable to resolve the Docker Compose configuration for system acceptance."
    }
    $composeConfigSha256 = Get-TextSha256 -Text $composeConfig
    $uvLockSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root "uv.lock")).Hash.ToLowerInvariant()
    $pnpmLockSha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root "frontend\pnpm-lock.yaml")
    ).Hash.ToLowerInvariant()

    $existingVolumes = @(
        & docker volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Docker volumes."
    }
    if ($existingVolumes -and -not $ResetVolumes) {
        throw "Compose project $ProjectName already has volumes. Re-run with -ResetVolumes for a clean acceptance dataset."
    }
    if ($ResetVolumes) {
        Invoke-DockerCompose -Arguments @("down", "--volumes", "--remove-orphans")
    }
    else {
        Invoke-DockerCompose -Arguments @("down", "--remove-orphans")
    }
    if (-not $SkipBuild) {
        foreach ($service in @("migrate", "api", "mock-provider", "frontend")) {
            Invoke-DockerCompose -Arguments @("build", $service)
        }
    }
    Invoke-DockerCompose -Arguments @("up", "--no-build", "-d")
    $readiness = Wait-HttpReady

    $script:postgresContainer = (& docker compose @composeArguments ps -q postgres).Trim()
    $apiContainer = (& docker compose @composeArguments ps -q api).Trim()
    $frontendContainer = (& docker compose @composeArguments ps -q frontend).Trim()
    $providerContainer = (& docker compose @composeArguments ps -q mock-provider).Trim()
    if (
        [string]::IsNullOrWhiteSpace($script:postgresContainer) -or
        [string]::IsNullOrWhiteSpace($apiContainer) -or
        [string]::IsNullOrWhiteSpace($frontendContainer) -or
        [string]::IsNullOrWhiteSpace($providerContainer)
    ) {
        throw "Compose did not return all required PostgreSQL, API, frontend, and Provider container IDs."
    }
    $postgresMounts = @((docker inspect $script:postgresContainer | ConvertFrom-Json)[0].Mounts)
    $postgresDataMount = @(
        $postgresMounts | Where-Object { $_.Destination -eq "/var/lib/postgresql/data" }
    )
    if ($postgresDataMount.Count -ne 1) {
        throw "PostgreSQL must have exactly one persistent data mount."
    }
    if (
        $UseReleasePostgresVolume -and
        $postgresDataMount[0].Name -ne "cybercontrol_release_postgres"
    ) {
        throw "PostgreSQL is not mounted to the isolated release acceptance volume."
    }
    $runtimeImageIds = [ordered]@{
        backend = (& docker inspect --format "{{.Image}}" $apiContainer).Trim()
        frontend = (& docker inspect --format "{{.Image}}" $frontendContainer).Trim()
        mock_provider = (& docker inspect --format "{{.Image}}" $providerContainer).Trim()
    }
    if ($LASTEXITCODE -ne 0 -or @($runtimeImageIds.Values | Where-Object { $_ -notmatch '^sha256:[0-9a-f]{64}$' }).Count -gt 0) {
        throw "Unable to resolve immutable runtime image IDs for system acceptance."
    }

    $migrationHead = Invoke-Psql -Sql "select version_num from alembic_version;"
    if ($migrationHead -ne "20260716_0009") {
        throw "Unexpected Alembic head: $migrationHead"
    }
    $initialCounts = Invoke-Psql -Sql (
        "select (select count(*) from topic1_courses)," +
        "(select count(*) from topic2_student_profiles)," +
        "(select count(*) from topic3_generated_candidates)," +
        "(select count(*) from topic4_verifications);"
    )
    if ($initialCounts -ne "0|0|0|0") {
        throw "The acceptance PostgreSQL volume is not business-data clean: $initialCounts"
    }

    $bootstrapRaw = & $bootstrapScript `
        -ApiBaseUrl $api `
        -KeycloakBaseUrl $keycloak `
        -SkipGeneration |
        Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Topic1/Topic2 API bootstrap failed."
    }
    $bootstrap = $bootstrapRaw | ConvertFrom-Json

    $learnerToken = Get-AccessToken -Username "learner" -Password "learner-local-only"
    $reviewerToken = Get-AccessToken -Username "reviewer" -Password "reviewer-local-only"
    $learnerClaims = Get-JwtClaims -Token $learnerToken
    $reviewerClaims = Get-JwtClaims -Token $reviewerToken
    if (
        $learnerClaims.tenant_id -ne "demo-academy" -or
        $reviewerClaims.tenant_id -ne "demo-academy" -or
        $reviewerClaims.roles -notcontains "reviewer"
    ) {
        throw "OIDC tokens are not bound to the expected tenant and reviewer role."
    }

    $knowledgeRaw = Get-Content -LiteralPath $knowledgeScript -Raw -Encoding UTF8 |
        & docker exec -i $apiContainer python - `
            --tenant-id demo-academy `
            --subject-ref $reviewerClaims.sub `
            --trace-id ([Guid]::NewGuid().ToString("N"))
    if ($LASTEXITCODE -ne 0) {
        throw "C2 knowledge lifecycle bootstrap failed."
    }
    $knowledge = ($knowledgeRaw | Out-String) | ConvertFrom-Json
    if ($knowledge.index_state -ne "READY" -or $knowledge.chunk_count -lt 1) {
        throw "C2 did not activate a ready local knowledge index."
    }

    $generationSessionId = [Guid]::NewGuid()
    $generationBody = [ordered]@{
        schema_version = "topic3.generation-command.v1"
        operation_id = [Guid]::NewGuid().ToString()
        generation_session_id = $generationSessionId.ToString()
        learner_ref = [string]$learnerClaims.sub
        course_id = "CRS_ATC_001"
        target_kp_ids = @("KP_ATC_202_LAPLACE_TRANSFORM")
        requested_resources = @("Lecturer_Doc")
        lecturer_depth = "ENGINEERING"
        learning_goal = "Explain the Laplace transform strictly from the frozen Topic1 authority."
        locale = "zh-CN"
        max_parallelism = 1
        allow_partial = $false
        requested_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    Invoke-Api `
        -Method POST `
        -Uri "$api/internal/topic3/generations" `
        -Token $learnerToken `
        -IdempotencyKey "system-acceptance-generation-$($generationSessionId.ToString('N'))" `
        -Body $generationBody | Out-Null

    $generation = $null
    foreach ($attempt in 1..120) {
        Start-Sleep -Seconds 1
        $generation = Invoke-Api `
            -Method GET `
            -Uri "$api/internal/topic3/generations/$generationSessionId" `
            -Token $learnerToken
        if ($generation.payload.session.state -in @("COMPLETED", "PARTIAL", "FAILED", "CANCELLED")) {
            break
        }
    }
    if ($generation.payload.session.state -ne "COMPLETED") {
        throw "Topic3 generation did not complete: $($generation.payload.session.state)"
    }
    $candidate = @($generation.payload.candidates)[0]
    if ($null -eq $candidate -or $candidate.status -ne "COMPLETE") {
        throw "Topic3 did not persist a complete Candidate."
    }

    $verificationId = $null
    foreach ($attempt in 1..60) {
        $value = Invoke-Psql -Sql (
            "select verification_id from topic4_verifications " +
            "where source_candidate_id='$($candidate.candidate_id)' " +
            "order by created_at desc limit 1;"
        )
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $verificationId = [Guid]$value
            break
        }
        Start-Sleep -Seconds 1
    }
    if ($null -eq $verificationId) {
        throw "Topic3 Candidate was not handed off to Topic4."
    }

    $verification = $null
    foreach ($attempt in 1..120) {
        $verification = Invoke-Api `
            -Method GET `
            -Uri "$api/internal/topic4/verifications/$verificationId" `
            -Token $reviewerToken
        $state = [string]$verification.payload.state.current_state
        if ($state -in @(
                "RELEASE_PENDING", "RELEASED", "BLOCKED", "REVIEW_REQUIRED",
                "REVISION_PLANNING", "FAILED", "EXPIRED", "CANCELLED"
            )) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if ($verification.payload.state.current_state -ne "RELEASE_PENDING") {
        throw "Topic4 did not produce a release-eligible report: $($verification.payload.state.current_state)"
    }
    if ($verification.payload.report.decision -ne "RELEASE") {
        throw "Topic4 report decision is not RELEASE."
    }
    $moduleSummary = Assert-ModuleResults -Snapshot $verification.payload

    $deriveKey = "system-acceptance-c12-derive-$($verificationId.ToString('N'))"
    $derived = Invoke-Api `
        -Method POST `
        -Uri "$api/internal/topic4/release/authorizations/derive" `
        -Token $reviewerToken `
        -IdempotencyKey $deriveKey `
        -Body @{
            verification_id = $verificationId.ToString()
            requested_release_mode = "FULL"
            requested_block_ids = @()
            ttl_seconds = 300
        }
    $authorization = $derived.payload.authorization
    $commitKey = "system-acceptance-c12-commit-$(([Guid]$authorization.authorization_id).ToString('N'))"
    $commitBody = @{ authorization_id = $authorization.authorization_id }
    $published = Invoke-Api `
        -Method POST `
        -Uri "$api/internal/topic4/release/publications/commit" `
        -Token $reviewerToken `
        -IdempotencyKey $commitKey `
        -Body $commitBody
    $replayed = Invoke-Api `
        -Method POST `
        -Uri "$api/internal/topic4/release/publications/commit" `
        -Token $reviewerToken `
        -IdempotencyKey $commitKey `
        -Body $commitBody
    if (
        $published.payload.batch.publication_batch_id -ne
            $replayed.payload.batch.publication_batch_id -or
        $published.payload.batch.record_sha256 -ne $replayed.payload.batch.record_sha256
    ) {
        throw "C12 idempotent replay returned a different publication result."
    }

    $changedReplayStatus = $null
    try {
        Invoke-Api `
            -Method POST `
            -Uri "$api/internal/topic4/release/publications/commit" `
            -Token $reviewerToken `
            -IdempotencyKey "system-acceptance-c12-replay-attack-$(([Guid]::NewGuid()).ToString('N'))" `
            -Body $commitBody | Out-Null
        throw "C12 accepted a changed replay of a consumed authorization."
    }
    catch {
        $changedReplayStatus = Get-HttpStatusCode -ErrorRecord $_
        if ($changedReplayStatus -ne 409) {
            throw
        }
    }

    $released = Invoke-Api `
        -Method GET `
        -Uri "$api/internal/topic4/verifications/$verificationId" `
        -Token $reviewerToken
    if ($released.payload.state.current_state -ne "RELEASED") {
        throw "C12 commit did not append the RELEASED state."
    }

    $publicationBatchId = [string]$published.payload.batch.publication_batch_id
    $sseReplay = $null
    foreach ($attempt in 1..30) {
        $sseReplay = Invoke-Api `
            -Method GET `
            -Uri "$api/internal/topic4/sse/replay?after_sequence=-1" `
            -Token $reviewerToken
        $matching = @(
            $sseReplay.payload.events |
                Where-Object {
                    $_.event_type -eq "topic4.publication.committed" -and
                    ($_.data | ConvertTo-Json -Depth 20 -Compress) -match [regex]::Escape($publicationBatchId)
                }
        )
        if ($matching) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $matching) {
        throw "The committed publication did not reach durable Topic4 SSE replay."
    }

    $previousDemoToken = $env:LIYAN_DEMO_TOKEN
    try {
        $env:LIYAN_DEMO_TOKEN = $reviewerToken
        $sseStreamRaw = & uv run --frozen python $sseVerifier `
            --url "$api/internal/topic4/sse/stream" `
            --event-type "topic4.publication.committed" `
            --publication-batch-id $publicationBatchId `
            --timeout-seconds 30 |
            Out-String
        if ($LASTEXITCODE -ne 0) {
            throw "Authenticated Topic4 SSE stream verification failed."
        }
        $sseStream = $sseStreamRaw | ConvertFrom-Json
    }
    finally {
        if ($null -eq $previousDemoToken) {
            Remove-Item Env:LIYAN_DEMO_TOKEN -ErrorAction SilentlyContinue
        }
        else {
            $env:LIYAN_DEMO_TOKEN = $previousDemoToken
        }
    }

    $history = Invoke-Api `
        -Method GET `
        -Uri "$api/internal/topic4/release/history?verification_id=$verificationId" `
        -Token $reviewerToken

    foreach ($attempt in 1..60) {
        $outboxOpen = [int](Invoke-Psql -Sql (
                "select count(*) from outbox_messages where state in ('PENDING','CLAIMED');"
            ))
        if ($outboxOpen -eq 0) {
            break
        }
        Start-Sleep -Seconds 1
    }
    $databaseChecksRaw = Invoke-Psql -Sql @"
select 'tenant_tables', count(*) from information_schema.columns c
join pg_class p on p.relname=c.table_name
join pg_namespace n on n.oid=p.relnamespace and n.nspname=c.table_schema
where c.table_schema='public' and c.column_name='tenant_id' and p.relkind='r';
select 'forced_rls_tables', count(*) from information_schema.columns c
join pg_class p on p.relname=c.table_name
join pg_namespace n on n.oid=p.relnamespace and n.nspname=c.table_schema
where c.table_schema='public' and c.column_name='tenant_id' and p.relkind='r'
and p.relrowsecurity and p.relforcerowsecurity;
select 'append_only_triggers', count(*) from pg_trigger where not tgisinternal
and tgname like '%append_only%';
select 'audit_chain_breaks', count(*) from (
  select tenant_id, sequence, previous_hash,
         lag(event_hash) over (partition by tenant_id order by sequence) as expected_previous
  from audit_events
) chain where sequence > 0 and previous_hash <> expected_previous;
select 'outbox_dead', count(*) from outbox_messages where state='DEAD';
select 'outbox_open', count(*) from outbox_messages where state in ('PENDING','CLAIMED');
select 'outbox_published', count(*) from outbox_messages where state='PUBLISHED';
select 'authorization_consumptions', count(*) from topic4_release_authorization_consumptions
where authorization_id='$($authorization.authorization_id)';
select 'committed_batches', count(*) from topic4_publication_batches
where authorization_id='$($authorization.authorization_id)' and state='COMMITTED';
select 'public_stream_events', count(*) from topic4_public_stream_events
where authorization_id='$($authorization.authorization_id)';
"@
    $databaseChecks = [ordered]@{}
    foreach ($line in ($databaseChecksRaw -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $key, $value = $line.Split('|', 2)
        $databaseChecks[$key] = [int]$value
    }
    if (
        $databaseChecks.tenant_tables -ne $databaseChecks.forced_rls_tables -or
        $databaseChecks.audit_chain_breaks -ne 0 -or
        $databaseChecks.outbox_dead -ne 0 -or
        $databaseChecks.outbox_open -ne 0 -or
        $databaseChecks.authorization_consumptions -ne 1 -or
        $databaseChecks.committed_batches -ne 1 -or
        $databaseChecks.public_stream_events -ne 1
    ) {
        throw "Database acceptance invariants failed: $($databaseChecks | ConvertTo-Json -Compress)"
    }

    $foreignVisible = & docker exec `
        -e PGPASSWORD=liyans-app-local-only `
        $script:postgresContainer `
        psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U liyans_app -d liyans -At -c `
        "begin; select set_config('app.tenant_id','foreign-tenant',true); select count(*) from topic4_verifications; rollback;"
    if ($LASTEXITCODE -ne 0) {
        throw "RLS foreign-tenant visibility probe failed to execute."
    }
    $foreignCount = [int](@($foreignVisible)[-2])
    if ($foreignCount -ne 0) {
        throw "RLS exposed Topic4 records to a foreign tenant context."
    }

    $evidence = [ordered]@{
        schema_version = "cybercontrol.system-acceptance-evidence.v1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        git = [ordered]@{
            branch = $sourceBranch
            commit = $sourceCommit
            tree = $sourceTree
            require_clean_source = [bool]$RequireCleanSource
            clean_at_start = $sourceClean
            dirty_files_at_start = @($sourceStatus)
            dirty_files = @(& git status --short)
        }
        environment = [ordered]@{
            compose_project = $ProjectName
            compose_config_sha256 = $composeConfigSha256
            uv_lock_sha256 = $uvLockSha256
            pnpm_lock_sha256 = $pnpmLockSha256
            runtime_image_ids = $runtimeImageIds
            command = [ordered]@{
                reset_volumes = [bool]$ResetVolumes
                skip_build = [bool]$SkipBuild
                require_clean_source = [bool]$RequireCleanSource
                use_release_postgres_volume = [bool]$UseReleasePostgresVolume
                api_base_url = $api
                frontend_base_url = $frontend
                keycloak_base_url = $keycloak
                evidence_path = $evidenceFile
            }
            clean_volume_verified = $true
            postgres_volume = [string]$postgresDataMount[0].Name
            alembic_head = $migrationHead
            initial_business_counts = $initialCounts
            api_ready = $readiness.api.status
            frontend_ready = $readiness.frontend.status
            oidc_issuer = $readiness.oidc_issuer
            external_provider_mode = "local-fixture-only"
        }
        identity = [ordered]@{
            tenant_id = [string]$learnerClaims.tenant_id
            learner_subject_ref = [string]$learnerClaims.sub
            reviewer_subject_ref = [string]$reviewerClaims.sub
            reviewer_roles = @($reviewerClaims.roles)
            tokens_persisted = $false
        }
        topic1_topic2 = $bootstrap
        c2_knowledge = $knowledge
        topic3 = [ordered]@{
            generation_session_id = $generationSessionId.ToString()
            state = [string]$generation.payload.session.state
            candidate_id = [string]$candidate.candidate_id
            candidate_version = [int]$candidate.candidate_version
            candidate_sha256 = [string]$candidate.candidate_sha256
            resource_type = [string]$candidate.resource_type
        }
        topic4 = [ordered]@{
            verification_id = $verificationId.ToString()
            state_before_release = "RELEASE_PENDING"
            state_after_release = [string]$released.payload.state.current_state
            report_id = [string]$verification.payload.report.report_id
            report_sha256 = [string]$verification.payload.report.report_sha256
            decision = [string]$verification.payload.report.decision
            claim_count = @($verification.payload.claims).Count
            module_results = $moduleSummary
        }
        c12 = [ordered]@{
            authorization_id = [string]$authorization.authorization_id
            authorization_sha256 = [string]$authorization.record_sha256
            authorization_ttl_seconds = 300
            one_time_use = [bool]$authorization.one_time_use
            publication_batch_id = $publicationBatchId
            publication_batch_sha256 = [string]$published.payload.batch.record_sha256
            public_artifact_sha256 = [string]$published.payload.public_artifact.sha256
            public_event_id = [string]$published.payload.public_event.public_event_id
            public_event_sha256 = [string]$published.payload.public_event.record_sha256
            same_key_replay_idempotent = $true
            changed_replay_http_status = $changedReplayStatus
            history_record_count = @($history.payload.records).Count
        }
        sse = [ordered]@{
            replay_event = @($matching)[0]
            authenticated_stream = $sseStream
        }
        database = [ordered]@{
            invariants = $databaseChecks
            foreign_tenant_visible_verifications = $foreignCount
        }
    }

    $parent = Split-Path -Parent $evidenceFile
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $json = $evidence | ConvertTo-Json -Depth 40
    [IO.File]::WriteAllText($evidenceFile, $json + "`n", [Text.UTF8Encoding]::new($false))
    Write-Output $json
}
finally {
    Pop-Location
}
