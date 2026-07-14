# ADR-0002: Contract-First Versioning

**Status:** Accepted

## Decision

Pydantic models are the canonical contract source. JSON Schema and TypeScript
types are generated. All wire models reject unknown fields, and any semantic or
structural change creates a new major wire version.

## Consequences

- Hand-maintained duplicate frontend wire types are prohibited.
- Contract compatibility tests block merges.
- Historical records are read using their original schema version.
