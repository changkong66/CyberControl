# CyberControl Phase 7 Gate C P2 ADR 0026 Low-Interference Measurement Redesign

Process Version: `Gate-C-11-v1.0`

Record `process_version: Gate-C-11-v1.0` in every new diagnostic, preflight,
formal-run, manifest and package-reference record. Do not relabel or rewrite
historical evidence.

Work only from real protected-main, GitHub Actions, Docker, PostgreSQL,
Keycloak-issued Tokens and immutable evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, tests, CI,
Tokens, images, volumes, metrics, packages or acceptance decisions. Gate D-G
remain locked.

## Current Audited Boundary

- Current protected-main engineering baseline:
  `90a8cbc0e73ae65e844177e91ac4298704040a5e`
- Engineering tree: `72882290744d6c7cab7860633c083c236a246853`
- Current product source:
  `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Product tree: `963fcf73113e39a1e5868fae3957f4adfc102a4c`
- Last formally evaluated Gate C source:
  `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Last formally evaluated tree:
  `f721fca017c247aee93765d5f11fcbc37e12fcfc`
- Current protected-main CI:
  [Run 32674327220](https://github.com/changkong66/CyberControl/actions/runs/32674327220),
  8/8
- Frozen threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Formal state:
  `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`

PR #82 closed the eleventh formal failure archive. PR #84 froze P2 behavior
changes after two root-cause rounds failed to prove an actionable owner. PR
#87 archived ADR 0025's rejected measurement experiment. Its immutable package
is 5,676,313 bytes with SHA256
`10fb9477558ad203e1163198d8e28a941d16d922b6919d2711fdf6f69e22d92b`:

https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-adr0025-measurement-rejected-20260824-v1

ADR 0025 was rejected because tracemalloc materially changed the workload:
connection p95 was `17,989ms` versus the `673ms` control median, delivery p95
was `1,175ms` versus `45.5ms`, API CPU p95 was `101.98` versus `25.165`, and
baseline-to-recovery RSS delta was `59,334,656` versus `30,613,504` bytes.
No actionable RSS owner was proved. These results do not authorize a P2
behavior change or a formal Gate C replay.

## Phase 0: Close The Current Status PR

The current branch
`codex/phase7-gate-c-eleventh-p2-round3-status-closure` is docs-only. Before
creating ADR 0026:

1. Verify it changes only the four current-state documents and does not alter
   historical snapshots, source, contracts, tests, build files or evidence.
2. Require push and pull-request Release Quality Gates 8/8, ready review,
   Squash Merge and post-merge protected-main 8/8.
3. Fetch `origin/main` and record that exact merge SHA/tree and CI URL. The
   merge advances only `engineering_baseline_sha`; `product_source_sha`
   remains `a57d0ce...`.
4. Revalidate the frozen hashes, clean isolated worktree, Docker hard controls,
   disk capacity and preservation of all historical evidence, Releases,
   images and volumes. Do not reset, stash, prune, delete or overwrite them.

Only after this closure may a new exact-main branch be created:

`codex/phase7-gate-c-eleventh-p2-adr0026-design`

## ADR 0026 Scope: Design Only

ADR 0026 is a docs-only, independently reviewed measurement design. It must
not add a profiler, change a Dockerfile, alter runtime behavior, start a
diagnostic, unfreeze P2 product changes or claim Gate C progress.

The ADR must bind the then-current product and engineering SHA/tree, parent
main CI, process version, ADR 0025 run IDs, comparison/root-cause paths,
immutable package URI/size/SHA256, environment fingerprint and frozen hashes.
It must include one falsifiable ownership hypothesis, an impact assessment,
quantitative interference limits, stop conditions and a complete evidence
index.

The proposed hypothesis is sampled jemalloc heap profiling, compiled into a
profiling-capable diagnostic image but inactive by default, can identify a
repeatable allocation call-stack owner without materially changing workload
or RSS behavior. This is a hypothesis, not an approved implementation or root-
cause conclusion.

Before the design can be approved, it must specify and checksum:

- exact upstream jemalloc source URI, version and source archive SHA256;
- reproducible build toolchain/base image digests and every configure/build
  flag, including profiling and statistics support;
- installed library path, library SHA256, exported build/configuration output
  and immutable image build ID/digest;
- exact process-start allocator configuration, profiling sample rate, dump
  controls, activation/deactivation mechanism and output path containment;
- profiler artifact schema, symbolization method, redaction rules and offline
  comparator version/hash.

No floating package source, unpinned compiler, mutable image tag or unrecorded
build option is admissible.

## Controlled A / Measurement / A' Protocol

Use one profiling-capable image digest for A, measurement and A'. Do not
compare different allocator builds or let a candidate image masquerade as a
protected-main formal image. Each arm uses a unique Compose project, run
directory, network and fresh PostgreSQL volume, with real Keycloak issuance,
two tenants and twenty provisioned subjects.

All arms start the same image with jemalloc `config.prof=true` and runtime
`prof.active=false`. Hold the frozen 300-second idle baseline before any
activation or load:

1. **A control:** keep `prof.active=false` throughout the real frozen
   200-stream stage and 600-second recovery.
2. **Measurement:** only after the idle baseline completes, atomically activate
   sampling, reset/mark the profile epoch as defined by the ADR, run the same
   200-stream stage and recovery, capture only the predeclared profile dumps,
   then deactivate after the final synchronized endpoint.
3. **A' control:** independently repeat A with fresh resources and
   `prof.active=false` throughout.

The arm order, host fingerprint, image digest, environment controls, monitor
cadence, stage duration and recovery duration must be recorded. A and A' are
independent controls, not a candidate-branch revert. Do not run 2,000 streams
or the formal Gate C workload for measurement causality.

The design must explicitly prohibit tracemalloc, `gc.get_objects()`,
`asyncio.all_tasks()`, task-stack/frame enumeration, periodic object scans,
forced GC, allocator purge, `malloc_trim`, process restart, cache-limit changes
or any recovery-only mutation. Sampling must not expose an HTTP diagnostic
route or accept identity headers.

## Admission And Disproof Limits

Use the median of A and A' as the control. Reject the measurement design if any
condition is true:

- delivery p95, connection p95, API CPU p95 or event-loop lag p95 in the
  measurement arm is more than `10%` above control;
- baseline-to-recovery RSS delta differs from control by more than
  `max(8 MiB, 10% of the control delta)`;
- monitor completeness is below `0.95`, any required sample is missing, or a
  profile dump overlaps an unapproved lifecycle point;
- any zero-tolerance, security, ordering, pool/session, FD or terminal
  lifecycle control regresses;
- the profile cannot be correlated with synchronized RSS/USS/PSS, cgroup
  memory, `/proc` maps, jemalloc allocated/active/resident/retained values and
  bounded pool/cache/SSE inventories;
- no repeatable bounded allocation stack explains an actionable portion of
  the control-adjusted residual.

Passing these limits only makes the measurement admissible for a new root-
cause report. It does not prove the `<=1.10` formal recovery control and does
not authorize a product fix, PreflightSmoke or formal Gate C replay.

## Separate Capability PR

Only after the ADR 0026 design PR passes push/PR 8/8, Squash Merges and the new
protected-main run passes 8/8 may an implementation branch be created from
that exact main:

`codex/phase7-gate-c-eleventh-p2-adr0026-capability`

That PR may implement only the approved, disabled-by-default profiling
capability, runner support, offline analysis and focused tests. It must include
positive and negative/boundary tests for disabled mode, activation ownership,
duplicate/invalid activation rejection, atomic dumps, path containment,
shutdown waiting, redaction and absence of formal-finalizer/state mutation.
It must preserve the full RLS, tenant isolation, signed cursor, ordering,
idempotency, Outbox atomicity and fail-closed regression set, Python coverage
`>=90%`, all Release Quality Gates, push/PR 8/8, Squash Merge and protected-
main 8/8.

Only after that closure may the real A/measurement/A' diagnostic execute. Each
arm must be archived with `process_version`, source/tree, image digest,
environment fingerprint, frozen hashes, raw package SHA256 and redaction scan.
Diagnostics must not create a formal summary, append `gate_c_attempts`, update
acceptance state or be represented as formal Gate C evidence.

## Permanent Redlines And Stop Rule

Do not modify migrations 0001-0010, frozen contracts, RLS, `TenantContext`,
SERIALIZABLE transactions, C12, thresholds, workload, timeouts, aggregation or
Outbox atomicity. Preserve `FOR UPDATE SKIP LOCKED`, claim token, lease, retry,
partition order, idempotent durable acceptance, published cursor, signed
tenant-bound `Last-Event-ID`, strict replay order, duplicate suppression and
fail-closed authorization/cursor validation. Do not fabricate JWTs or send
tenant, subject, role or scope identity headers.

If ADR 0026 is not independently approved, if capability gates fail, if the
diagnostic exceeds any interference/redline limit or if it still proves no
actionable owner, archive the real result and keep P2 behavior changes frozen.
Do not start another product candidate or formal replay.

Gate C remains failed and Gate D-G remain locked. Do not start Gate D soak,
DR, Provider acceptance, production deployment, accessibility/privacy closure
or new product work. Gate D requires separate explicit authorization even if
it later becomes eligible.
