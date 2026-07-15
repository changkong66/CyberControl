[CmdletBinding()]
param(
    [switch]$FromGitCredentialManager,
    [switch]$Clear
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($Clear) {
    Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue
    Write-Host "GH_TOKEN was removed from the current PowerShell process." -ForegroundColor Green
    return
}

if ($FromGitCredentialManager) {
    $previousInteractive = $env:GCM_INTERACTIVE
    try {
        $env:GCM_INTERACTIVE = "Never"
        $lines = @("protocol=https`nhost=github.com`n`n" | git credential fill)
        if ($LASTEXITCODE -ne 0) {
            throw "Git Credential Manager has no non-interactive GitHub credential."
        }
        $credential = @{}
        foreach ($line in $lines) {
            $separator = $line.IndexOf("=")
            if ($separator -gt 0) {
                $credential[$line.Substring(0, $separator)] = $line.Substring($separator + 1)
            }
        }
        $plainToken = $credential["password"]
        $credential.Clear()
    } finally {
        if ($null -eq $previousInteractive) {
            Remove-Item Env:GCM_INTERACTIVE -ErrorAction SilentlyContinue
        } else {
            $env:GCM_INTERACTIVE = $previousInteractive
        }
    }
} else {
    $secureToken = Read-Host "GitHub fine-grained token" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

if ([string]::IsNullOrWhiteSpace($plainToken) -or $plainToken -match "\s") {
    throw "A non-empty GitHub token without whitespace is required."
}
Set-Item Env:GH_TOKEN -Value $plainToken
$plainToken = $null

Write-Host (
    "GH_TOKEN is available only in the current PowerShell process. " +
    "It was not written to disk or to a persistent environment scope."
) -ForegroundColor Green
