[CmdletBinding()]
param(
    [switch]$SkipPostgresIntegration,
    [switch]$SkipContainer,
    [switch]$SkipSecretScan
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$ArtifactRoot = Join-Path $RepositoryRoot "artifacts"
$EvidenceRoot = Join-Path $ArtifactRoot "quality-gates"
$SbomRoot = Join-Path $ArtifactRoot "sbom"
$SecurityRoot = Join-Path $ArtifactRoot "security"
$ToolCacheRoot = Join-Path $ArtifactRoot "toolchain-cache"
$TranscriptPath = Join-Path $EvidenceRoot "windows-quality-gates.log"
New-Item -ItemType Directory -Force -Path @(
    $EvidenceRoot,
    $SbomRoot,
    $SecurityRoot,
    $ToolCacheRoot,
    (Join-Path $ArtifactRoot "coverage"),
    (Join-Path $ArtifactRoot "test-results")
) | Out-Null

# A newly launched automation process does not automatically inherit user PATH
# changes made by the toolchain installer. Merge persisted entries explicitly.
$persistedPath = @(
    [Environment]::GetEnvironmentVariable("Path", "User"),
    [Environment]::GetEnvironmentVariable("Path", "Machine")
) -join ";"
foreach ($entry in @($persistedPath -split ";" | Where-Object { $_ })) {
    if (($env:Path -split ";") -notcontains $entry) {
        $env:Path = "$entry;$env:Path"
    }
}

function Write-Gate {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Resolve-Executable {
    param(
        [string]$Name,
        [string[]]$Candidates = @()
    )
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "$Name is unavailable. Restore the Phase 1.1 pinned toolchain before running gates."
}

function Invoke-Native {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Description
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Install-VerifiedZipTool {
    param(
        [string]$Name,
        [string]$Version,
        [string]$ArchiveName,
        [string]$DownloadUrl,
        [string]$ExpectedSha256,
        [string]$ExecutableName
    )
    $toolRoot = Join-Path $ToolCacheRoot "$Name-$Version"
    $archivePath = Join-Path $toolRoot $ArchiveName
    $executablePath = Join-Path $toolRoot $ExecutableName
    New-Item -ItemType Directory -Force -Path $toolRoot | Out-Null

    $archiveValid = $false
    if (Test-Path -LiteralPath $archivePath) {
        $archiveValid = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath
        ).Hash.ToLowerInvariant() -eq $ExpectedSha256.ToLowerInvariant()
    }
    if (-not $archiveValid) {
        $downloadPath = "$archivePath.download"
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $DownloadUrl -OutFile $downloadPath `
                    -TimeoutSec 180
                $actual = (
                    Get-FileHash -Algorithm SHA256 -LiteralPath $downloadPath
                ).Hash.ToLowerInvariant()
                if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
                    throw "$Name archive digest mismatch. Expected $ExpectedSha256, got $actual."
                }
                Move-Item -LiteralPath $downloadPath -Destination $archivePath -Force
                $archiveValid = $true
                break
            }
            catch {
                Remove-Item -LiteralPath $downloadPath -Force -ErrorAction SilentlyContinue
                if ($attempt -eq 3) { throw }
                Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
            }
        }
    }
    if (-not $archiveValid) {
        throw "$Name archive could not be verified."
    }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $toolRoot -Force
    if (-not (Test-Path -LiteralPath $executablePath)) {
        throw "$Name archive is valid but $ExecutableName is missing after extraction."
    }
    return $executablePath
}

$Uv = Resolve-Executable -Name "uv" -Candidates @(
    (Join-Path $env:APPDATA "Python\Python311\Scripts\uv.exe"),
    (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
)
$Git = Resolve-Executable -Name "git"
$Go = Resolve-Executable -Name "go"
$Node = Resolve-Executable -Name "node"
$Pnpm = Resolve-Executable -Name "pnpm"
$Docker = if ($SkipContainer) { $null } else { Resolve-Executable -Name "docker" }

Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null
Push-Location $RepositoryRoot
try {
    Write-Gate "GitHub Actions workflow syntax and expression validation"
    $actionlint = Install-VerifiedZipTool `
        -Name "actionlint" `
        -Version "1.7.12" `
        -ArchiveName "actionlint_1.7.12_windows_amd64.zip" `
        -DownloadUrl (
            "https://github.com/rhysd/actionlint/releases/download/" +
            "v1.7.12/actionlint_1.7.12_windows_amd64.zip"
        ) `
        -ExpectedSha256 "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9" `
        -ExecutableName "actionlint.exe"
    Invoke-Native -Executable $actionlint -Arguments @("-no-color") `
        -Description "GitHub Actions workflow validation"

    Write-Gate "Locked Python environment"
    Invoke-Native -Executable $Uv -Arguments @("lock", "--check") `
        -Description "uv lock validation"
    Invoke-Native -Executable $Uv -Arguments @(
        "sync", "--frozen", "--all-packages", "--all-extras"
    ) -Description "uv frozen synchronization"

    Write-Gate "Conventional Commit subject policy"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "python", "tools/validate_commit_messages.py",
        "--head", "HEAD"
    ) -Description "commit subject validation"

    Write-Gate "Ruff static and format redlines"
    Invoke-Native -Executable $Uv -Arguments @("run", "--frozen", "ruff", "check", ".") `
        -Description "Ruff static analysis"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "ruff", "format", "--check", "."
    ) -Description "Ruff format validation"

    Write-Gate "Frozen contract regeneration and drift"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "python", "tools/export_contracts.py"
    ) -Description "contract generation"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "python", "tools/validate_baseline.py"
    ) -Description "frozen baseline validation"
    Invoke-Native -Executable $Git -Arguments @(
        "diff", "--exit-code", "--",
        "schemas",
        "packages/contracts-ts/src/generated",
        "packages/contracts-go/contracts"
    ) -Description "generated contract drift validation"

    Write-Gate "Go vet, race test, and build"
    & (Join-Path $PSScriptRoot "build-go-contracts.ps1") -ProjectRoot $RepositoryRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Go contract gate failed with exit code $LASTEXITCODE."
    }
    Invoke-Native -Executable $Git -Arguments @(
        "diff", "--exit-code", "--", "packages/contracts-go/go.mod", "packages/contracts-go/go.sum"
    ) -Description "Go module graph drift validation"

    Write-Gate "Vue, TypeScript, pnpm audit, and Node SBOM"
    Invoke-Native -Executable $Pnpm -Arguments @(
        "--dir", "frontend", "install", "--frozen-lockfile"
    ) -Description "pnpm frozen installation"
    Invoke-Native -Executable $Pnpm -Arguments @(
        "--dir", "frontend", "exec", "tsc", "--noEmit", "--project",
        "../packages/contracts-ts/tsconfig.json"
    ) -Description "TypeScript contract validation"
    Invoke-Native -Executable $Pnpm -Arguments @("--dir", "frontend", "run", "typecheck") `
        -Description "Vue and TypeScript type checking"
    Invoke-Native -Executable $Pnpm -Arguments @("--dir", "frontend", "run", "build") `
        -Description "Vue production build"
    Invoke-Native -Executable $Pnpm -Arguments @(
        "--dir", "frontend", "audit", "--audit-level", "high"
    ) -Description "Node dependency audit"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "python", "tools/generate_node_sbom.py",
        "--project", "frontend", "--output", "artifacts/sbom/frontend.cdx.json"
    ) -Description "Node CycloneDX generation"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "python", "tools/validate_sbom_policy.py",
        "artifacts/sbom/frontend.cdx.json", "--output",
        "artifacts/sbom/frontend-license-policy.json"
    ) -Description "Node license policy validation"

    Write-Gate "Python dependency audit and CycloneDX SBOM"
    Invoke-Native -Executable $Uv -Arguments @(
        "export", "--quiet", "--frozen", "--all-packages", "--all-extras",
        "--no-emit-workspace", "--format", "requirements-txt",
        "--output-file", "artifacts/sbom/python-requirements.txt"
    ) -Description "Python dependency export"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "pip-audit", "--strict", "-r",
        "artifacts/sbom/python-requirements.txt"
    ) -Description "Python vulnerability audit"
    $env:PYTHONUTF8 = "1"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "cyclonedx-py", "environment", ".venv",
        "--pyproject", "backend/pyproject.toml", "--mc-type", "application",
        "--spec-version", "1.6", "--output-reproducible", "--output-format", "JSON",
        "--output-file", "artifacts/sbom/python.cdx.json", "--validate"
    ) -Description "Python CycloneDX generation"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "python", "tools/validate_sbom_policy.py",
        "artifacts/sbom/python.cdx.json", "--output",
        "artifacts/sbom/python-license-policy.json"
    ) -Description "Python license policy validation"

    Write-Gate "Deterministic Python unit suite"
    Invoke-Native -Executable $Uv -Arguments @(
        "run", "--frozen", "pytest", "-q", "-m", "not integration"
    ) -Description "Python unit tests"

    if (-not $SkipPostgresIntegration) {
        Write-Gate "PostgreSQL migrations, integration suite, and 89 percent coverage"
        if (
            -not $env:LIYAN_TEST_DATABASE_URL -or
            -not $env:LIYAN_TEST_MIGRATION_DATABASE_URL -or
            -not $env:LIYAN_TEST_DISPATCHER_DATABASE_URL
        ) {
            throw (
                "Runtime, migration, and dispatcher PostgreSQL test URLs are required " +
                "for the PostgreSQL quality gate. Use -SkipPostgresIntegration only for a quick check."
            )
        }
        $env:LIYAN_DATABASE_URL = $env:LIYAN_TEST_DATABASE_URL
        $env:LIYAN_DATABASE_MIGRATION_URL = $env:LIYAN_TEST_MIGRATION_DATABASE_URL
        Invoke-Native -Executable $Uv -Arguments @(
            "run", "--frozen", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"
        ) -Description "Alembic upgrade"
        Invoke-Native -Executable $Uv -Arguments @(
            "run", "--frozen", "alembic", "-c", "backend/alembic.ini",
            "current", "--check-heads"
        ) -Description "Alembic head validation"
        Invoke-Native -Executable $Uv -Arguments @(
            "run", "--frozen", "alembic", "-c", "backend/alembic.ini", "check"
        ) -Description "Alembic model drift validation"
        Invoke-Native -Executable $Uv -Arguments @(
            "run", "--frozen", "alembic", "-c", "backend/alembic.ini", "downgrade", "base"
        ) -Description "Alembic full downgrade validation"
        Invoke-Native -Executable $Uv -Arguments @(
            "run", "--frozen", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"
        ) -Description "Alembic second upgrade validation"
        Invoke-Native -Executable $Uv -Arguments @(
            "run", "--frozen", "alembic", "-c", "backend/alembic.ini",
            "current", "--check-heads"
        ) -Description "Alembic post-cycle head validation"
        Invoke-Native -Executable $Uv -Arguments @(
            "run", "--frozen", "alembic", "-c", "backend/alembic.ini", "check"
        ) -Description "Alembic post-cycle model drift validation"
        Invoke-Native -Executable $Uv -Arguments @(
            "run", "--frozen", "pytest", "-q", "-rs",
            "--junitxml=artifacts/test-results/python-junit.xml",
            "--cov=backend/src/liyans",
            "--cov=packages/contracts-python/src/liyans_contracts",
            "--cov-report=term-missing",
            "--cov-report=xml:artifacts/coverage/python-coverage.xml",
            "--cov-fail-under=89"
        ) -Description "PostgreSQL full regression and coverage"
    }

    if (-not $SkipContainer) {
        Write-Gate "Production container build and runtime constraints"
        $image = "liyans-backend:local-quality"
        Invoke-Native -Executable $Docker -Arguments @(
            "compose", "-f", "infra/docker-compose.yml", "config", "--quiet"
        ) -Description "Docker Compose validation"
        Invoke-Native -Executable $Docker -Arguments @(
            "build", "--pull=false", "--file", "infra/backend.Dockerfile",
            "--tag", $image, "."
        ) -Description "production image build"
        $configuredUser = (& $Docker image inspect $image --format "{{.Config.User}}").Trim()
        if ($LASTEXITCODE -ne 0 -or $configuredUser -ne "10001:10001") {
            throw "The runtime image must declare USER 10001:10001; found '$configuredUser'."
        }
        Invoke-Native -Executable $Docker -Arguments @(
            "run", "--rm", "--entrypoint", "/bin/sh", $image, "-c",
            "set -eu; id -u | grep -qx 10001; id -g | grep -qx 10001; " +
            "test ! -e /app/backend/src; test ! -e /app/packages; " +
            "test ! -x /app/.venv/bin/pytest; " +
            "test ! -x /usr/local/bin/pip; " +
            "test ! -e /usr/local/lib/python3.11/site-packages/setuptools; " +
            "test ! -e /usr/local/lib/python3.11/site-packages/wheel; " +
            "python -c 'import liyans, liyans_contracts'"
        ) -Description "minimal non-root image validation"

        $containerName = "liyans-quality-$PID"
        $existingContainer = & $Docker ps -aq --filter "name=^/$containerName$"
        if ($existingContainer) {
            Invoke-Native -Executable $Docker -Arguments @("rm", "-f", $containerName) `
                -Description "stale smoke container cleanup"
        }
        $containerId = (& $Docker run -d --name $containerName `
            -e "LIYAN_ENVIRONMENT=development" `
            -e "LIYAN_SSE_CURSOR_SECRET=local-container-cursor-secret-at-least-32-bytes" `
            $image).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $containerId) {
            throw "container smoke startup failed."
        }
        try {
            $healthy = $false
            for ($attempt = 1; $attempt -le 45; $attempt++) {
                $health = (& $Docker inspect --format "{{.State.Health.Status}}" $containerId).Trim()
                if ($health -eq "healthy") {
                    $healthy = $true
                    break
                }
                if ($health -eq "unhealthy") { break }
                Start-Sleep -Seconds 1
            }
            if (-not $healthy) {
                & $Docker logs $containerId
                throw "container liveness health check did not become healthy."
            }
        }
        finally {
            Invoke-Native -Executable $Docker -Arguments @("rm", "-f", $containerId) `
                -Description "smoke container cleanup"
        }

        Write-Gate "Container SBOM and fixable high or critical vulnerability redline"
        $trivy = Install-VerifiedZipTool `
            -Name "trivy" `
            -Version "0.70.0" `
            -ArchiveName "trivy_0.70.0_windows-64bit.zip" `
            -DownloadUrl (
                "https://github.com/aquasecurity/trivy/releases/download/" +
                "v0.70.0/trivy_0.70.0_windows-64bit.zip"
            ) `
            -ExpectedSha256 "eea5442eab86f9e26cd718d7618d43899e72a83767619e8bee47911bddbfb825" `
            -ExecutableName "trivy.exe"
        Invoke-Native -Executable $trivy -Arguments @(
            "image", "--timeout", "30m", "--no-progress", "--skip-version-check",
            "--format", "cyclonedx", "--output",
            "artifacts/sbom/backend-container.cdx.json", $image
        ) -Description "container CycloneDX generation"
        Invoke-Native -Executable $trivy -Arguments @(
            "image", "--timeout", "30m", "--no-progress", "--skip-version-check",
            "--db-repository", "public.ecr.aws/aquasecurity/trivy-db:2",
            "--db-repository", "ghcr.io/aquasecurity/trivy-db:2",
            "--scanners", "vuln", "--severity",
            "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL", "--format", "json", "--output",
            "artifacts/security/container-trivy.json", "--exit-code", "0", $image
        ) -Description "container vulnerability inventory"
        Invoke-Native -Executable $trivy -Arguments @(
            "image", "--timeout", "30m", "--no-progress", "--skip-version-check",
            "--skip-db-update", "--scanners", "vuln", "--severity", "HIGH,CRITICAL",
            "--ignore-unfixed", "--exit-code", "1", $image
        ) -Description "container vulnerability redline"
    }

    if (-not $SkipSecretScan) {
        Write-Gate "Full Git history secret scan"
        $gitleaks = Install-VerifiedZipTool `
            -Name "gitleaks" `
            -Version "8.30.1" `
            -ArchiveName "gitleaks_8.30.1_windows_x64.zip" `
            -DownloadUrl (
                "https://github.com/gitleaks/gitleaks/releases/download/" +
                "v8.30.1/gitleaks_8.30.1_windows_x64.zip"
            ) `
            -ExpectedSha256 "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e" `
            -ExecutableName "gitleaks.exe"
        Invoke-Native -Executable $gitleaks -Arguments @(
            "git", ".", "--log-opts=--all", "--redact", "--no-banner", "--exit-code", "1",
            "--report-format", "json", "--report-path", "artifacts/security/gitleaks.json"
        ) -Description "Gitleaks full-history scan"
        Invoke-Native -Executable $gitleaks -Arguments @(
            "dir", ".", "--redact", "--no-banner", "--exit-code", "1",
            "--report-format", "json", "--report-path",
            "artifacts/security/gitleaks-working-tree.json"
        ) -Description "Gitleaks working-tree scan"
    }

    $summary = [ordered]@{
        schema_version = "phase1.1.quality-gates.v1"
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        git_commit = (& $Git rev-parse HEAD).Trim()
        result = "passed"
        postgres_integration = -not $SkipPostgresIntegration
        container_security = -not $SkipContainer
        secret_history_scan = -not $SkipSecretScan
        tool_versions = [ordered]@{
            uv = (& $Uv --version).Trim()
            go = (& $Go version).Trim()
            node = (& $Node --version).Trim()
            pnpm = (& $Pnpm --version).Trim()
        }
    }
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (
        Join-Path $EvidenceRoot "windows-quality-gates.json"
    ) -Encoding utf8
    Write-Host "`nAll selected Phase 1.1 quality gates passed." -ForegroundColor Green
}
finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
