# CyberControl Project Stage Audit

## 1. Precise Stage Position

CyberControl is in **Phase 7 release closure**. The product scope, clean-volume
Gate B business replay, identity and account-management extension, and
`zh-CN`/`zh-TW`/`en-US` workbench are implemented on protected main. The
current protected-main archive baseline is
`76cd099a034a395a89b26496c0d40e0673aaa97d`, tree
`ffb7c72b3156f1dc271b5b0ec1afc2ce3f2c6870`. Release Quality Gates Run
31264518015 completed 8/8 jobs successfully. The fifth Gate C workload was
evaluated against that protected-main source and tree.

The formal state remains:

`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`

Gate A and Gate B are accepted. Gate C has not been accepted. The fifth
remediation replay passed 20, 200 and 500 authenticated SSE connections, then
failed frozen controls at 1,000 connections. The fail-fast harness therefore
did not execute the 2,000-connection stage or the ten-minute recovery
observation. Gate D through Gate G and unrelated product development remain
locked.

| Area | Current maturity | Evidence-based judgment |
| --- | --- | --- |
| Phase1.1 foundation | complete and frozen | protected, reproducible and covered by release gates |
| Topic1-Topic4 backend | complete for current product scope | trusted generation, verification, review and atomic release chain is frozen |
| Identity and account backend | complete for current product scope | Keycloak authority, registration, projection, administration and recovery are integrated |
| Frontend workbench | complete for current product scope | business, account and three-language surfaces are merged |
| Gate B business replay | accepted | clean PostgreSQL replay and evidence dataset controls passed from protected main |
| Gate C authenticated SSE | failed | fifth replay stopped at 1,000 due commit-to-client and Outbox latency failures; 2,000 and recovery remain unexecuted |
| Production operations | locked | soak, DR, Provider and deployment acceptance cannot start before Gate C success |

Feature completeness is not production acceptance. The remaining work is
smaller in feature count but contains the highest reliability and operational
risk.

## 2. Completed And Frozen Assets

### 2.1 Platform And Security Foundation

- Async FastAPI and SQLAlchemy on PostgreSQL 16.
- OIDC/JWKS authentication with server-derived `TenantContext`.
- 74 tenant tables with RLS and FORCE RLS.
- SERIALIZABLE transactions, idempotency, CAS and bounded retry controls.
- Append-only evidence, SHA-linked audit, Artifact Store and transactional
  Outbox.
- Persistent tenant SSE replay with signed cursors and fail-closed tenant
  checks.
- Reproducible Python, Node and Go toolchains with frozen lockfiles.
- Non-root containers and mandatory contract, SBOM, license, Trivy and
  Gitleaks gates.
- Docker Desktop data disk migrated to the D drive without deleting historical
  project volumes or evidence.

### 2.2 Trusted Education Product Chain

- Topic1 course, knowledge graph, prerequisite, textbook and question assets.
- Topic2 six-dimensional learner profile, memory model and adaptive path.
- Topic3 five-Agent generation with immutable Blueprint and Candidate
  resources.
- Topic4 C1-C12 claim extraction, specialist verification, revision, human
  review and server-derived atomic publication.
- Human-review CAS, C12 one-time authorization and Topic3-to-Topic4 handoff.
- Authenticated and public SSE projections with cross-language frozen
  contracts.
- C3 semantic verifier v2 with label-blind PostgreSQL evidence: 72/72 owner-
  reviewed records correct and zero unsafe `CONTRADICTED -> SUPPORTED`
  decisions.

### 2.3 Identity, Account And Frontend Delivery

- Keycloak remains the only password and identity-credential authority.
- Additive migration `20260720_0010`; migrations `0001-0009` remain unchanged.
- Email/phone registration, verification, profile/contact changes, tenant
  account administration, audit, disable/restore and recovery boundaries.
- Encrypted contact projection, keyed lookup digests, FORCE RLS, append-only
  audit and Outbox events.
- Vue 3, Vite, TypeScript strict, Pinia, Vue Router and OIDC PKCE.
- Envelope/runtime schema validation and no client-supplied tenant, subject,
  role or scope authority headers.
- Registration, profile, tenant account administration and Topic1-Topic4
  workbench pages.
