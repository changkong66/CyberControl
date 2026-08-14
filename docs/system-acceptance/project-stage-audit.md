# CyberControl Project Stage Audit

## 1. Precise Stage Position

CyberControl is in **Phase 7 release closure**. The current product scope,
clean-volume Gate B business replay, Keycloak-backed registration and account
management, and the `zh-CN`/`zh-TW`/`en-US` workbench are implemented on
protected main. The current protected-main source is
`0c35364d79cd89d149190c02557d2c352643300e`, tree
`284df2edd208daf2379f5e1827bad18f92e303c8`. Protected-main Release Quality
Gates Run 31798607779 completed 8/8 jobs successfully. The latest product-code
commit remains `c826b508ee5b094532a13bbe88d68e66948ed84c`; PR #70 changed evidence and
current-state documentation only. The eighth Gate C replay
itself remains bound to evaluated source
`4f0a7670782c5002a2da6e429c0428d8fef29153`, tree
`d79b15fce52b8a8b9afe4be361cfbcbba4c7ddc9`.

The formal state remains:

`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`

Gate A and Gate B are accepted. Gate C is not accepted. The eighth formal
Gate C replay completed the entire frozen workload, including 2,000
authenticated SSE streams for 1,804 seconds and the fixed ten-minute recovery
observation. Every stage-local control passed, but the final aggregate failed
the frozen Outbox p95 and memory-recovery controls. The final 30 recovery
samples also retained one LIVE subscriber, violating the required lifecycle
boundary. A partial or near-threshold pass cannot advance the release state.
Gate D through Gate G and unrelated product work remain locked.

| Area | Current maturity | Evidence-based judgment |
| --- | --- | --- |
| Phase 1.1 foundation | complete and frozen | protected, reproducible and covered by release gates |
| Topic1-Topic4 backend | complete for current scope | trusted generation, verification, review and atomic release chain is frozen |
| Identity and account backend | complete for current scope | Keycloak authority, registration, projection, administration and recovery are integrated |
| Three-language frontend | complete for current scope | business, account and locale surfaces are merged and tested |
| Gate B business replay | accepted | clean PostgreSQL replay and evidence dataset controls passed from protected main |
| Gate C authenticated SSE | failed | all stages passed locally, but final Outbox p95 and RSS recovery controls failed; one LIVE subscriber remained in recovery |
| Production operations | locked | soak, DR, Provider and deployment acceptance cannot start before Gate C success |

Feature completeness is not production acceptance. The remaining feature count
is small, but the unresolved reliability and operational work carries the
highest release risk.

## 2. Completed And Frozen Assets

### 2.1 Platform And Security Foundation

- Async FastAPI and SQLAlchemy on PostgreSQL 16.
- OIDC/JWKS authentication with server-derived `TenantContext`.
- 74 tenant tables with RLS and FORCE RLS.
- SERIALIZABLE transactions, idempotency, CAS and bounded retries.
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
- Topic4 C1-C12 extraction, specialist verification, revision, human review
  and server-derived atomic publication.
- Human-review CAS, C12 one-time authorization and Topic3-to-Topic4 handoff.
- Authenticated and public SSE projections with frozen cross-language
  contracts.
- C3 semantic verifier v2 with label-blind PostgreSQL evidence: 72/72
  owner-reviewed records correct and zero unsafe
  `CONTRADICTED -> SUPPORTED` decisions.

### 2.3 Identity, Accounts And Frontend

- Keycloak is the sole password and identity-credential authority.
- Additive migration `20260720_0010`; migrations `0001-0009` remain unchanged.
- Email/phone registration, verification, profile/contact changes, tenant
  account administration, audit, disable/restore and recovery boundaries.
- Encrypted contact projection, keyed lookup digests, FORCE RLS, append-only
  audit and Outbox events.
- Vue 3, Vite, strict TypeScript, Pinia, Vue Router and OIDC PKCE.
- Runtime schema validation and no client-supplied tenant, subject, role or
  scope authority headers.
- Registration, profile, tenant administration and Topic1-Topic4 workbench
  pages in `zh-CN`, `zh-TW` and `en-US`.
- Hardened non-root Nginx runtime with CSP and SSE proxy controls.
- Frontend unit, browser and mobile workflow coverage integrated into CI.

### 2.4 Accepted Release Evidence

- Gate B used a clean PostgreSQL 16 volume and completed registration, real
  Keycloak PKCE login, Topic1-Topic4, review, C12 release and SSE delivery with
  final state `RELEASED`.
- Learner administration access failed closed; tenant-admin visibility and
  cross-tenant RLS checks passed.
