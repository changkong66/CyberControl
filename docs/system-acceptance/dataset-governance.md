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
to the exact facts SHA256. It must state source citation, license expression,
reviewer subject reference, review time, policy version, and `ACCEPTED`.

No model-generated, benchmark-generated, or pre-existing demonstration fixture
may be relabelled as human-reviewed solely because it has a source citation or
a Git author. Source citations and repository authorship do not prove an
independent academic review.

## Current Boundary

At this point the repository contains a deterministic 100,000-record benchmark
generator and a local Topic1 fixture. It does not contain a qualifying human
reviewed academic golden fact set or review attestation. Consequently accuracy
metrics are not yet eligible for release acceptance, and Phase 7 must remain
below `SYSTEM_ACCEPTED`.
