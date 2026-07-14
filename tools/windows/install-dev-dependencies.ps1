[CmdletBinding()]
param(
    [ValidateSet("Auto", "Machine", "User")]
    [string]$Scope = "Auto",
    [string]$RuffVersion = "0.15.21",
    [int]$MaxAttempts = 3
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-WithRetry {
    param(
        [scriptblock]$Operation,
        [string]$Description
    )
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            & $Operation
            return
        }
        catch {
            if ($attempt -eq $MaxAttempts) {
                throw "$Description failed after $MaxAttempts attempts: $($_.Exception.Message)"
            }
            $delay = [Math]::Min(10, [Math]::Pow(2, $attempt))
            Write-Warning "$Description failed on attempt $attempt. Retrying in $delay seconds."
            Start-Sleep -Seconds $delay
        }
    }
}

function Add-EnvironmentPath {
    param(
        [string]$Directory,
        [ValidateSet("User", "Machine")]
        [string]$Target
    )
    $resolved = [IO.Path]::GetFullPath($Directory)
    $current = [Environment]::GetEnvironmentVariable("Path", $Target)
    $entries = @($current -split ";" | Where-Object { $_ })
    if ($entries -notcontains $resolved) {
        $updatedEntries = @($resolved) + $entries
        [Environment]::SetEnvironmentVariable(
            "Path",
            ($updatedEntries -join ";"),
            $Target
        )
    }
    if (($env:Path -split ";") -notcontains $resolved) {
        $env:Path = "$resolved;$env:Path"
    }
}

function Set-PersistentEnvironment {
    param(
        [string]$Name,
        [string]$Value,
        [ValidateSet("User", "Machine")]
        [string]$Target
    )
    [Environment]::SetEnvironmentVariable($Name, $Value, $Target)
    Set-Item -Path "Env:$Name" -Value $Value
}

function Assert-Command {
    param(
        [string]$Name,
        [string[]]$Arguments
    )
    $command = Get-Command $Name -ErrorAction Stop
    Write-Host "$Name => $($command.Source)" -ForegroundColor Green
    & $command.Source @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name validation failed with exit code $LASTEXITCODE"
    }
}

