# Topic4 C4 Mermaid Graph Verification Runtime

## 1. Scope

C4 validates Mermaid knowledge graphs emitted by the frozen Topic3 MindMap
contract. It parses only a bounded, non-executable Mermaid subset, resolves graph
nodes against an immutable Topic1 snapshot, and checks prerequisite topology against
the exact Topic1 graph version referenced by the C2 evidence bundle.

C4 is a deterministic verifier. It does not call a model provider, an external
search service, an embedding service, or the public Internet. C1 remains the owner
of verification state, transaction boundaries, result persistence, aggregation, and
Outbox publication. C4 returns the frozen C1 `ModuleFinding` shape and writes only
an immutable content-addressed result artifact.

## 2. Runtime Flow

```mermaid
flowchart LR
    T3["Topic3 MindMap Candidate"] --> C1["C1 ModuleExecutionContext"]
    C1 --> SRC["C2 EvidenceBundle + KnowledgeBaseVersion"]
    SRC --> B{ "Tenant / Claim / Trace / SHA binding" }
    B -->|"reject"| E1["C4 diagnostic artifact"]
    B -->|"valid"| P["Bounded Mermaid parser"]
    P -->|"unsafe or malformed"| E2["UNSAFE finding"]
    P -->|"parsed IR"| R["Topic1 snapshot resolver"]
    R --> G["Node, edge, prerequisite and cycle checks"]
    G --> V["Conservative graph verdict"]
    SRC --> G
    V --> A["Canonical JSON artifact"]
    A --> H["SHA-bound ArtifactObjectRef"]
    H --> F["Frozen C1 ModuleFinding"]
    F --> C1DB["C1 persistence and aggregation"]
    C1DB --> O["Existing audit / Outbox / SSE path"]
```

## 3. Layer Responsibilities

| Layer | Component | Responsibility |
| --- | --- | --- |
| Parsing | `BoundedMermaidParser` | Normalize and parse the Topic3-safe grammar with bounded resource and directive policies. |
| Evidence | `PostgresGraphEvidenceSource` | Atomically load the latest C2 bundle, its knowledge-base version, and the exact Topic1 snapshot. |
| Resolution | `Topic1GraphVerifier` | Resolve node IDs, titles, and aliases to Topic1 knowledge-point IDs and validate immutable snapshot integrity. |
| Topology | `Topic1GraphVerifier` | Check prerequisite direction, omitted edges, unresolved endpoints, unsupported relations, and cycles. |
| Orchestration | `C4GraphHandler` | Enforce C1 context compatibility, classify failures, create artifacts, and return `ModuleFinding`. |
| Artifact | Existing `ArtifactObjectStore` | Persist canonical JSON under a tenant-scoped, SHA-addressed immutable key. |

## 4. Input and Binding Contract

1. The dispatch item tenant and Claim tenant must be identical.
2. The Claim kind must be `GRAPH`.
3. Evidence must match tenant, verification ID, Claim ID, and Trace ID.
4. Every evidence record must pass its canonical record hash and excerpt hash
   validation.
5. Every evidence reference in the selected C2 bundle must point to the same
   `KnowledgeBaseVersion` as the bundle.
6. The knowledge-base record and evidence-bundle record must pass their canonical
   record hash checks.
7. The knowledge base must resolve to the requested immutable Topic1 snapshot and
   its graph version must match the knowledge-base binding.
8. A positive graph finding always carries at least one authoritative evidence
   reference. Missing evidence cannot be promoted by parser or topology results.

The source adapter performs the database-bound checks in one existing transaction.
The handler repeats the security-critical evidence and knowledge-base binding checks
at the module boundary so alternate test or worker loaders cannot bypass them.

## 5. Bounded Mermaid Grammar

The parser accepts the graph forms required by the frozen Topic3 MindMap output:

- `graph` and `flowchart` headers with `TB`, `TD`, `BT`, `RL`, or `LR` direction;
- explicit rectangle, round, circle, diamond, hexagon, and subroutine nodes;
- directed prerequisite edges, labeled supported relation edges, and undirected
  contrast edges;
- safe comments, accessibility text, class/style declarations, and bounded
  subgraphs.

The parser rejects executable or ambiguous constructs, including script tags,
JavaScript/data URLs, click callbacks, init directives, unsafe CSS URLs, malformed
fences, duplicate declarations, duplicate edges, self edges, unknown relation labels,
and unclosed subgraphs. Character, line, node, edge, label, and subgraph-depth limits
are enforced before the graph is handed to semantic verification.

