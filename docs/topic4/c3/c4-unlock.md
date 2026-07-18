# C4 Development Unlock Certificate

## Authorization

Topic4 C3 Academic Verification is `ACCEPTED` for the code checkpoint
`78935de20699036b3db04032ea62241dc548b76a`.

The exact checkpoint passed the local release gates and GitHub Actions Run
`29496695774` (`Release Quality Gates`), which completed with `success`:

https://github.com/changkong66/CyberControl/actions/runs/29496695774

This certificate unlocks only C4 Mermaid graph and dependency verification. It does
not accept the overall Topic4 runtime and does not unlock C5-C12 or the frontend.

## Permitted Scope

- Implement deterministic Mermaid syntax, node, edge, dependency, and graph-integrity
  verification using the frozen Topic1 graph and Topic4 Envelope contracts.
- Add compatible C4 runtime code, tests, documentation, and non-invasive adapters.
- Reuse the accepted C1 execution, C2 evidence, C3 evidence-binding, artifact, audit,
  and tenant-isolation boundaries.

## Immutable Boundaries

- Do not modify Phase1.1, Topic1, Topic2, Topic3, C1, C2, or C3 frozen semantics.
- Do not bypass C1 dispatch, C2 evidence binding, tenant RLS, immutable artifacts, or
  the future C12 release gate.
- Do not start C5-C12 or frontend implementation in the C4 change set.
- Do not introduce external web retrieval, unapproved model providers, or external
  embeddings.

## Required C4 Exit Gate

C4 must provide deterministic graph validation, cross-tenant and malformed-input
tests, artifact and trace binding, local quality gates, a C4 acceptance report, and a
remote CI-successful checkpoint before C5 can be unlocked.
