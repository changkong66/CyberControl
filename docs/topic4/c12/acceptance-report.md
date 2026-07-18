# Topic4 C12 Atomic Release Gate Acceptance Report

## 1. Decision

C12 is **ACCEPTED** on `codex/topic4-verifier-runtime`.

The original implementation commit is
`7ffcc0bd49664b8b13604926c5c1980a2feb35ce`. The production FastAPI/runtime
wiring, real PostgreSQL release tests, 200-way contention test, Outbox/SSE
integration, and database recovery evidence were completed by
`8d143ba43ae78f3b66ab8d691d1513f03f8baa2d`. That commit passed Release Quality
Gates Run `29634407475` with all eight jobs successful.

## 2. Accepted Capabilities

- One-time, tenant-bound, expiring release authorization.
- Candidate, report, request, allowed block, and artifact SHA256 binding.
- `FULL` and `FULL_WITH_DISCLOSURE` publication policy.
- Content-addressed public Candidate and publication-event artifacts.
- SERIALIZABLE authorization consumption and publication record transaction.
- Append-only authorization, consumption, PENDING/COMMITTED batch, and public
  stream event records.
- Transactional audit hash-chain append and Outbox publication event.
- Public SSE projection, duplicate-delivery suppression, and replay.
- Fail-closed expiry, changed replay, hash tampering, tenant mismatch, object
  metadata corruption, Outbox failure, and transaction interruption behavior.

## 3. Corrected Database Evidence

The earlier C12 archive relied partly on `_FakeSession`, `_FakeDatabase`, and
`_FakeOutbox` adapter tests. Those tests were removed. They are replaced by
real asynchronous PostgreSQL integration coverage in:

- `backend/tests/integration/test_postgres_topic4_release.py`;
- `backend/tests/integration/test_postgres_topic4_runtime.py`.

The real database tests cover FORCE RLS, authorization expiry, content and
report SHA tampering, changed replay, 200 concurrent consumption attempts,
Outbox failure rollback, immutable publication history, persistent SSE, and
duplicate Outbox delivery.

## 4. Acceptance Evidence

| Gate | Result |
| --- | --- |
| C12 deterministic unit tests | 8 passed |
| Real PostgreSQL C12 repository tests | 2 passed |
| Real PostgreSQL Topic4 runtime tests | 2 passed |
| Full repository regression | 428 passed, 1 skipped |
| Global coverage | 91.19% |
| Concurrent authorization consumption | 200 operations; one immutable result |
| Changed replay and expired authorization | blocked |
| Cross-tenant authorization/publication | blocked |
| Outbox append failure | complete database rollback; retry passed |
| Publication replay p95 gate | passed (`<= 300 ms`, 25 samples) |
| Database restart recovery | passed |
| Trivy and Gitleaks | zero findings |
| Remote CI | Run `29634407475`, 8/8 jobs successful |

## 5. Atomicity Interpretation

The public visibility boundary is the committed PostgreSQL batch, Outbox event,
and SSE projection. Content-addressed objects are written before the database
commit so their SHA can be bound into immutable rows. A failed database
transaction can leave an unreachable content-addressed object, but it cannot
create a public batch, consume an authorization, append a committed event, or
emit public SSE. Unreferenced objects are non-public and can be reclaimed by a
separate retention process.

## 6. Frontend Boundary

C12 backend acceptance prerequisites are complete. Frontend development is not
active until the Topic4 pull request is approved by CODEOWNERS and merged into
the protected `main` branch. The certificate in this directory records that
conditional activation rule.
