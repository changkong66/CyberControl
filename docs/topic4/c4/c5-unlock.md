# C5 Quiz Verification Development Unlock

## Authorization

C5 quiz verification is authorized to begin after the commit containing this
certificate completes the protected GitHub `Release Quality Gates` workflow. The
authorization is based on the accepted C4 implementation commit
`a02d09761fa365f72fdb04c5a7291880db69155f` and successful remote Run
`29503160951`.

## Allowed Scope

The newly unlocked scope is limited to the C5 quiz verification domain:

- bounded parsing of Topic3 Tester quiz blocks into the frozen C5 verifier IR;
- question-stem completeness and ambiguity checks;
- answer-key correctness and option-consistency checks;
- deterministic solution-step and scoring consistency checks;
- misconception diagnostic and knowledge-point label validation;
- difficulty calibration against Topic1 golden questions and Topic2 personalization
  context where the frozen contracts permit it;
- C2/C3 evidence-bound verdicts, immutable artifacts, and C1 `ModuleFinding`
  compatibility;
- dedicated unit, integration, tenant-isolation, boundary, and security tests;
- C5 architecture and independent acceptance evidence.

## Mandatory Dependencies

C5 must consume the accepted Phase1.1 and Topic1-Topic3 foundations plus accepted C1,
C2, C3, and C4 modules without invasive modification. Topic1 golden questions and
knowledge-point mappings remain the authority source; C2 evidence remains immutable;
C1 remains the state, transaction, retry, audit, and Outbox owner.

## Prohibited Scope

C5 development may not modify frozen contracts, database migrations, Phase1.1,
Topic1, Topic2, Topic3, C1-C4 semantics, Provider policy, or frontend code. C6 code
verification, C7 extension verification, C8 revision, C9-C11 security/compliance, C12
release authorization, Topic4 final API/worker publication, and frontend development
remain locked.

## Entry Criteria

Before C5 code is written, this acceptance archive must be committed and pushed, and
its exact remote workflow run must complete successfully. The C5 implementation must
then start from that clean, remotely verified checkpoint and preserve the repository
coverage, static-analysis, multi-tenant, container, vulnerability, and secret-scan
redlines.
