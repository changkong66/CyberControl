[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository,

    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Branch = "main",

    [string]$RequiredContext = "Release quality redline"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($env:GH_TOKEN)) {
    throw "GH_TOKEN with repository administration permission is required."
}

$Headers = @{
    Accept = "application/vnd.github+json"
    Authorization = "Bearer $($env:GH_TOKEN)"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "Liyan-Phase11-Protection"
}
$ApiRoot = "https://api.github.com/repos/$Repository"
$EncodedBranch = [Uri]::EscapeDataString($Branch)

function Invoke-GitHubJson {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "PUT")]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [hashtable]$Body
    )

    $arguments = @{
        Method = $Method
        Uri = $Uri
        Headers = $Headers
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
        $statusCode = $_.Exception.Response.StatusCode.value__
        throw "GitHub API $Method $Uri failed with HTTP $statusCode."
    }
}

$Protection = @{
    required_status_checks = @{
        strict = $true
        checks = @(
            @{
                context = $RequiredContext
                app_id = -1
            }
        )
    }
    enforce_admins = $true
    required_pull_request_reviews = @{
        dismiss_stale_reviews = $true
        require_code_owner_reviews = $true
        required_approving_review_count = 1
        require_last_push_approval = $true
        bypass_pull_request_allowances = @{
            users = @()
            teams = @()
            apps = @()
        }
    }
    restrictions = $null
    required_linear_history = $true
    allow_force_pushes = $false
    allow_deletions = $false
    block_creations = $true
    required_conversation_resolution = $true
    lock_branch = $false
    allow_fork_syncing = $true
}

if ($PSCmdlet.ShouldProcess("$Repository/$Branch", "Apply protected-branch redlines")) {
    Invoke-GitHubJson -Method PUT `
        -Uri "$ApiRoot/branches/$EncodedBranch/protection" `
        -Body $Protection | Out-Null
    Invoke-GitHubJson -Method PUT `
        -Uri "$ApiRoot/actions/permissions/workflow" `
        -Body @{
            default_workflow_permissions = "read"
            can_approve_pull_request_reviews = $false
        } | Out-Null
}

$Verified = Invoke-GitHubJson -Method GET `
    -Uri "$ApiRoot/branches/$EncodedBranch/protection"
$Contexts = @($Verified.required_status_checks.contexts)
if ($Contexts -notcontains $RequiredContext) {
    throw "Required status context '$RequiredContext' is absent after protection update."
}
$RequiredFlags = @(
    $Verified.enforce_admins.enabled,
    $Verified.required_linear_history.enabled,
    $Verified.required_conversation_resolution.enabled
)
if ($RequiredFlags -contains $false) {
    throw "One or more required branch-protection flags remain disabled."
}
if ($Verified.allow_force_pushes.enabled -or $Verified.allow_deletions.enabled) {
    throw "Force pushes or branch deletion remain enabled."
}

[ordered]@{
    repository = $Repository
    branch = $Branch
    required_context = $RequiredContext
    strict_status_checks = $Verified.required_status_checks.strict
    administrators_enforced = $Verified.enforce_admins.enabled
    force_pushes_allowed = $Verified.allow_force_pushes.enabled
    deletions_allowed = $Verified.allow_deletions.enabled
    verified_at_utc = [DateTime]::UtcNow.ToString("o")
} | ConvertTo-Json -Depth 5
