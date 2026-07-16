# Topic4 C12 Atomic Release Gate Acceptance Report

## 1. Current Decision

C12 implementation is complete locally and is marked
`IMPLEMENTED_PENDING_REMOTE`. It is not yet `ACCEPTED`, and no frontend unlock
certificate is issued. This status is intentional because the local machine
does not currently expose the repository's PostgreSQL integration URLs.

## 2. Delivered Assets

- `backend/src/liyans/domains/release/engine.py`
  - canonical authorization and report integrity checks;
  - trusted tenant and subject checks;
  - FULL/FULL_WITH_DISCLOSURE policy enforcement;
  - deterministic content-addressed artifact creation;
  - idempotent in-memory atomic adapter for deterministic tests.
- `backend/src/liyans/domains/release/postgres_repository.py`
  - SERIALIZABLE transaction execution;
  - issued authorization row binding;
  - one-time consumption uniqueness boundary;
  - PENDING/COMMITTED append-only snapshots;
  - public stream event persistence;
  - audit hash-chain append and Outbox event registration;
  - complete replay contract and hash validation.
- `backend/src/liyans/domains/release/__init__.py`
  - stable C12 service/repository exports.
- `backend/tests/test_topic4_c12_release.py`
  - 11 deterministic tests covering success, disclosure filtering, expiry,
    tenant isolation, hash tampering, changed replay, issued-row mismatch,
    corrupted object metadata, PostgreSQL transaction wiring, replay snapshot
    integrity, and authorization-row tampering.

## 3. Security and Consistency Controls

| Control | Verification | Result |
| --- | --- | --- |
| Tenant isolation | trusted context equality before storage/repository access | locally covered; remote RLS pending |
| Authorization replay | append-only consumption identity and request SHA | locally passed |
| Expired authorization | reject before first consumption | locally passed |
| Committed replay after expiry | return existing committed snapshot | implemented; remote DB evidence pending |
| Candidate tampering | canonical Candidate SHA recomputation | locally passed |
| Report tampering | Topic4 record SHA and report artifact SHA checks | locally passed |
| Disclosure leakage | public artifact filters to allowed block IDs | locally passed |
| Batch/event tampering | full contract hash validation on replay | locally passed |
| External SSE side effects | Outbox only inside transaction; dispatcher after commit | implemented; remote integration pending |
| Partial database commit | SERIALIZABLE transaction boundary | implementation covered; remote rollback pending |

## 4. Local Verification Evidence

The dedicated suite completed **11 passed**. Ruff and format checks pass for
the C12 source and tests. The C12 release package coverage is **87.0 percent**
in the local deterministic suite. The complete project-wide coverage and
PostgreSQL evidence must be collected by the repository quality workflow
before the state can change to `ACCEPTED`.

## 5. Acceptance Conditions Still Open

1. Run the full remote quality workflow with PostgreSQL integration enabled.
2. Verify the public-event foreign key to the COMMITTED batch snapshot.
3. Verify FORCE RLS, tenant separation, unique one-time consumption, and
   rollback using restricted PostgreSQL roles.
4. Confirm the global coverage redline and all supply-chain/security gates.
5. Commit the final archive, wait for remote CI, then update this status to
   `ACCEPTED` and issue `frontend-unlock.md`.

## 6. Frozen Compatibility Boundary

No Phase1.1, Topic1, Topic2, Topic3, C1-C11 source, contract, migration,
frontend, or CI policy was modified. C12 is additive under the release domain
and consumes existing frozen contracts and infrastructure interfaces.
