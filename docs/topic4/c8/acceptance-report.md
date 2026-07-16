# Topic4 C8 Immutable Revision Acceptance Report

## 1. Decision

**Decision: ACCEPTED.** C8 is accepted as an isolated Topic4 self-correction
runtime on `codex/topic4-verifier-runtime`. The local implementation checkpoint
is `9ca2c51`; the GitHub remote verification commit is
`f25ce7aed19f39eb37a391fee62aaef17a4aaa17`. GitHub Actions Run
`29522491591` completed the protected Release Quality Gates workflow with all
eight jobs successful.

This certificate accepts C8 only and unlocks C9-C11 cross-cutting security and
compliance development. C12 atomic publication, final Topic4 acceptance, and
frontend development remain locked.

## 2. Delivered Scope

- Validated the trusted tenant context before any revision lookup or write.
- Bound each revision request to the exact logical Candidate ID, Candidate
  version, Candidate SHA-256, owning Topic3 Agent, Trace ID, Claim IDs, and
  deadline.
- Enforced the two-round ceiling by requiring revision round one to revise
  Candidate version one and round two to revise Candidate version two.
- Added a PostgreSQL `pg_advisory_xact_lock` keyed by tenant and Candidate ID.
  The lock is transaction-scoped, so rollback and connection loss release it
  without a stale process lock.
- Appended immutable cycle snapshots for `LOCKED`, `GENERATING`, and
  `COMPLETED` states. C8 never updates or deletes a historical cycle, plan,
  patch, Candidate, evidence, or report.
- Validated replacement artifacts through the tenant-partitioned object store,
  including byte length, object SHA-256, frozen Topic3 `BlockV1`, content schema,
  block identity/type, dependency topology, and replacement content SHA-256.
- Allowed removal only for terminal `FAILED` or `SUPERSEDED` blocks and rejected
  every removal that would create a dangling dependency or empty Candidate.
- Created Candidate version N+1 with the same logical Candidate ID, explicit
  parent version, contiguous ordinals, and a new canonical Candidate SHA-256.
- Emitted immutable `RevisionResponseV1`, an SHA-addressed response artifact,
  and a deterministic child C1 re-verification command.
- Stored a replay manifest in the completed cycle so duplicate requests replay
  the immutable outcome without producing another Candidate or response.

No migration, frozen contract, Phase1.1 infrastructure, Topic1-Topic3 source,
C1-C7 source, provider policy, API route, workflow rule, or frontend file was
modified. Existing C1 ownership of `SERIALIZABLE` transactions, audit hash
chain, idempotency, Outbox, and re-verification orchestration remains intact.

## 3. Security and Consistency Invariants

| Threat or invariant | C8 control | Expected result |
| --- | --- | --- |
| Cross-tenant revision | `assert_tenant` plus tenant-scoped repository and object store calls | denied |
| Stale Candidate | Candidate ID, version, and SHA CAS check | denied |
| Stale block patch | base block content SHA check | denied |
| Wrong Agent or schema | frozen Agent ownership and Topic3 content schema checks | denied |
| Artifact tampering | immutable object byte-size and SHA verification | denied |
| Concurrent same-Candidate revision | PostgreSQL transaction advisory lock | serialized |
| Duplicate request replay | completed request manifest and deterministic IDs | one Candidate |
| Infinite correction loop | revision round tied to Candidate version and max two | impossible |
| Unsafe block removal | terminal-state and dependency checks | denied |
| Dirty publish | C8 emits no publication and leaves C1 transaction ownership intact | impossible |

## 4. Test Evidence

The dedicated C8 suite completed with **10 passed** and **91 percent** package
coverage. It covers successful replacement, response and child re-verification
emission, terminal block removal, stale Candidate and block CAS values, tenant
isolation, instruction and replacement artifact tampering, invalid runtime input,
two-round exhaustion, idempotent replay, concurrent duplicate requests, and the
PostgreSQL repository append-only boundary.

The selected C1-C8 regression completed with **145 passed**. The deterministic
release suite completed with **338 passed, 1 skipped, and 52 deselected**. The
root-discovered PostgreSQL release-equivalent suite completed with **389 passed
and 2 expected skips**. Total Python plus contract coverage was **90.92 percent**,
above the frozen 90.54 percent baseline and the CI 90 percent redline.

## 5. Engineering and Security Evidence

The Windows quality-gate script passed workflow syntax, locked dependency
reproduction, Conventional Commit policy, Ruff check and format, contract
generation and drift, Go formatting/vet/race/build, Vue and TypeScript checks,
pnpm and pip vulnerability audits, Python and Node SBOM generation, license
policy, PostgreSQL migration round trip, model drift, deterministic tests,
PostgreSQL integration tests, non-root container runtime, container SBOM,
Trivy, and full-history plus working-tree Gitleaks.

Alembic remained at `20260716_0009`; no migration was added for C8 because the
0009 revision tables and existing Topic3 Candidate table already provide the
frozen persistence boundary. The remote run completed all eight jobs:

1. Python, contracts, and deterministic tests.
2. PostgreSQL integration and coverage.
3. Go contract compiler gate.
4. Vue, TypeScript, pnpm audit, and Node SBOM.
5. Python audit and SBOM.
6. Container build, runtime, SBOM, and vulnerability scan.
7. Full Git history secret scan.
8. Release quality redline.

## 6. Failure and Recovery Boundaries

1. C8 performs no commit; the caller's existing C1 `SERIALIZABLE` transaction
   rolls back cycle, plan, patch, and Candidate writes together on failure.
2. An advisory lock is released automatically on transaction rollback or
   connection termination.
3. Immutable object writes may leave an unreferenced content-addressed object
   after a database rollback; it cannot be published and is safe for the
   existing artifact retention process to collect.
4. A malformed replay manifest fails closed rather than reconstructing a
   partially trusted response.
5. C8 does not call external models, external search, external embeddings, or
   public URLs.

## 7. Unlock Decision

C9-C11 are now the only newly unlocked implementation scope. They must provide
mandatory prompt-injection, sensitive-content, PII, tenant-boundary, SBOM,
vulnerability, and license compliance gates for every candidate before C12 can
issue release authorization. C12, final Topic4 status, and frontend development
remain locked until C9-C11 and their independent remote acceptance are complete.
