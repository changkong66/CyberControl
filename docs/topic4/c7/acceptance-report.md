# Topic4 C7 Extension Provenance Acceptance Report

## 1. Decision

**Decision: ACCEPTED.** C7 is accepted as an isolated Topic4 vertical module on
`codex/topic4-verifier-runtime`. The verified implementation commit is
`1b9e52befb9ff449a62f4b444d82925125719dde`. GitHub Actions Run
`29517993876` completed the protected Release Quality Gates workflow with all
eight jobs successful.

This certificate accepts C7 only and unlocks C8 two-round revision. C9-C11, C12,
final Topic4 publication, and frontend development remain locked.

## 2. Delivered Scope

- Reconstructed the exact immutable Topic3 extension resource from the Claim JSON
  pointer, Candidate identity/version/SHA, block ID, block ordinal, resource
  ordinal, and block content SHA.
- Loaded the immutable Topic3 Candidate, C2 EvidenceBundle and EvidenceRef records,
  KnowledgeBaseVersion, and Topic1 graph snapshot through one tenant-scoped read
  adapter with explicit tenant predicates and existing FORCE RLS.
- Verified citation provenance only against the local C2 approved corpus. Source
  URLs remain inert metadata and are never fetched.
- Validated Topic1 knowledge-point identities and computed deterministic relevance
  from target coverage plus token overlap with Topic1 titles, aliases, summaries,
  objectives, categories, and tags.
- Detected citation placeholders, insufficient metadata, invalid/future publication
  years, fabricated or absent corpus sources, unknown knowledge points, and low
  domain relevance.
- Derived a conservative SPDX-like license expression only from the Candidate
  citation and immutable local evidence. Unknown licenses remain insufficient;
  GPL, AGPL, and non-commercial CC terms are fail-closed as incompatible.
- Emitted frozen `VerifierExtensionResourceV1` and
  `ExtensionVerificationResultV1` records with Trace ID, tenant identity, CAS,
  canonical record SHA, immutable markers, evidence IDs, and C1-compatible
  verdicts.
- Stored only canonical content-addressed result artifacts. C1 remains the owner
  of state, retries, transactions, audit, Outbox, and publication.

No migration, frozen contract, Phase1.1 infrastructure, Topic1-Topic3 source,
C1-C6 source, provider policy, API route, workflow rule, or frontend file was
modified.

## 3. Verdict Invariants

| Condition | Required result |
| --- | --- |
| Local approved source, valid citation, compatible license, Topic1 target, and relevance pass | `SUPPORTED` |
| Missing Candidate, snapshot, evidence, or unknown license | `INSUFFICIENT_EVIDENCE` |
| Fabricated source, invalid citation, unknown Topic1 target, or low relevance | `CONTRADICTED` |
| Explicitly incompatible license | `UNSAFE` |
| Tenant, Claim, Candidate, Trace, record SHA, excerpt SHA, snapshot, or artifact binding failure | fail-closed `UNSAFE` or `ERROR` |

C7 never calls an external model, external search service, external embedding, or
public Internet endpoint. A positive verdict always includes immutable local C2
evidence references.

## 4. Test Evidence

The dedicated C7 suite completed with **12 passed** and **95 percent** package
coverage. It covers exact resource reconstruction, Candidate and block tampering,
unknown Topic1 targets, source absence, placeholder citations, future publication
years, incompatible and unknown licenses, C1 execution, immutable artifacts,
tenant isolation, evidence and record SHA failures, knowledge-base and snapshot
binding, policy limits, and PostgreSQL adapter boundaries.

The C1-C7 regression completed with **128 passed**. The full local PostgreSQL
release-equivalent suite completed with **379 passed and 2 expected skips**. Total
line coverage was **90.89 percent**, above both the frozen 90.54 percent baseline
and the 90 percent release gate.

The expected skips are the opt-in Docker database restart probe and the Windows
symbolic-link capability test. No C7 test was skipped.

## 5. Engineering and Security Evidence

Local gates passed for workflow syntax, Conventional Commits, Ruff, Python
compilation, frozen contract/catalog/provider drift, Go formatting/vet/race/build,
Vue and TypeScript, pnpm and pip audit, Python/Node/container SBOM, license policy,
non-root container runtime, Trivy zero vulnerabilities, and Gitleaks zero leaks.

The PostgreSQL gate used one isolated PostgreSQL 16 instance with separate
least-privilege `liyans_app`, `liyans_migrator`, and `liyans_dispatcher` roles.
Alembic downgraded from `20260716_0009` to base and upgraded back to the same head,
with no model drift.

Remote Run `29517993876` completed all eight jobs successfully:

1. Python, contracts, and unit tests.
2. PostgreSQL 16 integration and coverage.
3. Go contract compiler gate.
4. Vue, TypeScript, pnpm audit, and Node SBOM.
5. Python audit and SBOM.
6. Container build, runtime, SBOM, and vulnerability scan.
7. Full Git history secret scan.
8. Release quality redline.

## 6. Frozen Compatibility Evidence

The implementation commit contains only the C7 extension domain package, its
dedicated tests, and C7 architecture documentation. No database migration is
required because C7 consumes frozen C2 evidence and C1 persistence ownership.

Topic1 remains the academic authority, C2 remains the immutable evidence owner,
Topic3 Candidate versions remain immutable inputs, and C1 remains the state and
transaction owner. Existing FORCE RLS, audit, Outbox, retry, and artifact
semantics are reused without invasive changes.

## 7. Failure and Recovery Boundaries

1. Missing or malformed Candidate resources cannot produce a positive finding.
2. Missing evidence or unverified license terms remain insufficient, never guessed.
3. Cross-tenant, cross-Claim, cross-Trace, knowledge-base, record SHA, excerpt SHA,
   and snapshot mismatches fail before analysis.
4. External URLs are never dereferenced and cannot introduce an external
   hallucination or prompt-injection source.
5. Artifact metadata mismatch prevents a valid ModuleFinding from being returned.
6. C7 performs no database mutation; C1 owns retry, rollback, audit, and Outbox
   recovery.

## 8. Next Gate

C8 two-round immutable revision is now the only newly unlocked implementation
scope. It must enforce a maximum of two rounds, per-Candidate concurrency locks,
Candidate/version/SHA/Block/Trace binding, append-only patch history, and automatic
re-entry into C1. C9-C12 and frontend development remain locked until their
preceding acceptance certificates are complete.
