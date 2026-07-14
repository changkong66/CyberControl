[CmdletBinding()]
param(
    [string]$UvVersion = "0.11.28",
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = (Get-Command python -ErrorAction Stop).Source

function Add-CurrentUserScriptsPath {
    $scripts = & $python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"
    $scripts = $scripts.Trim()
    if (($env:Path -split ";") -notcontains $scripts) {
        $env:Path = "$scripts;$env:Path"
    }
}

function Invoke-Native {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Description
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

if ((& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')") -ne "3.11") {
    throw "Python 3.11 is required for the Phase 1.1 environment."
}

Add-CurrentUserScriptsPath
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv -or (& $uv.Source --version) -notmatch "uv $([regex]::Escape($UvVersion))") {
    Invoke-Native -Executable $python -Arguments @(
        "-m", "pip", "install", "--user", "uv==$UvVersion"
    ) -Description "uv installation"
    Add-CurrentUserScriptsPath
    $uv = Get-Command uv -ErrorAction Stop
}

Push-Location $repositoryRoot
try {
    if ($Recreate -and (Test-Path ".venv")) {
        $resolved = (Resolve-Path ".venv").Path
        $allowed = $repositoryRoot.TrimEnd("\") + "\"
        if (-not $resolved.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a virtual environment outside the repository."
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    Invoke-Native -Executable $uv.Source -Arguments @("lock", "--check") `
        -Description "lock-file validation"
    Invoke-Native -Executable $uv.Source -Arguments @(
        "sync", "--frozen", "--all-packages", "--all-extras"
    ) -Description "frozen workspace synchronization"
    Invoke-Native -Executable $uv.Source -Arguments @(
        "run", "--frozen", "python", "-c",
        "import sys; assert sys.version_info[:2] == (3, 11); print(sys.version)"
    ) -Description "Python runtime validation"
}
finally {
    Pop-Location
}

Write-Host "Python workspace synchronization passed." -ForegroundColor Green
