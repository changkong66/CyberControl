# CyberControl Project Stage Audit

Process Version: `Gate-C-12-v2.0`

## 1. Precise Stage Position

CyberControl is in **Phase 7 release closure**. The current product scope,
clean-volume Gate B business replay, Keycloak-backed registration and account
management, and the `zh-CN`/`zh-TW`/`en-US` workbench are implemented on
protected main. The current protected-main engineering baseline is
`b4b3c6eaf00f4c9f013fad8acfd2f0d9d2860211`, tree
`f21426de47935f043055519558bb0816095b509a`. Protected-main Release Quality
Gates Run `33582128563` completed 8/8 jobs successfully. PR #93 changed build,
capacity and diagnostic infrastructure, PR #94 changed status documents, PR
#95 accepted the measurement design and PR #96 added default-off diagnostic
capability. PR #100-#102 rebuilt the trusted engineering foundation, PR #103
closed its status, PR #104 hardened only diagnostic execution governance, PR
#105 closed that status, PRs #106-#108 repaired diagnostic tooling/readiness,
PR #109 archived the final design rejection, PR #110 closed that status, and
PR #111 authorized ADR-0033. None changed core product
behavior, so the current product source
remains
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

D1 reached a valid source-bound readiness state and executed one complete S
control arm, but its physical ledger produced `non_jemalloc_anon=-352256`.
ADR 0032 classifies this structural inability to produce a nonnegative
mutually exclusive ledger as design failure two and requires new diagnostic
design work to stop under `Gate-C-12-v1.0`. ADR-0033 now authorizes only a
versioned, default-off replacement diagnostic implementation under
`Gate-C-12-v2.0`; no RSS owner or product fix is authorized. The current stage
is therefore ADR-0033 status closure followed by implementation and D1/D
closure, not D2 or remediation.

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
- Docker Desktop data disk migrated to the F drive without deleting historical
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

## 13. Gate C Twelfth Phase 0 Infrastructure Audit

Process Version: `Gate-C-12-v1.0`

PR #93 head `bfe89390f281e1229b46b4e86dd60012a4543416` passed push Run
`32828446684` and pull-request Run `32829198360`, Squash Merged as
`cd93b8438408a381b27275165b5650c8ce447ecb`, and passed protected-main Run
`32829926696`. Each chain completed 8/8 and the protected-main tree is
`e9fd1ebe3df09988bac5f82cb8cd6cb80b03ec30`.

The change is classified `BUILD_INFRASTRUCTURE`. It binds backend, frontend,
migrate, provider, load and supporting service image references to one source-
bound image lock; records a reproducible build receipt; removes mutable Alpine
index input; and normalizes Python image metadata. The image-lock and build-
receipt SHA256 values are respectively
`7fd28b88fed9bfa6edab48b8568be29e06087c307a037db4fa1f880e7c43cc3f`
and `c2ca64f04450e8802ec8d3931f839051699008b4cc2ab53c9d65b43f645efa6a`.
No frozen threshold, workload or core trusted semantic changed.

The accepted capacity policy is `15/8/5 GiB`: admission at 15 GiB, a warning
and only non-destructive temporary-resource cleanup below 8 GiB, and graceful
`INFRA_ABORTED` stop below 5 GiB. The startup snapshot race and missing
`TEMP`/`TMP` portability defect are covered by regressions. At closure, D: had
`19.237309 GiB` free; Docker Server 29.6.1 had 16 CPUs, 7,958,888,448 bytes of
memory and zero running containers. Historical containers, images, volumes and
evidence remain preserved; no prune occurred.

The authoritative Phase 0 quality package is 237,689 bytes, SHA256
`bcda2bc3af873cbc47f1722e16df6c5c8039c9c8604568b41e64253988d669da`.
Its manifest SHA256 is
`b094738da6a43b85c55deac4786fb139443eb8b7f41fa86ad75d6de0a753f2ff`,
covering 23 files and 2,325,408 uncompressed bytes with exact archive
verification. Local Python unit was `704 passed, 2 skipped`; real
PostgreSQL/Keycloak was `792 passed, 2 skipped` with 91.70% coverage; frontend
72 tests, Playwright 8/8, Go, contract, supply-chain, SBOM/license, Trivy and
Gitleaks gates passed.

