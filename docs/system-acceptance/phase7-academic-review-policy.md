# Phase 7 Academic Golden Review Policy

Policy version: `phase7.academic-review-policy.v1`

## Scope

This policy governs the human decision for
`phase7-academic-human-reviewed-facts.v1`. The set evaluates only the frozen
Topic4 `C3_ACADEMIC` verdict boundary. It does not certify C2 retrieval
capacity, C4-C12 security or compliance modules, the accuracy of generated
teaching content, or the system as a whole.

## Source Eligibility And Rights

A source is eligible only when its identity, stable URL, content hash, locator,
and reuse terms are recorded in
`docs/system-acceptance/evidence/phase7-academic-source-ledger.v1.json`.
Accepted reuse terms must permit commercial use. CC BY and public-domain
sources are eligible; noncommercial, no-derivatives, unknown-rights, paywalled
text-mining-only, and permission-ambiguous sources are excluded.

Facts must be original short paraphrases. The dataset must not reproduce source
figures, tables, equations as artwork, or substantial passages. Attribution is
provided through the source ledger and each fact's structured citation.

## Reviewer Qualification And Conflict

The reviewer must be a natural person with relevant automatic-control or
education-technology expertise. A single-maintainer repository owner may act as
reviewer only when all of the following are recorded in the attestation:

- reviewer subject reference;
- relevant qualification statement;
- project and dataset ownership conflict;
- explicit disposition of that conflict;
- exact facts, source-ledger, and policy SHA256 values.

Owner review is not represented as institutionally independent peer review.
External academic review remains a recommended production-readiness control,
but is not silently inferred or fabricated.

## Review Procedure

The reviewer checks every record for:

1. one stable unique fact identifier;
2. a precise claim suitable for deterministic adjudication;
3. the expected frozen `VerificationVerdict`;
4. a source locator that supports the adjudication or explains why the input is
   under-specified;
5. matching commercial-use license information;
6. absence of copied source prose and unlicensed media;
7. absence of tenant, learner, reviewer, or production PII.

The final decision is valid only for the exact facts SHA256. Any byte change to
the facts, source ledger, policy, reviewer identity, or decision fields requires
a new review timestamp and attestation.

## Label Mapping And Balance

Permitted expected outcomes are:

- `SUPPORTED`: the cited source directly supports the claim.
- `CONTRADICTED`: the cited source directly conflicts with the claim.
- `INSUFFICIENT_EVIDENCE`: the claim cannot be determined from the supplied
  conditions; the correct behavior is abstention, not invention.

`NOT_APPLICABLE`, `PARTIALLY_SUPPORTED`, `UNSAFE`, and `ERROR` are not
used in this C3 fact-only v1 set. They require separate reviewed fixtures.

The v1 set contains at least 60 records, at least 20 records per permitted
outcome, at least 16 distinct topics, and only `C3_ACADEMIC` targets. Aggregate
accuracy must never hide per-class or per-topic results.

## Metrics

For each class, report one-vs-rest TP, FP, TN, and FN, plus precision and recall.
Report abstention accuracy separately for `INSUFFICIENT_EVIDENCE`. Division by
zero is reported as `NOT_MEASURABLE`, never coerced to 0 or 1.

A contradicted claim predicted as `SUPPORTED` is a critical unsafe false
negative. Any such result blocks Gate B accuracy acceptance. Other thresholds
must be declared before execution and reported by class and topic.

## Tenant Isolation And Retention

Golden records contain no tenant data and are immutable repository fixtures.
Runtime evaluation must seed them into an isolated acceptance tenant in real
PostgreSQL, verify FORCE RLS with a second tenant, and delete the temporary
runtime projection after evidence capture. The source JSONL and attestation are
retained under Git history; superseded versions are not rewritten.

## Decision States

- `PENDING_HUMAN_HASH_CONFIRMATION`: candidate facts and hashes exist, but the
  named human has not confirmed that exact version.
- `ACCEPTED`: the named human explicitly accepts the exact bound hashes.
- `REJECTED`: one or more academic, provenance, rights, or conflict controls
  failed.

A coding agent may prepare the files and record a human instruction, but must
not convert a pending decision to `ACCEPTED` without a human confirmation
bound to the displayed facts SHA256.

