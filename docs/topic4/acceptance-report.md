# Topic4 C1-C12 Final Backend Acceptance Report

## 1. Acceptance Decision

Topic4 C1-C12 is **ACCEPTED on `codex/topic4-verifier-runtime`** at
`8d143ba43ae78f3b66ab8d691d1513f03f8baa2d`.

Release Quality Gates Run `29634407475` completed successfully with all eight
jobs green. The implementation is ready for a protected pull request to
`main`. This report does not claim that the mainline merge or CODEOWNERS
approval has already occurred.

## 2. Module Acceptance Matrix

| Module | Accepted capability |
| --- | --- |
| C1 | Claim extraction, risk, DAG dispatch, aggregation, report, review routing |
| C2 | BM25, Topic1 graph, formula signatures, 2048-d hash, local Faiss |
| C3 | Formula, theorem, numeric, unit, and stability verification |
| C4 | Mermaid topology and Topic1 dependency verification |
| C5 | Quiz stem, answer, solution, misconception, and difficulty verification |
| C6 | Python/MATLAB static control-code and resource-safety verification |
| C7 | Local citation provenance, relevance, date, and license verification |
| C8 | Maximum two-round immutable revision and C1 re-entry |
| C9 | Injection, credential, malware, exfiltration, and tenant-reference defense |
| C10 | PII detection, tokenization, redaction, and non-waivable privacy blocks |
| C11 | SBOM, vulnerability, license, and reproducible provenance verification |
| C12 | One-time authorization, atomic publication records, Outbox, and public SSE |

## 3. P0 Runtime Closure

The final implementation closes the previously identified delivery gaps:

1. `backend/src/liyans/api/routes/topic4.py` registers 19 authenticated Topic4
   REST and SSE routes.
2. `backend/src/liyans/main.py` assembles C1, C2, C3-C11, C8, C12, the task
   queue, Topic3 finalized-event consumer, and publication SSE consumer.
3. Topic3 finalized Candidates automatically become Topic4 verification tasks.
4. C12 committed Outbox events are projected to persistent public SSE and can
   be replayed after disconnect.
5. The production container installs the local retrieval extra and validates
   Faiss import at runtime.

## 4. P1 Verification Closure

- Fake C12 PostgreSQL adapters were removed and replaced with real asynchronous
  PostgreSQL tests.
- 200 concurrent C1 verifications produced 200 reports without lost tasks or
  duplicate Claims.
- 200 concurrent C12 consumption attempts converged on one immutable
  publication result without authorization reuse.
- Outbox append failure rolled back authorization consumption and every
  publication row.
- Database container restart recovery passed locally and remotely.
- Duplicate Outbox delivery produced one persistent public SSE event.
- Real C8 v1-to-v2 revision created an immutable child Candidate and child C1
  verification.

## 5. Quantitative Evidence

| Gate | Result |
| --- | --- |
| JUnit | 429 total, 428 passed, 1 skipped, 0 failed |
| Coverage | 91.19% (`18,589 / 20,384` lines) |
| Topic4 tests | 201 |
| Topic4 PostgreSQL integration tests | 12 |
| Alembic | `0009 -> base -> 0009` passed |
| Model drift | passed |
| RAG 100k p95 | 12.283 ms (`<= 200 ms`) |
| RAG max | 14.048 ms |
| Release replay p95 | threshold assertion passed (`<= 300 ms`) |
| Ruff/format | passed, 299 files checked |
| Go | format, mod verify, vet, race, build passed |
| TypeScript/Vue | typecheck and build passed |
| Trivy | 0 findings at all severities |
| Gitleaks | 0 history findings, 0 worktree findings |
| SBOM/license/dependency audits | passed |
| Production image | Faiss import, non-root `10001:10001`, liveness passed |

The only skip is the Windows symbolic-link privilege test. The Docker database
restart probe was enabled in the final local and remote suites.

## 6. Remote Evidence

Run `29634407475` executed:

1. Python, contracts, and unit tests;
2. PostgreSQL 16 integration and coverage;
3. Go contract compiler gate;
4. Vue, TypeScript, pnpm audit, and Node SBOM;
5. Python audit and SBOM;
6. container build, runtime, SBOM, and vulnerability scan;
7. full Git history secret scan;
8. release quality redline.

The run published six evidence artifacts: PostgreSQL/Python test evidence,
container security evidence, frontend SBOM, Python supply-chain evidence, Go
contract evidence, and secret-scan evidence.

## 7. Residual Governance Boundary

Topic4 backend implementation is accepted, but repository integration remains
subject to branch protection. The next action is a formal pull request from
`codex/topic4-verifier-runtime` to `main`, followed by required CODEOWNERS
approval and green PR checks. Frontend business development remains inactive
until that merge completes.
