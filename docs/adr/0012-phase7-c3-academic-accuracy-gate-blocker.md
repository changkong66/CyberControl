# ADR-0012: Phase 7 C3 Academic Accuracy Gate Blocker

- Status: Blocked pending versioned remediation
- Date: 2026-07-22
- Owners: Verification platform

## Context

Phase 7 Gate B now has a hash-bound, human-reviewed academic fact set. The
project owner and dataset owner, Wu Chuhan (吴楚涵), accepted the exact facts,
source ledger, and review-policy versions. The owner conflict is disclosed;
the decision is not represented as institutionally independent peer review.

The set contains 72 C3 claims across 24 automatic-control topics, balanced as
24 `SUPPORTED`, 24 `CONTRADICTED`, and 24 `INSUFFICIENT_EVIDENCE` records. Only
the accepted `SUPPORTED` premise for each topic is imported into the evidence
corpus. Expected labels, rationales, and the other hypothesis text are not
indexed, so the evaluation does not use label leakage.

## Formal Evidence

The clean-source run was executed from commit
`557bcca967ade6b8f6aa3f4925ecdaee0334f423` against a fresh PostgreSQL 16
container and volume, with restricted `liyans_app` and `liyans_migrator`
roles. The release volume was not used.

- Facts SHA256:
  `c6f70ff86b7803fa6a0a82bcf5742019c495d8941ed95e62f5e52ea9cf0332dd`
- Source ledger SHA256:
  `f683441fe1b23057e525fc839f5495d358e03bc3d8dd8f26aa2b8ca6a81b88cc`
- Review policy SHA256:
  `bc7a0ca0ca21b2e06bfa869e4d86a80e33ddaa1402df947df7c209c4f77fc12e`
- Accuracy policy SHA256:
  `137adf72c20c2f91f37759a581950209a99556838d41c664dc25122fa1a700b9`
- Report internal SHA256:
  `c9e9f6fce42af978948cb2376d5533296935f482f803480cf4febda2a58b6262`
- Evidence report:
  `docs/system-acceptance/evidence/phase7-c3-accuracy.json`

PostgreSQL and tenant controls passed:

- all seven participating tables had RLS and `FORCE ROW LEVEL SECURITY`;
- the adversarial tenant observed zero claims, plans, retrieval runs,
  evidence references, and evidence bundles;
- immutable changed-content replay was rejected and the original hash was
  preserved;
- all 72 retrieval runs and all 72 result records were present;
- runtime and migration roles were neither superusers nor `BYPASSRLS`.

## Decision

1. Gate B remains `BLOCKED`. Gates C through G remain locked. The accepted
   human-review attestation proves dataset rights, provenance, and reviewer
   acceptance; it does not waive the runtime accuracy threshold.
2. The frozen C3 v1 implementation must not be modified inside the evidence
   branch or by changing the dataset to improve this result.
3. Any remediation must be a separate ADR and versioned compatibility
   extension. Existing C3 v1 contracts, persistence, RLS, transaction, audit,
   and Outbox semantics remain unchanged until a separately reviewed change is
   approved.

## Observed Failure

The formal run produced:

- exact-match accuracy: `0.611111` (`44/72`);
- `CONTRADICTED` precision/recall: `0.500000` / `0.041667`;
- `INSUFFICIENT_EVIDENCE` precision/recall: `0.638889` / `0.958333`;
- `SUPPORTED` precision/recall: `0.588235` / `0.833333`;
- abstention accuracy: `0.958333`;
- critical unsafe false negatives: `13`;
- missing results: `0`; non-deterministic results: `0`.

The unsafe false-negative IDs are:

`C3-001-CON`, `C3-002-CON`, `C3-004-CON`, `C3-005-CON`, `C3-006-CON`,
`C3-008-CON`, `C3-010-CON`, `C3-011-CON`, `C3-012-CON`, `C3-013-CON`,
`C3-017-CON`, `C3-023-CON`, and `C3-024-CON`.

The current `ClaimFactVerifier` primarily measures token overlap and detects
negation in the evidence excerpt. It does not reliably model the semantic
polarity of a negated or contradicted claim against a positive premise. The
observed confusion matrix is therefore a product-behavior failure, not a
database, tenant-isolation, replay, or harness failure.

## Required Remediation Before Re-running Gate B

The owning team must define and review a versioned C3 semantic-verification
extension that:

1. distinguishes claim polarity from evidence polarity and fails closed when
   contradiction cannot be established;
2. preserves evidence provenance and does not accept client-supplied verdicts;
3. adds a predeclared, label-leakage-resistant contradiction benchmark;
4. proves deterministic behavior, tenant isolation, replay rejection, and
   artifact integrity with real PostgreSQL tests;
5. meets the existing thresholds, including zero
   `CONTRADICTED -> SUPPORTED` unsafe false negatives, before Gate B can move.

The remediation must be implemented and reviewed separately from this formal
failure record. A passing result may replace the current Gate B evidence only
after it binds to a new source commit, policy hash, dataset hash, and complete
run report.
