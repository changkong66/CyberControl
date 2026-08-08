# CyberControl Phase 7 Gate C Fifth Remediation And Rerun - Next Task

You are the enterprise reliability and trusted-context engineer for
CyberControl. Work only from real protected-main evidence, real PostgreSQL,
real Keycloak Tokens, real Docker images and real GitHub Actions. Do not
reinterpret a partial pass as Gate C acceptance and do not start Gate D.

## Fixed Baseline

- Workspace: `C:/Users/wch06/Documents/CyberControl`
- Verified fourth-remediation product source:
  `97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504`
- Verified source tree:
  `bad6b0f9e7008b934a54681f9f304a786ee9afe7`
- Fourth remediation PR: [#52](https://github.com/changkong66/CyberControl/pull/52)
- PR #52 head: `3c75c532bc8860debfe865eb08f63543fbd70eea`
- Protected-main CI:
  [Run 30196139462](https://github.com/changkong66/CyberControl/actions/runs/30196139462),
  attempt 2, 8/8 successful
- Current state: `RELEASE_CANDIDATE`
- Formal state: `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Latest failed run:
  `D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260808T083601Z-97bfa5fef7e1`
- Latest failure analysis:
  `docs/system-acceptance/evidence/phase7-gate-c-fourth-remediation-failure-analysis.md`
- Raw evidence package SHA256:
  `9b2c4c116752197bf10dd1bc9d29409e59bdca1eca7be3cd4a0df1d1bef26f8d`
- Gate D-G: locked

Before creating a branch, fetch `origin/main`. Require its exact current tip
to be a descendant of `97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504`, to contain the
fourth-remediation failure-evidence metadata, and to have a successful 8/8
protected-main Release Quality Gates run. Branch only from that verified tip.

## Evidence-Backed Failure Boundary

The formal fresh-volume run passed 20, 200 and 500 authenticated SSE streams.
The 1,000-stream stage held 1,000 active streams for 603 seconds and then failed
the unchanged controls:

- commit-to-client p95/p99: `1631 / 6132 ms`, required
  `<= 1000 / <= 3000 ms`;
- Outbox p95/p99: `6292.587 / 8712.164 ms`, required
  `<= 2000 / <= 5000 ms`;
- Outbox `DEAD`: `2`, required `0`.

Both DEAD rows are `topic3.workflow.finalized`, sequence `2`, attempts `3/3`,
with `last_error_code=LIYAN-AUTH-FORBIDDEN`. This proves an authorization
failure in finalized-event durable delivery. It does not prove whether the
defect is the event envelope, service-subject policy, publisher tenant-context
propagation, consumer context construction or another authorization boundary.

At 1,000 streams, connection and reconnect/replay success were `1.0`, event
loss, duplicate final rendering, cross-tenant leakage, HTTP 5xx, pool timeouts,
OOM and unplanned restarts were zero. Final subscribers, queued events and
replay-cache events were `0/0/0`; FORCE RLS remained `74/74`. Preserve all of
these results.

Connection-establishment p95/p99 was `19964/23705 ms`; real Keycloak Token
acquisition had zero failures. This is a readiness signal, not permission to
increase client timeout. The 2,000-stream and recovery stages were not executed
and remain completely unproven by this run.

## Non-Negotiable Constraints

1. Do not modify migrations `0001-0010`, frozen contracts, RLS, FORCE RLS,
   identity authority, `TenantContext`, SERIALIZABLE semantics, Outbox
   atomicity, C12 publication semantics, Gate C thresholds or workload.
2. Do not send `X-Tenant-ID`, `X-Subject-Ref`, role or scope identity headers.
   Tenant, subject and authorization must remain server-derived.
3. Do not bypass policy checks, grant broader service roles, acknowledge an
   event before authorized acceptance, or classify authorization failure as
   success.
4. Do not hide latency by increasing client timeout, changing grace periods,
   reducing events/connections, weakening ordering, forcing GC, excluding
   coverage or changing metric aggregation.
5. Every formal rerun must use real Keycloak-issued Tokens, a new evidence
   directory, new Compose project and fresh isolated PostgreSQL volume.
6. Preserve all historical failed packages and volumes. Never prune, overwrite
   or reuse development, release or historical Gate C volumes.
7. Gate D-G remain locked regardless of local tests, CI or partial-stage pass.

## Required PR-1: Fifth Scoped Remediation

Create `codex/phase7-gate-c-fifth-remediation` from the exact verified current
main. Before behavioral changes, add a concise ADR or design note that maps
each proposed change to a failed metric and states the measurement that would
disprove the root-cause hypothesis.

### A. Finalized-Event Trusted Authorization Chain

- Trace `topic3.workflow.finalized` from the transaction that writes the Outbox
  row through claim, publisher dispatch, consumer authorization, durable
  acceptance and SSE projection.
- Inspect the event envelope's tenant, subject, actor, audience, scope and
  provenance fields without logging raw Tokens, PII or tenant identifiers.
- Identify which trusted principal is expected to consume this internal event
  and how its policy is derived. Separate end-user authority from service-
  process authority; do not fabricate user claims for background work.
- Prove whether `TenantContext` and database session context are created,
  restored and cleared correctly for every claimed event, retry, cancellation
  and partition transition.
- Preserve fail-closed behavior for missing, malformed, mismatched or cross-
  tenant claims. A fix must make valid finalized events pass and invalid events
  fail for the correct reason.
- Add bounded, non-PII counters for authorization decision reason, event type,
  lifecycle phase and retry disposition. Do not use tenant, subject, Token,
  cursor or event ID as metric labels.

### B. Retry, DEAD And Claim Ownership

- Classify deterministic authorization failures separately from transient
  transport, timeout and dependency failures while retaining bounded retries
  and full auditability.
- Verify timeout or cancellation releases or renews claims atomically and does
  not leave long-lived `CLAIMED` or `PENDING` rows.
- Preserve `FOR UPDATE SKIP LOCKED`, claim tokens, leases, partition ordering,
  idempotent consumer behavior and published-cursor semantics.
- Do not reset attempts, silently republish a DEAD event, skip the failed event
  or acknowledge it early to satisfy latency.
- Add reconciliation evidence for an event whose external dispatch succeeds
  but local completion fails, and for local claim success followed by an
  authorization rejection.

### C. Outbox And Commit-To-Client Latency

- Measure at least `created -> claimable`, `claimable -> claimed`, `claimed ->
  dispatch start`, `dispatch start -> authorized acceptance`, `accepted -> SSE
  enqueue` and `enqueue -> client`.
- Correlate the two DEAD finalized events with partition head-of-line blocking,
  retries and the observed p95/p99, without putting identifiers into metric
  labels or reports.
- Determine whether the dominant delay is poll/wakeup cadence, claim query,
  partition serialization, authorization retries, dispatcher scheduling,
  notification fanout or client delivery.
- Apply only evidence-backed changes. Preserve atomic publication, ordered
  delivery, retry durability and tenant isolation.
- Include deterministic bounded-load regressions showing no finalized-event
  DEAD row and meeting stage-level latency budgets without claiming that a unit
  test proves the formal 1,000/2,000-stream gate.

### D. Admission Readiness Diagnostics

- Separate Keycloak Token issuance, TCP/HTTP admission, authentication,
  subscriber registration, replay acquisition, `REPLAYING -> LIVE` handoff and
  first heartbeat/event latency.
- Explain the 1,000-stage `19964/23705 ms` connection-establishment p95/p99
  with queue, task, file-descriptor, event-loop and PostgreSQL evidence.
- Preserve the fourth remediation's single close owner, zero `aclose()` races,
  zero tail loss, duplicate suppression and terminal `0/0/0` subscriber/queue/
  replay-cache gauges.
- Do not increase the load-client timeout or add a client-only grace period.

### E. Tests And Quality Gates

- Extend unit tests around the Outbox publisher, Topic3 Outbox envelope,
  authorization policy and tenant-context lifecycle.
- Add real PostgreSQL tests for valid finalized-event delivery, malformed and
  cross-tenant envelope rejection, service-principal authorization, retry
  exhaustion, claim release, partition ordering, duplicate dispatch,
  reconciliation and concurrent tenant isolation.
- Add a regression that reproduces the exact `topic3.workflow.finalized`
  sequence-2 path under concurrency and proves `PUBLISHED`, not `DEAD`, for a
  valid event while an invalid event remains fail-closed.
- Assert session/connection return and ContextVar restoration after success,
  forbidden decisions, timeout and cancellation.
- Keep Python coverage `>= 90%`; target no lower than the latest accepted local
  evidence. No empty assertions, fabricated scale tests or coverage excludes.
- Run complete local quality gates: Python unit and real PostgreSQL integration,
  frontend, Playwright, Go, contract drift, SBOM/license, Trivy and Gitleaks.
- Push and open the remediation PR. Require push and pull-request Release
  Quality Gates 8/8, Squash Merge only after green, then require the resulting
  protected main to pass 8/8.

## Required PR-2: Fresh Gate C Mainline Evidence

Only after PR-1 merges and protected main is clean and 8/8:

1. Build all images from the new main without `-SkipBuild` and record source
   commit/tree, image IDs, Compose hash, lock-file hashes, tool versions and
   host resources.
2. Create a unique Compose project, uniquely named PostgreSQL volume and new
   run directory. Do not reuse any prior Gate C, release or development volume.
3. Use real Keycloak Tokens, at least two tenants and at least ten real subjects
   per tenant.
4. Execute the unchanged frozen sequence: 20-stream smoke; 200 for five
   minutes; 500 for five minutes; 1,000 for ten minutes; 2,000 for thirty
   minutes; ten-minute recovery observation.
5. Collect Token issuance, admission, replay/LIVE handoff, reconnect,
   Last-Event-ID, client loss/duplicates/isolation, segmented Outbox and
   delivery latency, CPU, RSS, file descriptors, tasks, subscribers, queues,
   replay caches, PostgreSQL sessions/pool, RLS and Outbox terminal evidence.
6. Redact all Tokens, passwords, verification codes, secrets and PII. Produce
   SHA256 manifests and retain large raw evidence as an immutable Release Asset.
7. If every frozen control passes in the same run, create an independent
   success-evidence PR and mark
   `PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`.
8. If any frozen control fails, stop the workload, preserve the volume, archive
   a new immutable failure package and PR, retain
   `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, and stop.
9. The evidence PR must pass push and pull-request 8/8, Squash Merge, and the
   merged protected main must pass 8/8.

## Stop Rule

After the Gate C evidence PR is merged and protected-main CI is known, stop.
Do not begin Gate D soak, disaster recovery, Provider acceptance, production
deployment, accessibility/privacy closure or new product features. Gate D is
eligible only after a complete Gate C success-evidence PR has merged and a
separate user-authorized task begins.