The jemalloc calibration is explicitly rejected. The A arm passed, but the
Measurement arm produced HTTP 500 after profiling activation, so A' was not
executed. Package SHA256
`99d6fb8ed47950ea142def94c2fd3a6388ec0091e517ee6737ad5d2cdff7d423`
preserves that stop. No RSS owner, P2 candidate or acceptance result can be
derived from it.

`baseline_history` appends PR #93 as sequence 16 while `gate_c_attempts`
remains exactly 12. Product source remains `a57d0ce...`, engineering baseline
advances to `cd93b843...`, and the formal Gate C source remains `5fcb917b...`.
This closes Phase 0 infrastructure only. P2 behavior work, diagnostics,
PreflightSmoke, formal Gate C and Gate D-G remain locked until a new reviewed
diagnostic ADR receives explicit authorization.

## 14. Phase 0 Status Closure And ADR 0032 D0 Audit

PR #94 head `6d9bba6c77ac0af103e9c2add10dcd426bec380d` passed push Run
`32832723708` and pull-request Run `32833344654`, Squash Merged as
`5ae8637c46c741c8b6f079e22af3e2517bac7bb9`, and passed protected-main Run
`32834020352`; each chain completed 8/8. Its tree is
`9c478ed3c22debf65fe3eb4fef92ee58982f233f`. It is status documentation only,
so `baseline_history` advances to sequence 17 while product source
`a57d0ce...`, the last formal source `5fcb917b...`, M2 and twelve formal
attempts remain unchanged.

ADR 0032 is now present as the candidate final diagnostic design allowed by
the Gate-C-12 process. It separates signal delivery (`S`), profiler reset
(`R`), activation (`P`) and combined reset/activation (`F`) into matched
A/M/A' experiments. L1 bounded inventory and L2 sampled profiling each have
their own 200-connection interference boundary, and mutually intrusive probes
cannot be combined. This removes the ambiguity that invalidated earlier
ownership conclusions.

D0 completion requires all six reviewed artifacts: variable matrix,
interference formulas and zero-tolerance controls, mutually exclusive ledger,
strong/weak admission and multi-owner cutoff, failure exits, and the complete
evidence/image/cleanup contract. The structured record marks every artifact
present but correctly leaves D0 pending this candidate's future Squash Merge
and protected-main 8/8. It contains no fabricated run, owner, PR number, merge
SHA or future CI result.

Strong admission requires at least 90% reconciliation. Weak admission requires
a dominant owner of at least 70%, category-known residual, a conservative
passing prediction and a separate numbered append-only addendum with two
independent evidence packages and explicit `WEAK_ADMISSION_APPROVED`. This
preserves the repository rule that accepted ADRs are immutable.

`DESIGN_REJECTED` consumes the second and final design-failure slot;
`OWNER_UNRESOLVED` uses trusted but inconclusive data and does not consume that
slot; `INFRA_ABORTED` is limited to two same-cause retries of the interrupted
level. Actual recovery residual above 130% of the remediation ADR's
conservative prediction stops load escalation. Every round must archive,
verify and clean its own temporary resources before another round can start.

This record does not itself authorize execution. Only after its external D0
closure may the exact ADR 0032 instrumentation and calibration begin. Product
behavior, PreflightSmoke, formal Gate C and Gate D-G remain locked.

## 15. ADR 0032 D0 External Closure Audit

ADR 0032 design PR #95 head
`8076c4d0f313f094d5d71e844c6144d46076818a` passed push Run `32858328460`
attempt 2 and pull-request Run `32859688307`, Squash Merged as
`2c9d7debb2ba176f0688138d9519dca8805b5a6c`, and passed protected-main Run
`32860487073`; every chain completed 8/8. Its tree is
`d4b7e6542f34c3b43b80932a43fcfd52df228a47`.

This externally closes all six D0 artifacts required by `Gate-C-12-v1.0`:
the S/R/P/F variable matrix, exact interference and zero-tolerance formulas,
mutually exclusive physical ledger, strong/weak admission and multi-owner
cutoff, failure exits, and the evidence/image/cleanup contract. The accepted
ADR remains immutable. Any future weak admission requires a separate numbered,
evidence-bound addendum and its own protected-main closure.