## 6. Semantic Verification Rules

### 6.1 Node resolution

Resolution first accepts an exact Topic1 knowledge-point ID. Otherwise it matches a
normalized title or alias. Normalization applies Unicode NFKC, case folding,
punctuation folding, and whitespace normalization. Zero matches are unknown; more
than one match is ambiguous. An exact ID whose display label names a different
Topic1 point is rejected as `TOPIC1_NODE_ID_LABEL_MISMATCH`.

### 6.2 Edge and dependency checks

- `PREREQUISITE` edges must have resolved endpoints and the exact source-to-target
  direction present in Topic1.
- A Topic1 prerequisite between two displayed nodes may not be omitted.
- An invented or reversed prerequisite is contradictory.
- A candidate prerequisite subgraph containing a cycle is contradictory.
- `CONTAINS`, `DERIVES`, `CONTRASTS`, and `APPLIES_TO` are syntactically accepted
  for safe parsing but are not authoritative relations in the frozen Topic1
  prerequisite model. They produce `RELATION_NOT_VERIFIABLE_FROM_TOPIC1` and can
  never produce a positive finding.
- Unknown or ambiguous nodes produce insufficient evidence rather than a guessed
  mapping.

### 6.3 Verdict policy

| Condition | Verdict |
| --- | --- |
| Unsafe directive or parser security limit | `UNSAFE` |
| Snapshot or evidence integrity failure | `ERROR` or `UNSAFE` according to failure boundary |
| Reversed, invented, omitted, or cyclic prerequisite | `CONTRADICTED` |
| Unknown/ambiguous node, unsupported relation, or missing authoritative evidence | `INSUFFICIENT_EVIDENCE` |
| All resolved prerequisite relations agree with Topic1 and evidence is present | `SUPPORTED` |

The policy is fail-closed: absence of evidence, unresolved identity, and
non-authoritative relationships never become a positive result.

## 7. Immutable Result Artifact

The handler serializes a canonical JSON document containing:

- handler and schema versions;
- Trace ID, tenant ID, verification ID, Claim ID, and module-run ID;
- normalized Mermaid source and source SHA256;
- KnowledgeBaseVersion and Topic1 snapshot identifiers and hashes;
- ordered evidence reference IDs;
- immutable graph IR records;
- the structured graph verification result.

The artifact digest is calculated over the canonical document. The object key is
partitioned by verification ID, Claim ID, and digest. The existing object store
requires the same SHA and byte size when a key already exists, providing deterministic
replay and collision detection. C1 persists the returned `ModuleFinding` and remains
the sole owner of publication and audit side effects.

## 8. Failure and Recovery Boundaries

1. Parser policy failures return an immutable diagnostic artifact and `UNSAFE`.
2. Snapshot hash/count failures return a diagnostic artifact and `ERROR`.
3. Tenant, Claim, Trace, evidence, or knowledge-base binding failures return a
   diagnostic artifact and `UNSAFE`.
4. Missing snapshot or evidence returns `INSUFFICIENT_EVIDENCE`.
5. Artifact store metadata mismatch raises a validation error; no finding is
   considered publishable because C1 receives no valid artifact reference.
6. C4 does not mutate evidence, Topic1 snapshots, C2 indexes, C1 state, or frozen
   upstream contracts. Retry and transaction recovery remain delegated to C1 and
   the existing persistence runtime.

## 9. Resource and Security Limits

The default parser limits are 65,536 characters, 4,096 lines, 4,096 nodes, 16,384
edges, 512-character labels, and 16 subgraph levels. Result artifacts are bounded
to 32 MiB. All object writes use the existing tenant-partitioned artifact store.
No user-provided Mermaid string is executed or rendered inside the verifier.

## 10. Verification Evidence

The dedicated C4 suite covers parser grammar and security limits, Topic1 label and
topology semantics, cycles, omitted/reversed edges, cross-tenant evidence, trace and
Claim binding, knowledge-base version binding, snapshot integrity, artifact replay,
invalid loaders, and C1 executor compatibility. C4 acceptance status and exact
checkpoint/remote CI evidence are recorded in `acceptance-status.json` and
`acceptance-report.md` after the implementation checkpoint has passed the repository
quality workflow.

## 11. Explicit Scope Boundary

C4 does not implement C5 quiz verification, C6 code sandbox verification, C7 source
and license verification, C8 revision, C9-C11 security/compliance modules, C12
release authorization, Topic4 API routing, worker consumers, or frontend behavior.
Those modules remain locked until the preceding acceptance certificate is issued.
