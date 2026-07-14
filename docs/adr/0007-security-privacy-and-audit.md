# ADR-0007: Security, Privacy, and Audit Ownership

**Status:** Accepted

## Decision

The security domain owns prompt injection, secrets, and content policy. The
privacy domain owns PII tokenization, tenant authorization, and encryption. The
compliance domain owns the append-only audit chain, retention, SBOM, and license
records. C1.5 provides audit infrastructure; C10 applies privacy policy through it.

## Consequences

- No domain may maintain a second audit truth source.
- Security and cross-tenant blocks are not manually waivable.
- Model contexts receive only redacted minimum-necessary data.
