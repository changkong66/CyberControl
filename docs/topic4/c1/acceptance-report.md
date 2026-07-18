# Topic4 C1 Verification Control Plane Acceptance Report

## 1. Decision

C1 is **ACCEPTED** on `codex/topic4-verifier-runtime`.

The original C1 implementation checkpoint is
`91b27e68358550d281571f55b53be198375bfec0`. Its production application wiring,
real PostgreSQL concurrency coverage, and API surface were completed by
`8d143ba43ae78f3b66ab8d691d1513f03f8baa2d`, which passed Release Quality Gates
Run `29634407475` with all eight jobs successful.

## 2. Accepted Capabilities

- Immutable Candidate acceptance and source snapshot validation.
- Deterministic Claim extraction for text, formula, graph, quiz, code, and
  extension resource blocks.
- Risk scoring with mandatory C9-C11 cross-cutting verification.
- Acyclic C2-C11 dispatch planning and bounded module execution.
- Aggregate release, disclosure, revision, human-review, and block decisions.
- Maximum two-round revision state enforcement and C8 child re-verification.
- Tenant-scoped state, Claim, risk, dispatch, module result, verdict, report,
  and review persistence.
- Idempotency, version CAS, audit hash-chain append, transactional Outbox, and
  TraceID correlation.
- FastAPI and task-queue runtime integration.

## 3. Acceptance Evidence

| Gate | Result |
| --- | --- |
| Full Python/PostgreSQL regression | 428 passed, 1 skipped |
| Global Python coverage | 91.19% (`18,589 / 20,384` lines) |
| Topic4 tests in final JUnit | 201 |
| C1 control-plane and state-machine tests | 18 passed |
| Topic4 API tests | 3 passed |
| 200 concurrent C1 verifications | passed; 200 reports, no duplicate Claims |
| Cross-tenant verification access | blocked by repository scope and FORCE RLS |
| Alembic round trip | `20260716_0009 -> base -> 20260716_0009` passed |
| Database model drift | passed |
| Ruff and format | passed |
| Go, TypeScript, and Vue gates | passed |
| Trivy and Gitleaks | zero findings |
| Remote Release Quality Gates | Run `29634407475`, 8/8 jobs successful |

The single skipped test is the Windows symbolic-link privilege probe. The
database restart test was enabled and passed in the final remote run.

## 4. Failure and Recovery Evidence

1. Duplicate acceptance and state transitions return the persisted idempotent
   result or a deterministic conflict.
2. SERIALIZABLE conflicts retry with a fresh transaction and bounded attempts.
3. The audit predecessor is protected by a tenant advisory lock before reads.
4. Partial module execution is not published as a final report.
5. High-risk and non-waivable findings route to review or block states.
6. Topic3 finalized-event redelivery is deduplicated before C1 execution.

## 5. Freeze Boundary

C1 contracts and semantics are frozen. Later work may consume C1 through the
standard API, queue, repository, and contract surfaces, but must not weaken its
state machine, RLS, audit, Outbox, SHA, CAS, or fail-closed behavior.
