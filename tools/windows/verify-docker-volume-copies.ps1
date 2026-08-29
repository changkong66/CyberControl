[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]] $VolumeName,

    [Parameter(Mandatory = $true)]
    [string] $OutputPath,

    [string] $ProbeImage = "alpine:3.22",

    [string] $ProcessVersion = "Gate-C-12-v1.0"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$temporaryPrefix = "gatec12_migration_verify_"
$startedAt = [DateTimeOffset]::UtcNow
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-DockerText {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)

    $output = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return ($output -join "`n").Trim()
}

function Get-VolumeFingerprint {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][bool] $ReadOnly
    )

    $mount = "type=volume,src=$Name,dst=/data"
    if ($ReadOnly) {
        $mount += ",readonly"
    }

    $script = @'
set -eu
cd /data
metadata="$({ find . -mindepth 1 -xdev -print0 | sort -z | xargs -0 -r stat -c '%n|%F|%a|%u|%g'; find . -mindepth 1 -xdev -type f -print0 | sort -z | xargs -0 -r stat -c '%n|file-size|%s'; } | sort | sha256sum | cut -d' ' -f1)"
content="$({ find . -xdev -type f -print0 | sort -z | xargs -0 -r sha256sum; find . -xdev -type l -print0 | sort -z | while IFS= read -r -d '' item; do printf '%s|%s\n' "$item" "$(readlink "$item")"; done; } | sha256sum | cut -d' ' -f1)"
bytes="$(du -sk . | cut -f1)"
files="$(find . -xdev -type f | wc -l | tr -d ' ')"
dirs="$(find . -xdev -type d | wc -l | tr -d ' ')"
links="$(find . -xdev -type l | wc -l | tr -d ' ')"
pg="$(cat ./PG_VERSION 2>/dev/null || true)"
printf '%s|%s|%s|%s|%s|%s|%s\n' "$metadata" "$content" "$bytes" "$files" "$dirs" "$links" "$pg"
'@

    $raw = Invoke-DockerText -Arguments @(
        "run", "--rm", "--network", "none", "--mount", $mount,
        $ProbeImage, "sh", "-ec", $script
    )
    $parts = $raw.Split("|")
    if ($parts.Count -ne 7) {
        throw "unexpected fingerprint output for volume ${Name}: $raw"
    }
    return [ordered]@{
        metadata_sha256 = $parts[0]
        content_sha256 = $parts[1]
        kibibytes = [Int64]$parts[2]
        files = [Int64]$parts[3]
        directories = [Int64]$parts[4]
        symlinks = [Int64]$parts[5]
        postgres_version = $parts[6]
    }
}

