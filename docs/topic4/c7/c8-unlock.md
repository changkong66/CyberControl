# C8 Two-Round Revision Development Unlock

## Authorization

C8 revision development is authorized after C7 implementation commit
`1b9e52befb9ff449a62f4b444d82925125719dde` completed GitHub Actions Run
`29517993876` with all eight Release Quality Gates jobs successful.

## Allowed Scope

The newly unlocked scope is limited to C8:

- maximum two-round immutable revision-cycle enforcement;
- per-Candidate concurrent revision exclusion and stale-lock recovery;
- revision plan and patch validation against Candidate ID, base version,
  Candidate SHA, Block ID, Claim IDs, and Trace ID;
- append-only Candidate version creation without rewriting historical Candidate,
  report, evidence, or patch records;
- deterministic patch application to frozen Topic3 block content;
- automatic C1 re-entry command generation after a successful revision;
- C1 transaction, audit, Outbox, and idempotency integration through existing
  frozen boundaries;
- dedicated unit, concurrency, tenant-isolation, replay, boundary, and recovery
  tests plus independent C8 architecture and acceptance evidence.

## Prohibited Scope

C8 may not modify Phase1.1, Topic1-Topic3, C1-C7 contracts or semantics, existing
migrations, provider policy, C9-C12 runtime, API routing, or frontend code. It may
not mutate historical Candidate versions or bypass the two-round limit.

## Entry Criteria

Start C8 from the clean remotely verified C7 acceptance checkpoint. Preserve
global coverage at or above 90.89 percent, keep Trivy and Gitleaks at zero, and
complete the C8 implementation-commit then acceptance-archive remote CI sequence
before unlocking C9-C11.
