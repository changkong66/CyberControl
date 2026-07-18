# Topic4 C5 Quiz Verification Runtime

## 1. Scope

C5 verifies immutable Topic3 Tester questions against the exact Topic1 graph
snapshot and C2 evidence selected for a C1 Claim. It checks question completeness,
knowledge-point targeting, golden-answer coverage, solution coherence,
misconception diagnostics, question type, and normalized difficulty. C5 is fully
deterministic and performs no provider call, external search, external embedding,
or Internet access.

C1 remains the sole owner of state transitions, retries, result persistence,
aggregation, audit records, and Outbox publication. C5 adds no table or migration;
it emits the frozen C5 IR/result contracts inside a tenant-scoped immutable
content-addressed artifact and returns the existing C1 ModuleFinding.

## 2. Runtime Flow

~~~mermaid
flowchart LR
    C1["C1 quiz Claim"] --> B["Read-only evidence adapter"]
    B --> T3["Exact Topic3 Candidate version"]
    B --> C2["Latest C2 EvidenceBundle"]
    C2 --> KB["Exact KnowledgeBaseVersion"]
    KB --> T1["Immutable Topic1 snapshot"]
    T3 --> P["Frozen Tester question parser"]
    P --> IR["QuizItemVerifierIRV1"]
    IR --> V["Deterministic C5 verifier"]
    T1 --> V
    C2 --> V
    V --> R["QuizVerificationResultV1"]
    R --> A["Canonical SHA-addressed artifact"]
    A --> F["C1 ModuleFinding"]
~~~

## 3. Binding and Isolation Invariants

1. Dispatch tenant, Claim tenant, database tenant context, Candidate tenant,
   evidence tenant, and artifact tenant must be identical.
2. Candidate identity, version, canonical SHA, block identity, block ordinal,
   content SHA, question ordinal, and Claim JSON pointer are validated before
   parsing.
3. EvidenceBundle, KnowledgeBaseVersion, EvidenceRef, excerpt SHA, Trace ID,
   verification ID, Claim ID, and graph snapshot version are validated in one
   existing database transaction.
4. The adapter uses frozen repositories whose queries include explicit tenant
   predicates and remain protected by FORCE RLS.
5. Positive findings require at least one immutable C2 evidence reference.

## 4. Verification Rules

### 4.1 Stem and target validation

The stem must be bounded by the frozen Tester contract, contain a concrete
question/command signal, contain balanced math delimiters, and not contain
placeholder text. Every target knowledge-point ID must exist in the exact Topic1
snapshot. Golden-question selection is limited to questions whose primary or
related knowledge points intersect the candidate targets. Exact question IDs win;
otherwise deterministic token similarity is used and ambiguous ties fail closed.

### 4.2 Answer and solution validation

Topic1 answer_document leaves are compared by type:

- finite numbers use deterministic absolute/relative tolerance and percentage
  normalization;
- booleans require explicit positive/negative conclusions;
- formula-like strings use the accepted C3 safe local SymPy parser, then fall back
  to normalized authority-token coverage;
- nested arrays and objects are flattened in canonical key/index order.

All authority leaves must be covered for answer_correct=true. Solution steps must
be non-placeholder, unique, overlap the answer, and overlap the authoritative
Topic1 solution. C5 never executes generated content.

### 4.3 Diagnostic and difficulty validation

Misconception diagnostics must map to the exact misconception IDs or diagnosis tags
referenced by the selected golden question. Difficulty levels 1-5 normalize to
0.00, 0.25, 0.50, 0.75, and 1.00; deviation above 0.26 is flagged. Frozen Topic3
question types are mapped conservatively to frozen C5 item types and compared with
the Topic1 golden-question family.

## 5. Verdict Policy

| Condition | Verdict |
| --- | --- |
| Complete match with immutable authority and evidence | SUPPORTED |
| Difficulty-only or non-fatal metadata mismatch | PARTIALLY_SUPPORTED |
| Wrong/incomplete answer, incoherent solution, invalid diagnosis, type/topic mismatch | CONTRADICTED |
| Missing Candidate, snapshot, golden question, or evidence | INSUFFICIENT_EVIDENCE |
| Tenant, Claim, SHA, evidence, or contract binding failure | UNSAFE |
| Immutable Topic1 authority integrity failure | ERROR |

## 6. Persistence and Recovery

The result document includes Candidate SHA, KnowledgeBaseVersion, Topic1 snapshot
SHA, selected golden question, similarity/coverage metrics, frozen C5 IR, frozen C5
result, and evidence IDs. Canonical JSON is stored under a C5 verification/Claim
content-addressed key. Existing object-store collision checks make replay
idempotent. C5 writes no database rows directly, so C1 transaction rollback, retry,
audit, and Outbox behavior remain unchanged.

## 7. Explicit Boundary

C5 does not implement C6 code execution checks, C7 extension provenance, C8
revision, C9-C11 cross-cutting security/compliance, C12 release authorization,
Topic4 final API/worker wiring, or frontend behavior. Those scopes remain locked
until their preceding remote acceptance certificate is issued.
