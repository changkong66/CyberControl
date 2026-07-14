[CmdletBinding()]
param(
    [string]$ProjectRoot = "C:\Users\wch06\Documents\CyberControl",
    [switch]$SkipRace
)

$ErrorActionPreference = "Stop"
$contractsRoot = Join-Path $ProjectRoot "packages\contracts-go"
$logRoot = Join-Path $ProjectRoot "artifacts\toolchain"
$logPath = Join-Path $logRoot "go-build.log"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

# Merge persisted paths because automation hosts do not automatically refresh
# their parent process after an installer updates the user environment.
$persistedPaths = @(
    [Environment]::GetEnvironmentVariable("Path", "User"),
    [Environment]::GetEnvironmentVariable("Path", "Machine")
) -join ";"
foreach ($entry in @($persistedPaths -split ";" | Where-Object { $_ })) {
    if (($env:Path -split ";") -notcontains $entry) { $env:Path = "$entry;$env:Path" }
}
foreach ($name in @("GOROOT", "GOPATH", "GOMODCACHE", "GOCACHE")) {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if ($value) { Set-Item -Path "Env:$name" -Value $value }
}

function Write-Log {
    param([string]$Message)
    Write-Host $Message
    $Message | Out-File -LiteralPath $logPath -Append -Encoding utf8
}

function Invoke-GoStep {
    param(
        [string]$Title,
        [string[]]$Arguments
    )
    Write-Log "`n==> $Title"
    $stdoutPath = [IO.Path]::GetTempFileName()
    $stderrPath = [IO.Path]::GetTempFileName()
    try {
        $process = Start-Process `
            -FilePath $script:GoExecutable `
            -ArgumentList $Arguments `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        $exitCode = $process.ExitCode
        $output = @(
            Get-Content -LiteralPath $stdoutPath -ErrorAction SilentlyContinue
            Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue
        )
        foreach ($line in $output) { Write-Log $line }
    }
    finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
    if ($exitCode -ne 0) {
        throw "$Title failed with exit code $exitCode. See $logPath"
    }
}

if (-not (Test-Path $contractsRoot)) {
    throw "Go contracts directory does not exist: $contractsRoot"
}
if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    throw "go is not available on PATH. Run install-dev-dependencies.ps1 first."
}
$script:GoExecutable = (Get-Command go -ErrorAction Stop).Source

Set-Content -Path $logPath -Value "Liyan Go contract validation $(Get-Date -Format o)" `
    -Encoding utf8
Push-Location $contractsRoot
try {
    if (-not (Test-Path "go.mod")) {
        Invoke-GoStep -Title "Initialize module" -Arguments @(
            "mod", "init", "github.com/liyans/contracts-go"
        )
    }
    Invoke-GoStep -Title "Normalize Go language version" -Arguments @("mod", "edit", "-go=1.22")
    Invoke-GoStep -Title "Resolve module graph" -Arguments @("mod", "tidy", "-v")
    Invoke-GoStep -Title "Download dependencies" -Arguments @("mod", "download")
    Invoke-GoStep -Title "Verify module cache" -Arguments @("mod", "verify")

    Write-Log "`n==> Format source"
    & gofmt -w .
    if ($LASTEXITCODE -ne 0) { throw "gofmt failed with exit code $LASTEXITCODE" }

    Invoke-GoStep -Title "Static semantic validation" -Arguments @("vet", "./...")
    Invoke-GoStep -Title "Unit tests with coverage" -Arguments @("test", "-cover", "./...")
    if (-not $SkipRace) {
        Invoke-GoStep -Title "Race-enabled unit tests" -Arguments @("test", "-race", "./...")
    }
    Invoke-GoStep -Title "Compile all packages" -Arguments @("build", "./...")
    Invoke-GoStep -Title "List resolved packages" -Arguments @("list", "-deps", "./...")
}
finally {
    Pop-Location
}

Write-Host "Go contract validation passed. Log: $logPath" -ForegroundColor Green
