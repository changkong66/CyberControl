# Implementation Sequence

## Phase 0: Baseline consolidation

- Finalize the Topic 3 Envelope against `EnvelopeHeaderV1`.
- Export the canonical JSON Schema bundle and generated TypeScript package.
- Run contract-registry and provider-policy validation.
- Record any superseding decisions as ADRs.

Exit criteria: no schema ownership conflict, no unresolved provider capability,
and no frozen requirement without a code/test owner.

Status: completed for the Topic 3 shared wrapper and Provider policy baseline.

## Phase 1: Engineering foundation

- Configure the Python and Node workspaces and lock dependencies.
- Implement settings, authentication context, async database sessions, artifact
  repository, transactional outbox, structured logs, metrics, and trace context.
- Establish CI checks, SBOM generation, secret scanning, and migration ownership.

Status: completed and frozen as Phase 1.1. PostgreSQL RLS, OIDC/JWKS, transactional
Outbox, global idempotency, audit hash chain, persistent SSE, reproducible locks,
SBOM, container security, and local/remote CI gates are accepted.

## Phase 2: Topics 1 and 2

- Implement the frozen data repositories and knowledge topology readers.
- Implement profile extraction, decay, Ebbinghaus scheduling, and route planning.
- Add deterministic and multi-tenant tests before model integration.

Status: completed, accepted, and frozen. The Topic 1 acceptance commit remains
`7eb9b940ed10dbca09c62d2caed809245e75ae5b`; Topic 2 subsequently completed its
six-dimensional profile, memory-decay, and adaptive-path runtime.

## Phase 3: Topic 3 generation plane

- Implement immutable blueprints, envelopes, candidates, provider adapters, and
  the five generation agents.
- Stage candidate bodies and implement generation-status SSE events.

Status: completed, accepted, and frozen. The five-agent cluster, immutable
blueprints, DAG orchestration, transactional Outbox, and persistent SSE runtime are
part of the protected backend baseline.

## Phase 4: Topic 4 verifier core

- Implement C1 contracts, state machine, claims, routing, module scheduler,
  aggregation, release authorization, audit, recovery, and SSE publication.

Status: completed, accepted, and frozen as the C1 control plane and C12 release
foundation.

## Phase 5: Specialist verification

- Implement C2 and C3 first, then C4-C7.
- Implement C8 revision only after specialist results are stable.
- Implement C9-C11 as mandatory release dependencies.

Status: completed, accepted, and merged through Topic 4 PR #16. C1-C12, local-only
RAG, specialist verification, two-cycle revision, cross-cutting compliance, and the
atomic publication gate are present on protected `main` at
`190ed863c13f8f71d909b6083b929c899e4db69f`.

## Phase 6: Frontend integration

- Implement the Vue learning workspace, generated TypeScript contracts, SSE
  reducer, Markdown/LaTeX/Mermaid rendering, quizzes, code views, review states,
  and mobile/desktop layout verification.

Status: active. `codex/frontend-workbench` is created and the frontend unlock is
active. Governance synchronization, additive trust-boundary APIs, and the frontend
engineering foundation must land sequentially before Topic business pages begin.

## Phase 7: System acceptance

- Execute C12 G0-G12 gates, golden datasets, security red-team tests, 2000 SSE
  connections, 100 concurrent verification workflows, soak, and disaster recovery.
- Produce `SystemAcceptanceReportV1`; production release requires `ACCEPTED`.

Status: pending. Topic 4 module acceptance does not satisfy the G0-G12 product-level
acceptance gates.
