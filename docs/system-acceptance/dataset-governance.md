# Phase 7 Dataset Governance

## Purpose Boundaries

Phase 7 uses three strictly separated dataset classes.

| Class | Permitted use | Prohibited claim |
| --- | --- | --- |
| Synthetic retrieval-performance corpus | C2 retrieval latency, throughput, memory, and index-size measurement | Academic accuracy, hallucination rate, or educational coverage |
| Local demonstration fixtures | Repeatable local OIDC, Topic1-Topic4, publication, and SSE demonstrations | Production corpus quality or redistribution rights |
| Human-reviewed academic golden facts | Module-specific precision, recall, false-positive, and false-negative measurement | Performance capacity without a separate load corpus |

The 100,000-record C2 corpus is generated deterministically and is content
addressed at execution time. It is synthetic by design. Its historical p95
result is a performance observation, not a quality or accuracy result.

## Eligibility

The human-reviewed academic set is accepted only when its JSONL facts and review
attestation pass `tools/acceptance/build-phase7-dataset-inventory.py` with
`--require-human-reviewed-golden`. The attestation binds the reviewer decision
to the exact facts, source-ledger, and review-policy SHA256 values. It must state
source citation, license expression, reviewer subject reference, qualification,
ownership conflict and disposition, review time, policy version, rights review,
class counts, and `ACCEPTED`.

No model-generated, benchmark-generated, or pre-existing demonstration fixture
may be relabelled as human-reviewed solely because it has a source citation or
a Git author. Source citations and repository authorship do not prove an
independent academic review.

## Current Boundary

The Gate B branch now contains a structurally valid 72-record C3 set, a
commercial-use source ledger, a review policy, and an `ACCEPTED` hash-bound
human attestation. The exact-hash human-review prerequisite is complete, so the
set is eligible for module-specific release accuracy execution. Phase 7 remains
below `SYSTEM_ACCEPTED` until clean-commit validation, module-specific accuracy
execution, real PostgreSQL isolation evidence, CI, protected-main merge, and
mainline replay all pass.
