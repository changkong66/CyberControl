# CyberControl Project Stage Audit

## 1. Precise Stage Position

CyberControl has completed Phase1.1, Topic1-Topic4, the complete business
workbench, the Keycloak-backed identity backend, frontend registration/account
management, and `zh-CN`/`zh-TW`/`en-US` localization. The Gate B replay archive
baseline is
`a6024716ebbe2311daf73b9409fd84e9ed512f59`; Release Quality Gates Run
29888873754 completed 8/8 jobs successfully.

The project is in **Phase 7 release closure**, at the boundary between product
completion and final non-functional/production acceptance. Gate A and Gate B are
accepted. The second scoped Gate C remediation is merged through protected main,
and PR #48 has archived its failed fresh-volume rerun through main
`a2834c4c541a7b752e8f38c5cb5449af1f08d504` with protected-main CI attempt 2 at
8/8. The rerun failed the frozen 2,000-stream thresholds. It remains a
`RELEASE_CANDIDATE`, not `SYSTEM_ACCEPTED`; Gate D-G are locked while a third
scoped remediation is prepared.

Feature completeness is not an acceptance state. The remaining work is smaller
in feature count but high in operational risk, external review dependency and
elapsed test time.

| Area | Maturity | Objective assessment |
| --- | --- | --- |
| Phase1.1 foundation | 100% | merged, protected and reproducible |
| Topic1-Topic4 backend | 100% current product scope | frozen trusted-learning and release chain |
| Identity backend | 100% current product scope | registration, projection, administration and recovery boundary complete |
| Frontend workbench | 100% current product scope | business, identity and three-language surfaces merged |
| Local demonstrable product | accepted release candidate | clean-volume registration-to-release chain passes from merged main |
| Dataset and C3 accuracy boundary | mainline accepted | 72 owner-reviewed records pass at 100% with zero unsafe false negatives from protected-main replay |
| Production operations | Gate C failed after second remediation rerun | third remediation and fresh-volume rerun required; soak, DR and deployment remain serially locked |

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
- Envelope/runtime schema validation and prohibited client tenant headers.
- Bearer-authenticated fetch SSE with tenant-partitioned cursor recovery.
- Knowledge, learning, Agent, verification, revision, review and publication pages.
- Email/phone registration, profile and verified contact management.
- Tenant account administration with expected-version conflict handling.
- Keycloak-delegated recovery.
- `zh-CN`, `zh-TW`, `en-US` application and Keycloak locale integration.
- Hardened non-root Nginx runtime with CSP and proxy buffering controls.
- 72 Vitest tests and eight Playwright scenarios.

### 2.4 Identity Boundary

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

- Frontend identity/i18n PR #30 merged through protected main.
- Push, pull-request and merged-main workflows each passed all eight jobs.
- The release volume was recreated without deleting development volumes.
- Initial business counts were `0|0|0|0|0` at migration head `0010`.
- A newly registered learner logged in through real Keycloak OIDC.
- Learner administration access returned 403; tenant-admin visibility passed.
- Topic1-Topic4, C12 and authenticated SSE completed with final state `RELEASED`.
- 74/74 tenant tables retained FORCE RLS; audit and Outbox invariants passed.
- Exact release backend, frontend and Mock Provider images have zero Trivy
  findings at all severities.
- Browser runtime inspection rendered all three locales without console errors.
- Evidence archive PR #32 merged and current protected-main Run 29840722346
  passed all eight jobs.
- Gate A preflight captured Docker D-drive location, release-volume provenance,
  image/source binding and resource limits without recording secrets.
- Gate B materialized a content-addressed 100,000-record synthetic performance
  corpus and correctly kept it separate from academic accuracy evidence.
- The named owner/expert accepted a licensed 72-record academic set with the
  single-maintainer conflict disclosed and no independent peer-review claim.
- ADR-0013 preserves v1 behavior while adding an explicit C3 semantic v2
  runtime. The label-blind clean-source PostgreSQL run at
  `a23cbe38a116c493223579a4675bf595f90b8252` classified 72/72 correctly,
  produced zero unsafe `CONTRADICTED -> SUPPORTED` decisions, passed FORCE RLS
  adversarial reads and rejected changed-content replay.
- PR #34 merged the academic evidence through protected main after push Run
  29886312423 and pull-request Run 29886314403 each passed 8/8 jobs.
- PR #35 was retargeted to `main`, merged the C3 semantic verifier v2 through
  protected main after push Run 29886959510 and pull-request Run 29886962210 each
  passed 8/8 jobs, and produced main SHA
  `7e2a1d7cc3efc55ce27044e10959c4f5889a85da`.
- The resulting protected main passed Run 29887219266 at 8/8 jobs.
- The merged-main Gate B replay at `7e2a1d7cc3efc55ce27044e10959c4f5889a85da`
  and tree `c9821405359f59fee9fb993873ed3ba7f55e8b00` used a fresh PostgreSQL 16
  volume, classified 72/72 correctly, produced zero unsafe false negatives,
  verified 86 artifacts, left `cybercontrol_release_postgres` untouched and
  removed temporary replay resources.
- The scoped Gate C remediation local quality gate reports 630 collected tests,
  628 passed, two explicit skips and 91.74% line coverage. This passes the 90%
  hard gate and exceeds both the prior 91.58% current record and the historical
  91.19% observation target.
- PR #36 archived the current-state replay evidence through protected main. Its
  push Run 29888597039, pull-request Run 29888658077 and post-merge main Run
  29888873754 each completed all eight jobs successfully.
- PR #47 merged the second Gate C remediation at
  `7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8`. Push Run 30157996109,
  pull-request Run 30158060313 and protected-main Run 30158839398 each passed
  8/8.

