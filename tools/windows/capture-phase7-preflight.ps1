[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,62}$')]
    [string]$ProjectName = "cybercontrol-frontend-mainline",

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$')]
    [string]$ReleaseVolume = "cybercontrol_release_postgres",

    [string]$ProtectedMainRef = "origin/main",

    [string]$RuntimeSourceEvidencePath = "docs/system-acceptance/evidence/frontend-identity-i18n-mainline.json",

    [string]$EvidencePath = "docs/system-acceptance/evidence/phase7-preflight.json",

    [string]$ReportPath = "docs/system-acceptance/evidence/phase7-preflight-report.md",

    [switch]$AllowDirtySource
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$composeFile = Join-Path $root "infra\docker-compose.yml"
$releaseComposeFile = Join-Path $root "infra\docker-compose.release.yml"
$dockerSettingsFile = Join-Path $env:APPDATA "Docker\settings-store.json"
$runtimeSourceEvidenceFile = if ([IO.Path]::IsPathRooted($RuntimeSourceEvidencePath)) {
    $RuntimeSourceEvidencePath
}
else {
    Join-Path $root $RuntimeSourceEvidencePath
}
$evidenceFile = if ([IO.Path]::IsPathRooted($EvidencePath)) {
    $EvidencePath
}
else {
    Join-Path $root $EvidencePath
}
$reportFile = if ([IO.Path]::IsPathRooted($ReportPath)) {
    $ReportPath
}
else {
    Join-Path $root $ReportPath
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = & $FilePath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
    return ($output | Out-String).Trim()
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
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

function Get-SafePath {
    param([AllowNull()][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $Path
    }
    $safe = $Path.Replace($root, '${REPOSITORY_ROOT}')
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $safe = $safe.Replace($env:USERPROFILE, '${USER_PROFILE}')
    }
    return $safe
}

function Get-OptionalProperty {
    param(
        [Parameter(Mandatory = $true)]$InputObject,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Get-CommandVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $resolved = Get-Command $Command -ErrorAction SilentlyContinue
    if ($null -eq $resolved) {
        return [ordered]@{ available = $false; version = $null }
    }
    try {
        return [ordered]@{
            available = $true
            version = Invoke-NativeText -FilePath $Command -Arguments $Arguments
        }
    }
    catch {
        return [ordered]@{
            available = $true
            version = $null
            error = $_.Exception.Message
        }
    }
}

function Get-ContainerEvidence {
    param([Parameter(Mandatory = $true)]$Container)

    $environmentNames = @(
        $Container.Config.Env |
            ForEach-Object { ([string]$_).Split('=', 2)[0] } |
            Sort-Object -Unique
    )
    $mounts = @(
        $Container.Mounts |
            ForEach-Object {
                $mountName = Get-OptionalProperty -InputObject $_ -Name "Name"
                [ordered]@{
                    type = [string]$_.Type
                    name = if ($null -eq $mountName) { $null } else { [string]$mountName }
                    source = Get-SafePath -Path ([string]$_.Source)
                    destination = [string]$_.Destination
                    read_write = [bool]$_.RW
                }
            }
    )
    $ports = [ordered]@{}
    if ($null -ne $Container.NetworkSettings.Ports) {
        foreach ($property in $Container.NetworkSettings.Ports.PSObject.Properties) {
            if ($null -eq $property.Value) {
                $ports[$property.Name] = @()
                continue
            }
            $ports[$property.Name] = @(
                $property.Value |
                    ForEach-Object {
                        [ordered]@{
                            host_ip = [string](Get-OptionalProperty -InputObject $_ -Name "HostIp")
                            host_port = [string](Get-OptionalProperty -InputObject $_ -Name "HostPort")
                        }
                    }
            )
        }
    }
    return [ordered]@{
        id = [string]$Container.Id
        name = ([string]$Container.Name).TrimStart('/')
        service = [string]$Container.Config.Labels.'com.docker.compose.service'
        state = [string]$Container.State.Status
        health = if ($null -eq (Get-OptionalProperty -InputObject $Container.State -Name "Health")) {
            $null
        }
        else {
            [string]$Container.State.Health.Status
        }
        restart_count = [int]$Container.RestartCount
        image_reference = [string]$Container.Config.Image
        image_id = [string]$Container.Image
        image_manifest_digest = if ($null -eq (Get-OptionalProperty -InputObject $Container -Name "ImageManifestDescriptor")) {
            $null
        }
        else {
            [string]$Container.ImageManifestDescriptor.digest
        }
        runtime_user = [string]$Container.Config.User
        privileged = [bool]$Container.HostConfig.Privileged
        read_only_rootfs = [bool]$Container.HostConfig.ReadonlyRootfs
        resources = [ordered]@{
            memory_bytes = [int64]$Container.HostConfig.Memory
            nano_cpus = [int64]$Container.HostConfig.NanoCpus
            pids_limit = if ($null -eq (Get-OptionalProperty -InputObject $Container.HostConfig -Name "PidsLimit")) {
                $null
            }
            else {
                [int64]$Container.HostConfig.PidsLimit
            }
            shm_bytes = [int64]$Container.HostConfig.ShmSize
        }
        ports = $ports
        mounts = $mounts
        environment_variable_names = $environmentNames
    }
}

Push-Location $root
try {
    $sourceStatusText = Invoke-NativeText -FilePath "git" -Arguments @("status", "--porcelain=v1")
    $sourceStatus = @(
        $sourceStatusText -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if (-not $AllowDirtySource -and $sourceStatus.Count -ne 0) {
        throw "Phase 7 preflight requires a clean source tree. Commit tooling before capturing evidence."
    }

    $sourceCommit = Invoke-NativeText -FilePath "git" -Arguments @("rev-parse", "HEAD")
    $sourceTree = Invoke-NativeText -FilePath "git" -Arguments @("rev-parse", 'HEAD^{tree}')
    $sourceBranch = Invoke-NativeText -FilePath "git" -Arguments @("branch", "--show-current")
    $protectedMainCommit = Invoke-NativeText -FilePath "git" -Arguments @("rev-parse", $ProtectedMainRef)
    $protectedMainTree = Invoke-NativeText -FilePath "git" -Arguments @("rev-parse", "$ProtectedMainRef^{tree}")
    $composeConfig = (& docker compose `
        -p $ProjectName `
        -f $composeFile `
        -f $releaseComposeFile `
        config | Out-String)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($composeConfig)) {
        throw "Unable to resolve the release Docker Compose configuration."
    }

    $containerIdsText = Invoke-NativeText -FilePath "docker" -Arguments @(
        "ps", "-a",
        "--filter", "label=com.docker.compose.project=$ProjectName",
        "--format", "{{.ID}}"
    )
    $containerIds = @($containerIdsText -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($containerIds.Count -eq 0) {
        throw "No containers were found for Compose project $ProjectName."
    }
    $containers = @(
        $containerIds |
            ForEach-Object {
                $raw = Invoke-NativeText -FilePath "docker" -Arguments @("inspect", $_)
                (ConvertFrom-Json $raw)[0]
            }
    )
    $containerEvidence = @($containers | ForEach-Object { Get-ContainerEvidence -Container $_ })

    if (-not (Test-Path -LiteralPath $runtimeSourceEvidenceFile)) {
        throw "Runtime source evidence does not exist: $runtimeSourceEvidenceFile"
    }
    $runtimeSourceEvidence = Get-Content -LiteralPath $runtimeSourceEvidenceFile -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $runtimeImages = [ordered]@{
        backend = [string]($containerEvidence | Where-Object { $_.service -eq "api" } | Select-Object -First 1).image_id
        frontend = [string]($containerEvidence | Where-Object { $_.service -eq "frontend" } | Select-Object -First 1).image_id
        mock_provider = [string]($containerEvidence | Where-Object { $_.service -eq "mock-provider" } | Select-Object -First 1).image_id
    }
    $runtimeImageMatch = (
        $runtimeImages.backend -eq [string]$runtimeSourceEvidence.environment.runtime_image_ids.backend -and
        $runtimeImages.frontend -eq [string]$runtimeSourceEvidence.environment.runtime_image_ids.frontend -and
        $runtimeImages.mock_provider -eq [string]$runtimeSourceEvidence.environment.runtime_image_ids.mock_provider
    )
    if (-not $runtimeImageMatch) {
        throw "Running image IDs do not match the immutable mainline replay evidence."
    }

    $imageEvidence = @(
        $containers.Image |
            Sort-Object -Unique |
            ForEach-Object {
                $image = (ConvertFrom-Json (
                    Invoke-NativeText -FilePath "docker" -Arguments @("image", "inspect", $_)
                ))[0]
                [ordered]@{
                    id = [string]$image.Id
                    repo_digests = @($image.RepoDigests | Sort-Object)
                    created = [string]$image.Created
                    os = [string]$image.Os
                    architecture = [string]$image.Architecture
                }
            }
    )

    $releaseVolumeEvidence = (ConvertFrom-Json (
        Invoke-NativeText -FilePath "docker" -Arguments @("volume", "inspect", $ReleaseVolume)
    ))[0]
    $dockerInfo = ConvertFrom-Json (
        Invoke-NativeText -FilePath "docker" -Arguments @("info", "--format", "{{json .}}")
    )

    $networkId = Invoke-NativeText -FilePath "docker" -Arguments @(
        "network", "ls",
        "--filter", "label=com.docker.compose.project=$ProjectName",
        "--format", "{{.ID}}"
    )
    $networkEvidence = $null
    if (-not [string]::IsNullOrWhiteSpace($networkId)) {
        $network = (ConvertFrom-Json (
            Invoke-NativeText -FilePath "docker" -Arguments @("network", "inspect", ($networkId -split "`r?`n")[0])
        ))[0]
        $networkContainers = @(
            $network.Containers.PSObject.Properties |
                ForEach-Object {
                    [ordered]@{
                        name = [string]$_.Value.Name
                        ipv4_address = [string]$_.Value.IPv4Address
                        ipv6_address = [string]$_.Value.IPv6Address
                    }
                } |
                Sort-Object name
        )
        $networkEvidence = [ordered]@{
            name = [string]$network.Name
            driver = [string]$network.Driver
            scope = [string]$network.Scope
            internal = [bool]$network.Internal
            attachable = [bool]$network.Attachable
            ipam = @($network.IPAM.Config)
            containers = $networkContainers
        }
    }

    $dockerDiskLocation = $null
    if (Test-Path -LiteralPath $dockerSettingsFile) {
        $dockerSettings = Get-Content -LiteralPath $dockerSettingsFile -Raw | ConvertFrom-Json
        $dockerDiskLocation = [string]$dockerSettings.CustomWslDistroDir
    }
    $dockerVhdx = if ([string]::IsNullOrWhiteSpace($dockerDiskLocation)) {
        $null
    }
    else {
        Join-Path $dockerDiskLocation "disk\docker_data.vhdx"
    }
    $dockerVhdxEvidence = if ($null -ne $dockerVhdx -and (Test-Path -LiteralPath $dockerVhdx)) {
        $item = Get-Item -LiteralPath $dockerVhdx
        [ordered]@{
            path = Get-SafePath -Path $item.FullName
            bytes = [int64]$item.Length
            gib = [math]::Round($item.Length / 1GB, 2)
            last_write_time_utc = $item.LastWriteTimeUtc.ToString("o")
        }
    }
    else {
        $null
    }

    $operatingSystem = Get-CimInstance Win32_OperatingSystem
    $computerSystem = Get-CimInstance Win32_ComputerSystem
    $processor = Get-CimInstance Win32_Processor | Select-Object -First 1
    $evidence = [ordered]@{
        schema_version = "cybercontrol.phase7-preflight.v1"
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        gate = "A"
        result = "PREFLIGHT_CAPTURED"
        git = [ordered]@{
            branch = $sourceBranch
            commit = $sourceCommit
            tree = $sourceTree
            clean_at_start = ($sourceStatus.Count -eq 0)
            dirty_files_at_start = @($sourceStatus)
        }
        baselines = [ordered]@{
            protected_main = [ordered]@{
                reference = $ProtectedMainRef
                commit = $protectedMainCommit
                tree = $protectedMainTree
            }
            running_product = [ordered]@{
                source_evidence_path = Get-SafePath -Path $runtimeSourceEvidenceFile
                source_evidence_sha256 = Get-FileSha256 -Path $runtimeSourceEvidenceFile
                source_commit = [string]$runtimeSourceEvidence.git.commit
                source_tree = [string]$runtimeSourceEvidence.git.tree
                compose_config_sha256 = [string]$runtimeSourceEvidence.environment.compose_config_sha256
                image_ids = $runtimeImages
                image_ids_match_source_evidence = $runtimeImageMatch
            }
        }
        source_inputs = [ordered]@{
            compose_config_sha256 = Get-TextSha256 -Text $composeConfig
            files = @(
                [ordered]@{ path = "infra/docker-compose.yml"; sha256 = Get-FileSha256 -Path $composeFile }
                [ordered]@{ path = "infra/docker-compose.release.yml"; sha256 = Get-FileSha256 -Path $releaseComposeFile }
                [ordered]@{ path = "uv.lock"; sha256 = Get-FileSha256 -Path (Join-Path $root "uv.lock") }
                [ordered]@{ path = "frontend/pnpm-lock.yaml"; sha256 = Get-FileSha256 -Path (Join-Path $root "frontend\pnpm-lock.yaml") }
            )
        }
        host = [ordered]@{
            os = [ordered]@{
                caption = [string]$operatingSystem.Caption
                version = [string]$operatingSystem.Version
                build_number = [string]$operatingSystem.BuildNumber
                architecture = [string]$operatingSystem.OSArchitecture
                last_boot_time_utc = $operatingSystem.LastBootUpTime.ToUniversalTime().ToString("o")
            }
            cpu = [ordered]@{
                name = [string]$processor.Name
                physical_cores = [int]$processor.NumberOfCores
                logical_processors = [int]$processor.NumberOfLogicalProcessors
            }
            memory = [ordered]@{
                total_bytes = [int64]$computerSystem.TotalPhysicalMemory
                free_bytes = [int64]$operatingSystem.FreePhysicalMemory * 1KB
            }
            disks = @(
                Get-PSDrive -PSProvider FileSystem |
                    ForEach-Object {
                        [ordered]@{
                            name = [string]$_.Name
                            used_bytes = [int64]$_.Used
                            free_bytes = [int64]$_.Free
                        }
                    }
            )
        }
        docker = [ordered]@{
            server_version = [string]$dockerInfo.ServerVersion
            operating_system = [string]$dockerInfo.OperatingSystem
            kernel_version = [string]$dockerInfo.KernelVersion
            architecture = [string]$dockerInfo.Architecture
            storage_driver = [string]$dockerInfo.Driver
            cgroup_version = [string]$dockerInfo.CgroupVersion
            cpu_limit = [int]$dockerInfo.NCPU
            memory_limit_bytes = [int64]$dockerInfo.MemTotal
            root_dir = [string]$dockerInfo.DockerRootDir
            desktop_disk_location = Get-SafePath -Path $dockerDiskLocation
            data_vhdx = $dockerVhdxEvidence
            release_volume = [ordered]@{
                name = [string]$releaseVolumeEvidence.Name
                driver = [string]$releaseVolumeEvidence.Driver
                scope = [string]$releaseVolumeEvidence.Scope
                created_at = [string]$releaseVolumeEvidence.CreatedAt
                labels = $releaseVolumeEvidence.Labels
                mountpoint = [string]$releaseVolumeEvidence.Mountpoint
            }
            containers = $containerEvidence
            images = $imageEvidence
            network = $networkEvidence
        }
        tools = [ordered]@{
            git = Get-CommandVersion -Command "git" -Arguments @("--version")
            docker = Get-CommandVersion -Command "docker" -Arguments @("version", "--format", "{{.Client.Version}}|{{.Server.Version}}")
            docker_compose = Get-CommandVersion -Command "docker" -Arguments @("compose", "version")
            uv = Get-CommandVersion -Command "uv" -Arguments @("--version")
            python = Get-CommandVersion -Command "python" -Arguments @("--version")
            node = Get-CommandVersion -Command "node" -Arguments @("--version")
            pnpm = Get-CommandVersion -Command "pnpm" -Arguments @("--version")
            go = Get-CommandVersion -Command "go" -Arguments @("version")
            trivy = Get-CommandVersion -Command "trivy" -Arguments @("--version")
            gitleaks = Get-CommandVersion -Command "gitleaks" -Arguments @("version")
        }
        security = [ordered]@{
            container_environment_values_recorded = $false
            sensitive_value_scan_passed = $false
        }
    }

    $json = $evidence | ConvertTo-Json -Depth 100
    $sensitiveValues = @(
        $containers.Config.Env |
            ForEach-Object {
                $name, $value = ([string]$_).Split('=', 2)
                if (
                    $name -match '(?i)(PASSWORD|SECRET|TOKEN|API_KEY|PEPPER|DATABASE_URL)' -and
                    -not [string]::IsNullOrWhiteSpace($value) -and
                    $value.Length -ge 8
                ) {
                    $value
                }
            } |
            Sort-Object -Unique
    )
    foreach ($value in $sensitiveValues) {
        if ($json.Contains($value)) {
            throw "Sensitive container environment data would be written to the preflight evidence."
        }
    }
    $evidence.security.sensitive_value_scan_passed = $true
    $json = $evidence | ConvertTo-Json -Depth 100

    [IO.Directory]::CreateDirectory((Split-Path -Parent $evidenceFile)) | Out-Null
    [IO.File]::WriteAllText($evidenceFile, $json + "`n", [Text.UTF8Encoding]::new($false))

    $running = @($containerEvidence | Where-Object { $_.state -eq "running" }).Count
    $healthy = @($containerEvidence | Where-Object { $_.health -eq "healthy" }).Count
    $report = @"
# Phase 7 Gate A Preflight Report

- Result: PREFLIGHT_CAPTURED
- Generated (UTC): $($evidence.generated_at_utc)
- Source branch: $sourceBranch
- Tooling source commit: $sourceCommit
- Tooling source tree: $sourceTree
- Protected main commit: $protectedMainCommit
- Running product source commit: $($runtimeSourceEvidence.git.commit)
- Running image IDs match immutable source evidence: $runtimeImageMatch
- Clean source at capture: $($evidence.git.clean_at_start)
- Compose project: $ProjectName
- Compose configuration SHA256: $($evidence.source_inputs.compose_config_sha256)
- Release PostgreSQL volume: $ReleaseVolume
- Docker Desktop disk location: $dockerDiskLocation
- Docker capacity: $($dockerInfo.NCPU) CPUs, $([math]::Round($dockerInfo.MemTotal / 1GB, 2)) GiB RAM
- Project containers: $($containerEvidence.Count) total, $running running, $healthy healthy
- Sensitive container environment values recorded: false
- Sensitive value scan passed: $($evidence.security.sensitive_value_scan_passed)

This report is a read-only reproducibility snapshot. It does not claim that the
2,000-connection load, eight-hour soak, disaster recovery, sealed Provider or
production operations gates have passed.
"@
    [IO.Directory]::CreateDirectory((Split-Path -Parent $reportFile)) | Out-Null
    [IO.File]::WriteAllText($reportFile, $report.Trim() + "`n", [Text.UTF8Encoding]::new($false))

    Write-Output $json
}
finally {
    Pop-Location
}
