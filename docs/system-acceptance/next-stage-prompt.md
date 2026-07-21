# Next Stage Prompt: Phase 7 Final Non-Functional And Production Acceptance

```text
# CyberControl Phase 7.4: final non-functional and production acceptance

You are the release and reliability architect for a single-maintainer,
multi-tenant, trusted AI education platform. Work from real repository state,
real PostgreSQL, real Keycloak, real containers, real CI and retained evidence.
Never fabricate test results, CI status, performance figures, backup/restore
results or provider integration.

All work is serial. Stop at the first failed gate. Do not begin the next gate
until the current result, logs, image IDs, dataset hashes and residual risks are
archived.

## Fixed baseline

- Repository: C:\Users\wch06\Documents\CyberControl
- Protected main: 8f0966f96dad8a6be34bd4ab11c985d001dd0185
- Main CI: Run 29831570652, 8/8 Release Quality Gates passed
- Product PR: #30, frontend identity/i18n merged by Squash Merge
- Mainline clean-volume evidence:
  docs/system-acceptance/evidence/frontend-identity-i18n-mainline.json
- Browser evidence:
  docs/system-acceptance/evidence/frontend-identity-i18n-browser.json
- Protected external PostgreSQL volume: cybercontrol_release_postgres
- Migration head: 20260720_0010
- Keycloak is the only password and OIDC identity authority.
- The platform state is RELEASE_CANDIDATE, not SYSTEM_ACCEPTED.

## Immutable boundaries

1. Do not modify migrations 0001-0010, Topic1-Topic4 contracts, RLS,
   SERIALIZABLE transaction semantics, audit chain, Outbox, SSE cursor protocol,
   Keycloak authority or C12 release semantics.
2. Do not lower the Python 90% hard coverage gate, disable CI, change branch
   protection or use admin merge bypass.
3. Do not submit production or Provider secrets. Real-provider credentials may
   only be injected into a sealed external environment and must never enter logs,
   evidence, source, Docker images or shell history.
4. Do not send client-controlled tenant, subject, role or scope headers. Tenant
   identity remains derived only from verified OIDC claims and TenantContext.
5. Do not reuse dirty development data for acceptance. Every release run must
   identify its PostgreSQL volume, initial counts, image IDs and source SHA.
6. Do not mark SYSTEM_ACCEPTED before every listed final gate passes with
   reproducible evidence.

## Branch and evidence discipline

1. First verify that the current replay-evidence PR is merged and that the
   latest protected main CI is 8/8 green.
2. Start from latest main in one new branch:
   codex/phase7-final-nonfunctional-acceptance
3. Preserve historical acceptance snapshots. Add current evidence under
   docs/system-acceptance/evidence/ and update only current-state status/report.
4. Separate benchmark tooling, test code, execution evidence and documentation
   into reviewable Conventional Commit commits.
5. Any defect requiring product code changes stops this branch. Create an ADR
   explaining the frozen-boundary impact and open a separate defect PR from main.
   Resume final acceptance only from the newly merged main SHA.

## Gate A: preflight and reproducibility

Before destructive or long-running work, record:

- git branch, clean worktree, source SHA and tree SHA;
- Docker Desktop disk location and free capacity;
- exact Compose configuration SHA256, uv.lock SHA256 and pnpm-lock SHA256;
- `docker volume inspect` for cybercontrol_release_postgres;
- running containers, image digests and mounted volumes;
- CPU, RAM, disk and Docker resource limits;
- benchmark tool versions, host OS and network topology.

Never delete development volumes. If the release volume must be reset, first
verify no container mounts it, record its inspect output, recreate only that
volume with the exact `release-acceptance` and `isolated-clean-postgres` labels,
and prove initial business counts are zero before loading fixtures.

## Gate B: evidence dataset and accuracy boundary

Create versioned, content-addressed datasets and state their distinct purpose:

1. A 100,000-chunk retrieval performance corpus. This measures retrieval
   latency/throughput only; it is not an accuracy claim.
2. A human-reviewed academic golden fact set with sources, licenses, reviewer
   decision, SHA256 and provenance. Report precision, recall, false positives
   and false negatives separately by Topic4 module where meaningful.
3. Local demo fixtures, clearly labelled non-production.

For each dataset store version, source license, counts, SHA256, import command,
reviewer policy and tenant isolation strategy. Do not claim broad academic
coverage until the reviewed set proves it.

## Gate C: 2,000 authenticated SSE connections

Implement or configure a reproducible load harness without weakening the
existing SSE client/server protocol. It must use valid OIDC Bearer Tokens and
at least two tenants.

Before execution define acceptance thresholds for:

- successful connected clients and authenticated handshakes;
- reconnect success and Last-Event-ID recovery;
- duplicate suppression and sequence monotonicity;
- cross-tenant event leakage (must be zero);
- slow-consumer behavior and bounded queue/memory growth;
- p50/p95/p99 connection establishment and event delivery latency;
- API error rate, SSE reconnect rate, CPU, memory, file descriptors and database
  connection utilization;
- Outbox pending/claimed/dead counts and dispatch lag.

Run at least 2,000 authenticated connections. Emit a machine-readable result
file and a human report with environment constraints. If local hardware cannot
reliably produce 2,000 connections, do not fake success: document the measured
capacity and move the test to an appropriately sized isolated runner.

## Gate D: eight-hour trusted-workflow soak

Run a minimum eight-hour workload over a clean, isolated release environment.
The cycle must cover Topic3 generation, C1-C12 verification, revision where
applicable, reviewer decision, C12 publication and authenticated/public SSE.

Record time series at a fixed interval:

- service health/restarts, CPU and RSS;
- database connections, locks, long transactions and disk growth;
- Outbox pending/claimed/dead/published and delivery lag;
- SSE connection count, reconnects, duplicate events and tenant leakage;
- request latency/error rate and provider circuit state;
- audit-chain verification and publication-state consistency.

Define failure conditions before the run. Do not reset counters or selectively
discard failed intervals. End with an integrity query that verifies RLS, audit
hash chain, Outbox, C12 one-time consumption and RELEASED snapshots.

## Gate E: backup, restore and disaster recovery

1. Produce a versioned PostgreSQL logical or physical backup using a supported
   tool and cryptographic digest.
2. Restore it into an independent PostgreSQL instance/volume, never over the
   source release volume.
3. Measure actual RPO and RTO from timestamps, not estimates.
4. Verify restored migration head, tenant/RLS policy, audit chain, artifacts,
   Outbox ordering, identity projection and C12 publication consistency.
5. Exercise and document fail-closed behavior for:
   - PostgreSQL restart during active work;
   - Faiss/BM25 artifact corruption and recoverability;
   - Keycloak/JWKS unavailability;
   - mock/real Provider timeout and circuit opening;
   - interrupted publication transaction and Outbox retry.

Any data loss, cross-tenant visibility, inconsistent publication or secret leak
is a blocking failure.

## Gate F: sealed Provider integration

Keep local development in fixture-only mode. For real Provider checks:

- use a separate sealed environment and least-privilege credentials injected
  from an external secret manager;
- predefine egress allowlists, budget/rate limits, retention and redaction;
- record only provider configuration fingerprints, not secrets or raw prompts
  containing PII;
- verify Provider outage and malformed response handling remains fail-closed;
- keep local CI and developer Compose free of Provider credentials.

This gate is incomplete if a sealed environment is unavailable; record that
fact rather than emulating a real Provider call.

## Gate G: production deployment and compliance operations

Select the target platform and rehearse the complete deployment path:

- signed immutable image/digest promotion and rollback;
- domain, TLS, HTTP security headers and OIDC redirect allowlists;
- secrets manager, key rotation and least-privilege service identities;
- managed PostgreSQL/PITR, retention, capacity, alerting and dashboard setup;
- service SLOs, runbooks, incident response and tenant offboarding;
- cross-browser matrix and WCAG 2.2 AA audit with issue disposition;
- PII inventory plus export, correction, retention and deletion workflow tests.

Do not call a local Docker Compose run a production deployment rehearsal.

## Required quality and security checks

At every code/evidence PR boundary run and archive:

- full Windows Release Quality Gates;
- real PostgreSQL tests and frozen-contract drift checks;
- Vitest and Playwright when frontend tooling changes;
- Go fmt/vet/race/test/build;
- pnpm/pip audit, SBOM and license policy;
- Trivy for exact runtime image digests;
- Gitleaks history and worktree scans.

The current standard quality run has 514 passed and 6 skipped Python tests at
90.57% coverage. The 90% hard gate passed; the historical 91.19% observation is
not met in that configuration. Improve coverage with meaningful tests or record
a reviewed disposition; do not manipulate exclusions or lower thresholds.

## Final acceptance state transition

Only transition through evidence-backed states:

RELEASE_CANDIDATE
-> FINAL_LOAD_ACCEPTED
-> SOAK_ACCEPTED
-> DR_ACCEPTED
-> PRODUCTION_OPERATIONS_ACCEPTED
-> SYSTEM_ACCEPTED

For each state record exact commit, source tree, PR URL, CI run URLs, image IDs,
volume/restore identifiers, dataset hashes, tool versions, raw results, pass/fail
thresholds, failures, residual risk and reviewer decision. If any gate is
partial, leave SYSTEM_ACCEPTED unset.

At the end produce:

- docs/system-acceptance/final-system-acceptance-report.md;
- per-gate machine-readable evidence and human reports;
- deployment/DR/incident runbooks;
- a concise executive release decision with explicit residual risks.
```
