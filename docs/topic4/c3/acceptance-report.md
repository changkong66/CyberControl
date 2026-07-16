# C3 Academic Verification Checkpoint Report

## Current State

The C3 implementation is a checkpoint, not a Topic4 acceptance. It is isolated on
`codex/topic4-verifier-runtime` and adds only new academic-domain code, tests, runtime
dependencies, and documentation. Phase1.1, Topic1, Topic2, Topic3, C1, and C2
semantics remain unchanged.

## Delivered Behavior

- Formula statements are normalized from bounded plain text, LaTeX fragments, and
  Chinese/English prose into immutable `FormulaIRV1` records.
- Symbolic equivalence, counterexample generation, relation-aware comparisons, and
  derivation-chain validation produce frozen C3 contract records.
- Transfer-function/characteristic-polynomial and state-space models are hash-bound;
  continuous and discrete pole boundaries are classified conservatively.
- Theorem conditions require versioned registry entries and evidence references.
- Numeric assertions normalize compatible units and distinguish contradiction from
  insufficient evidence.
- Fact coverage rejects cross-tenant, cross-claim, trace-mismatched, duplicate, or
  excerpt-tampered evidence.
- The C1 handler writes canonical, immutable, SHA-bound JSON artifacts and returns the
  existing `ModuleFinding` contract without changing the executor.

## Test Evidence

The dedicated C3 suite contains 35 deterministic tests covering parser security,
formula equivalence, derivation errors, stability boundaries, numeric units and
operators, theorem condition states, fact conflicts, PostgreSQL adapter behavior,
tenant isolation, artifact integrity, and C1 executor compatibility. The dedicated
C3 coverage is above 90 percent.

The repository-wide PostgreSQL gate was rerun after the C3 changes:

- `304 passed, 2 skipped`
- total coverage `90.37%`, above the repository redline of `90%`
- Alembic `head -> base -> head` round trip passed; final head is `20260716_0009`
- the two skips are an explicitly disabled Docker database restart probe and a
  Windows symbolic-link capability limitation

The deterministic unit suite separately passed with `251 passed, 1 skipped`.

## Engineering Gate Evidence

The following local gates were reproduced with the locked project toolchain:

- Ruff check and format, Python compile, frozen contract export, baseline validation:
  passed
- Go format, module verification, vet, race test, and build: passed
- generated TypeScript contract check, Vue/TypeScript typecheck, and production build:
  passed
- pnpm audit and pip-audit: no known vulnerabilities
- Python, Node, and container CycloneDX SBOM generation plus license-policy checks:
  passed
- production container compose validation, non-root UID/GID `10001:10001`, import
  smoke test, and liveness probe: passed
- Trivy full inventory and high/critical redline: no fixable high or critical findings
- Gitleaks v8.30.1 history scan covered 38 commits and the working-tree scan; both
  reported zero leaks

The local evidence is sufficient for this C3 checkpoint, but it is not a module
acceptance. Remote CI reproduction and review remain mandatory before the state can
become `ACCEPTED`.

## Remaining Gate

1. Push the checkpoint branch and wait for the remote release quality workflow to
   reproduce the local gates.
2. Reconcile remote evidence and mark C3 `ACCEPTED` only after the checkpoint is
   reviewed and the remote workflow is green.
3. Only after C3 is accepted may C4 development begin.