- Gate B separated the content-addressed 100,000-record synthetic performance
  corpus, the 72-record owner-reviewed academic fact set and local fixtures.
- PR #34 archived the academic evidence; PR #35 merged the C3 semantic
  verifier v2; PR #36 archived the merged-main Gate B replay.
- PR #38 merged the frozen Gate C harness, thresholds and workload.
- PRs #47, #50, #52, #58, #61 and #64 merged scoped Gate C remediations without
  changing migrations, frozen contracts, workload or thresholds.
- PR #64 delivered the seventh remediation as protected main
  `fa5b4bd92e4b56704f70b63416906a10c54e0ee1` after push Run 31592761559,
  pull-request Run 31592947063 and protected-main Run 31593377181 each passed
  8/8.
- Complete Python/PostgreSQL regression recorded 711 passed and 4 explicit
  environment-conditioned skips with 91.68% Python coverage. Frontend, browser,
  Go, contract, SBOM/license, dependency audit, Trivy and Gitleaks gates passed.
- Seven prior Gate C failures and their packages remain immutable; none is
  rewritten as a success.
- PR #65 closed the seventh failure archive as a docs/evidence-only change;
  protected-main Run 31610698379 completed 8/8.
- PR #66 delivered the eighth remediation as protected main
  `4f0a7670782c5002a2da6e429c0428d8fef29153` after push Run 31629029809,
  pull-request Run 31629100666 and protected-main Run 31629561293 each passed
  8/8. Its complete fresh-volume replay still failed Outbox p95 and RSS
  recovery; its failure package is newly archived and immutable.
- PR #67 opened the first independent failure-evidence archive. Its initial push Run
  31788710871 and pull-request Run 31788806194 were blocked by newly published
  advisory `GHSA-2v37-7h3g-55p8` in `nanoid 3.3.17`, not by the evidence files.
- Independent PR #68 updated `nanoid` to 3.3.18 and merged as protected main
  `c826b508ee5b094532a13bbe88d68e66948ed84c`; push Run 31790758140,
  pull-request Run 31790811040 and protected-main Run 31796150290 each passed
  8/8. The subsequent PR #67 retry reached 6/8 in Runs 31797008505 and
  31797011334 because merge commit `939d4b7b98c4` failed Conventional Commit
  subject validation; its other six jobs passed. PR #70 replaced it directly
  from protected main, passed push Run 31798234042 and pull-request Run
  31798238730 at 8/8, Squash Merged as
  `0c35364d79cd89d149190c02557d2c352643300e`, and passed protected-main Run
  31798607779 at 8/8. The eighth failure archive is closed on mainline.

## 3. Historical Seventh Gate C Evidence Boundary

The authoritative run is:

`D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260812T120720Z-fa5b4bd92e4b`

It used Compose project
`cybercontrol-gate-c-seventh-fa5b4bd-20260812`, fresh PostgreSQL volume
`cybercontrol_gate_c_seventh_fa5b4bd_20260812`, real Keycloak-issued Tokens,
two tenants and twenty real subjects. All images were built from the evaluated
main. The result is a single-host acceptance result and is not a production
cluster capacity claim.

| Stage | Active streams and duration | Delivery p95/p99 | Result |
| --- | ---: | ---: | --- |
| Smoke | 20 for 181s | 24/40 ms | pass |
| Ramp | 200 for 304s | 46/163 ms | pass |
| Ramp | 500 for 305s | 239/404 ms | pass |
| Ramp | 1,000 for 604s | 416/609 ms | pass |
| Formal | 2,000 for 1,803s | 781/990 ms | pass |

The complete run retained these controls:

- connection and reconnect/replay success: `1.0 / 1.0`;
- committed event loss and duplicate final render: `0 / 0`;
- cross-tenant leakage and invalid cursor acceptance: `0 / 0`;
- HTTP 5xx, unexpected disconnect, pool timeout, OOM and restart: all `0`;
- Outbox `PUBLISHED=221`, `DEAD=0`, with no terminal `PENDING/CLAIMED` rows;
- final subscribers, close owners, queued events/bytes, replay buffers, replay
  caches and replay tasks: all `0`;
- API file descriptors returned from `29` to `30` after peaking at `2,039`;
- migration head `20260720_0010`, FORCE RLS `74/74`, append-only triggers `57`
  and foreign-tenant visibility `0`;
- no `aclose()` race, traceback, error, pool-timeout, OOM or unplanned restart
  log entries.

The final aggregate failed exactly two frozen controls:

