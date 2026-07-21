# CyberControl Project Stage Audit

## 1. Precise Stage Position

CyberControl has completed the engineering foundation, Topic1-Topic4 backend,
and the frontend business workbench. The protected main branch is
`8df24c6c79c0674809e5891329d4fab405bb090e`; PRs #16-#26 are merged and protected
main Release Quality Gates run 29731316528 completed 8/8 jobs successfully.

The project is now in **Phase 7 system acceptance and release closure**, not
Phase 6 frontend implementation. PR #25, its PR/push gates and the merged-main
clean external-volume replay passed. The project is now a `RELEASE_CANDIDATE`,
not yet `SYSTEM_ACCEPTED`.

Weighted implementation estimate: **about 90%**.

This estimate is not an acceptance state. It assigns 50% to the backend product
chain, 25% to the frontend workbench, 10% to reproducible local acceptance, and
15% to production operations and final non-functional gates. The first three
areas are substantially complete; production deployment, long-running resilience
and external integration account for most remaining work.

| Area | Maturity | Objective assessment |
| --- | --- | --- |
| Phase1.1 foundation | 100% | merged, protected, reproducible |
| Topic1-Topic4 backend | 100% feature complete | frozen business scope; current patch fixes acceptance/runtime integration defects |
| Frontend workbench | about 95% | business surfaces delivered; real report rendered; some semantic and breadth gaps remain |
| Local demonstrable product | about 95% | real OIDC and trusted release chain passes on clean data |
| Production operations | about 45% | CI and secure containers exist; deployment, soak, DR and real Provider gates remain |

## 2. Completed And Frozen Assets

### 2.1 Phase1.1 Production Foundation

- Async FastAPI and SQLAlchemy runtime on PostgreSQL 16.
- OIDC/JWKS authentication and trusted `TenantContext`.
- Protected main has 68 tenant tables with RLS and FORCE RLS; the additive
  identity candidate raises the tested branch schema to 74/74.
- SERIALIZABLE transaction helpers, global idempotency and CAS controls.
- Append-only evidence, audit SHA chain and Artifact Store.
- Transactional Outbox, persistent SSE replay, signed cursors and recovery.
- Reproducible Python, Node and Go toolchains and frozen lockfiles.
- Non-root production containers, SBOM, license policy, Trivy and Gitleaks gates.
- Solo-maintainer protected-branch governance without disabling quality controls.

### 2.2 Topic1 Authoritative Knowledge Topology

- Course, knowledge-point, prerequisite, misconception, textbook and golden-question models.
- Immutable graph snapshots, import/export and rollback semantics.
- Repository/service/API layers and frozen cross-language contracts.
- Tenant isolation, revision CAS, append-only audit and acceptance archive.

### 2.3 Topic2 Adaptive Learning

- Six-dimensional behavior profile and immutable profile snapshots.
- Ebbinghaus memory decay, review reinforcement and forgetting risk.
- Adaptive path planning with prerequisite repair and deterministic replay.
- Tenant-scoped repository, APIs, idempotency and PostgreSQL concurrency tests.

### 2.4 Topic3 Five-Agent Generation Plane

- Lecturer, MindMap, Tester, CodeSandbox and Extension agents.
- Immutable Blueprint, DAG execution, retries and persisted Candidate resources.
- Provider allowlist and local fixture mode without committed vendor secrets.
- Outbox-backed workflow completion and authenticated persistent SSE.
- Topic3 Candidate output automatically consumed by Topic4.

### 2.5 Topic4 Trusted Verification And Release

- C1 Claim extraction, state machine, DAG planning, aggregation and review routing.
- C2 local BM25, graph expansion, formula signatures and hashed Faiss vectors.
- C3 academic formula, theorem, numeric and stability verification.
- C4 graph, C5 quiz, C6 code and C7 extension specialist verification.
- C8 immutable two-cycle revision with serialization and state-machine re-entry.
- C9 injection, C10 privacy and C11 compliance cross-cutting gates.
- C12 v2 server-derived, one-time authorization and SERIALIZABLE atomic publication.
- Human review read/write APIs with scope, CAS, audit, RLS and Outbox.
- 25 Topic4 OpenAPI operations in the running application.

### 2.6 Frontend Business Workbench

- Vue 3, Vite, TypeScript strict, Pinia and Vue Router architecture.
- Real Keycloak OIDC PKCE login, callback, renewal, logout and scope guards.
- API Envelope validation and no client-controlled tenant identity headers.
- Bearer-authenticated fetch-based SSE with cursor partitioning and deduplication.
- Topic1 knowledge, Topic2 learning, Topic3 agents, Topic4 verification/revision,
  review and publication pages.
- Responsive desktop/mobile shell, report printing and service-derived hash views.
- Terminal Verification matrices distinguish `NOT_REQUIRED` from active
  `PENDING`/`RUNNING` states.
- Vitest 54 tests and Playwright 3 integration scenarios.

### 2.7 Current Local System Acceptance

- Clean PostgreSQL volume and migration head verification.
- Topic1 -> Topic2 -> Topic3 -> Topic4 -> C12 -> SSE real local chain.
- A release-eligible persisted report and browser rendering of its 10 Claims.
- 516 Python tests with 91.41% coverage; one Windows symbolic-link test skipped.
- 100,000-chunk C2 benchmark p95 17.502 ms.
- 200 concurrent verifications and 200 concurrent release attempts.
- Database restart, Outbox duplicate, replay, tamper and cross-tenant tests.
- Trivy zero findings on all three runtime images and Gitleaks zero findings.
- Docker Desktop data image officially migrated to `D:\Docker\wsl` with image and
  volume inventory hashes preserved; isolated release volume created.

