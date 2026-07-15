[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository,

    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Branch = "main",

    [string]$RequiredContext = "Release quality redline",

    [string]$MainRulesetName = "main-release-governance",

    [string]$TagRulesetName = "immutable-release-tags"
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
    "User-Agent" = "CyberControl-Phase11-Protection"
}
$ApiRoot = "https://api.github.com/repos/$Repository"
$EncodedBranch = [Uri]::EscapeDataString($Branch)

function Invoke-GitHubJson {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "POST", "PUT", "PATCH")]
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
        $arguments.Body = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    try {
        return Invoke-RestMethod @arguments
    }
    catch {
        $statusCode = "transport-error"
        $responseProperty = $_.Exception.PSObject.Properties["Response"]
        if ($null -ne $responseProperty -and $null -ne $responseProperty.Value) {
            $statusProperty = $responseProperty.Value.PSObject.Properties["StatusCode"]
            if ($null -ne $statusProperty -and $null -ne $statusProperty.Value) {
                $statusCode = [int]$statusProperty.Value
            }
        }
        $responseBody = ""
        if ($null -ne $_.ErrorDetails -and -not [string]::IsNullOrWhiteSpace($_.ErrorDetails.Message)) {
            $responseBody = $_.ErrorDetails.Message
        }
        $exceptionMessage = $_.Exception.Message
        throw "GitHub API $Method $Uri failed with $statusCode. $exceptionMessage $responseBody"
    }
}

function Set-RepositoryRuleset {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Definition
    )

    $rulesetResponse = Invoke-GitHubJson -Method GET -Uri "$ApiRoot/rulesets"
    $existing = @()
    foreach ($candidate in @($rulesetResponse)) {
        $nameProperty = $candidate.PSObject.Properties["name"]
        $targetProperty = $candidate.PSObject.Properties["target"]
        if (
            $null -ne $nameProperty -and
            $null -ne $targetProperty -and
            $nameProperty.Value -eq $Definition.name -and
            $targetProperty.Value -eq $Definition.target
        ) {
            $existing += $candidate
        }
    }
    if ($existing.Count -gt 1) {
        throw "More than one ruleset named '$($Definition.name)' targets '$($Definition.target)'."
    }

    if ($existing.Count -eq 1) {
        return Invoke-GitHubJson -Method PUT `
            -Uri "$ApiRoot/rulesets/$($existing[0].id)" `
            -Body $Definition
    }
    return Invoke-GitHubJson -Method POST -Uri "$ApiRoot/rulesets" -Body $Definition
}

$repositoryState = Invoke-GitHubJson -Method GET -Uri $ApiRoot
if ($repositoryState.visibility -ne "public" -or $repositoryState.private) {
    throw "Repository ruleset activation requires the approved Public repository state."
}
if ($repositoryState.default_branch -ne $Branch) {
    throw "Expected default branch '$Branch', found '$($repositoryState.default_branch)'."
}
if (-not $repositoryState.permissions.admin) {
    throw "The current GitHub credential does not have repository administration permission."
}

