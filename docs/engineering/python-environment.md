# Reproducible Python Environment

## Decision

The Python workspace is locked by `uv.lock`, constrained to CPython 3.11, and
managed as one workspace containing the backend and canonical contract package.
Dependency ranges remain readable in package metadata while the lock file records
the exact transitive graph and hashes used by CI and deployment builds.

## Standard commands

Windows PowerShell:

```powershell
.\tools\windows\sync-python-environment.ps1
```

Cross-platform CI:

```text
uv sync --frozen --all-packages --all-extras
uv run --frozen pytest -q
uv run --frozen ruff check packages/contracts-python backend tools --config ruff.toml
```

Changing dependencies requires editing the owning `pyproject.toml`, running
`uv lock`, reviewing the lock diff and vulnerability report, then committing both
files in the same change. `uv sync` without `--frozen` is prohibited in CI.

## Dependency ownership

- Runtime: FastAPI, SQLAlchemy asyncio, asyncpg, Alembic, JWT cryptography,
  Prometheus metrics and approved infrastructure libraries.
- Academic and retrieval extras remain optional and are not imported by the core
  control plane.
- Development: pytest, Hypothesis, Ruff, coverage, PostgreSQL testcontainers,
  pip-audit and CycloneDX SBOM generation.

## Acceptance

- `uv lock --check` returns zero.
- A clean machine can create `.venv` using only the repository and network index.
- `uv sync --frozen --all-packages --all-extras` produces no lock mutation.
- Python reports major/minor version 3.11.
- Tests and Ruff run through `uv run --frozen`.