function Install-Chocolatey {
    param([string]$InstallTarget)
    $knownRoot = if ($InstallTarget -eq "Machine") {
        Join-Path $env:ProgramData "chocolatey"
    } else {
        [Environment]::GetEnvironmentVariable("ChocolateyInstall", "User")
    }
    if (-not $knownRoot) { $knownRoot = Join-Path $env:LOCALAPPDATA "Chocolatey" }
    $knownBin = Join-Path $knownRoot "bin"
    if (Test-Path (Join-Path $knownBin "choco.exe")) {
        Add-EnvironmentPath -Directory $knownBin -Target $InstallTarget
        return
    }
    Write-Step "Installing Chocolatey package manager"
    if ($InstallTarget -eq "Machine") {
        Invoke-WithRetry -Description "Chocolatey machine installation" -Operation {
            winget install --id Chocolatey.Chocolatey --exact --source winget `
                --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw "winget returned $LASTEXITCODE" }
        }
        Add-EnvironmentPath -Directory "$env:ProgramData\chocolatey\bin" -Target Machine
        return
    }

    $chocolateyRoot = Join-Path $env:LOCALAPPDATA "Chocolatey"
    Set-PersistentEnvironment -Name "ChocolateyInstall" -Value $chocolateyRoot -Target User
    Invoke-WithRetry -Description "Chocolatey user installation" -Operation {
        $installer = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "https://community.chocolatey.org/install.ps1" `
            -TimeoutSec 60
        & ([scriptblock]::Create($installer.Content))
    }
    Add-EnvironmentPath -Directory (Join-Path $chocolateyRoot "bin") -Target User
}

function Install-GoUser {
    Write-Step "Installing the official stable Go SDK for the current user"
    $releases = Invoke-RestMethod -Uri "https://go.dev/dl/?mode=json" -TimeoutSec 60
    $release = $releases | Where-Object { $_.stable } | Select-Object -First 1
    if (-not $release) { throw "The official Go release feed returned no stable release." }
    $archive = $release.files | Where-Object {
        $_.os -eq "windows" -and $_.arch -eq "amd64" -and $_.kind -eq "archive"
    } | Select-Object -First 1
    if (-not $archive) { throw "No Windows AMD64 Go archive was found." }

    $versionRoot = Join-Path $env:LOCALAPPDATA "Programs\Go\$($release.version)"
    $goRoot = Join-Path $versionRoot "go"
    $requiredFiles = @(
        (Join-Path $goRoot "bin\go.exe"),
        (Join-Path $goRoot "src\encoding\json\decode.go"),
        (Join-Path $goRoot "pkg\tool\windows_amd64\compile.exe")
    )
    $installationComplete = @($requiredFiles | Where-Object { -not (Test-Path $_) }).Count -eq 0
    if (-not $installationComplete) {
        $tempRoot = Join-Path $env:TEMP "liyans-go-$($release.version)"
        $zipPath = Join-Path $tempRoot $archive.filename
        New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
        $archiveValid = $false
        if (Test-Path $zipPath) {
            $cachedHash = (Get-FileHash -Algorithm SHA256 -Path $zipPath).Hash.ToLowerInvariant()
            $archiveValid = $cachedHash -eq $archive.sha256.ToLowerInvariant()
        }
        if (-not $archiveValid) {
            Invoke-WithRetry -Description "Go SDK download" -Operation {
                Invoke-WebRequest -UseBasicParsing -Uri "https://go.dev/dl/$($archive.filename)" `
                    -OutFile $zipPath -TimeoutSec 300
            }
        }
        $actualHash = (Get-FileHash -Algorithm SHA256 -Path $zipPath).Hash.ToLowerInvariant()
        if ($actualHash -ne $archive.sha256.ToLowerInvariant()) {
            throw "Go archive SHA-256 mismatch. Expected $($archive.sha256), got $actualHash."
        }
        if (Test-Path $versionRoot) {
            $allowedRoot = [IO.Path]::GetFullPath(
                (Join-Path $env:LOCALAPPDATA "Programs\Go")
            ).TrimEnd("\") + "\"
            $resolvedTarget = [IO.Path]::GetFullPath($versionRoot)
            if (-not $resolvedTarget.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to replace Go outside the user installation root: $resolvedTarget"
            }
            Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $versionRoot | Out-Null
        Expand-Archive -LiteralPath $zipPath -DestinationPath $versionRoot -Force
        $missingFiles = @($requiredFiles | Where-Object { -not (Test-Path $_) })
        if ($missingFiles) {
            throw "Go extraction is incomplete. Missing: $($missingFiles -join ', ')"
        }
    }
    Set-PersistentEnvironment -Name "GOROOT" -Value $goRoot -Target User
    Add-EnvironmentPath -Directory (Join-Path $goRoot "bin") -Target User
}

function Install-GoMachine {
    Write-Step "Installing the official stable Go SDK for all users"
    Invoke-WithRetry -Description "Go SDK machine installation" -Operation {
        winget install --id GoLang.Go --exact --source winget --silent `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "winget returned $LASTEXITCODE" }
    }
    Add-EnvironmentPath -Directory "C:\Program Files\Go\bin" -Target Machine
}

function Install-Ruff {
    param([string]$InstallTarget)
    Write-Step "Installing Ruff $RuffVersion for Python 3.11"
    $python = (Get-Command python -ErrorAction Stop).Source
    $arguments = @("-m", "pip", "install", "--disable-pip-version-check", "ruff==$RuffVersion")
    if ($InstallTarget -eq "User") { $arguments += "--user" }
    Invoke-WithRetry -Description "Ruff installation" -Operation {
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw "pip returned $LASTEXITCODE" }
    }
    if ($InstallTarget -eq "User") {
        $scriptsDirectory = & $python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"
        Add-EnvironmentPath -Directory $scriptsDirectory.Trim() -Target User
    }
}

function Install-CompilerTools {
    param([string]$InstallTarget)
    Write-Step "Installing GCC and GNU Make"
    if ($InstallTarget -eq "Machine") {
        Invoke-WithRetry -Description "GCC and Make installation" -Operation {
            choco install mingw make -y --no-progress --limit-output
            if ($LASTEXITCODE -ne 0) { throw "Chocolatey returned $LASTEXITCODE" }
        }
        return
    }

    $winLibsRoot = Join-Path $env:LOCALAPPDATA "Programs\WinLibs"
    $expectedBin = Join-Path $winLibsRoot "mingw64\bin"
    $gcc = if (Test-Path (Join-Path $expectedBin "gcc.exe")) {
        Get-Item (Join-Path $expectedBin "gcc.exe")
    } elseif (Test-Path $winLibsRoot) {
        Get-ChildItem -Path $winLibsRoot -Recurse -Filter gcc.exe -ErrorAction Stop |
            Select-Object -First 1
    } else {
        $null
    }
    if (-not $gcc) {
        Invoke-WithRetry -Description "WinLibs user installation" -Operation {
            winget install --id BrechtSanders.WinLibs.POSIX.UCRT --exact --source winget `
                --scope user --silent --location $winLibsRoot `
                --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw "winget returned $LASTEXITCODE" }
        }
        $gcc = Get-ChildItem -Path $winLibsRoot -Recurse -Filter gcc.exe -ErrorAction Stop |
            Select-Object -First 1
    }
    if (-not $gcc) { throw "WinLibs installation completed but gcc.exe was not found." }
    Add-EnvironmentPath -Directory $gcc.Directory.FullName -Target User
    $nativeMake = if (Test-Path (Join-Path $gcc.Directory.FullName "mingw32-make.exe")) {
        Get-Item (Join-Path $gcc.Directory.FullName "mingw32-make.exe")
    } else {
        Get-ChildItem -Path $winLibsRoot -Recurse -Filter mingw32-make.exe `
            -ErrorAction Stop | Select-Object -First 1
    }
    if (-not $nativeMake) { throw "WinLibs installation completed but GNU Make was not found." }
    $wrapperRoot = Join-Path $env:LOCALAPPDATA "Programs\LiyanTools\bin"
    New-Item -ItemType Directory -Force -Path $wrapperRoot | Out-Null
    $wrapperPath = Join-Path $wrapperRoot "make.cmd"
    $wrapperBody = "@echo off`r`n`"$($nativeMake.FullName)`" %*`r`n"
    Set-Content -LiteralPath $wrapperPath -Value $wrapperBody -Encoding ASCII
    Add-EnvironmentPath -Directory $wrapperRoot -Target User
}

$isAdmin = Test-Administrator
$effectiveScope = if ($Scope -eq "Auto") {
    if ($isAdmin) { "Machine" } else { "User" }
} else {
    $Scope
}
if ($effectiveScope -eq "Machine" -and -not $isAdmin) {
    throw "Machine scope requires an Administrator PowerShell terminal. Use -Scope User here."
}

Write-Step "Environment baseline"
Write-Host "PowerShell: $($PSVersionTable.PSVersion)"
Write-Host "Architecture: $env:PROCESSOR_ARCHITECTURE"
Write-Host "Administrator: $isAdmin"
Write-Host "Install scope: $effectiveScope"
if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "This script currently supports Windows AMD64 only."
}
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget is required. Install or update Microsoft App Installer first."
}

