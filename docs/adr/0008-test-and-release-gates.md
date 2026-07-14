# ADR-0008: Test and Release Gates

**Status:** Accepted

## Decision

Every frozen requirement maps to automated tests. G0-G12 release gates must pass,
with zero open P0/P1 defects and zero flaky core state, security, academic, or
publication tests.

## Consequences

- Coverage alone cannot satisfy academic or security acceptance.
- Provider tests separate local overhead from provider latency.
- The final release artifact includes SBOM, evidence-chain verification, load,
  recovery, and system acceptance reports.
