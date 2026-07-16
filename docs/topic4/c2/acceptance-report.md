# Topic4 C2 Checkpoint Acceptance Report

## 1. Decision

**Decision: CHECKPOINT_READY.** C2 local-first authoritative hybrid retrieval
is implemented and passes the current repository quality redlines. This report
does not mark Topic4 as `ACCEPTED`; C3-C12 and the final release gate remain
unimplemented.

## 2. Implemented Scope

- Deterministic Markdown, text, and structured JSON source ingestion.
- Immutable source-version, document-IR, chunk, formula-signature, and index
  artifact persistence.
- BM25, Topic1 graph expansion, formula-signature matching, and 2048-dimensional
  signed lexical hash retrieval.
- Sharded Faiss/BM25 artifacts with SHA validation, hot activation, restore, and
  local self-healing.
- Tenant-scoped repositories, PostgreSQL RLS compatibility, SERIALIZABLE
  lifecycle transactions, idempotency, audit hash-chain append, and Outbox
  events.
- Query plan, evidence reference, evidence bundle, and retrieval-run persistence
  with deterministic replay.
- Activation CAS refresh for cached retrieval services and concurrent recovery
  winner consumption.

## 3. Verification Evidence

| Gate | Result |
|---|---|
| C2 unit and integration suite | 18 passed, 1 normal skip |
| Full repository regression | 269 passed, 2 skipped |
| Full Python coverage | 90.32% |
| Database migration upgrade/downgrade/upgrade | passed at `20260716_0009` |
| Database restart recovery probe | 1 passed after real Docker restart |
| Concurrent Faiss/BM25 self-healing | passed for both artifact types |
| Cross-tenant KB/evidence read isolation | passed |
| Failed activation CAS rollback and same-key retry | passed |
| 100,000 knowledge-block retrieval | p95 11.933 ms, max 13.151 ms |
| 100,000-block index build | 22.297 s |
| 100,000-block serialized index size | 216.968 MiB |
| Peak process working set in benchmark | 1,298.797 MiB |
| Ruff and format | zero violations |
| Contract regeneration and drift | passed |
| Go vet, race test, build | passed |
| TypeScript/Vue typecheck and build | passed |
| Python dependency audit | passed |
| CycloneDX SBOM and license policy | passed |
| Trivy container scan | zero findings |
| Gitleaks working-tree and history scan | zero findings |

The reproducible benchmark output is stored in
`docs/topic4/c2-100k-benchmark.json`.

## 4. Rollback and Recovery Guarantees

1. A stale activation version aborts before any knowledge-base rows are
   committed.
2. A failed SERIALIZABLE operation leaves no knowledge-base, chunk, or manifest
   rows and permits a retry after the transaction rolls back.
3. Corrupt Faiss or BM25 artifacts are never accepted as valid evidence sources.
4. Recovery creates new artifact keys and manifest snapshots; historical data is
   retained for audit and replay.
5. Two concurrent recovery processes converge on one persisted READY snapshot.
6. A service/database restart reconstructs the active index from PostgreSQL
   metadata and immutable local artifacts.

## 5. Explicit Non-Claims

The following are intentionally outside this checkpoint:

- C3-C7 formula, graph, question, code, and extension professional verifiers.
- C8 bounded self-correction and Topic3 revision callback.
- C9-C11 injection, privacy, supply-chain, and license runtime verifiers.
- C12 one-time release authorization and atomic publication.
- Topic4 REST routes, asynchronous worker consumers, and public SSE wiring.
- Topic4 final `ACCEPTED` status and frontend unlock.

## 6. Checkpoint Exit Criteria

C2 can be committed as a standalone additive checkpoint when the working tree
contains only the listed C2 assets, the full quality gate remains green, and the
commit is pushed through the protected pull-request workflow. The next allowed
development step is C3-C7 vertical verification; no frontend or final release
work is unlocked by this report.
