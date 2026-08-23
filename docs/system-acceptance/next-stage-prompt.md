# CyberControl Phase 7 Gate C Eleventh Single-Variable Remediation And Rerun

Process Version: `Gate-C-11-v1.0`

Record `process_version: Gate-C-11-v1.0` in every new preflight, diagnostic and
formal-run metadata record. Do not rewrite historical records to add this
version.

Work only from real protected-main, GitHub Actions, Docker, PostgreSQL,
Keycloak-issued Tokens and immutable evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, CI, tests,
Tokens, metrics, images, volumes, packages or acceptance decisions. Gate D-G
remain locked.

## Verified Parent Baseline

- Protected parent main: `108e8aa0b6e85c304c9bcf4aa3a5c30ec6b5df1a`
- Parent tree: `8cc53ce175a44f103b4733fd9e4afa46cff98937`
- Parent main CI:
  [32487659559](https://github.com/changkong66/CyberControl/actions/runs/32487659559),
  8/8
- Product source before the docs-only closure:
  `108e8aa0b6e85c304c9bcf4aa3a5c30ec6b5df1a`
- Formal state:
  `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Latest failed run:
  `D:/CyberControlAcceptance/phase7/gate-c/gate-c-20260815T050434Z-64792b0420f4`
- Immutable package SHA256:
  `036b3c8e09a8ff039b7b30a0d45cf9d67d6939f29690a39b35b9c52e8756e91c`
- Immutable Release:
  [371033270](https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-tenth-remediation-failed-20260815-64792b0-evidence-v1)

The docs-only baseline-closure merge SHA becomes the next
`engineering_baseline_sha`; it does not supersede the product source. Require
that exact merged main and its protected-main 8/8 before creating a remediation
branch. A commit cannot contain its own merge SHA, so use GitHub PR/merge/CI
attestations and append the result in the next natural status update.

## Phase 0: Protected-Main And Environment Preflight

1. Fetch `origin/main` and verify branch tip, tree, protected-main CI, clean
   isolated worktree, frozen hashes and ancestry.
2. Preserve the main workspace and all uncommitted work. Do not reset, checkout,
   stash, amend, force-push, prune, delete or overwrite it.
3. Create a clean isolated worktree from exact `origin/main`. Do not copy the
   main workspace `.env`, virtualenv, `node_modules`, cache or untracked output.
4. Verify dependency locks, Dockerfiles, Compose, build scripts and configuration
   against the protected tree. Build every image only from the isolated
   worktree and reject untracked source in the build context.
5. Verify hard environment controls: Docker CPU/memory/swap, core image digests,
   PostgreSQL core settings, network mode, resource limits, permissions,
   Compose/lock hashes and threshold/workload hashes. Hard differences block
   execution.
6. Record reference-only differences such as Docker/OS patch versions and host
   background processes. Do not clear host page cache, terminate arbitrary host
   processes or run Docker prune.
7. After five minutes idle, take five samples. Remove the per-metric minimum and
   maximum, then calculate median and MAD. Use relative plus MAD bounds for
   RSS/USS/PSS, absolute percentage-point plus MAD bounds for near-zero CPU,
   absolute millisecond plus MAD bounds for event-loop lag and count bounds for
   FD/pool/subscriber/queue/replay state.
8. On mismatch, emit an environment-difference report. A documented reference
   difference may be approved; a hard difference must be corrected before one
   retry. Stop after a repeated unexplained or hard mismatch.
9. Inventory all historical Gate C containers, images, volumes, Releases and
   evidence read-only. Preserve every formal volume and immutable package.

## Audit And Evidence Contract

- Every ADR and metadata record must state `product_source_sha`,
  `engineering_baseline_sha`, source tree and process version.
- Maintain append-only `baseline_history` with sequence, time, main/tree,
  change type (`PRODUCT_CODE`, `STATUS_DOCS`, `EVIDENCE_ARCHIVE`), dual
  baselines, PR and CI references.
- Maintain append-only `gate_c_attempts` only for formal Gate C runs.
  Diagnostics, preflight and `INFRA_ABORTED` records belong in separate indexes.
- Store diagnostic summaries at `docs/diagnostics/gate-c/<run-id>/` with
  `summary.json`, `comparison.json`, `root-cause.md`, `package-reference.json`
  and redacted charts. Store raw JSONL, logs, heap snapshots and memory maps
  outside Git under
  `D:/CyberControlAcceptance/phase7/gate-c-diagnostics/<run-id>/`.
- `package-reference.json` must include run ID, path/immutable URI, bytes,
  SHA256, source/tree, dual baselines, environment fingerprint, frozen hashes,
  process version and credential/JWT/PII scan result.
- Upload every diagnostic package cited by an ADR as an immutable external
  package. Other exploratory packages may retain repository summaries and local
  hash references; they may be deleted only after Gate C acceptance, an
  approved destruction manifest and integrity verification.
- Every ADR needs an evidence index listing run IDs, summary paths and raw
  package SHA/URI. Commit messages must reference the ADR number.

## Diagnostic Runner Interfaces

Implement explicit non-acceptance modes in
`tools/windows/run-phase7-gate-c.ps1`:

```powershell
-Mode DiagnosticStages -DiagnosticStages smoke-20,ramp-200,ramp-500
-Mode PreflightSmoke
```

Both modes must record the process version and dual baselines. They must never
call the formal finalizer, create an official `gate-c-summary.json`, update
formal status or claim Gate C acceptance. Diagnostic recovery is permitted only
when the diagnostic includes the 2,000 stage and uses the unchanged ten-minute
recovery interval.

Preflight and the formal run may reuse the same protected-main image digests,
but never state. After `PreflightSmoke`, destroy its Compose project, network
and PostgreSQL volume completely. The formal run must use new isolated
resources. Only a product-code merge triggers a no-SkipBuild image rebuild;
docs/evidence merges verify the existing product-source image binding.

## Layered A/B/A' And Candidate State Machine

- Reproduce each root cause on parent A, validate candidate B and reproduce on
  an independent clean parent A' worktree. Do not use `git revert` on candidate
  B as A'.
- Use deterministic unit/real-PostgreSQL integration A/B/A' for logic,
  lifecycle and boundary defects. Escalate to a 200-connection diagnostic only
  when the test layer cannot reproduce a concurrency/performance defect. Never
  use three full formal 2,000-client runs as the default control experiment.
- Each fix must add positive proof and negative/boundary regression tests.
  Always run the complete RLS, tenant isolation, idempotency, partition order,
  atomic publication, signed cursor and fail-closed regression set.
- Use one prebuilt candidate image set for three independent Smoke validations,
  each with a new project/network/volume: cold deployment, controlled API
  restart and stable-idle deployment.
- Reject immediately on semantic, security, functional or zero-tolerance
  failure. A performance-only near miss within 10% may receive one separate,
  same-root-cause micro-adjustment PR. This allowance never applies to safety
  or zero-tolerance controls.
- If one of three candidate validations fails, run two more independent
  validations. Any additional failure rejects the candidate.
- After two failed root-cause rounds in one problem domain, freeze code changes
  in that domain and return to measurement with a new root-cause report and
  explicit review. Counts are isolated by P0/P1/P2; one domain does not consume
  another domain's count. Freezing one domain does not by itself prevent another
  domain from opening later, but every domain must still satisfy its own evidence
  freshness and opening gates.

## P0: Eleventh Remediation

Only after the docs-only closure merges and protected main passes 8/8, create
exactly:

`codex/phase7-gate-c-eleventh-remediation`

P0 may address only the tenth-run smoke delivery p99 `6850ms`, monitor
completeness `31/39` and seven `/metrics` ReadTimeout observations. Before code
changes, add an ADR with measurable hypotheses, evidence index, semantic
boundaries, disproof metrics, impact report and stop conditions.

First inspect the effective container diagnostic configuration. Measure actual
metrics substeps, `generate_latest`, event-loop lag/runnable tasks, request and
serialization time, metric cardinality, producer-to-client segments, RSS,
objects, FD and queues. Do not assume `gc.get_objects` or tracemalloc snapshots
run on every scrape without evidence.

P0 passes only when all three independent Smokes satisfy every frozen control,
monitor completeness is at least 0.95, `/metrics` ReadTimeout is zero and all
zero-tolerance controls remain passed. Do not alter monitor timeout,
aggregation, workload, event count or client grace periods.

## Conditional P1 And P2

- Merge P0 only after complete local gates, push 8/8, PR 8/8, Squash Merge and
  protected-main 8/8.
- Run protected-main Preflight and then one complete fresh formal Gate C. Do not
  use ninth-run Outbox/RSS evidence to claim the current code still fails.
- Create a separate P1 Outbox PR only if that latest complete formal run proves
  created-to-published p95 exceeds 2,000ms. Compare 20/200/500/1,000 gradients
  using correlated created, claimable, claimed, dispatch, authorization,
  durable acceptance, published, notification, SSE enqueue and client timing,
  plus queues, pools, DB waits and scheduling evidence. Do not use simplistic
  linear/exponential attribution.
- Create a separate P2 RSS PR only if the latest complete formal run proves
  Outbox passed but recovery RSS ratio exceeds 1.10. Trace subscriber, queue,
  replay, task/frame, metric-label, HTTP/DB pool, Python heap and native
  allocator creation, ownership and release. Fix the concrete reference owner;
  do not force GC, restart, recovery-only trim or change the baseline.
- Each PR may contain one root cause and the minimum corresponding change. No
  unrelated refactoring, formatting or optimization is permitted.

## Preserved Semantics And Test Gates

Do not modify migrations 0001-0010, frozen contracts, RLS, TenantContext
authority, SERIALIZABLE transactions, C12, Outbox atomicity, thresholds,
workload, events, connections, timeouts, grace periods or aggregation. Do not
fabricate JWTs, send client identity headers, force GC, hide a defect with more
workers or acknowledge publication before durable acceptance.

Preserve `FOR UPDATE SKIP LOCKED`, claim token, lease, retry, partition order,
idempotency, durable acceptance, published cursor, signed tenant-bound
Last-Event-ID, strict ordered replay, duplicate suppression, single idempotent
close ownership and fail-closed authorization/cursor validation.

Add deterministic and real PostgreSQL tests for metrics readiness/timeout,
event-loop delay, delivery segments, notification/SSE order, slow consumers,
replay, cancellation/double-close/shutdown, ContextVar/session/pool/task/frame/
FD cleanup, Outbox wakeup/lease/claim/retry/partition order, valid/invalid/
duplicate/cross-tenant dispatch, signed cursor rejection and concurrent tenant
isolation. A defect regression must fail on A/A' and pass on B. Keep Python
coverage at least 90% with no exclusions, empty assertions, forced GC or fake
scale claims.

Run Python unit and real PostgreSQL integration, frontend typecheck/build/unit/
coverage, Playwright, Go fmt/vet/race/test/build, contract drift, SBOM/license,
dependency audit, Trivy and Gitleaks. Every code/docs/evidence PR requires push,
pull-request, Squash Merge and protected-main 8/8.

## Formal Gate C Rerun

After the latest product-code remediation merges and main passes 8/8:

1. Build all product images once from exact clean protected main without
   `-SkipBuild`; attach source/tree, dual-baseline and process-version labels.
2. Run `PreflightSmoke` with a unique project and volume. It is not a formal
   attempt. Destroy every preflight resource after evidence capture.
3. Use the same verified image digests with a different unique Compose project,
   run directory and fresh PostgreSQL volume for the formal run.
4. Use real Keycloak-issued Tokens, two tenants and at least ten real subjects
   per tenant. Do not send tenant/subject/role/scope identity headers.
5. Execute the unchanged 20 smoke, 200/five-minute, 500/five-minute,
   1,000/ten-minute, 2,000/thirty-minute and ten-minute recovery stages.
6. Bind source/tree, dual baselines, process version, image IDs/digests,
   Compose/lock/frozen hashes, Token issuance, admission/replay/handoff,
   Outbox segments, delivery, monitor completeness, CPU/RSS/USS/PSS/FD/restarts,
   PostgreSQL session/pool/RLS/Outbox terminal state, redacted logs and SHA256
   manifest.
7. Preserve the new formal volume and publish a new immutable external package.

Zero-tolerance failures include event loss, final duplicate rendering,
cross-tenant leakage, invalid-cursor acceptance, unauthorized access, Outbox
`DEAD`, ordering/atomicity regression, pool timeout, OOM, unplanned restart or
`aclose()` race. Stop immediately, preserve the scene and archive a formal
failure.

Only objective host evidence of Docker daemon failure, disk exhaustion, host
restart or external network interruption, with no preceding product failure,
may be classified `INFRA_ABORTED`. Preserve logs/environment/manifest in a
separate index, do not append `gate_c_attempts`, and retry with new resources
after Phase 0 and Preflight. If causality is uncertain, record a formal failure.

If all frozen controls pass in one formal run, create an independent success
evidence PR, append `baseline_history` and `gate_c_attempts`, and mark
`PHASE7_GATE_C_MAINLINE_ACCEPTED_GATE_D_READY`. If any control fails, create an
independent immutable failure-evidence PR, append the same histories and retain
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. Both paths require push/PR/main 8/8 and
Squash Merge.

## External Proof And Stop Rule

Any external proof package must bind product SHA, engineering baseline SHA,
formal evidence package SHA, generation date and process version. Every number
must cite a formal evidence index. Include this disclaimer:

> 本成果基于特定版本内部验收数据，代表当前研发阶段的性能表现，不代表生产环境最终指标。

Do not publish raw logs, Tokens, identity/security configuration, PII or
unproven claims. Require release/acceptance, security/privacy and
product/competition review.

After the independent evidence PR merges and protected-main CI is verified,
stop. Do not start Gate D soak, DR, Provider acceptance, production deployment,
accessibility/privacy closure or new product work. Gate D requires separate
explicit authorization even if Gate C becomes eligible.