| Frozen control | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Outbox created-to-published p95 | 2,225.796 ms | <= 2,000 ms | fail |
| Outbox created-to-published p99 | 3,026.102 ms | <= 5,000 ms | pass |
| Post-ramp API RSS ratio | 1.492792 | <= 1.10 | fail |

API RSS first/last/peak was
`276404634 / 412614656 / 448371098` bytes. Host CPU p95/max was
`37.4/52.6%`; database connections and checked-out pool connections peaked at
`21/6`. The remaining RSS is not explained by a live subscriber, queue,
replay-cache or file-descriptor owner because those inventories returned to
baseline. Allocator arenas, metric state, object pools and allocation high-water
retention are candidates only; none is yet a proven root cause.

The Outbox sample contains 221 lifecycle observations. Events were immediately
claimable, 203 were claimed within one second, and 211 were published within
2.5 seconds. Claim-batch execution was generally small. Existing evidence
implicates a combined created-to-claimed, durable-acceptance and published-mark
tail, but does not prove which segment owns the p95 breach.

The original failed volume is preserved. Forensic inspection used
`cybercontrol_gate_c_seventh_fa5b4bd_20260812_forensics`, derived without
writable mounting of the original; its content SHA256 is
`e78e3ff34f14fa88a5d931081621704ce4fb0ef96375ff50005ec6d4ad7ba67a`.

The immutable external package is 5,337,204 bytes with SHA256
`a01a16fdfc4f50f14b0a74a234a9e5f332ab20a29451c49096b6f7901236f2fd`:
https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-seventh-remediation-failed-20260812-fa5b4bd.
GitHub reports the Release and asset as immutable, and the credential/JWT scan
recorded zero hits.

## 4. Eighth Gate C Evidence Boundary

The current authoritative run is:

`D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260812T190722Z-4f0a7670782c`

It used Compose project `cybercontrol-gate-c-eighth-4f0a767-20260813`, fresh
PostgreSQL volume `cybercontrol_gate_c_eighth_4f0a767_20260813`, real
Keycloak-issued Tokens, two tenants and twenty real subjects. The five stages
and fixed recovery completed. Stage-local safety and delivery controls passed;
the final Outbox p95 was `2247.346ms` against `<=2000ms`, and post-ramp RSS
ratio was `1.393027` against `<=1.10`. Outbox p99 was `3438.55ms` and passed.

The last 30 recovery samples all had `subscribers=1` and
`subscribers_live=1`, while close owners, queued events/bytes, replay
buffers/caches and replay tasks were zero. This residual is explicitly recorded
as a lifecycle defect and possible memory owner, not treated as acceptance.
Container RSS first/last/peak was `264660582 / 368679322 / 435054182` bytes;
PSS `300299264 -> 407353344`; USS `297070592 -> 404389888`; anonymous RSS
`259416064 -> 363573248`; file RSS was unchanged. FDs returned to `29` after
peaking at `2039`; Outbox terminal `PENDING/CLAIMED/DEAD=0`; FORCE RLS was
`74/74`; foreign-tenant visibility was `0`.

The valid immutable package is
`gate-c-20260812T190722Z-4f0a7670782c-eighth-remediation-failed-evidence-v1.zip`,
SHA256 `b22f81bbcd42fb5dab0c9bc64891fe8b49888663ab9c0f13260b1de313802ff1`,
on Release `369510663`. Immutable Release `369509815` has zero assets and is
preserved as a disclosed audit exception.

## 4A. Ninth Gate C Evidence Boundary

The current authoritative run is:

`D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260814T163148Z-993ed9719dfb`

It evaluated protected-main source
`993ed9719dfb363238fe3c2f075f1d7e7e269b40`, tree
`8dcbe0c2c23b618c851acc9e4b5de4dd4f3681c5`, after PR #72 and its push,
pull-request and main CI runs each passed 8/8. The run used Compose project
`cybercontrol-gate-c-ninth-993ed97-20260815`, fresh PostgreSQL volume
`cybercontrol_gate_c_ninth_993ed97_20260815`, real Keycloak-issued Tokens,
two tenants and twenty real subjects.

All five stages and recovery completed. Stage-local safety and delivery
controls passed, including connection/reconnect `1.0/1.0`, delivery p95/p99
`811/1070ms`, zero loss, zero final duplicate rendering, zero tenant leakage,
zero Outbox `DEAD`, zero HTTP 5xx and zero pool timeout. The final 30 recovery
samples had zero subscribers, close owners, queued events/bytes, replay cache
events and replay tasks; this proves that the eighth run's one-live-subscriber
residual did not persist.

