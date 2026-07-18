# Topic4 End-to-End Backend Validation Report

## 1. Validated Chain

The real PostgreSQL runtime suite validates this chain:

`Topic3 finalized Candidate -> Topic4 C1 acceptance -> queue execution ->
C2-C11 findings -> aggregate report -> C8 immutable revision and child C1
verification when required -> C12 authorization consumption -> committed
publication Outbox event -> persistent public SSE -> cursor replay`.

## 2. Trace and Persistence Evidence

The integration scenario uses one tenant-bound TraceID across Candidate,
verification, Claim, evidence, report, authorization, publication batch, public
event, Outbox envelope, and SSE payload. Trace queries remain tenant scoped and
return immutable record SHA and version metadata.

## 3. Topic3 Handoff Evidence

The Topic3 finalized-event consumer loads the durable generation session,
selects COMPLETE Candidates, creates deterministic verification identities,
accepts them through C1, and enqueues the standard Topic4 task type. Duplicate
event delivery is idempotent.

## 4. Revision Evidence

The suite creates a real C8 replacement artifact, persists Candidate version 2
without changing version 1, creates a child verification request, and executes
the child C1 control plane.

## 5. Publication and SSE Evidence

The C12 scenario issues and consumes a one-time authorization, persists the
append-only batch and public event, appends the Outbox envelope in the same
database transaction, dispatches it through the message bus, and verifies one
persistent SSE replay event after duplicate delivery.

## 6. Acceptance Result

The final JUnit run contains 12 Topic4 PostgreSQL integration tests and 201
Topic4 tests overall. The full suite passed with no failures at 91.19% global
coverage, and the exact implementation commit passed remote Run `29634407475`.
