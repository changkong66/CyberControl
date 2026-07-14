# Architecture Baseline

## Current phase

The project has completed requirements and detailed design for Topics 1-4 and
C1-C12. This repository starts the next phase: contract consolidation and
engineering implementation.

## Runtime shape

The selected architecture is a modular FastAPI control plane with isolated
workers where the security or resource boundary requires it.

```text
Vue 3 Web
  -> FastAPI API/control plane
     -> Topic 1 data and knowledge topology
     -> Topic 2 profile and learning-path domains
     -> Topic 3 generation orchestration and SSE staging
     -> Topic 4 verifier orchestration
        -> knowledge retrieval worker
        -> academic truth worker
        -> graph/quiz/extension validators
        -> isolated code sandbox service
     -> durable public SSE event log and release gate
```

This avoids premature microservice fragmentation while preserving process and
deployment isolation for code execution, CPU-heavy retrieval, and mathematical
verification.

## Ownership boundaries

| Boundary | Owns | Must not own |
|---|---|---|
| `topic1` | frozen business data and course topology | verification artifacts |
| `topic2` | six-dimensional profile and route decisions | academic truth rules |
| `topic3` | blueprints, agents, candidates, generation SSE | final release authority |
| `verification` | state machine, claims, decisions, release authorization | source candidate mutation |
| `knowledge` | verifier evidence assets and indexes | topic1 graph mutation |
| `security` | injection, secrets, PII policy decisions | academic scoring |
| `compliance` | audit, SBOM, licenses, retention | generation logic |
| `sandbox` | isolated code validation | provider credentials or core DB access |

## Persistence boundaries

Topic 1 remains frozen. New Topic 4 records use separate schemas or equivalent
repositories:

```text
verification.*
verification_kb.*
audit.*
compliance.*
sandbox.*
```

PostgreSQL is the business state source of truth. Artifact bodies are immutable
objects referenced by hashes. Transactional outbox records bridge state changes
to asynchronous execution and SSE publication.

## Canonical contracts

Pydantic models in `packages/contracts-python` are canonical. JSON Schema and
TypeScript output are generated. Schema consumers use exact version literals
and reject unknown fields.

## Provider posture

- Spark text, XFYun code assistance, and the frozen SeeDance alias are the only
  business-AI provider capabilities on the allowlist.
- All providers are disabled until credentials, official endpoint ownership,
  quota, data policy, and wire compatibility are validated.
- No external embedding provider is approved. The initial RAG implementation
  uses deterministic local retrieval features and Faiss.