Install-Chocolatey -InstallTarget $effectiveScope
if ($effectiveScope -eq "Machine") { Install-GoMachine } else { Install-GoUser }

$goPath = Join-Path $env:USERPROFILE "go"
$goModCache = Join-Path $goPath "pkg\mod"
$goBuildCache = Join-Path $env:LOCALAPPDATA "go-build"
New-Item -ItemType Directory -Force -Path $goPath, $goModCache, $goBuildCache | Out-Null
Set-PersistentEnvironment -Name "GOPATH" -Value $goPath -Target User
Set-PersistentEnvironment -Name "GOMODCACHE" -Value $goModCache -Target User
Set-PersistentEnvironment -Name "GOCACHE" -Value $goBuildCache -Target User

Install-Ruff -InstallTarget $effectiveScope
Install-CompilerTools -InstallTarget $effectiveScope

Write-Step "Validating installed commands"
Assert-Command -Name go -Arguments @("version")
Assert-Command -Name go -Arguments @("env", "GOROOT", "GOPATH", "GOMODCACHE", "GOCACHE")
Assert-Command -Name ruff -Arguments @("version")
Assert-Command -Name choco -Arguments @("--version")
Assert-Command -Name gcc -Arguments @("--version")
$makeCommand = Get-Command make -ErrorAction SilentlyContinue
if (-not $makeCommand) { $makeCommand = Get-Command mingw32-make -ErrorAction Stop }
Write-Host "make => $($makeCommand.Source)" -ForegroundColor Green
& $makeCommand.Source --version
if ($LASTEXITCODE -ne 0) { throw "GNU Make validation failed." }

Write-Host "`nAll requested development dependencies are available." -ForegroundColor Green
