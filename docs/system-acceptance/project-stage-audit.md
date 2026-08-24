# CyberControl Project Stage Audit

Process Version: `Gate-C-11-v1.0`

## 1. Precise Stage Position

CyberControl is in **Phase 7 release closure**. The current product scope,
clean-volume Gate B business replay, Keycloak-backed registration and account
management, and the `zh-CN`/`zh-TW`/`en-US` workbench are implemented on
protected main. The current protected-main engineering baseline is
`d4b646c29bf82297332b9fdd8bc58be19744aecb`, tree
`c6e1009ec81fab9b28c1d6de9d2b0a0216e33b20`. Protected-main Release Quality
Gates Run `32707158181` completed 8/8 jobs successfully. PR #86 is the latest
change to a deployable backend artifact, so the current product source is
`a57d0ce57427804ede3f3c620fda2a93b3a300ff`, tree
`963fcf73113e39a1e5868fae3957f4adfc102a4c`. The eleventh formal Gate C replay
predates that diagnostic instrumentation and remains bound to
`5fcb917b63889cb6da8dd019efdd133f4ec3fb60` / `f721fca...`.

The formal state remains:

`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`

Gate A and Gate B are accepted. Gate C is not accepted. The eleventh formal
Gate C replay completed the entire frozen workload, including 2,000
authenticated SSE streams for 1,804 seconds and the fixed ten-minute recovery
observation. Every stage-local control passed and Outbox p95/p99 passed, but
the final aggregate failed the frozen memory-recovery ratio at `1.417200`
against `<=1.10`. All terminal lifecycle gauges were zero. A stage-local or
near-threshold pass cannot advance the release state.
Gate D through Gate G and unrelated product work remain locked.

| Area | Current maturity | Evidence-based judgment |
| --- | --- | --- |
| Phase 1.1 foundation | complete and frozen | protected, reproducible and covered by release gates |
| Topic1-Topic4 backend | complete for current scope | trusted generation, verification, review and atomic release chain is frozen |
| Identity and account backend | complete for current scope | Keycloak authority, registration, projection, administration and recovery are integrated |
| Three-language frontend | complete for current scope | business, account and locale surfaces are merged and tested |
| Gate B business replay | accepted | clean PostgreSQL replay and evidence dataset controls passed from protected main |
| Gate C authenticated SSE | failed | all stages and Outbox passed, but final RSS recovery ratio 1.417200 exceeded 1.10 |
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

### 5.1 Tenth Failure Archive Closure: Completed

- PR #76 merged the independent docs/evidence-only archive as
  `e6b461cd0b919dfe01e87ed040d04771a746d6c2` after push Run `31883430063`,
  pull-request Run `31883432630` and protected-main Run `31883708144` each
  passed 8/8. Historical runs, Releases, images and volumes remain preserved.
