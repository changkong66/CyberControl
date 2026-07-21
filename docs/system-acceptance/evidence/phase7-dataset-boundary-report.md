# Phase 7 Gate B Dataset Boundary Report

## Decision

Gate B is **blocked**. The repository now has a content-addressed, deterministic
100,000-record retrieval-performance corpus, but it does not contain the
independently human-reviewed academic golden facts and review attestation needed
to calculate or accept accuracy metrics. This is a real gate failure, not a
test failure to be ignored.

The Phase 7 serial process must not start the 2,000-connection SSE benchmark,
eight-hour soak, disaster recovery, sealed Provider, or production operations
gates until this dataset boundary is accepted.

## Source Binding

- Dataset-tool source commit: `265310f7563c75eb8e0aaf0dd48bd6e8c702eb08`
- Dataset-tool source tree: `d96a0b7fd157c49dc33ea7d0505d175cfcb9539b`
- Source tree was clean at generation: `true`
- Protected main at Gate A: `d25ed4dd92afd37720c158e4828794853ba8670a`
- Dataset inventory: [phase7-dataset-inventory.json](phase7-dataset-inventory.json)
- Dataset inventory SHA256: `ad218c75e5b0bcbecf28d1c8f9a9de06fc62503829bfe49bf9dc14b40b3273b0`
- Registry descriptor SHA256: `a8526a9a080eb775a6d84817bf26ad054c814c1c8163f84513bdd9407fe7b356`

## Dataset Classes

| Dataset | Status | Permitted conclusion |
| --- | --- | --- |
| `phase7-c2-synthetic-retrieval-performance.v1` | Materialized | Retrieval latency, throughput, memory, and index behavior only |
| `phase7-local-demo-fixtures.v1` | Present | Local demonstration workflow only |
| `phase7-academic-human-reviewed-facts.v1` | Missing | None; academic accuracy is not accepted |

### Synthetic Performance Corpus

- Records: `100000`
- Knowledge-point partitions: `100`
- Artifact path: `D:\CyberControlAcceptance\phase7\datasets\phase7-c2-synthetic-retrieval-performance.v1.jsonl`
- Artifact bytes: `52067890`
- Artifact SHA256: `12614d0eb5a59dccf841d1ef8479efec905fa7cff3d7f4d5f6214e9fe9dd4393`
- Generator: `backend/benchmarks/topic4_c2_retrieval.py`
- Generator SHA256: `283c6b11ce739588490f17fbb200d2c8349deeb23e8bb250bb07fa6907a7bbaa`
- License label: `LicenseRef-CyberControl-Internal-Benchmark`

This corpus is synthetic and deterministic. It is intentionally not described
as a human-reviewed factual set, academic coverage corpus, or a measurement of
hallucination accuracy.

### Local Demonstration Fixture

`data/topic1/automatic-control-principles.v1.json` has SHA256
`7de9d68ca809f6a72db58829dfac87628b023adf15813cf2281019b92a9119b1`.
It remains a local fixture with redistribution rights not asserted. Its five
Topic1 golden questions have source citations, but no independent review
attestation or license ledger qualifying them for the Phase 7 accuracy gate.

## Blocking Requirement

The sole Gate B blocker is a supplied, independently reviewed set at:

- `tests/golden/phase7-academic-golden-facts.v1.jsonl`
- `tests/golden/phase7-academic-golden-review.v1.json`

The facts require a source citation and license expression per item. The review
attestation must bind its `ACCEPTED` decision to the exact facts SHA256, identify
the reviewer subject, timestamp, and policy version. The validator must then
pass with `--require-human-reviewed-golden` before the state can advance.
