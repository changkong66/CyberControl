# ADR-0005: Local-First RAG Vectorization

**Status:** Accepted

## Decision

Until an embedding capability is explicitly added to the provider allowlist,
RAG uses local BM25, formula signatures, Topic 1 graph expansion, and 2048-
dimension deterministic feature-hash vectors in Faiss.

## Consequences

- No online embedding call is permitted.
- A future semantic embedding capability requires a new ADR, provider review,
  embedding profile, and complete new knowledge-base version.
- Different embedding profiles never share one index.
