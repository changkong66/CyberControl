# Phase 1.1 Release Quality and Supply-Chain Gates

## 1. Purpose and frozen boundary

This document freezes Phase 1.1 Step 8. The gate converts the repository from a
developer-validated baseline into a reproducible release candidate with mandatory
compiler, database, security, dependency, SBOM, and test evidence.

The gate may regenerate and compare frozen Topic 3 artifacts, but it may not alter
Topic 1/2 persistence contracts, Topic 3 Envelope/Block/Candidate semantics, or the
five Agent payload contracts. Any generated contract difference fails the build.
Business AI calls are not made by CI. Provider policy remains restricted to Spark
text, XFYun code assistance, and SeeDance aliases.

```mermaid
flowchart LR
    PR["Pull request or main push"] --> P["Python + Ruff + unit tests"]
    PR --> DB["PostgreSQL 16 + Alembic + RLS integration"]
    PR --> GO["Go vet + race + build"]
    PR --> FE["pnpm + TypeScript + Vue build"]
    PR --> SC["Python/Node dependency audit + SBOM"]
    PR --> IMG["Pinned image build + non-root smoke + Trivy"]
    PR --> SEC["Gitleaks history + worktree scan"]
    P --> RED["Release quality redline"]
    DB --> RED
    GO --> RED
    FE --> RED
    SC --> RED
    IMG --> RED
    SEC --> RED
    RED -->|"all success"| MERGE["Eligible for protected-main merge"]
    RED -->|"failed, cancelled, or skipped"| BLOCK["Release blocked"]
```

## 2. Reproducible toolchain

| Layer | Frozen CI baseline | Enforcement |
|---|---:|---|
| Python | 3.11 | `actions/setup-python` plus `requires-python <3.12` |
| Python resolver | uv 0.11.28 | `uv lock --check`, `uv sync --frozen` |
| Go language level | 1.22.x | `go.mod`, minimum-version CI compiler |
| Node.js | 22.20.0 | root `.node-version` and CI environment |
| pnpm | 11.7.0 | `packageManager`, frozen lock install |
| PostgreSQL | digest-pinned 16 Alpine in CI | real restricted migrator/runtime/dispatcher roles |
| Runtime base | pinned Python image digest | Dockerfile digest, not a floating tag |
| Trivy | 0.70.0 in the pinned Action | complete inventory and blocking scan |
| Gitleaks CLI | 8.30.1 | archive SHA-256 verified before execution |

Every external GitHub Action is referenced by a full 40-character commit SHA.
Version comments are retained so Dependabot can propose reviewed pin updates. Actions
run with repository-level `contents: read`; no write token or provider credential is
available to the workflow.

## 3. Mandatory gate matrix

### 3.1 Python, contracts, and unit tests

1. Validate `uv.lock` without mutation.
2. Validate every pushed or pull-request commit subject against the repository
   Conventional Commit policy using the full immutable Git history.
3. Validate every workflow expression and job dependency with checksum-pinned
   Actionlint before any release gate can become the protected status.
4. Recreate every workspace package and extra from the frozen lock.
5. Run strict repository-wide Ruff lint and format checks with zero findings.
6. Regenerate JSON Schema, TypeScript, and Go contracts from canonical Pydantic
   models. `gofmt` is part of deterministic generation.
7. Validate the frozen provider and Responses Lite baseline.
8. Reject any Git difference under generated contract paths.
9. Run all non-PostgreSQL tests.

Redline: zero commit-policy/lint findings, zero formatting changes, zero generated
drift, and a 100% passing unit suite.

### 3.2 PostgreSQL 16 integration and migration gate

CI starts an isolated PostgreSQL 16 service and provisions `liyans_migrator` and
`liyans_app` plus the cross-tenant, column-restricted `liyans_dispatcher` as
non-superuser, non-`BYPASSRLS` roles. It then performs:

1. upgrade to Alembic head;
2. head and model-drift checks;
3. downgrade to base on the disposable CI database;
4. a second upgrade and drift check;
5. the complete unit and PostgreSQL fault-integration suite;
6. line coverage over backend and Python contracts.

Redline: every migration direction succeeds, no model drift exists, all transaction,
RLS, restart, lease, idempotency, Outbox, audit, and SSE recovery tests pass, and
coverage is at least 88.00%.

### 3.3 Go contract gate

The gate rejects any `gofmt` output, normalizes the module graph, verifies no
unexpected module dependency has entered the zero-dependency contract package,
runs `go vet`, executes race-enabled tests, and compiles all packages.

Redline: zero formatter/vet/race/compiler findings and no unreviewed `go.mod` or
`go.sum` change.

### 3.4 Frontend and Node supply-chain gate

The frontend uses a pnpm frozen install with package lifecycle scripts denied except
the explicitly approved `esbuild` binary setup. CI validates the generated contract
package, both Vue/Node TypeScript configurations, the production Vite build, and a
registry audit at `high` severity. A deterministic CycloneDX 1.6 document is produced
from the complete pnpm dependency graph. Missing external license evidence and
AGPL/GPL/SSPL/BUSL/Commons-Clause/Elastic-License families fail closed; curated
platform-binary metadata is explicitly marked in the SBOM.

Redline: zero type/build failures, zero high or critical audit findings, and a valid
Node SBOM.

### 3.5 Python supply-chain gate

`uv export` produces a hash-pinned, marker-aware requirements snapshot without
editable workspace references. `pip-audit --strict` scans that exact graph. The
workspace environment is then exported as a reproducible CycloneDX 1.6 application
SBOM and validated by the CycloneDX tool and the same license policy.

Redline: no collection ambiguity, no known vulnerability, and a schema-valid SBOM.