The change is `DIAGNOSTIC_DESIGN`, so `baseline_history` appends sequence 18.
Product source remains `a57d0ce...`, the last formal source remains
`5fcb917b...`, M2 remains current and `gate_c_attempts` remains 12. D0 permits
only implementation and calibration of the exact design; it does not authorize
product remediation, PreflightSmoke or formal Gate C.

## 16. Diagnostic Capability And D1 Readiness Audit

Diagnostic-capability PR #96 head
`fb9dc93937c2a8c0b5dda314b55a0f5cc44710d7` passed push and pull-request Runs
`32874073910` and `32874795456`, Squash Merged as
`d2bee3861adf1129f80aae9b10d4709610a69251`, and passed protected-main Run
`32875417540`; every chain completed 8/8. Its protected-main tree is
`69eed0310296f95718660dfd798ea6262bbac291`.

PR #96 implements the bounded L1 inventory, mutually exclusive RSS ledger,
S/R/P/F and L1 A/M/A' runners, real TLS PostgreSQL churn, evidence packaging,
exact cleanup receipts, diagnostic image separation and default-off event-loop
heartbeat authorized by ADR 0032. It does not establish an RSS owner and does
not alter default product behavior or frozen Gate C semantics.

The change is `DIAGNOSTIC_CAPABILITY`, so `baseline_history` appends sequence
19. The engineering baseline advances to `d2bee386...`; product source remains
`a57d0ce...`, the last formal source remains `5fcb917b...`, M2 and all twelve
formal attempts remain unchanged.

Before D1, a manifest-driven cleanup removed only proven unreferenced temporary
diagnostic resources. The receipt is
`D:\CyberControlAcceptance\phase7\gate-c\diagnostics\gate-c12-capacity-cleanup-20260825T171029Z\cleanup-receipt.json`,
SHA256 `cb28d0eedaf1987329469edbb5e8395ef3ed7dedba8d4e78e21382260f3317ed`;
the pre-cleanup manifest SHA256 is
`eff7be833b5e4c0efca35598c48c0b4b687a5ad89262495f27d55c24c12d0029`.
Evidence-anchor mismatches and remaining candidate resources are zero. No
prune, formal-volume deletion, evidence-image deletion or development-
container stop occurred.

Post-cleanup D: free space is `10.823 GiB`, below the `15 GiB` admission floor.
D1 runtime is classified `INFRA_ABORTED_CAPACITY`. No image build, calibration
or diagnostic run is permitted until free space is restored and reverified.
This stop consumes neither a design-failure slot nor a formal attempt. Product
remediation, PreflightSmoke, formal Gate C and Gate D-G remain locked.

## 17. Trusted Foundation And Governance Closure Audit

PR #97 is retained as an explicit infrastructure-aborted state event. Its push
Run `32878844972` and pull-request Run `32879010344` attempt 2 passed 8/8; it
Squash Merged as `689b118c5e61112005770ea0286698f43ae1ca78`, tree
`c034d19a46ca94818c44ef8bea03d11f44b1c78d`, but protected-main Run
`32881158651` failed when the container job timed out downloading the Alpine
jemalloc patch. No product decision was made and no formal attempt was added.

PR #100/#101/#102 then closed the underlying foundation, governance and
Windows evidence-tool defects. They merged as
`10c6888454860155d24ad3947a9926c648c63783`,
`63900736b537c60864f24a24cc312e48d564c2b8` and
`70b6466f238887676ff4a0c1482923354ef8bd26`; all nine push, pull-request and
protected-main runs passed 8/8. Post-merge closure receipts bind each merge
SHA/tree to product source `a57d0ce...`, formal state and 12 attempts.

The audit verified the following controls:

- Docker migration result `MIGRATION_VALIDATED`, 13/13 formal volumes, zero
  running business containers and a validated non-overwriting rollback path.
- Fully offline build inputs with hash-locked APK, wheelhouse, pnpm and OCI
  content; license propagation classes distinguish build-only, runtime,
  linked/derived and diagnostic-only components.
