Set-StrictMode -Version Latest

function Get-GateCCapacityState {
    param(
        [Parameter(Mandatory = $true)][int64]$FreeBytes,
        [Parameter(Mandatory = $true)][double]$WarningGiB,
        [Parameter(Mandatory = $true)][double]$StopGiB
    )

    if ($FreeBytes -lt [int64]($StopGiB * 1GB)) {
        return "HARD_STOP"
    }
    if ($FreeBytes -lt [int64]($WarningGiB * 1GB)) {
        return "WARNING"
    }
    return "NORMAL"
}

function Get-GateCHostCapacityTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][double]$AdmissionGiB,
        [Parameter(Mandatory = $true)][double]$WarningGiB,
        [Parameter(Mandatory = $true)][double]$StopGiB
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $driveRoot = [IO.Path]::GetPathRoot($resolvedPath)
    if ([string]::IsNullOrWhiteSpace($driveRoot)) {
        throw "Gate C capacity target $Name has no resolvable drive: $Path"
    }
    $driveName = $driveRoot.TrimEnd('\').TrimEnd(':')
    $drive = Get-PSDrive -Name $driveName -ErrorAction Stop
    $freeBytes = [int64]$drive.Free
    return [ordered]@{
        name = $Name
        probe = "HOST_PS_DRIVE"
        path = $resolvedPath
        root = $driveRoot
        drive = $driveName
        free_bytes = $freeBytes
        free_gib = [math]::Round([double]$freeBytes / 1GB, 3)
        admission_ready = ($freeBytes -ge [int64]($AdmissionGiB * 1GB))
        state = Get-GateCCapacityState `
            -FreeBytes $freeBytes -WarningGiB $WarningGiB -StopGiB $StopGiB
    }
}

function Get-GateCDockerInternalCapacityTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][double]$AdmissionGiB,
        [Parameter(Mandatory = $true)][double]$WarningGiB,
        [Parameter(Mandatory = $true)][double]$StopGiB
    )

    $output = @(& wsl.exe -d docker-desktop -- df -B 1 $Path 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to probe Docker Desktop internal capacity at $Path."
    }
    $filesystemLine = @(
        $output | Where-Object {
            [string]$_ -match '^\s*\S+\s+\d+\s+\d+\s+\d+\s+\d+%\s+\S+\s*$'
        }
    ) | Select-Object -Last 1
    if ($null -eq $filesystemLine) {
        throw "Docker Desktop internal capacity output was not parseable."
    }
    $columns = @(([string]$filesystemLine).Trim() -split '\s+')
    if ($columns.Count -lt 6 -or $columns[3] -notmatch '^\d+$') {
        throw "Docker Desktop internal capacity output has an invalid available-byte field."
    }
    $freeBytes = [int64]$columns[3]
    return [ordered]@{
        name = "docker_internal_root"
        probe = "WSL_DF"
        distribution = "docker-desktop"
        path = $Path
        filesystem = $columns[0]
        free_bytes = $freeBytes
        free_gib = [math]::Round([double]$freeBytes / 1GB, 3)
        admission_ready = ($freeBytes -ge [int64]($AdmissionGiB * 1GB))
        state = Get-GateCCapacityState `
            -FreeBytes $freeBytes -WarningGiB $WarningGiB -StopGiB $StopGiB
    }
}

function Get-GateCMultiRootCapacitySnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$ResultsRoot,
        [Parameter(Mandatory = $true)][string]$DockerDataRoot,
        [Parameter(Mandatory = $true)][string]$DockerInternalRoot,
        [Parameter(Mandatory = $true)][string]$PolicyRevision,
        [Parameter(Mandatory = $true)][double]$AdmissionGiB,
        [Parameter(Mandatory = $true)][double]$WarningGiB,
        [Parameter(Mandatory = $true)][double]$StopGiB,
        [ValidatePattern('^Gate-C-12-v[12]\.0$')]
        [string]$ProcessVersion = "Gate-C-12-v1.0",
        [string]$ProjectName
    )

    if ($StopGiB -ge $WarningGiB -or $WarningGiB -ge $AdmissionGiB) {
        throw "Gate C capacity thresholds must satisfy stop < warning < admission."
    }
    if (-not (Test-Path -LiteralPath $DockerDataRoot -PathType Container)) {
        throw "Docker data root does not exist: $DockerDataRoot"
    }

    $targets = @(
        Get-GateCHostCapacityTarget -Name "results_root" -Path $ResultsRoot `
            -AdmissionGiB $AdmissionGiB -WarningGiB $WarningGiB -StopGiB $StopGiB
        Get-GateCHostCapacityTarget -Name "docker_data_root" -Path $DockerDataRoot `
            -AdmissionGiB $AdmissionGiB -WarningGiB $WarningGiB -StopGiB $StopGiB
        Get-GateCDockerInternalCapacityTarget -Path $DockerInternalRoot `
            -AdmissionGiB $AdmissionGiB -WarningGiB $WarningGiB -StopGiB $StopGiB
    )
    $hardStops = @($targets | Where-Object { $_.state -eq "HARD_STOP" })
    $warnings = @($targets | Where-Object { $_.state -eq "WARNING" })
    $state = if ($hardStops.Count -gt 0) {
        "HARD_STOP"
    }
    elseif ($warnings.Count -gt 0) {
        "WARNING"
    }
    else {
        "NORMAL"
    }
    $minimum = $targets | Sort-Object free_bytes | Select-Object -First 1
    return [ordered]@{
        schema_version = "cybercontrol.gate-c-capacity-sample.v2"
        process_version = $ProcessVersion
        policy_revision = $PolicyRevision
        project = $ProjectName
        sampled_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        admission_gib = $AdmissionGiB
        warning_gib = $WarningGiB
        stop_gib = $StopGiB
        state = $state
        admission_ready = (@($targets | Where-Object { -not $_.admission_ready }).Count -eq 0)
        free_bytes = [int64]$minimum.free_bytes
        free_gib = [double]$minimum.free_gib
        drive = "MULTI_ROOT"
        limiting_target = [string]$minimum.name
        warning_targets = @($warnings | ForEach-Object { $_.name })
        hard_stop_targets = @($hardStops | ForEach-Object { $_.name })
        targets = $targets
    }
}
