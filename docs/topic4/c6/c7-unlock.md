# C7 Extension Provenance Development Unlock

## Authorization

C7 extension provenance verification is authorized after C6 implementation commit
`272478f10bca56645f14577c81b682584cdf1b9c` completed the protected GitHub Release
Quality Gates workflow in Run `29514876119` with eight successful jobs.

## Allowed Scope

The newly unlocked scope is limited to C7:

- deterministic verification of Topic3 extension resources against Topic1 and C2
  local authority;
- document, paper, citation, industry-application, and academic-source
  provenance checks;
- citation format, identifier, source-version, and content binding validation;
- domain relevance and unsupported-extension detection;
- immutable evidence and result artifacts compatible with C1 and C2;
- dedicated unit, integration, tenant-isolation, boundary, and provenance tests;
- C7 architecture and independent acceptance evidence.

## Mandatory Dependencies

C7 must consume accepted Phase1.1, Topic1-Topic3, C1-C6 foundations without
invasive modification. Topic1 and C2 remain the only authority sources; C1 remains
the state, retry, transaction, audit, Outbox, and publication owner.

## Prohibited Scope

C7 development may not modify frozen contracts, database migrations, Phase1.1,
Topic1, Topic2, Topic3, C1-C6 semantics, provider policy, API routing, C8-C12
runtime, or frontend code. External web search, external embeddings, and
unapproved provider access remain prohibited.

## Entry Criteria

Start C7 from the clean remotely verified C6 acceptance checkpoint. Preserve the
global coverage floor of 90.79 percent, keep Trivy and Gitleaks at zero, retain
all static and supply-chain redlines, and complete the C7 implementation commit
then acceptance-archive remote CI sequence before unlocking C8.