### 3.6 Container security gate

The release image is built from the digest-pinned base using the frozen uv lock. The
runtime layer must declare UID/GID `10001`, contain installed wheels rather than
source trees, exclude pytest and development packages, and pass the real FastAPI
`/health/live` probe.

Trivy emits a complete vulnerability JSON inventory including unfixed findings. A
second blocking scan rejects every fixable high or critical OS/library finding.
Unfixed findings are never hidden from evidence; they require a tracked exception
and remediation deadline before an actual release is approved.

Redline: deterministic image build, valid Compose configuration, non-root minimal
runtime, passing liveness, valid container SBOM, and zero fixable high/critical CVEs.

### 3.7 Secret history gate

The open-source Gitleaks CLI is downloaded directly from its release and verified
against the pinned SHA-256. This avoids the separately licensed hosted Action and
its external license-validation dependency. CI scans both all reachable Git commits
and the checked-out worktree. Findings are redacted in logs and artifacts.

Redline: zero secret findings. A discovered credential is rotated and removed; an
allow rule cannot substitute for credential rotation.

## 4. Evidence and retention

| Evidence artifact | Contents | Retention |
|---|---|---:|
| `python-postgres-test-evidence` | JUnit and XML coverage | 30 days |
| `go-contract-evidence` | race coverage and module inventory | 30 days |
| `frontend-sbom` | CycloneDX 1.6 Node graph and license-policy ledger | 90 days |
| `python-supply-chain` | requirements, dependency tree, Python SBOM, license ledger | 90 days |
| `container-security-evidence` | image inspect, container SBOM, Trivy inventory | 90 days |
| `secret-scan-evidence` | redacted history/worktree reports | 90 days |

Release tags must retain or copy the corresponding SBOMs, test evidence, image
digest, workflow run URL, and source commit into the release compliance index.
Generated evidence stays outside Git; source policies and generator implementations
remain version controlled.

## 5. Protected-branch configuration

`main` must require pull requests, an owner review, conversation resolution, and the
status check named **Release quality redline**. Force pushes and branch deletion are
disabled. The final job uses `always()` and explicitly rejects failed, cancelled, or
skipped prerequisites, preventing a bypass through conditional job execution.

Repository administrators may re-run transient network failures, but may not merge
with a waived gate. Emergency changes use a reviewed corrective branch and the same
redline; there is no direct-to-main exception.

The checked-in scripts apply and verify this state through the GitHub REST API:

```powershell
$env:GH_TOKEN = "<fine-grained administration token>"
& .\tools\github\configure-repository-protection.ps1 -Repository "owner/repository"
& .\tools\github\verify-remote-quality-gate.ps1 `
  -Repository "owner/repository" `
  -Branch "codex/phase-1.1-foundation"
```

Tokens are never written to source, logs, or evidence artifacts.

## 6. Windows local execution

After starting an isolated PostgreSQL test database and applying the role bootstrap,
run the same hard gates from a normal PowerShell terminal:

```powershell
$env:LIYAN_TEST_DATABASE_URL = `
  "postgresql+asyncpg://liyans_app:liyans-app-local-only@127.0.0.1:5432/liyans"
$env:LIYAN_TEST_MIGRATION_DATABASE_URL = `
  "postgresql+asyncpg://liyans_migrator:liyans-migrator-local-only@127.0.0.1:5432/liyans"
$env:LIYAN_TEST_DISPATCHER_DATABASE_URL = `
  "postgresql+asyncpg://liyans_dispatcher:liyans-dispatcher-local-only@127.0.0.1:5432/liyans"
& .\tools\windows\run-quality-gates.ps1
```

The script merges persisted Windows tool paths, verifies all native exit codes,
downloads Gitleaks and Trivy into the ignored artifact cache with fixed checksums,
uses the official AWS Public ECR vulnerability database mirror before the official
GHCR fallback, and writes its transcript and machine-readable result under
`artifacts/quality-gates/`.

`-SkipPostgresIntegration`, `-SkipContainer`, and `-SkipSecretScan` exist only for
developer diagnostics. Any run using a skip flag is not release-equivalent and
cannot be used as acceptance evidence.

## 7. Dependency update and vulnerability operations

Dependabot checks uv, npm, Go modules, GitHub Actions, and Docker inputs weekly.
Minor/patch updates are grouped by ecosystem; major updates remain isolated for
explicit compatibility review. Every update must regenerate the relevant lock/SBOM,
pass this workflow, and preserve frozen contract drift at zero.

Vulnerability response objectives:

| Severity | Triage objective | Remediation objective |
|---|---:|---:|
| Critical, exploitable | 4 hours | 24 hours or release block |
| High, exploitable | 1 business day | 7 days or release block |
| Medium | 3 business days | 30 days |
| Low | next dependency cycle | 90 days |

A temporary exception must identify the component/PURL, CVE, affected scope,
exploitability evidence, compensating control, owner, approval, expiry, and removal
plan. Expired exceptions fail closed. Phase 1.1 freezes with no active vulnerability
exception.

## 8. Quantified Step 8 acceptance

- all Action references immutable by commit SHA;
- Python lock and pnpm lock reproduce without mutation;
- Ruff findings and generated contract drift equal zero;
- Go vet/race/build and TypeScript/Vue build all pass;
- PostgreSQL integration passes on version 16 with coverage at least 89%;
- Python and Node known high/critical dependency findings equal zero;
- fixable high/critical container findings equal zero;
- secret findings equal zero;
- Python, frontend, and container CycloneDX evidence is generated for every release
  candidate;
- a single non-bypassable final status aggregates every prerequisite.

These gates form the production entry boundary for Topic 1/2 repository binding and
all later Agent and Verifier implementation work.
