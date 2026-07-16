# Topic4 C12 Atomic Release Gate Acceptance Report

## 1. Final Decision

C12 is **ACCEPTED** on `codex/topic4-verifier-runtime`. The implementation
commit `7ffcc0bd49664b8b13604926c5c1980a2feb35ce` passed implementation Run
`29531563951`, and the final archive commit
`0ae8fc7685e88c6f61e5ff6babc00403774cd1ac` passed archive Run `29531925104`.
Both runs completed successfully with all eight jobs green.

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

The dedicated suite completed **11 passed** locally. Ruff and format checks
pass for the C12 source and tests. The remote PostgreSQL evidence package
reported **424 tests with 1 existing database-restart probe skipped** and
global Python coverage of **90.88 percent**, above the `90.54` redline.

The remote job matrix completed 8/8 successfully on both the implementation
and archive runs:

- Python, contracts, and unit tests;
- PostgreSQL 16 integration and coverage;
- Go contract compiler gate;
- Vue, TypeScript, pnpm audit, and Node SBOM;
- Python audit and SBOM;
- container build, runtime, SBOM, and vulnerability scan;
- full Git history secret scan; and
- release quality redline.

The remote run published Python/PostgreSQL test evidence, container security
evidence, secret-scan evidence, Python supply-chain evidence, frontend SBOM,
and Go contract evidence artifacts.

## 5. Remote Acceptance Evidence

The PostgreSQL job verified the C12 repository against the migrated schema,
restricted database roles, append-only constraints, tenant policies, foreign
keys, SERIALIZABLE transaction behavior, Outbox persistence, and rollback
semantics. The container and secret-scan jobs completed without findings, and
the static, contract, Go, TypeScript, SBOM, license, and dependency gates were
successful.

The one skipped test is the existing Docker database-restart probe, which is
explicitly opt-in in the repository workflow and is not a C12 failure. All
mandatory C12 release and PostgreSQL tests completed successfully.

## 6. Frozen Compatibility Boundary

No Phase1.1, Topic1, Topic2, Topic3, C1-C11 source, contract, migration, or CI
policy was modified. C12 is additive under the release domain and consumes
existing frozen contracts and infrastructure interfaces. Frontend development
is now unlocked by the separate certificate in this directory.
