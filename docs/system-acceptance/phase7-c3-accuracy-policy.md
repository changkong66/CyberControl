# Phase 7 C3 Academic Accuracy Policy

Policy version: `phase7.c3-accuracy-policy.v1`

## Scope

This policy evaluates only the frozen Topic4 `C3_ACADEMIC` runtime against
`phase7-academic-human-reviewed-facts.v1`. It does not measure C2 retrieval
capacity, other Topic4 modules, generated-content quality, or system-wide
acceptance.

## Evidence Input

Each of the 24 topics has exactly one human-reviewed `SUPPORTED` claim. That
source-derived paraphrase is the only academic excerpt indexed for all three
claims in the same topic. `expected_outcome`, `expected_outcome_rationale`, and
the `CONTRADICTED` or `INSUFFICIENT_EVIDENCE` claim text are never inserted into
the C2 evidence corpus.

This premise/hypothesis layout prevents expected-label leakage while keeping
the evaluated source material within the reviewed CC BY attribution boundary.
C2 retrieval must persist immutable `EvidenceRefV1` and `EvidenceBundleV1`
records in real PostgreSQL. C3 must load those records through
`PostgresAcademicEvidenceSource` and execute through `BoundedModuleExecutor`.

## Metrics

The report must include:

- the complete expected-versus-actual confusion matrix;
- exact-match accuracy;
- one-vs-rest TP, FP, TN, FN, precision, and recall for each expected class;
- abstention accuracy for `INSUFFICIENT_EVIDENCE`;
- per-topic outcomes;
- every `CONTRADICTED` claim predicted as `SUPPORTED` as a critical unsafe
  false negative;
- unexpected verdicts without remapping them to a passing class.

Division by zero is reported as `NOT_MEASURABLE`, never as zero or one.

## Predeclared Thresholds

Gate B academic accuracy requires all of the following:

- overall exact-match accuracy at least `0.90`;
- precision and recall at least `0.90` for `SUPPORTED`;
- precision and recall at least `0.90` for `CONTRADICTED`;
- precision and recall at least `0.90` for `INSUFFICIENT_EVIDENCE`;
- abstention accuracy at least `0.90`;
- zero critical unsafe false negatives;
- zero missing module results;
- zero non-deterministic results.

No aggregate score can waive a failed class threshold or unsafe false
negative.

## PostgreSQL And Tenant Controls

The evaluator must use restricted PostgreSQL roles that are neither superusers
nor `BYPASSRLS`. It provisions one evaluation tenant and one adversarial tenant
in an isolated ephemeral database, verifies `RLS` and `FORCE RLS` on all
participating tables, and proves that the adversarial tenant sees zero Claims,
query plans, evidence references, evidence bundles, and retrieval runs from the
evaluation tenant.

A changed-content replay using an existing immutable Claim identity must be
rejected and the original Claim hash must remain unchanged. The ephemeral
database and artifact directory must be destroyed after evidence capture; they
must not use or modify `cybercontrol_release_postgres`.

## Decision

The evaluator writes evidence even when thresholds fail. A threshold or
database-control failure returns a blocking exit code and Gate B remains below
accepted. Product behavior must not be changed inside the evidence run to make
the metric pass.