$classicProtection = @{
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

$mainRuleset = @{
    name = $MainRulesetName
    target = "branch"
    enforcement = "active"
    bypass_actors = @(
        @{
            actor_id = 5
            actor_type = "RepositoryRole"
            bypass_mode = "pull_request"
        }
    )
    conditions = @{
        ref_name = @{
            include = @("~DEFAULT_BRANCH")
            exclude = @()
        }
    }
    rules = @(
        @{ type = "deletion" },
        @{ type = "non_fast_forward" },
        @{ type = "required_linear_history" },
        @{
            type = "pull_request"
            parameters = @{
                allowed_merge_methods = @("squash", "rebase")
                dismiss_stale_reviews_on_push = $true
                require_code_owner_review = $true
                require_last_push_approval = $true
                required_approving_review_count = 1
                required_review_thread_resolution = $true
            }
        },
        @{
            type = "required_status_checks"
            parameters = @{
                do_not_enforce_on_create = $false
                strict_required_status_checks_policy = $true
                required_status_checks = @(
                    @{ context = $RequiredContext }
                )
            }
        }
    )
}

$tagRuleset = @{
    name = $TagRulesetName
    target = "tag"
    enforcement = "active"
    bypass_actors = @()
    conditions = @{
        ref_name = @{
            include = @("refs/tags/*")
            exclude = @()
        }
    }
    rules = @(
        @{ type = "deletion" },
        @{ type = "non_fast_forward" }
    )
}

if ($PSCmdlet.ShouldProcess("$Repository/$Branch", "Apply Classic and Repository Ruleset redlines")) {
    Invoke-GitHubJson -Method PUT `
        -Uri "$ApiRoot/branches/$EncodedBranch/protection" `
        -Body $classicProtection | Out-Null
    Invoke-GitHubJson -Method PUT `
        -Uri "$ApiRoot/actions/permissions/workflow" `
        -Body @{
            default_workflow_permissions = "read"
            can_approve_pull_request_reviews = $false
        } | Out-Null
    Set-RepositoryRuleset -Definition $mainRuleset | Out-Null
    Set-RepositoryRuleset -Definition $tagRuleset | Out-Null
}

$verifiedClassic = Invoke-GitHubJson -Method GET `
    -Uri "$ApiRoot/branches/$EncodedBranch/protection"
$contexts = @($verifiedClassic.required_status_checks.contexts)
if ($contexts -notcontains $RequiredContext) {
    throw "Required status context '$RequiredContext' is absent after protection update."
}
$requiredFlags = @(
    $verifiedClassic.enforce_admins.enabled,
    $verifiedClassic.required_linear_history.enabled,
    $verifiedClassic.required_conversation_resolution.enabled
)
if ($requiredFlags -contains $false) {
    throw "One or more required Classic branch-protection flags remain disabled."
}
if ($verifiedClassic.allow_force_pushes.enabled -or $verifiedClassic.allow_deletions.enabled) {
    throw "Classic protection still permits force pushes or branch deletion."
}
$reviewPolicy = $verifiedClassic.required_pull_request_reviews
if ($null -eq $reviewPolicy) {
    throw "Classic pull-request review protection is absent."
}
if (
    $reviewPolicy.required_approving_review_count -lt 1 -or
    -not $reviewPolicy.require_code_owner_reviews -or
    -not $reviewPolicy.dismiss_stale_reviews -or
    -not $reviewPolicy.require_last_push_approval
) {
    throw "One or more required Classic pull-request review controls remain disabled."
}

$rulesetResponse = Invoke-GitHubJson -Method GET -Uri "$ApiRoot/rulesets"
$rulesets = @()
foreach ($candidate in @($rulesetResponse)) {
    if ($null -ne $candidate.PSObject.Properties["name"]) {
        $rulesets += $candidate
    }
}
$verifiedMainSummary = $rulesets | Where-Object {
    $_.name -eq $MainRulesetName -and $_.target -eq "branch"
} | Select-Object -First 1
$verifiedTagSummary = $rulesets | Where-Object {
    $_.name -eq $TagRulesetName -and $_.target -eq "tag"
} | Select-Object -First 1
if ($null -eq $verifiedMainSummary -or $null -eq $verifiedTagSummary) {
    throw "One or more required Repository Rulesets are absent."
}
$verifiedMain = Invoke-GitHubJson -Method GET -Uri "$ApiRoot/rulesets/$($verifiedMainSummary.id)"
$verifiedTag = Invoke-GitHubJson -Method GET -Uri "$ApiRoot/rulesets/$($verifiedTagSummary.id)"
if ($verifiedMain.enforcement -ne "active" -or $verifiedTag.enforcement -ne "active") {
    throw "One or more required Repository Rulesets are not active."
}
$mainRuleTypes = @($verifiedMain.rules | ForEach-Object { $_.type })
$requiredMainRuleTypes = @(
    "deletion",
    "non_fast_forward",
    "required_linear_history",
    "pull_request",
    "required_status_checks"
)
foreach ($ruleType in $requiredMainRuleTypes) {
    if ($mainRuleTypes -notcontains $ruleType) {
        throw "Main ruleset is missing required rule '$ruleType'."
    }
}
$tagRuleTypes = @($verifiedTag.rules | ForEach-Object { $_.type })
if ($tagRuleTypes -notcontains "deletion" -or $tagRuleTypes -notcontains "non_fast_forward") {
    throw "Tag ruleset does not block deletion and non-fast-forward updates."
}

$workflowPermissions = Invoke-GitHubJson -Method GET `
    -Uri "$ApiRoot/actions/permissions/workflow"
if (
    $workflowPermissions.default_workflow_permissions -ne "read" -or
    $workflowPermissions.can_approve_pull_request_reviews
) {
    throw "GitHub Actions default token permissions are not read-only."
}

$evidence = [ordered]@{
    schema_version = "phase1.1.repository-protection.v2"
    repository = $Repository
    visibility = $repositoryState.visibility
    branch = $Branch
    required_context = $RequiredContext
    classic = [ordered]@{
        strict_status_checks = $verifiedClassic.required_status_checks.strict
        administrators_enforced = $verifiedClassic.enforce_admins.enabled
        required_approving_reviews = $reviewPolicy.required_approving_review_count
        code_owner_reviews_required = $reviewPolicy.require_code_owner_reviews
        stale_reviews_dismissed = $reviewPolicy.dismiss_stale_reviews
        last_push_approval_required = $reviewPolicy.require_last_push_approval
        conversation_resolution_required = $verifiedClassic.required_conversation_resolution.enabled
        linear_history_required = $verifiedClassic.required_linear_history.enabled
        matching_branch_creation_blocked = $verifiedClassic.block_creations.enabled
        force_pushes_allowed = $verifiedClassic.allow_force_pushes.enabled
        deletions_allowed = $verifiedClassic.allow_deletions.enabled
    }
    rulesets = [ordered]@{
        main = [ordered]@{
            id = $verifiedMain.id
            name = $verifiedMain.name
            enforcement = $verifiedMain.enforcement
            rule_types = $mainRuleTypes
            bypass_actors = @($verifiedMain.bypass_actors)
        }
        tags = [ordered]@{
            id = $verifiedTag.id
            name = $verifiedTag.name
            enforcement = $verifiedTag.enforcement
            rule_types = $tagRuleTypes
            bypass_actors = @($verifiedTag.bypass_actors)
        }
    }
    actions = [ordered]@{
        default_workflow_permissions = $workflowPermissions.default_workflow_permissions
        can_approve_pull_requests = $workflowPermissions.can_approve_pull_request_reviews
    }
    conventional_commit_enforcement = [ordered]@{
        mode = "required_status_check"
        context = $RequiredContext
        repository_metadata_rule_available = $false
    }
    verified_at_utc = [DateTime]::UtcNow.ToString("o")
}
$evidenceRoot = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) `
    "artifacts\quality-gates"
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$evidence | ConvertTo-Json -Depth 12 | Set-Content `
    -LiteralPath (Join-Path $evidenceRoot "repository-protection.json") `
    -Encoding utf8
$evidence | ConvertTo-Json -Depth 12
