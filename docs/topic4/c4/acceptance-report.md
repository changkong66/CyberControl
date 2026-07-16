# C4 Mermaid Graph Verification Acceptance Report

## 1. Decision

**Decision: ACCEPTED.** The C4 Mermaid graph verification runtime is accepted as an
isolated Topic4 vertical module on `codex/topic4-verifier-runtime`. The verified
implementation commit is
`a02d09761fa365f72fdb04c5a7291880db69155f`. GitHub Actions Run
`29503160951` reproduced the complete Release Quality Gates workflow for that exact
commit and completed successfully.

This acceptance freezes C4 behavior and unlocks C5 quiz verification after this
acceptance archive itself passes the protected remote workflow. It does not accept
Topic4 as a whole and does not unlock C6-C12 or the frontend.

## 2. Delivered Scope

- A bounded Mermaid parser accepts the safe grammar emitted by the frozen Topic3
  MindMapAgent and rejects executable directives, unsafe styles, malformed graphs,
  duplicate nodes/edges, self edges, and resource-limit violations.
- Mermaid nodes resolve deterministically against Topic1 knowledge-point IDs, titles,
  and aliases with Unicode normalization and ambiguity rejection.
- Topic1 prerequisites are checked for correct direction, omitted dependencies,
  invented edges, unresolved endpoints, and cycles.
- An exact knowledge-point ID paired with a label naming a different Topic1 entity is
  rejected instead of silently trusting either representation.
- Relations not represented by the frozen Topic1 prerequisite model are fail-closed
  as insufficient evidence and cannot produce a positive finding.
- The PostgreSQL adapter atomically binds the latest C2 EvidenceBundle to its exact
  KnowledgeBaseVersion, evidence references, and immutable Topic1 graph snapshot.
- Bundle, knowledge-base, evidence-record, excerpt, snapshot SHA, and snapshot count
  integrity checks are enforced before semantic verification.
- Tenant, verification ID, Claim ID, Trace ID, and knowledge-base version bindings are
  checked at both the PostgreSQL adapter and handler boundaries.
- The C1-compatible handler writes canonical, content-addressed result artifacts and
  returns the frozen `ModuleFinding` structure without changing C1 execution or
  transaction ownership.

No migration or contract change was required. C4 consumes existing frozen C1, C2,
C4, Topic1, and Topic3 contracts and uses the existing ArtifactObjectStore.

## 3. Verdict Invariants

| Condition | Required result |
| --- | --- |
| Safe graph, resolved nodes, authoritative evidence, exact Topic1 prerequisite match | `SUPPORTED` |
| Invented, reversed, omitted, or cyclic prerequisite | `CONTRADICTED` |
| Unknown/ambiguous node, unsupported relation, or missing evidence | `INSUFFICIENT_EVIDENCE` |
| Executable/unsafe Mermaid or tenant/evidence binding failure | `UNSAFE` |
| Immutable Topic1 snapshot integrity failure or unexpected runtime failure | `ERROR` |

A positive result always carries authoritative evidence. C4 never guesses an
ambiguous node, promotes a relation absent from Topic1, executes Mermaid, or mutates
upstream records.

## 4. Test Evidence

The dedicated C4 suite completed with `22 passed` and `93.73%` C4 package coverage.
It covers safe grammar, parser limits, executable directive rejection, node shapes,
relation parsing, Topic1 resolution, ID/label confusion, reversed and omitted
prerequisites, cycles, unknown and ambiguous nodes, missing evidence, snapshot
tampering, tenant isolation, Claim/Trace/knowledge-base binding, duplicate evidence,
invalid loaders, content-addressed artifact replay, and C1 executor compatibility.

The full local PostgreSQL release-equivalent suite completed with:

- `326 passed, 2 skipped`;
- total line coverage `90.54%`, above the `90%` repository redline;
- Alembic `head -> base -> head` round trip at final head `20260716_0009`;
- expected skips limited to the opt-in Docker database restart probe and Windows
  symbolic-link capability.

The deterministic non-integration suite separately completed with `275 passed, 1
skipped, 52 deselected`. The dedicated C4 suite has no skip.

## 5. Engineering and Security Evidence

The full Windows release-equivalent quality script completed successfully after
reproducing all selected gates:

- actionlint, Conventional Commit validation, Ruff check/format, Python compile,
  contract export, and frozen-baseline drift: passed;
- Go formatting, module verification, vet, race test, and build: passed;
- generated TypeScript contracts, Vue/TypeScript typecheck, and production build:
  passed;
- pnpm audit and pip-audit: no known vulnerabilities;
- Python, Node, and container CycloneDX SBOM plus license policy: passed;
- production image non-root UID/GID `10001:10001`, minimal-runtime assertions, import
  smoke test, and liveness: passed;
- Trivy inventory for Alpine and Python packages: zero findings at all severities;
- Gitleaks scanned the 40-commit implementation history and the C4 working tree:
  zero leaks.

Remote Run `29503160951` completed all eight jobs successfully: Python/contracts/unit,
PostgreSQL 16 integration and coverage, Go contracts, Vue/TypeScript/Node SBOM, Python
audit/SBOM, production container security, full Git history secret scan, and the final
release quality redline.

## 6. Frozen Compatibility Evidence

The C4 implementation commit contains only the C4 graph domain package, its dedicated
tests, and C4 architecture documentation. It does not modify Phase1.1, Topic1,
Topic2, Topic3, C1, C2, C3, database migrations, wire contracts, generated schemas,
Provider policy, API routing, or frontend code. Contract regeneration produced no
drift.

C1 remains the transaction and state owner. C2 remains the immutable evidence owner.
Topic1 remains the sole authoritative graph source. Existing audit, Outbox, SSE, RLS,
and artifact semantics are consumed without invasive changes.

## 7. Recovery and Failure Boundaries

1. Invalid or unavailable evidence is rejected before graph semantics are evaluated.
2. A missing Topic1 snapshot cannot produce a positive result.
3. A snapshot hash or count mismatch returns a fail-closed integrity result.
4. Result artifacts are canonical JSON and must match the object-store SHA and byte
   count before C1 receives a finding.
5. C4 writes no database state directly; C1 retries and persists module results using
   the existing idempotent transaction and Outbox flow.
6. Historical evidence and Topic1 snapshots remain immutable and replayable.

## 8. Residual Scope

C4 acceptance does not claim quiz-answer correctness, executable code safety, source
or license validity, revision-loop safety, prompt-injection/PII protection, supply
chain runtime verification, release authorization, API/worker wiring, or final Topic4
publication. Those responsibilities remain in C5-C12 and the later integration
phases.

## 9. Next Gate

The next and only newly unlocked implementation scope is C5 quiz verification. C5
must validate question stems, answer keys, solution steps, misconception diagnostics,
difficulty/knowledge-point labels, and grading consistency against immutable Topic1
golden questions plus C2/C3 evidence. C6-C12 and frontend development remain locked
until their preceding acceptance gates complete.
