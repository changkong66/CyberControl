# Topic4 C9 Content Security Acceptance Report

## 1. Decision

The C9 implementation is **ACCEPTED** on `codex/topic4-verifier-runtime`.
The verified remote commit is
`ddc6dd4f8b452b00fad343e7049a400319f3794d`. GitHub Actions Release Quality
Gates Run `29525812332` completed with all eight jobs successful. C10 is now
unlocked; C11, C12, and frontend development remain locked.

## 2. Delivered implementation

- Added `DeterministicSecurityDetector` with bounded recursive Candidate
  traversal and deterministic SHA-256 match fingerprints.
- Added explicit detectors for prompt injection, credential exposure,
  malware-like download/execute and destructive commands, data exfiltration,
  unsafe content-policy instructions, and cross-tenant references.
- Added `SecurityEvidenceBundle` and a source protocol for local evidence
  injection without external retrieval.
- Added `C9SecurityHandler`, which validates trusted tenant context, Candidate
  CAS identity, canonical Candidate SHA, Claim and Trace-bound evidence, and
  evidence excerpt integrity.
- Added immutable `SecurityFindingV1` records to the result artifact while
  retaining no raw candidate content or raw secret value.
- Returned the frozen C1 `ModuleFinding` with deterministic verdict, codes,
  evidence references, artifact SHA, and C1 executor compatibility.

## 3. Security invariants

| Invariant | Control | Result |
| --- | --- | --- |
| Cross-tenant evidence | exact tenant equality before scan | denied |
| Candidate substitution | Candidate ID/version/SHA binding | denied |
| Evidence tampering | record and excerpt canonical hash checks | denied |
| Credential leakage in reports | fingerprint-only finding document | raw value absent |
| Resource exhaustion | bounded string length and match count | bounded |
| Non-waivable threats | CRITICAL finding categories force BLOCK | fail closed |
| Missing authority | no local evidence yields insufficient evidence | no false support |
| Replay drift | deterministic IDs and canonical artifact | reproducible |

## 4. Test evidence

The dedicated C9 suite completed **6 passed**. It covers clean support and
artifact replay, prompt injection blocking, raw-payload exclusion, non-waivable
credential and cross-tenant findings, cross-tenant evidence rejection, missing
evidence, deterministic bounded scanning, and the frozen C1 executor boundary.
The dedicated C9 package coverage is **90.0 percent**. Full repository
The remote PostgreSQL 16 suite completed **396 passed and 1 expected skip**;
global Python and contract coverage was **90.95 percent**. The Alembic
round-trip and model-drift checks passed at head `20260716_0009`. Gitleaks,
Trivy, SBOM/license, dependency, Ruff, Go, and TS/Vue gates all passed.

## 5. Compatibility boundary

No migration, frozen contract, Phase1.1 infrastructure, Topic1-Topic3 source,
C1-C8 source, C12 source, frontend file, or CI rule was modified. C9 is pure
additive code under `backend/src/liyans/domains/security` and uses the existing
artifact store and C1 execution protocol.

## 6. Next unlock decision

C10 is unlocked after this remote acceptance. C11 remains locked until C10 is
independently accepted. C12 remains locked until C9, C10, and C11 are all
formally accepted.