### 2.8 Identity Backend Candidate

- Additive migration `20260720_0010`; migrations `0001` through `0009` unchanged.
- Keycloak remains the only password and OIDC subject authority.
- Email/phone registration, verification challenges, profile/contact changes,
  tenant account list/detail/audit and disable/restore APIs are implemented.
- Six identity tables use FORCE RLS; registration/consent evidence is append-only.
- Email and phone values are encrypted at rest and indexed by keyed digests;
  plaintext passwords, password hashes, codes and Keycloak tokens are not stored.
- Keycloak/PostgreSQL partial failures use durable encrypted compensation jobs.
- A restricted catalog login can read only reconciliation `tenant_id` values;
  stale claims are recovered after restart and claim-token CAS blocks late workers.
- The development fixture inbox is loopback-only and production settings reject
  development secrets, HTTP Keycloak, fixture inbox and tenant fallback.
- Local evidence: 516 passed, 1 skipped, 91.41% Python coverage; remote PR CI is pending.

## 3. Current Work And Exact Boundary

Current branch: `codex/account-registration-backend`.

The branch contains the additive Keycloak-backed registration and account
projection backend. Historical migrations `0001` through `0009` and all frozen
Topic1-Topic4 contract fields remain unchanged. New migration `0010`, versioned
identity contracts, public registration APIs, account/profile administration,
encrypted PII projection, verification challenges, audit/Outbox evidence and a
restart-safe compensation reconciler are committed locally.

Current status:

- PR #26: merged by standard Squash Merge;
- protected main: `8df24c6c79c0674809e5891329d4fab405bb090e`;
- PR, push and protected-main CI: 8/8 jobs successful;
- merged-main clean-volume replay: passed on `cybercontrol_release_postgres`;
- final Verification state: `RELEASED`; authenticated SSE replay passed;
- official Docker data migration: completed and accepted with no asset loss;
- source traceability: dirty-source rejection and successful clean-source replay
  both passed; Compose, lockfile and runtime image fingerprints are archived.
- identity backend source: three conventional commits are complete and local
  PostgreSQL/Keycloak gates passed; branch push, PR, remote CI, merge and
  merged-main release-volume replay remain pending.

## 4. Remaining Work

### 4.1 P0 Current Evidence Closure

1. Push `codex/account-registration-backend`, create the backend PR and require
   all eight remote Release Quality Gates to pass.
2. Squash Merge through protected main, then replay registration -> OIDC login ->
   Topic1-Topic4 -> C12 -> SSE on `cybercontrol_release_postgres`.
3. Do not mark `SYSTEM_ACCEPTED` until every final non-functional gate below has evidence.

### 4.2 P1 Product Acceptance Gaps

1. Add `zh-CN`, `zh-TW` and `en-US` frontend plus Keycloak theme localization
   after the backend PR is merged and replayed.
2. Add real-data browser E2E for registration, account isolation, knowledge,
   learning, all five Agent resources,
   review CAS conflicts, publication history and account-switch cache isolation.
3. Execute 2,000 simultaneous authenticated SSE connections with reconnect,
   cursor recovery, duplicate delivery and slow-consumer measurements.
4. Execute an 8-hour minimum soak with continuous generation, verification,
   Outbox dispatch, SSE and publication while monitoring memory and queue depth.
5. Perform backup/restore disaster recovery into a separate PostgreSQL instance;
   measure RPO/RTO and verify audit, Artifact Store and Outbox consistency.
6. Execute sealed-environment integration with real approved Providers. No
   credentials may be committed, logged or embedded in evidence.
7. Build a human-reviewed academic golden set. The 100,000-chunk benchmark is a
   deterministic performance corpus, not 100,000 manually validated facts.

### 4.3 P1 Production Operations

- Production deployment target, TLS/domain, secret manager and environment policy.
- Managed PostgreSQL backup, point-in-time recovery and capacity plan.
- Metrics dashboards, alert rules, SLOs, on-call runbook and incident response.
- Artifact retention, privacy deletion policy and tenant offboarding procedure.
- Cross-browser and WCAG accessibility audit.
- Release signing, provenance and rollback rehearsal.

### 4.4 P2 Maintenance

- Resolve Dependabot major upgrades in isolated PRs after the release candidate is frozen.
- Remove or archive stale local branches after accepted merges.
- Reconcile current-state README/roadmap wording. Historical acceptance snapshots
  should remain immutable; a new current-state index should supersede them.

## 5. Documentation Drift Findings

- `README.md` still names `190ed863...` and Phase 6 as current.
- `docs/roadmap/implementation-sequence.md` still marks frontend integration active.
- `docs/topic4/acceptance-status.json` records `business_code_started=false`; this
  is valid as a Topic4 acceptance-time snapshot but is not a current project status.
- `docs/frontend/acceptance-report.md` states that no real C12 commit was claimed
  for its earlier long-lived volume. The new clean-volume evidence supersedes that
  limitation without rewriting the historical report.

`docs/system-acceptance/acceptance-status.json` is the authoritative current-state
document. Historical Topic and frontend reports remain time-point snapshots.

## 6. Final Audit Judgment

The protected-main product remains a reproducible release candidate with a real
release-eligible record. The additive identity backend is locally complete and
source-committed, but is not yet part of protected main. The immediate sequence is
backend PR -> 8/8 CI -> Squash Merge -> clean-volume mainline replay; only then may
the frontend registration/account-management and three-language PR begin. Final
load, soak, DR, sealed Provider and production operations gates still separate the
project from `SYSTEM_ACCEPTED`.
