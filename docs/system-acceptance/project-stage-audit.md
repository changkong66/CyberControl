# CyberControl Project Stage Audit

## 1. Precise Stage Position

CyberControl is in **Phase 7 release closure**. The product scope, clean-volume
Gate B business replay, identity and account-management extension, and
`zh-CN`/`zh-TW`/`en-US` workbench are implemented on protected main. The
current protected-main archive baseline is
`40c8a4c076b59d9c9fd3384454df7f4eab9a6f98`, tree
`071d7804d7c465153b4c17b84d2a1a0a8ecfebd3`. Release Quality Gates Run
31255915622 completed 8/8 jobs successfully. The fourth Gate C workload was
evaluated against product source `97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504`,
tree `bad6b0f9e7008b934a54681f9f304a786ee9afe7`.

The formal state remains:

`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`

Gate A and Gate B are accepted. Gate C has not been accepted. The fourth
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
| Gate C authenticated SSE | failed | fourth replay stopped at 1,000 due durable finalized-event authorization and latency failures |
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
- PRs #47, #50 and #52 merged scoped Gate C reliability remediations without
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
- The fourth formal run used real Keycloak Tokens, two tenants, twenty subjects,
  a newly built image set, unique Compose project and fresh isolated PostgreSQL
  volume.
- Raw fourth-run evidence is retained in a GitHub prerelease asset with SHA256
  `9b2c4c116752197bf10dd1bc9d29409e59bdca1eca7be3cd4a0df1d1bef26f8d`.

## 3. Current Gate C Failure Boundary

The current formal run directory is:

`D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260808T083601Z-97bfa5fef7e1`

It used Compose project `cybercontrol-gate-c-97bfa5f-20260808t0840z` and fresh
PostgreSQL volume `cybercontrol_gate_c_97bfa5f_20260808t0840z`. The original
failed volume remains preserved. Terminal database inspection used a separate
forensic copy and did not start the original failed volume.

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
| Commit-to-client p95 | 1,631 ms | <= 1,000 ms |
| Commit-to-client p99 | 6,132 ms | <= 3,000 ms |
| Outbox DEAD | 2 | 0 |
| Outbox lag p95 | 6,292.587 ms | <= 2,000 ms |
| Outbox lag p99 | 8,712.164 ms | <= 5,000 ms |

Both DEAD rows are `topic3.workflow.finalized`, sequence `2`, attempts `3/3`,
with `LIYAN-AUTH-FORBIDDEN`. This proves a durable-consumer authorization
failure, but does not yet prove whether the defect is in event-envelope claims,
service-subject policy, publisher tenant-context propagation, consumer context
construction or another trusted boundary. Authorization may not be bypassed to
make the Outbox pass.

Connection-establishment p95/p99 also rose to `19,964/23,705 ms` while real
Keycloak token issuance remained successful. This is a readiness signal that
must be decomposed into token, admission, replay and LIVE-handoff latency.

The authoritative current evidence is under
`docs/system-acceptance/evidence/phase7-gate-c-fourth-remediation-*`. Historical
Gate C evidence remains immutable.

## 4. Remaining Work

### 4.1 P0 Fifth Gate C Remediation

1. Trace one `topic3.workflow.finalized` event from transactional creation,
   claim and publisher dispatch through the authorized consumer decision.
2. Identify the exact trusted-context or policy mismatch that produces
   `LIYAN-AUTH-FORBIDDEN`; preserve server-derived tenant identity and fail-
   closed authorization.
3. Correct retry classification so transient failures remain recoverable while
   deterministic authorization failures remain observable and cannot cycle
   indefinitely.
4. Measure `created -> claimed`, `claimed -> dispatched`, `dispatched ->
   authorized/accepted` and `published -> client` separately.
5. Remove the evidenced latency source while preserving `FOR UPDATE SKIP
   LOCKED`, leases, partition ordering, retries and atomic publication.
6. Add deterministic unit and real PostgreSQL tests for finalized-event claims,
   publisher/consumer context propagation, retry exhaustion, claim release,
   multi-tenant isolation and latency instrumentation.
7. Preserve the fourth remediation's zero loss, zero duplicate render, clean
   close ownership and zero retained subscriber/queue/cache terminal state.

### 4.2 P0 Protected-Main Rerun

1. Merge the fifth remediation only after push and pull-request Release Quality
   Gates pass 8/8, then require protected-main 8/8.
2. Rebuild all images from the new main without `-SkipBuild`.
3. Use a unique Compose project, evidence directory and fresh PostgreSQL volume;
   never reuse development, release or historical Gate C volumes.
4. Execute the unchanged 20, 200, 500, 1,000 and 2,000 stages plus the
   ten-minute recovery observation with real Keycloak Tokens.
5. Any frozen-control failure keeps Gate D locked and requires a new immutable
   failure-evidence PR. Only a complete same-run pass can mark Gate C accepted.

### 4.3 P1-P2 Work Locked Behind Gate C

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
C remains the active release blocker. The fourth remediation materially
improved continuity and cleanup, but the protected-main replay exposed a
`topic3.workflow.finalized` durable-delivery authorization failure and latency
breach at 1,000 streams. The next authorized action is the fifth scoped Gate C
remediation and a fresh protected-main replay. Gate D-G remain locked until an
independent Gate C success-evidence PR passes CI and merges.