- Strict protected Squash fallback with required Release redline and container
  checks, administrator enforcement, linear history and no history rewrite.
- Exact-main and append-only governance, Full-only attempt updates,
  `process_version` enforcement, immutable evidence path protection, audit
  index generation and three-root capacity control.
- Independent network-isolated empty-cache builders producing identical normal
  and diagnostic image digests for source `70b6466...`.

Normal lock, diagnostic lock and build receipt SHA256 values are
`3d35955a2edd961f9364fca32f40d0dc9bbb8ab85d1f2fe4c97d550e6220d1f7`,
`2d9bf585972a3d0e89c2931f33187b14a98ea3f1d81698796e072355fff83734`
and `e81a26cf4ecb1747071bc892a8ac5a10b7a4e4a625c1e96c8262eecdbbe1db1e`.
The post-build three-root snapshot is `NORMAL` at
`146.205/327.564/827.397 GiB`; temporary builders and running containers are
both zero.

GitHub prerelease `379521605`, immutable asset `537480740`, stores the
36,710-byte non-acceptance package. Local and server SHA256 are both
`e6d3ef5a04e9f1f39438266e85e71e709859f4bcd1a0c66b1adbe1ee0fedc137`;
all 20 manifest members were independently rehashed with zero mismatch.

Typed `baseline_history` sequences 20-23 classify these events as `STATUS`,
`INFRA`, `INFRA` and `REMEDIATION`. The prior 19 entries are unchanged,
`gate_c_attempts` remains 12, product source remains `a57d0ce...`, and Gate D-G
remain locked. PR #103 externally closed that status snapshot and produced a
valid `D1_ONLY` receipt for `1103cdb...`; PR #104 now supersedes its source
binding, so new exact-main locks and readiness evidence are mandatory.

## 18. Target-Two Diagnostic Governance Closure Audit

PR #104 head `661f62bfd274d56cf59a6c97817ae272bcf059a3` passed push and
pull-request Runs `33487315626` and `33488418124`, Squash Merged as
`5ac3287bc6bd22dce1c7e179255246a7617b1817`, tree
`e0a39d9106361ad22023171e3a0960140241ed8b`, and passed protected-main Run
`33489319860`; all three chains completed 8/8. Post-merge closure receipt
SHA256 is `b6476dde8bbbd1e2941594349e050083f96be6586d507be67b87ce7685a2836f`.

The change closes five execution risks before D1: every probe now needs two
independent sequences; pre-package infrastructure faults propagate as
`INFRA_ABORTED`; the calibration workload is unambiguously 2,000 total TLS
connections at maximum concurrency 200 and 50/s; Preflight precedes mainline
gradients after any remediation; and L1 physical-ledger attribution is checked
across both runs. Local quality gates passed `783` deterministic tests and
`870` PostgreSQL/Keycloak tests with `91.47%` coverage, plus one independent
database-restart probe. No product runtime, migration, threshold, workload or
formal state changed.

`baseline_history` appends sequence 24 as `DIAGNOSTIC`; the first 23 entries
remain byte-for-byte historical, `gate_c_attempts` remains 12, product source
remains `a57d0ce...`, and Gate D-G remain locked. The prior `1103cdb...` D1
receipt was superseded because engineering source changed. At that snapshot,
the target-two status merge, external receipt, fresh exact-main dual-track
image lock and fresh `D1_ONLY` receipt were mandatory. PR #105 and the
`260913a...` readiness evidence below subsequently closed those prerequisites.

## 19. D1 Readiness And Design-Rejection Audit

PR #105 closed the target-two governance snapshot. PRs #106, #107 and #108
then corrected diagnostic sequence orchestration, bounded bootstrap retry and
source-bound readiness metadata without changing product runtime. Their merge
SHAs are `a1ae0f626ba4783e5d50365a3fb6faef22a7d139`,
`84eddf30d4e1280fafa0f588cbf79311169148ae`,
`7e88e67cd43d3b7ee529c8841a01699b41a12bc7` and
`260913a964ee8afbdbfbc073e89090f551b7cc67`. Every push, pull-request and
protected-main chain passed 8/8 and every merge has an external closure
receipt.