- `zh-CN`, `zh-TW` and `en-US` application and Keycloak locale integration.
- Hardened non-root Nginx runtime with CSP and SSE proxy controls.
- Frontend unit, browser and mobile workflow coverage integrated into CI.

### 2.4 Mainline Release Evidence

- PR #30 merged identity, registration, account management and internationalized
  frontend capabilities through protected main.
- Gate B used a clean PostgreSQL 16 volume and completed registration, real
  Keycloak PKCE login, Topic1-Topic4, review, C12 release and SSE delivery with
  final state `RELEASED`.
- Learner administration access failed closed; tenant-admin visibility and
  cross-tenant RLS checks passed.
- Gate B separated the content-addressed 100,000-record synthetic performance
  corpus, the 72-record owner-reviewed academic fact set and local fixtures.
- PR #34 archived the accepted academic evidence; PR #35 merged the C3 semantic
  verifier v2; PR #36 archived the merged-main Gate B replay.
- PR #38 merged the frozen Gate C harness and workload.
- PRs #47, #50, #52 and #58 merged scoped Gate C reliability remediations without
  changing migrations, frozen contracts, workload or thresholds.
- PR #52 head `3c75c532bc8860debfe865eb08f63543fbd70eea` Squash Merged as
  `97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504` after push Run 30195808808 and
  pull-request Run 30195810215 passed 8/8. Protected-main Run 30196139462
  attempt 2 also passed 8/8.
- PR #56 patched the newly disclosed Python and frontend dependency advisories
  and Squash Merged as `6f4a58b44ef6e30a850b50aa522b490f525215b1` after
  push Run 31255259498 and pull-request Run 31255260722 passed 8/8;
  protected-main Run 31255474059 also passed 8/8.
- PR #55 archived the fourth-remediation failure evidence and Squash Merged as
  `40c8a4c076b59d9c9fd3384454df7f4eab9a6f98` after push Run 31255692354 and
  pull-request Run 31255694689 passed 8/8; protected-main Run 31255915622 also
  passed 8/8.
- PR #58 merged the fifth remediation as
  `76cd099a034a395a89b26496c0d40e0673aaa97d`, tree
  `ffb7c72b3156f1dc271b5b0ec1afc2ce3f2c6870`, after push Run 31264197240 and
  pull-request Run 31264254111 passed 8/8; protected-main Run 31264518015 also
  passed 8/8.
- The fifth formal run used real Keycloak Tokens, two tenants, twenty subjects,
  a newly built image set, unique Compose project and fresh isolated PostgreSQL
  volume.
- Raw fifth-run evidence is retained in a GitHub prerelease asset with SHA256
  `566a65a5ac01d1eb6ec0f06a1bc85529bebcf7f53dc37c382d74dcbfa707630e`.

## 3. Current Gate C Failure Boundary

The current formal run directory is:

`D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260808T154326Z-76cd099a034a`

It used Compose project `cybercontrol-gate-c-fifth-76cd099-20260808t154325z`
and fresh PostgreSQL volume `cybercontrol_gate_c_fifth_76cd099_20260808t154325z`.
The original failed volume remains preserved. Terminal database inspection used
a separate forensic copy and did not start the original failed volume.

The 20, 200 and 500 stages passed. The 1,000 stage sustained 1,000 active
authenticated streams for 603 seconds and retained these passed controls:

- connection and reconnect/replay success: `1.0 / 1.0`;
- committed event loss, duplicate final render and cross-tenant leakage: `0`;
- HTTP 5xx, pool acquisition timeout, OOM and unplanned restart: `0`;
- final subscribers, queued events and replay-cache events: `0 / 0 / 0`;
- migration head `20260720_0010`, FORCE RLS `74/74`, foreign-tenant visibility
  `0`.

The same stage failed:

| Frozen control | Observed | Required |
| --- | ---: | ---: |
| Commit-to-client p95 | 1,532 ms | <= 1,000 ms |
| Commit-to-client p99 | 4,985 ms | <= 3,000 ms |
| Outbox DEAD | 0 | 0 |
| Outbox lag p95 | 5,830.700 ms | <= 2,000 ms |
| Outbox lag p99 | 8,434.789 ms | <= 5,000 ms |

