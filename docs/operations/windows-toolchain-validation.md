# Windows Toolchain Installation and Validation

## 1. Execution Order

### Administrator PowerShell

Use this path on CI builders, shared development machines, or when system-wide
commands are required.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Set-Location C:\Users\wch06\Documents\CyberControl
.\tools\windows\install-dev-dependencies.ps1 -Scope Machine
.\tools\windows\build-go-contracts.ps1
ruff check packages\contracts-python backend tools --config ruff.toml
```

Machine scope installs Chocolatey through Winget, installs the official Go SDK,
and installs MinGW/GNU Make through Chocolatey. The script refuses Machine scope
when the current terminal is not elevated.

### Standard User PowerShell

This was the path executed for the current workspace.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Set-Location C:\Users\wch06\Documents\CyberControl
.\tools\windows\install-dev-dependencies.ps1 -Scope User
.\tools\windows\build-go-contracts.ps1
ruff check packages\contracts-python backend tools --config ruff.toml
```

User scope installs the official Go archive under `%LOCALAPPDATA%`, Ruff under
the Python 3.11 user site, Chocolatey under `%LOCALAPPDATA%\Chocolatey`, and the
portable WinLibs toolchain under `%LOCALAPPDATA%\Programs\WinLibs`.

Open a new PowerShell after installation when running commands manually. The
project scripts also merge persisted User and Machine PATH values so automation
hosts do not depend on a shell restart.

## 2. Delivered Files

| File | Purpose |
|---|---|
| `tools/windows/install-dev-dependencies.ps1` | idempotent toolchain installation, retry, checksums, PATH and cache setup |
| `tools/windows/build-go-contracts.ps1` | Go module normalization, dependency verification, Vet, tests, Race, and build |
| `ruff.toml` | Python 3.11 strict lint and format policy |
| `packages/contracts-go/contracts/contracts_test.go` | Envelope and Candidate JSON/type contract tests |
| `artifacts/toolchain/go-build.log` | latest complete Go validation log |
| `artifacts/toolchain/ruff-initial.log` | initial required-path Ruff findings |
| `artifacts/toolchain/ruff-final-all.log` | final backend/contracts/tools Ruff result |

## 3. Installed Environment

Actual validated versions on 2026-07-14:

| Component | Version | Location |
|---|---|---|
| Go | 1.26.5 windows/amd64 | `%LOCALAPPDATA%\Programs\Go\go1.26.5\go` |
| Ruff | 0.15.21 | `%APPDATA%\Python\Python311\Scripts\ruff.exe` |
| Chocolatey | 2.7.3 | `%LOCALAPPDATA%\Chocolatey` |
| GCC | 16.1.0 MinGW-w64 UCRT | `%LOCALAPPDATA%\Programs\WinLibs\mingw64\bin` |
| GNU Make | 4.4.1 | `make.cmd` wrapper to `mingw32-make.exe` |
| Python | 3.11.15 | `C:\Espressif\tools\python\python.exe` |

Persisted Go cache configuration:

```text
GOROOT=C:\Users\wch06\AppData\Local\Programs\Go\go1.26.5\go
GOPATH=C:\Users\wch06\go
GOMODCACHE=C:\Users\wch06\go\pkg\mod
GOCACHE=C:\Users\wch06\AppData\Local\go-build
```

## 4. Installation Safety and Compatibility

The installer performs the following controls:

1. Requires Windows AMD64, Winget, PowerShell 5.1 or later, and Python 3.11.
2. Selects Machine or User scope from actual administrator membership.
3. Uses the official Go release JSON feed and selects the first stable release.
4. Verifies the Go archive against the official SHA-256 before extraction.
5. Validates `go.exe`, `encoding/json/decode.go`, and the Go compiler executable.
6. Removes an incomplete Go directory only after confirming it is below the
   expected `%LOCALAPPDATA%\Programs\Go` boundary.
7. Retries network operations with bounded exponential delays.
8. Preserves existing PATH entries and prepends exact tool directories.
9. Pins Ruff to `0.15.21`, which supports Python 3.11 and the project rule set.
10. Creates a stable `make` command because WinLibs exposes `mingw32-make`.

## 5. Go Contract Validation

The Go module remains compatible with Go 1.22 while compiling on Go 1.26.5:

```go
module github.com/liyans/contracts-go

go 1.22
```

The build script executes these steps in order:

```text
go mod edit -go=1.22
go mod tidy -v
go mod download
go mod verify
gofmt -w .
go vet ./...
go test -cover ./...
go test -race ./...
go build ./...
go list -deps ./...
```

Actual result:

```text
all modules verified
ok github.com/liyans/contracts-go/contracts coverage: [no statements]
ok github.com/liyans/contracts-go/contracts (race enabled)
github.com/liyans/contracts-go/contracts
Go contract validation passed
```

