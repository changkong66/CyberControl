# Topic4 C6 Control-Code Verification Acceptance Report

## 1. Decision

**Decision: ACCEPTED.** C6 is accepted as an isolated Topic4 vertical module on
`codex/topic4-verifier-runtime`. The verified implementation commit is
`272478f10bca56645f14577c81b682584cdf1b9c`. GitHub Actions Run
`29514876119` reproduced the protected Release Quality Gates workflow and
completed successfully with eight successful jobs.

This certificate accepts C6 only and unlocks C7 extension provenance. C8, C9-C11,
C12, final Topic4 publication, and frontend development remain locked.

## 2. Delivered Scope

- Reconstructed the exact immutable Topic3 `CodeSandboxContentV1` resource from
  the Claim JSON pointer, candidate identity, version, block ID, ordinal, and
  content SHA.
- Parsed Python with a bounded AST walk and MATLAB with a bounded syntax/token
  analyzer. Candidate code is never imported, evaluated, spawned, or executed by
  the verifier process.
- Enforced the local dependency allow-list and rejected dangerous imports,
  filesystem and network access, process creation, dynamic evaluation, native
  extensions, package installation, GUI operations, unsafe randomness, dunder
  access, unbounded loops, oversized ASTs, non-finite or oversized numeric
  literals, and oversized simulation grids.
- Detected control-model and simulation-flow presence and performed deterministic
  pole analysis for literal or top-level assigned transfer-function coefficients.
- Compared claimed stability conclusions with computed poles. Unprovable dynamic
  stability is returned as `INSUFFICIENT_EVIDENCE`; no unexecuted code is treated
  as successfully run.
- Emitted immutable C6 records for code artifacts, dependencies, sandbox policy,
  numeric assertions, and verification results, with Trace ID, tenant identity,
  CAS, canonical record SHA, and immutable markers.
- Returned a C1-compatible deterministic `ModuleFinding` and content-addressed
  source/result artifacts. C1 remains the owner of persistence, retries,
  transactions, audit, Outbox, and publication.
- Loaded Candidate, Topic1 snapshot, C2 evidence, and knowledge-base bindings
  through a tenant-scoped PostgreSQL adapter with explicit Claim, Trace, SHA, and
  record-integrity validation.

No migration, frozen contract, Phase1.1 infrastructure, Topic1-Topic3 source,
C1-C5 source, provider policy, API route, workflow rule, or frontend file was
modified.

## 3. Safety and Verdict Invariants

| Condition | Required result |
| --- | --- |
| Bounded syntax, safe static analysis, control flow, stability evidence, and authoritative evidence pass | `SUPPORTED` |
| Dynamic stability cannot be proven from local structure | `INSUFFICIENT_EVIDENCE` |
| Candidate, Topic1 snapshot, C2 evidence, or knowledge-base authority is missing | `INSUFFICIENT_EVIDENCE` |
| Missing control model, simulation flow, syntax, or stability consistency | `CONTRADICTED` |
| Dangerous capability, unsafe import, resource abuse, or unbounded execution pattern | `UNSAFE` with `POLICY_BLOCKED` |
| Tenant, Claim, Candidate, Trace, SHA, or artifact binding failure | `UNSAFE` or `ERROR` fail-closed |

C6 does not claim runtime execution. `SandboxPolicyV1` records the future hardened
execution boundary, but `NOT_RUN` is retained for statically accepted resources.
No external model, external embedding, public Internet, or unapproved provider is
used.

## 4. Test Evidence

The dedicated C6 suite completed with **20 passed** and **93.38 percent** package
coverage. It covers Python and MATLAB parsing, candidate reconstruction, syntax
and delimiter failures, dangerous capabilities, import and loop policies,
resource limits, stability contradictions, insufficient evidence, artifact
integrity, tenant isolation, evidence binding, loader failures, and C1 executor
compatibility.

The C1-C6 regression completed with **128 passed**. The latest full local
PostgreSQL release-equivalent suite completed with **367 passed and 2 expected
skips**, with global line coverage at **90.79 percent**.

The expected skips are limited to the opt-in Docker database restart probe and
the Windows symbolic-link capability test. No C6 test was skipped.

## 5. Engineering and Security Evidence

Local Release Quality Gates completed successfully after the C6 implementation:

- workflow syntax and Conventional Commit policy;
- Ruff check and format, Python compilation, frozen contract/catalog/provider
  drift checks;
- Go formatting, module verification, vet, race test, and build;
- Vue/TypeScript typecheck, production build, pnpm audit, Node SBOM, and license
  validation;
- Python dependency audit, Python SBOM, and license validation;
- non-root production container build and runtime constraints;
- Trivy container and Python inventory with zero findings at all severities;
- Gitleaks full history scan covering 44 commits and working-tree scan, both with
  zero leaks.

Remote Run `29514876119` completed all eight jobs successfully:

1. Python, contracts, and unit tests.
2. PostgreSQL 16 integration and coverage.
3. Go contract compiler gate.
4. Vue, TypeScript, pnpm audit, and Node SBOM.
5. Python audit and SBOM.
6. Container build, runtime, SBOM, and vulnerability scan.
7. Full Git history secret scan.
8. Release quality redline.

## 6. Frozen Compatibility Evidence

The implementation commit contains only the C6 code domain package, its dedicated
tests, and C6 architecture documentation. There is no database migration because
C6 consumes the existing Topic4 contracts and persistence boundary without new
state ownership.

C1 remains the state and transaction owner. C2 remains the immutable evidence
owner. Topic1 remains the academic authority. Topic3 Candidate versions remain
immutable inputs. Existing tenant context, FORCE RLS, artifact, audit, Outbox,
retry, and publication semantics are consumed without invasive changes.

## 7. Recovery and Failure Boundaries

1. Missing or invalid Candidate data cannot produce a positive finding.
2. Missing or mismatched C2 evidence remains insufficient or unsafe according to
   the binding boundary.
3. Topic1 snapshot or knowledge-base hash, version, node-count, or edge-count
   failures are rejected before analysis.
4. Artifact metadata mismatch prevents a valid `ModuleFinding` from being
   returned.
5. Repeated writes with the same canonical key are deterministic and collision
   checked by the immutable object store.
6. C6 performs no database state mutation, so C1 owns retry, rollback, audit, and
   Outbox recovery.
7. The verifier never falls back to executing untrusted source when static
   analysis is inconclusive; it returns `INSUFFICIENT_EVIDENCE` or a fail-closed
   error instead.

## 8. Next Gate

C7 extension provenance and compliance verification is now the only newly unlocked
implementation scope. C7 must start from this remotely verified checkpoint,
preserve global coverage at or above 90.79 percent, and complete its own
implementation-commit and acceptance-archive remote CI sequence before C8 is
unlocked. C8-C12 and frontend development remain locked.
