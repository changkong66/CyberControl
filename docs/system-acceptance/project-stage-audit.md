# CyberControl Project Stage Audit

## 1. Precise Stage Position

CyberControl has completed Phase1.1, Topic1-Topic4, the business workbench, the
Keycloak-backed identity backend and a protected-main clean external-volume
replay. Protected `main` is
`bc9836532f6300e91dc7c0a906b07dabe754c138`; Release Quality Gates Run
29801095074 completed 8/8 jobs successfully.

The project is in **Phase 7 release closure**, specifically the transition from
backend identity completion to frontend identity self-service and
internationalization. It is a `RELEASE_CANDIDATE`, not `SYSTEM_ACCEPTED`.

Weighted implementation estimate: **about 92%**.

This estimate is not an acceptance state. Product scope and reproducible local
delivery are substantially complete. Production load, long-running resilience,
disaster recovery, external Provider and operational controls represent most of
the remaining work.

| Area | Maturity | Objective assessment |
| --- | --- | --- |
| Phase1.1 foundation | 100% | merged, protected and reproducible |
| Topic1-Topic4 backend | 100% feature complete | frozen trusted-learning and release chain |
| Identity backend | 100% current scope | merged, remote CI green and mainline replayed |
| Frontend workbench | about 95% | core business surfaces complete; identity UI and i18n remain |
| Local demonstrable product | about 97% | clean-volume registration-to-release chain passes |
| Production operations | about 45% | CI and secure containers exist; load, DR and deployment gates remain |

## 2. Completed And Frozen Assets

### 2.1 Platform Foundation

- Async FastAPI and SQLAlchemy on PostgreSQL 16.
- OIDC/JWKS authentication and trusted server-derived `TenantContext`.
- 74 tenant tables with RLS and FORCE RLS.
- SERIALIZABLE transactions, idempotency, CAS and bounded retry controls.
- Append-only evidence, SHA-linked audit, Artifact Store and transactional Outbox.
- Persistent tenant SSE replay with signed cursors and recovery.
- Reproducible Python, Node and Go toolchains with frozen lockfiles.
- Non-root containers and mandatory SBOM, license, Trivy and Gitleaks gates.

### 2.2 Topic1-Topic4 Product Chain

- Topic1 authoritative course, graph, prerequisite, textbook and question data.
- Topic2 six-dimensional profile, Ebbinghaus memory and adaptive path planning.
- Topic3 five-Agent generation with immutable Blueprint and Candidate resources.
- Topic4 C1-C12 Claim extraction, specialist verification, revision, review and
  server-derived atomic publication.
- Human review CAS and C12 one-time authorization.
- Topic3-to-Topic4 automatic handoff and authenticated/public SSE projections.
- Frozen cross-language contracts and real PostgreSQL integration coverage.

### 2.3 Frontend Business Workbench

- Vue 3, Vite, TypeScript strict, Pinia and Vue Router.
- Keycloak Authorization Code + PKCE login and scope guards.
- Envelope validation and prohibition of client-controlled tenant headers.
- Bearer-authenticated fetch-based SSE with cursor isolation and deduplication.
- Knowledge, learning, Agent, verification, revision, review and publication pages.
- Desktop/mobile workbench, report print/export and service-derived SHA views.
- 54 Vitest tests and three Playwright scenarios.

### 2.4 Identity Backend

- Additive migration `20260720_0010`; migrations `0001-0009` unchanged.
- Keycloak-only password and OIDC authority.
- Email/phone registration, verification challenge, profile/contact change,
  tenant account list/detail/audit and disable/restore APIs.
- Encrypted contact projection and keyed lookup digests.
- Six FORCE RLS identity tables, append-only evidence, audit and Outbox.
- Durable compensation and least-privilege reconciliation catalog.
- Restart lease recovery and claim-token compare-and-set.
- Loopback-only development inbox and production fail-closed settings.

### 2.5 Mainline Acceptance

- Identity backend PR #27 merged through protected main.
- Acceptance/runtime PR #28 merged through protected main.
- Push, PR and main workflows each passed all eight jobs.
- A real replay found and closed missing identity Outbox runtime handlers.
- Clean `cybercontrol_release_postgres` replay passed from main `bc98365`.
- Registration, OIDC login, learner authorization, tenant administration, RLS,
  Topic1-Topic4, C12 and authenticated SSE all passed.
- 519 Python tests passed with 91.33% coverage.
- Outbox ended at 29 published, zero open and zero dead messages.

## 3. Current Boundary

The current evidence branch may update only current-state acceptance assets. It
must not modify historical Topic acceptance snapshots.

After that evidence PR merges, the only allowed product branch is a frontend
identity/i18n branch from the latest main. It may implement:

- email and phone registration UI;
- self-service profile and verified contact changes;
- tenant account administration UI;
- Keycloak-delegated recovery;
- `zh-CN`, `zh-TW` and `en-US` localization;
- frontend tests, accessibility regression and merged-main replay.

It may not modify migrations, identity backend semantics, TenantContext, RLS,
SERIALIZABLE transactions, Outbox, SSE, C12 or Topic1-Topic4 contracts.

## 4. Remaining Work

### 4.1 P0 Immediate Product Closure

1. Merge the mainline evidence PR with 8/8 gates.
2. Build the frontend registration, account and three-language layer in one
   serial PR from the latest main.
3. Replay a newly registered learner through OIDC and the complete trusted
   publication chain from the merged frontend main.

### 4.2 P1 Final Non-Functional Acceptance

1. Test 2,000 authenticated SSE connections, including reconnect,
   `Last-Event-ID`, duplicate suppression, slow consumers and tenant isolation.
2. Run at least eight hours of continuous generation, verification, review,
   release and SSE while measuring memory, queue depth and Outbox lag.
3. Restore PostgreSQL backup into an independent instance and measure RPO/RTO.
4. Verify audit chain, Artifact Store, Outbox and publication consistency after recovery.
5. Test database restart, Faiss corruption, OIDC outage and Provider circuit
   behavior as fail-closed scenarios.
6. Run approved real Providers only in a sealed environment with externally
   injected secrets.
7. Expand a human-reviewed academic golden set and report accuracy, false
   positives and false negatives separately from the 100,000-chunk performance corpus.

### 4.3 P1 Production Operations

- Select and rehearse the production deployment target.
- Configure TLS, domain, secret manager, monitoring, alerting and SLOs.
- Define managed PostgreSQL backup/PITR, capacity and rollback policy.
- Define incident response, tenant offboarding and artifact retention.
- Complete cross-browser and WCAG accessibility audits.
- Complete PII retention, export, correction and deletion workflows.
- Add release signing, provenance and rollback rehearsal.

### 4.4 P2 Maintenance

- Process major dependency upgrades in isolated PRs after release-candidate closure.
- Archive stale branches only after their merge and evidence are confirmed.
- Keep historical acceptance reports immutable and update only current-state indexes.

## 5. Final Audit Judgment

The backend and current trusted-learning product chain are no longer the
blocking area. The immediate development target is the frontend identity and
internationalization layer. Once that layer is merged and replayed, final load,
soak, DR, sealed Provider, deployment, accessibility and privacy-lifecycle work
still separates the release candidate from `SYSTEM_ACCEPTED`.
