# Topic4 C11 Supply-Chain Compliance Acceptance Report

## 1. Decision

The C11 implementation is a **local acceptance candidate** on
`codex/topic4-verifier-runtime`. Formal acceptance is pending the remote
Release Quality Gates run for the implementation checkpoint. C12 and frontend
development remain locked.

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
findings, and stable error-code mapping. Full repository coverage and remote
security gates remain required for acceptance.

## 5. Compatibility boundary

No migration, frozen contract, Phase1.1 infrastructure, Topic1-Topic3 source,
C1-C10 source, C12 source, frontend file, or CI policy was modified. C11 is
additive code under `backend/src/liyans/domains/compliance`.

## 6. Unlock decision

C12 remains locked until this C11 implementation checkpoint and its independent
remote acceptance are complete. Frontend development remains locked until the
complete Topic4 C12 release gate and final Topic4 acceptance are complete.
