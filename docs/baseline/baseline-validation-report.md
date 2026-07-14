# Baseline Validation Report

**Baseline:** `engineering-foundation/0.1.0`
**Result:** Topic 3 engineering foundation passed with production blockers

## Completed

- Repository ownership boundaries and monorepo layout are established.
- ADR-0001 through ADR-0009 are accepted.
- The provider policy is machine-readable and fail-closed.
- External embedding is prohibited by policy and code validation.
- Spark text, XFYun code assistance, and SeeDance default to disabled.
- The canonical Pydantic contract package is present.
- JSON Schema and TypeScript declarations are generated from that package.
- The C1-C12 contract catalog has unique schema names and owners.
- Baseline validation and Python bytecode compilation pass.
- Topic 3 Envelope, Block, Candidate, error receipt, and SSE chunk are strict v1.
- TypeScript and Go contracts are generated from the Pydantic source.
- Ordered messaging, idempotency, SSE recovery, task resilience, tenant context,
  hot configuration, unified errors, tracing, and audit hash chain are implemented.
- FastAPI health and internal Topic 3 contract endpoints are executable.
- Windows user-scope Go 1.26.5, Ruff 0.15.21, GCC 16.1.0, GNU Make 4.4.1,
  and Chocolatey 2.7.3 are installed and command-validated.
- Go contracts pass module verification, Vet, unit tests, Race tests, and build.
- Ruff strict scanning passes with zero findings across backend, contracts, and tools.

## Provider capability status

| Capability | Status | Blocker before enablement |
|---|---|---|
| Spark text | allowlisted, disabled | official endpoint, credentials, quota, wire smoke tests |
| XFYun code assistance | allowlisted, disabled | official service API and contract smoke tests |
| SeeDance | allowlisted alias, disabled | official product/endpoint and account evidence |
| external embedding | prohibited | requires policy change and superseding ADR |
| local deterministic retrieval | approved design | install and benchmark local dependencies |

No external provider is operationally confirmed in this repository because no
official credentials, endpoint evidence, or smoke-test artifacts are present.

## Production blockers

1. Implement PostgreSQL idempotency, transactional outbox, durable SSE, audit,
   tenant repositories, and migrations behind the coded ports.
2. Implement authentication and signed trusted identity propagation.
3. Install and lock Python and Node dependencies; generate initial SBOMs.
4. Validate the three allowlisted Provider adapters using approved credentials.
5. Add CI, secret scanning, dependency vulnerability gates, and load environments.

## Commands executed

```text
tools/export_contracts.py
tools/validate_baseline.py
python -m pytest -q
python -m compileall -q backend/src packages/contracts-python/src tools
ruff check packages/contracts-python backend tools --config ruff.toml
tools/windows/build-go-contracts.ps1
```

All completed successfully on Python 3.11.15 and Go 1.26.5. The backend and
contract suite has 25 passing tests. Frontend dependencies are locked with pnpm;
Vue type checking and the production build pass. Go and Ruff are now complete
release gates rather than unresolved environment blockers.
