# Topic4 C2 Local-First Hybrid RAG Acceptance Report

## 1. Decision

C2 is **ACCEPTED**. The implementation checkpoint
`c8e4009159b232cc324f6842699bac149d0aedf8` and its final production wiring in
`8d143ba43ae78f3b66ab8d691d1513f03f8baa2d` passed Release Quality Gates Run
`29634407475` with all eight jobs successful.

## 2. Accepted Scope

- Deterministic Markdown, text, and structured JSON ingestion.
- Bounded chunking and immutable source/document/chunk snapshots.
- BM25, Topic1 graph expansion, formula signatures, and 2048-dimensional
  signed lexical hash retrieval.
- Local Faiss shards without external embedding or network search.
- SHA-validated index artifacts, hot activation, CAS refresh, restore, and
  persistent self-healing.
- Tenant-scoped PostgreSQL repositories and FORCE RLS compatibility.
- SERIALIZABLE lifecycle transactions, idempotency, audit, and Outbox.
- Immutable query plans, retrieval runs, evidence references, and evidence
  bundles.
- FastAPI retrieval and evidence query integration.

## 3. Verification Evidence

| Gate | Result |
| --- | --- |
| Final repository regression | 428 passed, 1 skipped |
| Final global coverage | 91.19% |
| Database restart recovery | passed in local and remote Docker probes |
| Faiss corruption recovery | passed |
| BM25 corruption recovery | passed |
| Activation CAS rollback and retry | passed |
| Cross-tenant knowledge/evidence access | blocked |
| 100,000-block retrieval p95 | 12.283 ms |
| 100,000-block retrieval max | 14.048 ms |
| Index build time | 22.049 s |
| Serialized index size | 216.968 MiB |
| Peak working set | 1,221.141 MiB |
| Retrieval SLA | passed (`p95 <= 200 ms`) |
| Trivy and Gitleaks | zero findings |
| Remote CI | Run `29634407475`, 8/8 jobs successful |

The machine-readable benchmark is
`docs/topic4/c2-100k-benchmark.json`.

## 4. Recovery Guarantees

1. Corrupt Faiss or BM25 artifacts are rejected before activation.
2. Recovery rebuilds from immutable local corpus data and publishes a new
   content-addressed artifact.
3. Concurrent recovery converges through activation CAS.
4. A failed activation transaction leaves no partial database state.
5. Database restart reconstructs the active index from PostgreSQL metadata and
   immutable artifacts.

## 5. Freeze Boundary

C2 remains local-first and deterministic. External embeddings, external web
retrieval, cross-tenant indexes, mutable evidence, and unversioned activation
are prohibited compatibility breaks.
