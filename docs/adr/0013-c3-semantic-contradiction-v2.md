# ADR-0013: C3 Semantic Contradiction Verification V2

- Status: Accepted for implementation
- Date: 2026-07-22
- Owners: Verification platform

## Context

The Phase 7 Gate B run bound to commit
`557bcca967ade6b8f6aa3f4925ecdaee0334f423` proved that the C3 v1 persistence,
tenant-isolation, replay, and deterministic-execution controls work, but the
token-overlap fact verifier did not meet the predeclared academic-accuracy
thresholds. It produced `13` unsafe `CONTRADICTED -> SUPPORTED` decisions.

The accepted benchmark contains one reviewed premise and three hypotheses per
topic. Only the premise is placed in the evidence corpus. Fact IDs, topic
labels, expected outcomes, expected rationales, and non-premise hypotheses are
not available to the product verifier.

The existing `C3AcademicHandler` and `ClaimFactVerifier` are already used by
frozen v1 callers. Replacing their default behavior would make historical
artifacts and compatibility tests ambiguous.

## Decision

1. `ClaimFactVerifier` and the default `C3AcademicHandler` construction remain
   v1-compatible. No existing public contract, database migration, RLS policy,
   transaction, Outbox, or artifact schema is removed or rewritten.
2. Add `SemanticClaimVerifierV2`, a deterministic natural-language-inference
   boundary that accepts only `ClaimV1` and immutable `EvidenceRefV1` records.
   It must not accept or inspect benchmark identifiers, topic names, expected
   labels, or reviewer rationales.
3. Add `C3AcademicHandlerV2` as an explicit compatibility extension. It keeps
   the frozen `c3-academic-finding.v1` artifact schema and records a distinct
   handler build version.
4. Production runtime composition and the Phase 7 accuracy harness explicitly
   select v2. Existing code that directly constructs `C3AcademicHandler`
   continues to receive v1 behavior.
5. V2 uses conservative, explainable semantic relations for ordering,
   dependency, inclusion and exclusion, direction, stability polarity,
   quantifier scope, numeric association, and other bounded control-domain
   oppositions. Unsupported extrapolations abstain with
   `INSUFFICIENT_EVIDENCE`.
6. Specialized formula, numeric, theorem, and stability analyzers remain
   authoritative when their required structured input is present. Merely
   mentioning words such as "stability", "pole", "criterion", or "condition"
   does not force an unresolved specialized analyzer to override a valid
   semantic-evidence result.
7. Any ambiguous relation fails closed. V2 may return
   `INSUFFICIENT_EVIDENCE`; it must not infer `SUPPORTED` from lexical overlap
   when a contradiction signal or stronger unsupported quantifier is present.
8. Gate B can advance only after a clean-source run against a fresh,
   restricted PostgreSQL 16 database meets every existing threshold,
   including zero `CONTRADICTED -> SUPPORTED` unsafe false negatives.

## Verification Requirements

- Unit tests cover every generic semantic relation category and conservative
  abstention behavior.
- Compatibility tests prove the v1 constructor and v1 artifact build version
  are unchanged.
- A label-leakage test proves that runtime inputs contain no benchmark label or
  rationale fields.
- The complete 72-record benchmark is evaluated without fact-ID or topic-based
  branches.
- The formal evaluator uses `PostgresAcademicEvidenceSource`, restricted
  non-superuser/non-`BYPASSRLS` roles, `FORCE RLS`, immutable replay checks, and
  a fresh database and volume that are separate from release and development
  volumes.
- Passing evidence binds the exact source commit, source tree, dataset hash,
  source-ledger hash, review hash, policy hash, image/environment identity, and
  complete confusion matrix.

## Consequences

The runtime gains a safer semantic verifier without changing the v1 contract
surface. The deterministic rule set is intentionally conservative and
auditable; it is not represented as unrestricted general-purpose language
understanding. New languages or relation families require independent tests
and versioned extension rather than silent rule changes to archived evidence.
