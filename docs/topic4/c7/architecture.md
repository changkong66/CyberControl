# Topic4 C7 Extension Provenance Verification Runtime

## Scope and Boundary

C7 verifies frozen Topic3 extension resources against the tenant-scoped immutable
C2 evidence bundle and the frozen Topic1 graph snapshot. It never performs web
fetches, external search, external embedding, or model inference. A source URL is
treated as citation metadata only; provenance is accepted only when the local C2
approved corpus supplies matching immutable evidence.

## Runtime Flow

~~~mermaid
flowchart LR
    C1["C1 extension Claim"] --> B["Tenant-scoped evidence adapter"]
    B --> T3["Exact immutable Topic3 Candidate"]
    B --> C2["C2 EvidenceBundle and EvidenceRef"]
    C2 --> T1["Topic1 graph snapshot"]
    T3 --> P["Frozen extension parser"]
    P --> V["Citation and resource verifier"]
    T1 --> V
    C2 --> V
    V --> R["ExtensionResourceV1 + ExtensionVerificationResultV1"]
    R --> O["Canonical SHA-addressed artifact"]
    O --> F["C1 ModuleFinding"]
~~~

## Binding Invariants

1. Claim, Candidate, dispatch item, database tenant context, evidence, Topic1
   snapshot, and artifact tenant are identical.
2. Candidate identity, version, SHA, block ID, block ordinal, content SHA, and
   Claim JSON pointer are checked before parsing.
3. Evidence is ordered by the immutable C2 bundle, and each reference is checked
   for tenant, Claim, Trace, knowledge-base version, record SHA, excerpt SHA, and
   duplicate identity.
4. Topic1 snapshot hash and node/edge counts are checked before relevance scoring.
5. A positive finding requires matching approved-corpus evidence and a compatible
   known license. Unknown provenance remains insufficient evidence.

## Verification Policy

- Citation placeholders, unknown references, future publication years, and missing
  structured citation metadata are rejected or held insufficient.
- Candidate knowledge-point IDs must exist in Topic1. Relevance combines target ID
  coverage and deterministic token overlap with Topic1 title, aliases, summary,
  objectives, category, and tags.
- Citation provenance is local-only. Exact citation matches or conservative token
  overlap against C2 citation/excerpt text are accepted; no URL is fetched.
- SPDX-like license expressions are inferred only from the candidate citation and
  local evidence. Unknown licenses do not produce a positive verdict. GPL, AGPL,
  and non-commercial CC licenses are fail-closed as incompatible for the platform.
- The verdict is `SUPPORTED`, `CONTRADICTED`, `INSUFFICIENT_EVIDENCE`, or `UNSAFE`
  according to the frozen Topic4 common contract and C1 aggregation semantics.

## Persistence and Recovery

C7 writes no database rows directly. It emits immutable contracts and one
content-addressed result artifact; C1 owns transaction state, retries, audit,
Outbox, and publication. Replaying the same Claim and immutable Candidate version
reproduces the same analysis and object key. Loader, tenant, evidence, snapshot,
and artifact integrity failures are fail-closed and never downgraded to a
positive finding.

## Explicit Non-Scope

C7 does not implement C8 revision, C9-C11 cross-cutting security/compliance, C12
release authorization, final API wiring, or frontend behavior. Those modules remain
locked until this acceptance certificate is complete and independently verified.