## 3. Current Boundary

The current protected main is `7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8`.
It contains the Gate C harness, both remediation implementations and the
protected-main CI closure for PR #47. The second-remediation formal run reached
2,000 active authenticated streams on a single host, but failed frozen
connection, replay/event-loss, Outbox-lag and memory-recovery thresholds. The
project remains `RELEASE_CANDIDATE`, and Gate D-G remain locked.

Current failed evidence is archived in
docs/system-acceptance/evidence/phase7-gate-c-second-remediation-summary.json,
docs/system-acceptance/evidence/phase7-gate-c-second-remediation-failure-analysis.md
and related manifest files. The retained external evidence package is
SHA256-bound in
docs/system-acceptance/evidence/phase7-gate-c-second-remediation-package.json.

Any future acceptance branch must not modify historical Topic acceptance
snapshots, migrations, identity authority, TenantContext, RLS, SERIALIZABLE
transactions, Outbox, SSE tenant isolation or C12 semantics. The only allowed
immediate engineering activity is a third scoped Gate C remediation PR, followed
by a fresh Gate C rerun from a new protected-main baseline.

## 4. Remaining Work

### 4.1 Gate C Evidence Archive - Complete

1. PR #38 merged the Gate C load harness into protected main at 63d62f071176185da33c195dbdf682186b3e8c9e.
2. PR #38 pull-request Run 30090497603 and post-merge main Run 30091054880 were
   both 8/8.
3. The formal Gate C run failed; PR #39 archived that result through protected
   main at `865735015f6600f88d79b34ddbe7ba06e635f72e` after push, pull-request and
   post-merge main quality gates each passed 8/8.

### 4.2 P0 Gate C Remediation And Rerun

1. Implementation commit `0389961` hardens SSE async-generator cancellation,
   ContextVar release, database-session cleanup, replay fanout and Outbox claim
   recovery.
2. Test commit `2fcfb57` adds unit and real PostgreSQL regression coverage for
   replay/live cancellation, connection return, cursor isolation, publisher
   timeout and Outbox retry behavior.
3. The complete local quality gate passed with 91.74% Python coverage, frozen
   contract drift checks, frontend/Go gates, SBOM/license policy, Trivy and
   Gitleaks. No migration or frozen threshold changed. The result is bound by
   `docs/system-acceptance/evidence/phase7-gate-c-remediation-local.json`.
4. PR #47 merged the second remediation through protected main with push,
   pull-request and post-merge 8/8 CI. Its fresh-volume Gate C rerun failed;
   the failure evidence is recorded in the second-remediation evidence files.
   PR #48 archived that evidence on main after push Run 30163755928,
   pull-request Run 30163777964 and protected-main Run 30163981110 attempt 2
   all completed 8/8. The first protected-main attempt failed on transient
   BuildKit pull infrastructure and a heartbeat-sensitive PostgreSQL SSE test;
   the unchanged rerun passed. Local or CI success does not equal Gate C
   acceptance.

### 4.3 P0 Third Gate C Remediation And Rerun

1. Eliminate the remaining concurrent `aclose()` ownership error with a single
   close owner, explicit task join and cancellation-state instrumentation.
2. Diagnose and fix 2,000-stream connection admission, reconnect/replay
   completion and the 1,700-event loss using timing, sequence and subscriber
   lifecycle evidence; do not add retries that hide loss.
3. Reduce Outbox p95/p99 lag and retained API memory without changing atomicity,
   ordering, thresholds or workload.
4. Add focused unit and real PostgreSQL regressions, then pass protected push,
   pull-request and post-merge 8/8 CI.
5. Rerun the unchanged Gate C workload on a new main and a new PostgreSQL volume.
   Any failed threshold keeps Gate D locked and requires a new failure archive.

### 4.4 P1 Gate D Soak Acceptance

1. Only after Gate C acceptance, run at least eight hours of continuous
   generation, verification, review, release and SSE while recording memory,
   CPU, connection pools, queue depth, Outbox lag and error rates.
2. Define soak-specific pass/fail thresholds before execution and archive the
   complete time series and failure evidence.

### 4.5 P1 Disaster Recovery

1. Take a versioned PostgreSQL backup and restore it into an independent
   instance.
2. Measure and report RPO/RTO; do not infer them from configuration.
3. Verify audit chain, Artifact Store references, Outbox ordering, identity
   projections and publication records after restore.
4. Test database restart, Faiss/BM25 corruption, OIDC outage and Provider
   circuit behavior as explicit fail-closed scenarios.

### 4.6 P1 Production Operations

- Select and rehearse the target deployment platform.
- Configure domain, TLS, secret manager, monitoring, alerts and SLOs.
- Define managed PostgreSQL backup/PITR, capacity and rollback policy.
- Verify signed images/provenance and a rollback rehearsal.
- Run approved real Providers only in a sealed environment with external
  secrets.
- Complete cross-browser and WCAG accessibility audits.
- Complete PII retention, export, correction and deletion workflows.
- Define incident response, tenant offboarding and artifact retention.

### 4.7 P2 Maintenance

- Process major dependency upgrades in isolated PRs after release closure.
- Archive stale branches only after merge and evidence are confirmed.
- Keep historical acceptance reports immutable and update current-state indexes
  only.

## 5. Final Audit Judgment

The product feature chain is complete for the current commercial scope, and Gate
A/B remain accepted. Gate C is the active blocker: the platform can demonstrate
the full trusted education workflow, but the second-remediation mainline still
does not satisfy the frozen 2,000 authenticated SSE reliability gate. No soak,
disaster-recovery or production operations gate can begin until a third
remediation and a fully passing protected-main Gate C rerun are evidenced.