API CPU reached `127.604/131.840` one-core units at p95/max and peak API file
descriptors reached `1038`. Fail-fast ended with `826` closing owners; because
the recovery stage was not executed, this is a diagnostic observation rather
than a failed or passed memory-recovery conclusion.

The fifth remediation eliminated the previously observed two `DEAD`
`topic3.workflow.finalized` rows and preserved zero cross-tenant visibility,
but did not bring the commit-to-client or Outbox latency within the frozen
thresholds. The 2,000-stream and recovery stages remain unexecuted, so memory
recovery and full-scale continuity are still unproven.

Connection-establishment p95/p99 was `19,166/22,324 ms` while real Keycloak
token issuance remained successful. This is a readiness signal that
must be decomposed into token, admission, replay and LIVE-handoff latency.

The authoritative current evidence is under
`docs/system-acceptance/evidence/phase7-gate-c-fifth-remediation-*`. Historical
Gate C evidence remains immutable.

## 4. Remaining Work

### 4.1 P0 Fifth Failure-Evidence Archive Closure

1. Commit only the fifth-remediation partial-failure summary, report, database
   and environment evidence, manifest, package metadata and current-state docs.
2. Bind the archive to source `76cd099a034a395a89b26496c0d40e0673aaa97d`,
   tree `ffb7c72b3156f1dc271b5b0ec1afc2ce3f2c6870`, frozen hashes, fresh volume,
   image digests and the immutable external package.
3. Preserve every prior Gate C snapshot and retain
   `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.
4. Require push, pull-request and protected-main Release Quality Gates 8/8 and
   Squash Merge only after green.

### 4.2 P0 Sixth Gate C Remediation

Only after archive closure, trace and remediate SSE fan-out lock contention,
event-loop scheduling, slow-consumer backpressure, notification/publisher wakeup
and Outbox-to-client latency. Preserve the fifth remediation's valid finalized-
event authorization, zero Outbox `DEAD`, fail-closed invalid/cross-tenant events,
ordered delivery, leases, retries, atomic publication and tenant context. Add
deterministic unit, concurrency and real PostgreSQL regressions, with each
behavior change mapped to a failed metric and disproof metric.

### 4.3 P0 Protected-Main Rerun

1. Merge the sixth remediation only after push and pull-request Release Quality
   Gates pass 8/8, then require protected-main 8/8.
2. Rebuild all images from the new main without `-SkipBuild`.
3. Use a unique Compose project, evidence directory and fresh PostgreSQL volume;
   never reuse development, release or historical Gate C volumes.
4. Execute the unchanged 20, 200, 500, 1,000 and 2,000 stages plus the
   ten-minute recovery observation with real Keycloak Tokens.
5. Any frozen-control failure keeps Gate D locked and requires a new immutable
   failure-evidence PR. Only a complete same-run pass can mark Gate C accepted.

### 4.4 P1-P2 Work Locked Behind Gate C

- Gate D: at least eight hours of generation, verification, review, release and
  SSE soak with thresholds frozen before execution.
- Disaster recovery: independent PostgreSQL backup restore, measured RPO/RTO,
  audit/Artifact Store/Outbox consistency and fail-closed fault drills.
- Provider acceptance: sealed-environment credentials only; no repository or
  development secrets.
- Production operations: target platform, TLS, secret manager, monitoring,
  alerting, SLOs, capacity, PITR, rollback and incident rehearsal.
- Commercial assurance: cross-browser, WCAG, PII retention/export/correction/
  deletion, tenant offboarding and artifact-retention review.
- Major dependency upgrades and unrelated features only after release closure,
  in isolated PRs.

## 5. Final Audit Judgment

CyberControl's current commercial product feature chain is implemented and Gate
A/B evidence is accepted. The project is not production accepted because Gate
C remains the active release blocker. The fifth remediation removed the prior
finalized-event `DEAD` condition and preserved zero loss, duplicate render and
tenant leakage, but the protected-main replay still breached commit-to-client
and Outbox latency at 1,000 streams. The next authorized action is the fifth
failure-evidence archive closure; only after it merges may the sixth scoped Gate
C remediation and fresh replay begin. Gate D-G remain locked until an
independent Gate C success-evidence PR passes CI and merges.
