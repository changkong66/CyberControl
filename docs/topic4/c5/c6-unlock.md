# C6 Control-Code Verification Development Unlock

## Authorization

C6 control-code verification is authorized after C5 implementation commit
782e62c20203164347dd06aef1b9693b04ab3f45 completed the protected GitHub Release
Quality Gates workflow in Run 29510019468 with eight successful jobs.

## Allowed Scope

The newly unlocked scope is limited to C6:

- bounded parsing of frozen Topic3 CodeSandboxContentV1 files;
- MATLAB and Python syntax and entrypoint validation without executing untrusted
  code in the verifier process;
- automatic-control transfer-function, stability, parameter, and simulation-flow
  checks using local deterministic analysis;
- bounded loop, resource, filesystem, process, network, and unsafe-import detection;
- dependency and SBOM binding checks using the existing C11-compatible evidence
  contracts where the frozen design requires them;
- C2 evidence-bound verdicts, immutable artifacts, and C1 ModuleFinding
  compatibility;
- dedicated unit, integration, tenant-isolation, boundary, and security tests;
- independent C6 architecture and acceptance evidence.

## Mandatory Dependencies

C6 must consume accepted Phase1.1, Topic1-Topic3, C1-C5 foundations without
invasive modification. Topic1 control knowledge and C2 evidence remain authoritative;
C1 remains the state, retry, transaction, audit, and Outbox owner.

## Prohibited Scope

C6 development may not modify frozen contracts, database migrations, Phase1.1,
Topic1, Topic2, Topic3, C1-C5 semantics, provider policy, API routing, C7-C12
runtime, or frontend code. C7 extension verification, C8 revision, C9-C11
security/compliance, C12 release authorization, and frontend development remain
locked.

## Entry Criteria

Start C6 from the clean remotely verified C5 checkpoint. Preserve global coverage
at or above 90.69 percent, keep all static/security/supply-chain redlines green,
and complete the same implementation-commit then acceptance-archive remote CI
sequence before unlocking C7.