The final `260913a...` D1-readiness receipt passed with scope `D1_ONLY`. It
binds source tree `8748b79cf25d31ea158825312ac19eb7b1107e27`, product source
`a57d0ce...`, normal/diagnostic image locks
`0c366407ee1baeaa85a9e8c87f4bc529d2618734749169b2e1780db5c9a20f58` /
`c79df22c2e78b37f4292745d1bd8b0e7438172dea504d510749cfb8daff1e8de`
and build receipt
`29b3401895797a3d050e51f3a4008136e713c292c4298413e2577643171b7843`.
Readiness Release `380635279` has matching local/server package SHA256
`8bd3be496b0ca0d137812aef887eb652783f9a239eeb9a0dfa71197966e2f961`.

D1/S arm `adr0032-s-a-20260901T155200Z-f160628c` completed 2,000/2,000 TLS
connections, the full 300-second idle and 600-second recovery windows, sample
completeness `1.0`, and no OOM or restart. This excludes infrastructure abort
and confirms that the failure occurred at the accepted design's trust gate.
Recovery `RssAnon=57,323,520` and jemalloc `resident=57,675,776` yielded
`non_jemalloc_anon=-352,256`, violating the nonnegative physical-partition
invariant. The arm is correctly classified `BoundedMemoryInventoryRejected`
and the overall decision is `ADR_0032_FINAL_DESIGN_REJECTED`.

This is design failure ordinal two. It is not owner non-resolution and cannot
be reclassified as infrastructure failure. It produces no admissible owner,
no conservative remediation estimate and no permission for D2, product
changes, PreflightSmoke or Full. The accepted stop rule prohibits a third
diagnostic design under `Gate-C-12-v1.0`.

Evidence PR #109 passed push/PR/main Runs
`33531776126/33532803157/33533885658` at 8/8 and merged as
`44ff28af5b54b574aa8a6fd3f62f2d258244fd74`, tree
`e72cab3d31f83a6071141623661b08fb9e48eed6`. Closure receipt SHA256 is
`239ec2f0cdc64548bfc1ca64557ac90625e9f1edbdde5cdef5f475206f2dfe9a`.
Immutable Release `380653216` stores the 35,912-byte evidence package with
matching local/server SHA256
`94bfd0a483f56a4789588c8fd2968b140acbcb1142744730cec0cb239f32a093`.

The sequence wrapper's missing `reason` property lookup is separately tracked
as `SEQUENCE_FAILURE_REASON_MASKING`. It did not alter the arm evidence or
classification. ADR-0033 requires a fail-preserving wrapper repair and test
before D1/D execution.

## 20. Gate-C-12-v2.0 Domain-Separated Attribution Authorization

PR #110 closed the v1 design-rejection status. It merged as
`841020d0f97737adf925950792f3bb4f0dc8df2e`, tree
`d5e07269d971236674e48d2d7bee99c1bf131d3b`, after push/PR/main Runs
`33539024249/33539091225/33540046732` passed 8/8. Its immutable receipt SHA256
is `09cbab9803ea6e984fc3e94ca4166ee0b5fe5f1b718a3d1e5a4cdf54168d6733`.

ADR-0033 PR #111 passed Runs `33581087504/33581119453/33582128563` at 8/8
and merged as `b4b3c6eaf00f4c9f013fad8acfd2f0d9d2860211`, tree
`f21426de47935f043055519558bb0816095b509a`. Immutable Release `380938164`
stores its 1,579-byte closure receipt; local and server SHA256 are both
`b01073c7191b919a3826940ef3027f44c645ea11a35f5a8bb11eedb75f844c96`.

`Gate-C-12-v2.0` is a new diagnostic-governance cycle. Historical v1 evidence
and classifications remain unchanged. The new model separates cgroup physical,
Linux process and jemalloc accounting domains, treats cross-domain differences
as signed non-additive signals, and calibrates bounded bracketed sampling as
variable `D`. This closes the identified measurement-model defect but does not
establish an owner. Only implementation and D1/D become eligible after the
status and implementation chains close. Typed `baseline_history` sequence 30
records PR #111; no Full occurred, so `gate_c_attempts` remains 12 and all
product and downstream gates remain locked.
