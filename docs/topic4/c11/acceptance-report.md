# Topic4 C11 Supply-Chain Compliance Acceptance Report

## 1. Decision

The C11 implementation is **ACCEPTED** on `codex/topic4-verifier-runtime`.
The verified remote commit is
`360455ea1895fe8f36f29ea106333df7e9e46d67`. GitHub Actions Release Quality
Gates Run `29528397986` completed with all eight jobs successful. C12 is now
unlocked; frontend development remains locked.

## 2. Delivered scope

- Added `ComplianceEvidenceBundle` for tenant-bound CodeArtifact, CycloneDX
  manifest/document, component records, vulnerability records, provenance, and
  local evidence.
- Added exact tenant, Claim, Trace, Candidate, CodeArtifact, SBOM, component,
  vulnerability, and provenance SHA binding checks.
- Added canonical CycloneDX document hash verification and bounded component
  limits.
- Added dependency-to-SBOM completeness checks.
- Added license policy enforcement for approved commercial-compatible licenses,
  unknown evidence, unapproved licenses, and prohibited copyleft/commercial
  restrictions.
- Added open HIGH/CRITICAL vulnerability and non-waivable accepted-risk
  blocking.
- Added reproducible build provenance checks for source, output, SBOM, sandbox
  policy, and build-command fingerprints.
- Added `NOT_APPLICABLE` behavior for non-code Claims and frozen C1
  `ModuleFinding` output for all paths.

## 3. Security and consistency invariants

| Invariant | Control | Expected result |
| --- | --- | --- |
| Cross-tenant supply-chain evidence | exact source and record tenant checks | denied |
| SBOM tampering | canonical document and artifact SHA equality | denied |
| Dependency omission | every CodeArtifact dependency must match SBOM | unsafe |
| Prohibited license | critical non-waivable policy finding | blocked |
| Open high vulnerability | vulnerability status/severity gate | blocked |
| False reproducibility | source/output/SBOM/provenance binding | denied |
| External hallucinated evidence | local evidence source only | unavailable |
| Resource exhaustion | bounded evidence/component/artifact sizes | bounded |

## 4. Test evidence

The dedicated C11 suite completed **10 passed** with **90.0 percent** package
coverage. It covers clean support, prohibited licenses, open high
vulnerabilities, tenant and SBOM hash mismatch, missing evidence, non-code
claims, C1 executor compatibility, loader/policy boundaries, empty SBOM
findings, and stable error-code mapping. The remote PostgreSQL 16 suite
completed **412 passed and 1 expected skip**; global Python and contract
coverage was **90.93 percent**. Alembic round-trip and model-drift checks
passed at head `20260716_0009`. Gitleaks, Trivy, SBOM/license, dependency,
Ruff, Go, and TS/Vue gates all passed.

## 5. Compatibility boundary

No migration, frozen contract, Phase1.1 infrastructure, Topic1-Topic3 source,
C1-C10 source, C12 source, frontend file, or CI policy was modified. C11 is
additive code under `backend/src/liyans/domains/compliance`.

## 6. Unlock decision

C12 is unlocked after this remote acceptance. Frontend development remains
locked until the complete Topic4 C12 release gate and final Topic4 acceptance
are complete.
