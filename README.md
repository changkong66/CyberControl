# Liyan

Liyan is an automation-course personalized learning platform built with a
Vue 3 frontend and a Python 3.11/FastAPI backend. Topic 3 shared Envelope
contracts and the executable engineering foundation are now implemented.

## Repository layout

```text
backend/                    FastAPI control plane and domain modules
frontend/                   Vue 3 application
packages/contracts-python/  Canonical Python/Pydantic wire contracts
packages/contracts-ts/      Generated TypeScript contract package
config/                     Versioned non-secret policy configuration
docs/                       Architecture baseline, ADRs, and implementation roadmap
infra/                      Local and production deployment assets
tests/                      Cross-system contract, security, load, and E2E tests
tools/                      Contract export and repository automation
```

## Frozen engineering decisions

- Python 3.11, FastAPI, and fully asynchronous I/O.
- Vue 3 Composition API, Tailwind CSS, and SSE.
- A modular control-plane backend with isolated retrieval and sandbox workers.
- Canonical contracts are authored in Pydantic and exported to JSON Schema and
  TypeScript. Hand-maintained duplicate wire types are prohibited.
- Business AI providers are restricted to the approved XFYun/SeeDance aliases
  in `config/providers.toml`.
- No additional external embedding provider is approved. RAG starts with local
  BM25, formula signatures, knowledge-graph expansion, and deterministic
  feature-hash vectors in Faiss.

See `docs/roadmap/implementation-sequence.md` for the implementation order.
See `docs/topic3/envelope-and-infrastructure.md` for the Topic 3 freeze.
See `docs/operations/windows-toolchain-validation.md` for Windows Go/Ruff setup
and the current toolchain acceptance record.
