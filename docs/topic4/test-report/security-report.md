# Topic4 Security Acceptance Report

## 1. Tenant Isolation

- All 41 Topic4 tables are included in the frozen tenant table inventory.
- Migrations enable and FORCE PostgreSQL RLS.
- Runtime repositories bind every query to `current_tenant()`.
- Real PostgreSQL tests verify cross-tenant verification, knowledge, evidence,
  authorization, publication, and history access is blocked or invisible.

## 2. Integrity and Replay Defense

- Contracts carry canonical SHA256 and immutable markers.
- Candidate, Claim, evidence, report, revision, authorization, batch, and event
  bindings are revalidated at trust boundaries.
- C8 uses version CAS and a per-Candidate transaction advisory lock.
- C12 authorizations are one-time, expiring, tenant-bound, and request-bound.
- Changed replay, expired use, forged hashes, and cross-tenant publication are
  rejected in real PostgreSQL tests.

## 3. Content Security

- C9 covers prompt injection, credentials, malware, exfiltration, policy, and
  cross-tenant reference detection.
- C10 covers national IDs, biometrics, credentials, email, phone, student IDs,
  names, and addresses with non-reversible tokenization or redaction.
- C11 validates trusted CycloneDX SBOM, component licenses, vulnerabilities,
  and reproducible provenance. Missing trusted code supply-chain evidence fails
  closed.

## 4. Supply-Chain and Repository Scans

- Trivy 0.72.0: zero container findings at all severities.
- Gitleaks 8.30.1: zero history findings and zero worktree findings.
- Python dependency audit: passed.
- pnpm audit: passed.
- Python and frontend CycloneDX SBOM generation: passed.
- License policy: passed.
- Go contract build and race gate: passed.
- Production container runs as non-root `10001:10001` and excludes build/test
  package managers and test frameworks.

## 5. Remote Evidence

Release Quality Gates Run `29634407475` published container security,
secret-scan, Python supply-chain, frontend SBOM, Go contract, and PostgreSQL
test evidence. All eight jobs completed successfully.