- The formal state remains `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

### 5.2 P0 Eleventh Scoped Remediation

- Correlate the smoke-20 delivery tail from producer/commit through claim,
  authorization, durable acceptance, notification, SSE enqueue, socket write
  and client receipt. Diagnose the seven `/metrics` timeouts and one Docker
  inspection failure as observability readiness or event-loop cost, not as a
  reason to alter the monitor threshold.
- Fix only measured owners while preserving leases, retries, partition order,
  idempotency, atomic publication, signed tenant-bound cursors, ordered
  delivery, zero loss, zero final duplicates, zero tenant leakage and zero
  Outbox `DEAD`.
- Add deterministic unit, concurrency and real PostgreSQL regressions. Keep
  Python coverage at least 90% and pass every release-quality gate.

### 5.3 P0 Fresh Protected-Main Replay After Eleventh Remediation

1. Merge the eleventh remediation only after push and pull-request 8/8, then
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
tenth remediation passed release-quality CI, but its fresh Gate C replay failed
at smoke-20 on delivery p99 and monitor completeness; later stages and recovery
were not executed. PR #76 closed that immutable failure archive on protected
main as `e6b461cd0b919dfe01e87ed040d04771a746d6c2` with Run `31883708144` at
8/8. Gate D-G remain locked until an independent complete Gate C success-
evidence PR passes CI and merges. An eleventh remediation requires a separate
authorization and must start from this protected main.

## 7. Tenth Remediation And Partial Replay Audit

PR #75 merged the tenth remediation as
`64792b0420f436d18beea2a301bd4017bc7e7a82`, tree
`61da331c23a5d5b6988aff70d0db5455732886cc`. Its push, pull-request and
protected-main Release Quality Gates were each 8/8: Runs `31865357058`,
`31865358914` and `31865636339`.

The fresh run is
`D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260815T050434Z-64792b0420f4`.
It used unique Compose project
`cybercontrol-gate-c-tenth-main-64792b-20260815050434`, preserved fresh volume
`cybercontrol_gate_c_tenth_main_64792b_20260815050434`, real Keycloak Tokens,
two tenants and twenty principals. All images were built without `-SkipBuild`.

`smoke-20` completed and failed delivery p99 at `6850ms` against `<=3000ms`
and monitor completeness at `31/39=0.7948717949` against `>=0.95`. Delivery
p95 was `439ms`. Seven `/metrics` reads timed out and the final monitor sample
had one Docker inspection failure. The mandatory stop rule left all later
stages and recovery unexecuted; no RSS recovery conclusion is valid.

The completed smoke stage retained connection/reconnect `1.0/1.0`, zero loss,
zero final duplicates, zero tenant leakage, zero HTTP 5xx, zero pool timeout and
zero Outbox `DEAD`. PostgreSQL retained migration 0010, FORCE RLS `74/74`, 57
append-only triggers and zero foreign-tenant visibility. Terminal Outbox state
was `PUBLISHED=25`, with no open or dead row.

Immutable Release `371033270` contains the 341,283-byte package with SHA256
`036b3c8e09a8ff039b7b30a0d45cf9d67d6939f29690a39b35b9c52e8756e91c`.
The package and failed volume remain preserved. Gate C remains failed and Gate
D-G remain locked.

PR #76 archived the tenth failure as a docs/evidence-only change. Its final
head `40471a50f58c758a5acf129f259126ca2ece0288` corrected repository evidence
hashes to the committed LF bytes without changing the immutable external ZIP.
Push Run `31883430063` and pull-request Run `31883432630` passed 8/8; the PR
Squash Merged as `e6b461cd0b919dfe01e87ed040d04771a746d6c2`, and protected-main
Run `31883708144` passed 8/8. The archive is closed without changing the failed
Gate C decision.

## 8. Eleventh Process Baseline Audit

Process Version: `Gate-C-11-v1.0`

Phase 0 revalidated the exact protected parent main
`108e8aa0b6e85c304c9bcf4aa3a5c30ec6b5df1a`, tree
`8cc53ce175a44f103b4733fd9e4afa46cff98937`. PR #79 push Run `32487117834`,
pull-request Run `32487121236` and protected-main Run `32487659559` each passed
8/8. The current product source and verified parent engineering baseline are
therefore both `108e8aa0b6e85c304c9bcf4aa3a5c30ec6b5df1a` before this status-only
commit.

The isolated worktree was created directly from that protected tip. Its tree
was clean, and its lock files, Dockerfiles, Compose files and runner came only
from the protected tree. The main workspace was not used as a build context and
was not reset, checked out, stashed or modified.

Phase 0 evidence also established:

- threshold SHA256
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`;
- workload SHA256
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`;
- Docker Engine 29.6.1 with 16 CPUs and 7,958,888,448 bytes of memory,
  matching the tenth formal environment record;
- 62 inspected CyberControl/Gate C volumes and zero running containers;
- C/D free space not lower than the tenth-run environment record;
- immutable Release `371033270`, asset size 341,283 bytes and GitHub-recorded
  digest
  `036b3c8e09a8ff039b7b30a0d45cf9d67d6939f29690a39b35b9c52e8756e91c`.

No historical volume, image, Release, package or snapshot was deleted or
rewritten. No diagnostic, preflight or formal workload was executed during the
closure. `baseline_history` begins with the tenth product/closure chain, while
older authoritative baseline fields remain intact. `gate_c_attempts` indexes
all eleven existing formal runs and leaves their historical `process_version`
as null.

This baseline-closure PR is documentation-only. It does not alter deployable
behavior or the frozen acceptance semantics. The formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; M1 has not been
claimed, and Gate D-G remain locked.

## 9. Eleventh Remediation And M2 Failure Audit

PR #81 head `af10947bf05b40a5759f40973770f3aaef561f89` passed push Run
`32644827393` and pull-request Run `32644829425`, Squash Merged as
`5fcb917b63889cb6da8dd019efdd133f4ec3fb60`, and passed protected-main Run
`32645162420`; all three Release Quality Gate runs were 8/8. The source tree is
`f721fca017c247aee93765d5f11fcbc37e12fcfc`.

P0 closed with three independent Smoke passes and a clean protected-main
preflight. Their Compose projects, networks and PostgreSQL volumes were removed
and were not reused. The formal attempt then used a new Compose project and the
new preserved volume `cybercontrol_gate_c_eleventh_5fcb917_20260823`.

All five formal stages and recovery completed. At 2,000 streams delivery was
`758/1077ms` p95/p99, monitor completeness was `491/495`, and Outbox was
`1879.698/2898.555ms` p95/p99 with `PUBLISHED=226` and no open or dead row.
Connection and replay success remained 1.0; loss, duplicates, leakage, invalid
cursor acceptance, HTTP 5xx, pool timeout, OOM and restart remained zero.
Terminal subscriber, queue, replay, cache, task and pool gauges were zero.

The sole failed final control was recovery memory. API cgroup memory was
262,144,000 bytes first, 371,510,477 bytes final and 436,941,619 bytes peak,
producing `1.417200 > 1.10`. Process RSS/USS/PSS also remained elevated after
the ten-minute recovery. This proves a P2 defect remains but does not prove its
owner. P1 is closed by the current Outbox evidence; P2 may open only after this
failure archive closes and receives separate authorization.

Release `375257600` is immutable and its asset digest matches package SHA256
`205517caae21e184d079219454e9e66903083839b9af87c6cc1d45b2bc604ab8`.
The formal run and volume remain preserved. This is milestone M2, while the
formal state remains `PHASE7_GATE_C_FAILED_GATE_D_LOCKED` and Gate D-G remain
locked.

## 10. P2 Round 3 Measurement Rejection And Status Closure

The formal failure archive is closed by PR #82, merge
`d5494dd1dce671c30ebfe40e046319d7572a52f5`, after push/PR/main Runs
`32652339505`, `32652673118` and `32652984515` each passed 8/8. P2 root-cause
rounds 1 and 2 were archived by PR #84 and triggered the process-level freeze
on further P2 behavior changes.

ADR 0025 then tested a new measurement design rather than a behavior fix.
PR #85 merged the design and PR #86 merged opt-in checkpoint instrumentation;
their protected-main Runs `32663785036` and `32667597681` passed 8/8. Because
PR #86 changes the deployable artifact, the dual-baseline audit records it as
the current product source even though the instrumentation is disabled by
default and has not been formally evaluated.

The real A2 and A' controls passed at 200 streams, while the measurement arm
failed ADR 0025's predeclared interference limits: connection p95
`17,989ms` versus `673ms`, delivery p95 `1,175ms` versus `45.5ms`, API CPU p95
`101.98` versus `25.165`, and RSS delta `59,334,656` versus `30,613,504`
bytes. No actionable owner was proven. PR #87 archived this result as
`90a8cbc0e73ae65e844177e91ac4298704040a5e`; Runs `32673675887`,
`32674014293` and `32674327220` each passed 8/8.

The immutable round-3 package SHA256 is
`10fb9477558ad203e1163198d8e28a941d16d922b6919d2711fdf6f69e22d92b`.
At that snapshot, the next allowed work was ADR 0026 design and review for
lower-interference ownership measurement. No new P2 candidate or formal replay
was authorized.

## 11. P2 Round 4 ADR 0026 Measurement Rejection Audit

PR #88 closed the previous status as
`c96a648f97c6033fd3ce027dc166942a3d48f373`; its push/PR/main Runs
`32676245119`, `32676665813` and `32676982606` passed 8/8. PR #89 merged the
ADR 0026 design as `d6cf032ec4cda5e2997a6da8e6ce0910d6b939fa`, and PR #90 merged the scoped
profiling capability as `ff4f3b9d33ef608772f8c499d8e906e215bc0daf`. Their
protected-main Runs `32683062644` and `32692818024` passed 8/8.

The valid diagnostic controls were independently stable. A2 and A' connection
p95 differed by `7.4919%`, delivery p95 by `4.5455%`, API CPU p95 by
`0.4407%`, and RSS delta by `1,212,416` bytes, below the declared
`8,388,608`-byte control limit. Both completed the real 200-stream stage and
600-second recovery with monitor completeness `194/194`.

The measurement arm failed the causal admission boundary: connection p95,
delivery p95 and API CPU p95 were `1.143322x`, `1.204545x` and `1.11591x`
their control medians; RSS delta was `32,808,960` bytes versus the
`19,103,744`-byte control median, a `13,705,216`-byte difference. The
measurement profile is real and source-bound, but it is inadmissible for
selecting a cache, pool, allocator, serializer, task or SSE lifecycle owner.

The first A' attempt stopped during recovery when D: free space fell to about
`0.60 GiB`; it is separately classified `INFRA_ABORTED` and was not used as a
control. The valid retry used a new project and PostgreSQL volume. All five
volumes remain preserved, and all five Compose projects have zero remaining
containers and networks.

The redacted immutable package is Release `375536270`, asset `527281489`,
86,286 bytes, SHA256
`97b3203f98b3783dfdbbe7e66be64f8e05eac1c62befc567a2f0215df4b22410`.
Its package manifest contains 32 files with no missing, mismatched or
unexpected entries; 28 JSON files parsed successfully. JWT/Bearer/private-key/
credential/PII scans found no actionable content, and Gitleaks' three findings
were SHA256 evidence fields.

This is diagnostic evidence, not formal attempt 13. `gate_c_attempts` remains
at 12 entries. The formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. After this archive
and its status-only closure pass the complete CI/merge chain, work must stop
unless a new low-interference measurement ADR receives separate authorization.

## 12. P2 Round 4 Evidence Archive Closure

Docs/evidence-only PR #91 head
`cc0955523a3bf8dfa7b0cfbb05c988d38342fcca` passed push Run `32705709392` and
pull-request Run `32706368555`, Squash Merged as
`d4b646c29bf82297332b9fdd8bc58be19744aecb`, and passed protected-main Run
`32707158181`. Each Release Quality Gate run completed 8/8. The merge tree is
`c6e1009ec81fab9b28c1d6de9d2b0a0216e33b20`.

PR #91 changed diagnostic evidence and current-state documents only. It did
not change a deployable artifact, frozen acceptance semantics or any formal
result. The dual baseline therefore records engineering baseline `d4b646c...`
while product source remains `a57d0ce...`; the last formal Gate C evaluation
remains `5fcb917b...`. `baseline_history` appends PR #91 as diagnostic evidence,
while `gate_c_attempts` remains exactly 12.

The round-4 archive is closed, but ADR 0026's ownership data remains
inadmissible. No behavior candidate, diagnostic, preflight or formal replay is
authorized. After the independent status-only closure completes push, PR,
Squash Merge and protected-main 8/8, work stops. Gate C remains failed and Gate
D-G remain locked.