try {
    $runningBefore = @(Invoke-DockerText -Arguments @("ps", "--quiet") -ErrorAction Stop |
        Where-Object { $_ }).Count
    if ($runningBefore -ne 0) {
        throw "volume verification requires zero running containers; found $runningBefore"
    }

    $knownVolumes = @(
        (Invoke-DockerText -Arguments @("volume", "ls", "--quiet")) -split "`r?`n" |
            Where-Object { $_ }
    )

    foreach ($source in $VolumeName) {
        if ($source -notin $knownVolumes) {
            throw "required source volume does not exist: $source"
        }

        $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 12)
        $temporary = "$temporaryPrefix$suffix"
        if (-not $temporary.StartsWith($temporaryPrefix, [StringComparison]::Ordinal)) {
            throw "temporary volume name escaped the safety prefix"
        }

        $created = $false
        try {
            $null = Invoke-DockerText -Arguments @(
                "volume", "create",
                "--label", "com.cybercontrol.process-version=$ProcessVersion",
                "--label", "com.cybercontrol.purpose=docker-migration-copy-verification",
                "--label", "com.cybercontrol.source-volume=$source",
                $temporary
            )
            $created = $true

            $copyScript = "set -eu; cd /source; tar --numeric-owner -cpf - . | tar --numeric-owner -xpf - -C /copy"
            $null = Invoke-DockerText -Arguments @(
                "run", "--rm", "--network", "none",
                "--mount", "type=volume,src=$source,dst=/source,readonly",
                "--mount", "type=volume,src=$temporary,dst=/copy",
                $ProbeImage, "sh", "-ec", $copyScript
            )

            $sourceFingerprint = Get-VolumeFingerprint -Name $source -ReadOnly $true
            $copyFingerprint = Get-VolumeFingerprint -Name $temporary -ReadOnly $true
            $strictMatches = (
                $sourceFingerprint.metadata_sha256 -eq $copyFingerprint.metadata_sha256 -and
                $sourceFingerprint.content_sha256 -eq $copyFingerprint.content_sha256 -and
                $sourceFingerprint.files -eq $copyFingerprint.files -and
                $sourceFingerprint.directories -eq $copyFingerprint.directories -and
                $sourceFingerprint.symlinks -eq $copyFingerprint.symlinks -and
                $sourceFingerprint.postgres_version -eq $copyFingerprint.postgres_version
            )
            $results.Add([ordered]@{
                volume = $source
                copy_verification = if ($strictMatches) { "PASS" } else { "FAIL" }
                source = $sourceFingerprint
                copy = $copyFingerprint
                physical_allocation_delta_kib = (
                    $copyFingerprint.kibibytes - $sourceFingerprint.kibibytes
                )
                source_mounted_read_only = $true
                temporary_copy_volume = $temporary
                temporary_copy_removed = $false
            })
            if (-not $strictMatches) {
                throw "source and copy fingerprints differ for volume $source"
            }
        }
        finally {
            if ($created) {
                if (-not $temporary.StartsWith($temporaryPrefix, [StringComparison]::Ordinal)) {
                    throw "refusing to remove a non-verification volume: $temporary"
                }
                $null = Invoke-DockerText -Arguments @("volume", "rm", $temporary)
                if ($results.Count -gt 0 -and $results[$results.Count - 1].volume -eq $source) {
                    $results[$results.Count - 1].temporary_copy_removed = $true
                }
            }
        }
    }

    $runningAfter = @(Invoke-DockerText -Arguments @("ps", "--quiet") |
        Where-Object { $_ }).Count
    $leftovers = @(
        (Invoke-DockerText -Arguments @("volume", "ls", "--quiet", "--filter", "label=com.cybercontrol.purpose=docker-migration-copy-verification")) -split "`r?`n" |
            Where-Object { $_ }
    )
    if ($runningAfter -ne 0 -or $leftovers.Count -ne 0) {
        throw "verification cleanup failed: running=$runningAfter temporary_volumes=$($leftovers.Count)"
    }

    $report = [ordered]@{
        schema_version = "cybercontrol.docker-migration-volume-copy-verification.v1"
        process_version = $ProcessVersion
        classification = "NON_ACCEPTANCE_INFRASTRUCTURE_VERIFICATION"
        generated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        probe_image = $ProbeImage
        source_access = "READ_ONLY_VOLUME_MOUNT"
        copy_method = "tar --numeric-owner"
        comparison_dimensions = @(
            "file-content-sha256",
            "non-root-path-type-mode-uid-gid-size",
            "file-directory-symlink-counts",
            "postgres-version"
        )
        non_decisive_observations = @(
            "volume-root-directory-metadata",
            "filesystem-physical-allocation-kibibytes"
        )
        required_volume_count = $VolumeName.Count
        passed_volume_count = @($results | Where-Object { $_.copy_verification -eq "PASS" }).Count
        running_containers_before = $runningBefore
        running_containers_after = $runningAfter
        temporary_volumes_remaining = $leftovers
        started_at_utc = $startedAt.ToString("o")
        volumes = $results
        result = "PASS"
    }

    $parent = Split-Path -Parent $OutputPath
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8NoBOM
    Write-Output $OutputPath
}
catch {
    $failure = [ordered]@{
        schema_version = "cybercontrol.docker-migration-volume-copy-verification.v1"
        process_version = $ProcessVersion
        classification = "NON_ACCEPTANCE_INFRASTRUCTURE_VERIFICATION"
        generated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        started_at_utc = $startedAt.ToString("o")
        volumes = $results
        result = "FAIL"
        error = $_.Exception.Message
    }
    $parent = Split-Path -Parent $OutputPath
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $failure | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8NoBOM
    throw
}
