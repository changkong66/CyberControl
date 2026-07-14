# ADR-0003: Provider Allowlist and Adapter Isolation

**Status:** Accepted

## Decision

Only the frozen Spark text, XFYun code-assistance, and SeeDance aliases may be
implemented as external business-AI adapters. All are disabled until runtime
validation succeeds. No third-party model or embedding provider is permitted.

## Consequences

- Business code depends on internal provider protocols, never vendor SDK types.
- Provider output is untrusted and schema-validated.
- A provider outage cannot authorize release or suppress required verification.