`coverage: [no statements]` is expected because the generated package contains
wire structs and enum declarations rather than executable functions. The tests
compile every field type and perform JSON round trips for Envelope and Candidate.

The contract generator was corrected so boolean JSON Schema constants generate
Go `bool` fields. `ReleaseAuthorizationPayloadV1.OneTimeUse` is now compiled and
tested as `bool`, not `string`.

## 6. Ruff Policy

The configuration enables:

- Pyflakes and pycodestyle correctness rules;
- import ordering and Python 3.11 modernization;
- async misuse checks;
- Bandit security checks;
- annotation checks;
- bugbear, simplification, return, exception, and redundancy rules;
- Pylint branch/statement controls and McCabe complexity limit 12;
- performance, pathlib, logging, datetime timezone, and dead-code rules.

Tests permit `assert` and omit strict annotations where pytest fixtures make them
counterproductive. Production source receives no blanket security suppression.

Commands:

```powershell
# Report safe automatic fixes without applying them.
ruff check packages\contracts-python backend tools --config ruff.toml --diff

# Apply safe fixes and normalize formatting.
ruff check packages\contracts-python backend tools --config ruff.toml --fix
ruff format packages\contracts-python backend tools --config ruff.toml

# Release gate. This command must return exit code zero.
ruff check packages\contracts-python backend tools --config ruff.toml
```

## 7. Ruff Scan Statistics

Required backend and Python contract paths:

| Stage | Result |
|---|---|
| initial scan | 71 findings reported |
| safe autofix re-analysis | 50 findings automatically fixed |
| remaining engineering review | 24 findings |
| final remaining findings | 0 |

Ruff recalculates findings after each transformation, so the autofix pass reported
74 findings internally while the initial concise baseline contained 71. The final
zero result is authoritative.

The expanded `tools/` scan initially found 11 additional generator issues. Import
and formatting items were automatically fixed; TypeScript/Go schema type mapping
was refactored into smaller helpers to remove complexity findings. Final result:

```text
All checks passed!
```

## 8. Manual Risk Remediation

| Finding | Remediation |
|---|---|
| hardcoded SSE development secret | cryptographically random process default; production requires `LIYAN_SSE_CURSOR_SECRET` |
| swallowed listener/compensation failures | structured exception logging with operation identity |
| pseudo-random retry jitter warning | changed to `SystemRandom` |
| runtime `assert` in retry engine | explicit impossible-state exception |
| blind pytest `Exception` assertions | exact Provider and tenant exception classes |
| missing SSE iterator annotation | explicit `AsyncIterator[bytes]` |
| generator complexity | split special, union, scalar, string, and object type mapping |
| Go boolean constant mismatch | schema-aware bool/int/float/string literal mapping |

## 9. Observed Failures and Resolutions

### PowerShell execution policy

```text
cannot be loaded because running scripts is disabled
```

Resolution:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

### Machine scope without elevation

The installer fails before changing the machine when `-Scope Machine` is used in
a standard terminal. Start PowerShell with Run as administrator or use User scope.

### Go command exists but standard library is missing

Observed after an extraction process was externally terminated:

```text
package encoding/json is not in std
```

The installer now checks standard library and compiler files, validates the target
directory boundary, removes the partial version, and re-extracts the verified archive.

### Winget reports no upgrade with a nonzero code

The installer checks the expected WinLibs `gcc.exe` before invoking Winget. An
already installed toolchain no longer enters the upgrade path.

### Ruff installed but command is not found

The script uses `sysconfig.get_path('scripts', 'nt_user')` instead of assuming
`site.USER_BASE\Scripts`, then persists that exact Python 3.11 Scripts directory.

### PowerShell wraps harmless Go stderr as NativeCommandError

The Go build script uses `Start-Process` with separate stdout/stderr files and
uses the process exit code as the sole success signal. The complete log remains
UTF-8 and retains harmless output such as `no module dependencies to download`.

### Race test cannot find GCC

Run the installer again, open a new terminal, and verify:

```powershell
gcc --version
go env CGO_ENABLED
```

Use `build-go-contracts.ps1 -SkipRace` only for a constrained emergency builder;
the normal release gate requires the Race test.

## 10. Final Acceptance

| Gate | Status |
|---|---|
| Go version and cache configuration | passed |
| Chocolatey, GCC, Make, Ruff command discovery | passed |
| Go module normalization and verification | passed |
| Go Vet | passed |
| Go unit and JSON round-trip tests | passed |
| Go Race tests | passed |
| Go full package build | passed |
| Ruff backend/contracts/tools strict scan | passed, zero findings |
| Python baseline and 25 tests | passed |
| TypeScript contracts and Vue production build | passed |
| Docker Compose configuration | passed |
