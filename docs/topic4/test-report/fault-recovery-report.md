# Topic4 Fault Recovery Acceptance Report

## 1. Database Recovery

The C2 restart probe closes the active database manager, restarts the actual
PostgreSQL Docker container, waits for health, reconnects with a new manager,
and verifies that the active knowledge-base manifest and retrieval behavior are
preserved. The probe passed locally and in Run `29634407475`.

## 2. Index Corruption Recovery

- Corrupt Faiss artifacts are rejected by SHA and format validation.
- Corrupt BM25 artifacts are rejected by SHA and format validation.
- Rebuild uses the immutable local corpus, creates a new artifact, and switches
  activation through CAS.
- Concurrent recovery attempts converge on one READY activation.

## 3. Transaction Failure Recovery

The C12 PostgreSQL test injects an Outbox append failure inside publication. It
asserts that authorization consumption, PENDING and COMMITTED batches, public
events, and audit-visible publication state do not partially commit. A retry
after the failure succeeds.

## 4. Duplicate Delivery Recovery

The publication Outbox envelope is dispatched twice through the message bus.
The idempotency store marks the second delivery as duplicate, while persistent
SSE replay contains one committed public event.

## 5. Artifact Concurrency Recovery

Two hundred concurrent content-addressed filesystem writes for the same key and
content produce one created object and 200 identical SHA results. Nonexistent
deep paths are validated against their nearest existing ancestor to avoid
Windows false path-escape failures without weakening symbolic-link checks.

## 6. Fail-Closed Conditions

Expired authorizations, changed replays, tenant mismatch, SHA mismatch, missing
evidence, invalid state transitions, failed index validation, and uncertain
publication transactions are blocked rather than downgraded to success.
