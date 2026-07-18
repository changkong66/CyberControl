# Topic4 C10 Privacy Acceptance Report

## 1. Decision

The C10 implementation is **ACCEPTED** on `codex/topic4-verifier-runtime`.
The verified remote commit is
`2d90a268800a686c17ad5b914c543c7f69f0bb20`. GitHub Actions Release Quality
Gates Run `29526860801` completed with all eight jobs successful. C11 is now
unlocked; C12 and frontend development remain locked.

## 2. Delivered scope

- Added a local `DeterministicPIIDetector` with bounded recursive traversal,
  JSON Pointer locations, confidence, and SHA-256 value fingerprints.
- Added structural and pattern detection for credential, biometric, national
  ID, student ID, name, address, email, and phone data.
- Added trusted `source_tenant_id` proof in the evidence boundary; a missing or
  foreign source tenant cannot produce a positive result.
- Added immutable `PIIFindingV1`, `TokenizedValueV1`, and
  `PrivacyTenantResultV1` construction with deterministic identifiers.
- Added tokenization for email, phone, and student ID values, redaction for
  names and addresses, and non-waivable blocking for critical PII classes.
- Added content-addressed redacted Candidate artifacts that exclude raw PII.
- Returned the frozen C1 `ModuleFinding` without changing C1 persistence,
  transaction, audit, Outbox, or executor semantics.

## 3. Security invariants

| Invariant | Control | Expected result |
| --- | --- | --- |
| Cross-tenant source | exact `source_tenant_id` equality | denied |
| Cross-tenant evidence | evidence tenant/Claim/Trace checks | denied |
| Candidate substitution | Candidate ID/version/SHA CAS | denied |
| Critical PII release | BLOCK and non-waivable contract fields | denied |
| Raw PII persistence | hash-only findings and transformed artifact | absent |
| Token replay ambiguity | deterministic token and versioned vault reference | reproducible |
| Resource exhaustion | bounded strings and matches | bounded |
| Missing authority | no evidence yields insufficient evidence | no false support |

## 4. Test evidence

The dedicated C10 suite completed **6 passed** with **92.0 percent** package
coverage. It covers clean support, tokenization and redaction without raw
value persistence, critical PII blocking, tenant-boundary rejection, missing
evidence, deterministic bounded scanning, and C1 executor compatibility. The
remote PostgreSQL 16 suite completed **402 passed and 1 expected skip**;
global Python and contract coverage was **90.97 percent**. Alembic round-trip
and model-drift checks passed at head `20260716_0009`. Gitleaks, Trivy,
SBOM/license, dependency, Ruff, Go, and TS/Vue gates all passed.

## 5. Compatibility boundary

No migration, frozen contract, Phase1.1 infrastructure, Topic1-Topic3 source,
C1-C9 source, C12 source, frontend file, or CI policy was modified. C10 is
additive code under `backend/src/liyans/domains/privacy`.

## 6. Unlock decision

C11 is unlocked after this remote acceptance. C12 remains locked until C9,
C10, and C11 are all formally accepted.