The same run failed frozen Outbox p95 at `3102.698ms` against `<=2000ms` and
post-ramp memory ratio at `1.416064` against `<=1.10`. Outbox p99 was
`3935.444ms` and passed. API container memory first/last/peak was
`261095424 / 369727898 / 437256192` bytes; process RSS was
`307769344 / 413544448 / 482349056`; anonymous RSS increased from
`257699840` to `363474944`, while file RSS stayed at `50069504`. FDs returned
from `29` to `29` after peaking at `2037`. PostgreSQL ended at migration 0010,
FORCE RLS `74/74`, Outbox `PUBLISHED=223`, terminal
`PENDING/CLAIMED/DEAD=0`, and foreign-tenant visibility `0`.

The immutable package is
`gate-c-20260814T163148Z-993ed9719dfb-ninth-remediation-failed-evidence-v1.zip`,
`5481915` bytes with SHA256
`d6b5454dad9c4b9471415211b5f212efc6f73c8f90358af2743f363f87362ea3`,
on immutable GitHub Release ID `370734489`, asset ID `514719132`. The asset
digest matches, and the JWT/credential/PII scan recorded zero hits.

## 5. Remaining Release Work

### 5.1 Ninth Failure Archive Closure: Completed

- PR #73 merged the independent docs/evidence-only archive as
  `b15ec9b63b15a36603f606c4da94f7382fb4a9fb` after push Run `31828555182`,
  pull-request Run `31828625199` and protected-main Run `31829334301` each
  passed 8/8. Historical runs, Releases, images and volumes remain preserved.
- The formal state remains `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

### 5.2 P0 Tenth Scoped Remediation

- Correlate each Outbox event from transaction commit through claim,
  authorization, durable acceptance, published marking, notification and SSE
  enqueue. Fix only measured owners while preserving leases, retries,
  partition order, idempotency and atomic publication.
- Distinguish live-object retention from allocator fragmentation/high-water
  behavior using tracemalloc, object counts, USS/PSS/RSS, allocator and map
  evidence.
  Fix the actual owner or production allocator behavior; forced GC, recovery-
  only trimming, restart or altered aggregation is not an acceptance fix.
- Preserve all five stage passes, zero loss, zero final duplicates, zero tenant
  leakage, zero Outbox `DEAD`, signed tenant-bound cursors, ordered delivery,
  zero close races and the ninth run's terminal lifecycle gauges of zero.
- Add deterministic unit, concurrency and real PostgreSQL regressions. Keep
  Python coverage at least 90% and pass every release-quality gate.

### 5.3 P0 Fresh Protected-Main Replay

1. Merge the tenth remediation only after push and pull-request 8/8, then
   require protected-main 8/8.
2. Build all images from that main without `-SkipBuild`.
3. Use a unique Compose project, evidence directory and fresh PostgreSQL volume;
   never reuse development, release or historical Gate C volumes.
4. Execute the unchanged 20, 200, 500, 1,000 and 2,000 stages plus the fixed
   ten-minute recovery observation using real Keycloak Tokens.
5. Any frozen-control failure requires a new immutable failure archive and
   keeps Gate D locked. Only a complete same-run pass can mark Gate C accepted.

### 5.4 Work Locked Behind Gate C

- Gate D: at least eight hours of generation, verification, review, release and
  SSE soak under pre-frozen thresholds.
- Gate E: independent PostgreSQL backup restore, measured RPO/RTO and recovered
  audit/Artifact Store/Outbox/publication consistency.
- Gate F: database restart, Faiss corruption, temporary OIDC loss and Provider
  circuit-breaker fail-closed drills; sealed Provider credentials only.
- Gate G: target deployment, TLS, secret management, monitoring, alerting,
  capacity, PITR, rollback, incident rehearsal, cross-browser/WCAG and PII
  lifecycle acceptance.
- Major dependency upgrades and unrelated product features remain isolated and
  unauthorized during Gate C closure.

## 6. Final Audit Judgment

CyberControl's current commercial product feature chain is implemented, and
Gate A/B evidence is accepted. The project is not production accepted. The
ninth remediation completed the full Gate C workload, passed all stage-local
controls and ended with zero terminal subscriber/queue/replay state. The same
run still failed Outbox p95 by `1102.698ms` and retained `1.416064` of the
frozen RSS baseline. The ninth failure archive is now closed on protected main.
A tenth remediation may begin only from this resulting protected main under a
separate task. Gate D-G remain locked until an independent complete
Gate C success-evidence PR passes CI and merges.
