# CyberControl Gate C Twelfth ADR 0032 D1 Capacity Recovery And Calibration

Process Version: `Gate-C-12-v1.0`

Use only the real protected repository, GitHub Actions, locked images, Docker,
PostgreSQL, Keycloak-issued tokens and immutable evidence. Do not fabricate a
source, CI run, image, token, volume, metric, package, owner or decision. Gate
D-G remain locked.

## Audited Parent Boundary

- Protected main: `d2bee3861adf1129f80aae9b10d4709610a69251`
- Tree: `69eed0310296f95718660dfd798ea6262bbac291`
- Protected-main CI: Run `32875417540`, 8/8
- Product source: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Last formal Gate C source: `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Frozen threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Formal state:
  `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Formal attempts: 12
- `baseline_history`: 19 entries, ending at diagnostic-capability PR #96

ADR 0032 design PR #95 passed push attempt 2, pull-request and protected-main
Runs `32858328460`, `32859688307` and `32860487073`, each 8/8, and Squash
Merged as `2c9d7debb2ba176f0688138d9519dca8805b5a6c`. Diagnostic-capability PR #96
passed push, pull-request and protected-main Runs `32874073910`, `32874795456`
and `32875417540`, each 8/8, and Squash Merged as the protected main above.
Neither changes product source or formal evidence.

The eleventh formal run remains M2. All workload stages, Outbox and
zero-tolerance controls passed; the only failed control was API cgroup recovery
ratio `1.417200 > 1.10`, from baseline/recovery/peak
`262144000/371510477/436941619` bytes. No accepted owner exists.

ADR 0030 rejected the first Gate-C-12 profiling protocol after Measurement
returned HTTP 500. Package SHA256 is
`99d6fb8ed47950ea142def94c2fd3a6388ec0091e517ee6737ad5d2cdff7d423`.
Do not derive an owner from it.

## D0 And Capability Closure

D0 is complete. All six required artifacts are accepted by PR #95: S/R/P/F
and A/M/A' variable matrix, interference formulas and zero-tolerance controls,
mutually exclusive ledger, strong/weak attribution rules and multi-owner
cutoff, failure exits, and evidence/image/cleanup contract. PR #96 implements
only that bounded diagnostic scope. Accepted ADR 0032 remains immutable.

This closure authorizes diagnostic calibration only. Product remediation,
PreflightSmoke, formal Gate C and Gate D-G remain locked. No owner may be
inferred from tooling availability or the rejected ADR 0030 package.

## D1 Capacity Gate

The latest manifest-driven cleanup receipt is
`D:\CyberControlAcceptance\phase7\gate-c\diagnostics\gate-c12-capacity-cleanup-20260825T171029Z\cleanup-receipt.json`,
SHA256 `cb28d0eedaf1987329469edbb5e8395ef3ed7dedba8d4e78e21382260f3317ed`.
Its pre-cleanup manifest SHA256 is
`eff7be833b5e4c0efca35598c48c0b4b687a5ad89262495f27d55c24c12d0029`.
No prune, formal-volume deletion, evidence-image deletion or stop of the five
development containers occurred.

D: has `10.823 GiB` free, below the `15 GiB` admission floor. D1 is
`INFRA_ABORTED_CAPACITY`. Do not build images or run any calibration until
drive D has at least `15 GiB` free and the protected-main/environment checks pass
again. The same proven infrastructure cause may be retried at most twice and
does not consume a design-failure slot or append `gate_c_attempts`.

After capacity admission, fetch current `origin/main`, create a new exact-main
isolated worktree, and build a source-bound all-service normal image lock plus
the separate diagnostic image role. Verify every digest before execution.

## Exact D1 Diagnostic Scope

The connection-churn harness uses 2,000 real TLS PostgreSQL connections per
arm, maximum concurrency 200 and fixed admission rate 50/s. Each variable uses
fresh matched A/M/A' resources:

- `S`: signal/event-loop delivery with verified mallctl no-op.
- `R`: `prof.reset` only.
- `P`: `prof.active=true` only, without reset.
- `F`: reset plus activation, only after S/R/P independently pass and evidence
  requires the combination.

Implement L0 passive ledger first. L1 bounded inventory and L2 sampled
profiling are separate probe levels; both require a 200-connection A/M/A'
interference pass before escalation. L1, L2, tracemalloc, GC object scans,
task/frame stacks and heavy checkpoints are pairwise exclusive. L0 alone may
accompany one active probe.

Every valid calibration requires:

- A/A' drift no more than 10% for connection p95, delivery p95, CPU p95 and
  event-loop lag p95;
- M/control median no more than 1.10 for the same metrics;
- RSS interference no more than `max(8 MiB, 10% of control RSS delta)`;
- completeness 1.0 for the micro harness and at least 0.95 for real API/L1;
- two independent matched passes before attribution use;
- zero HTTP 5xx, Bad address, loss, duplicates, leakage, invalid cursors,
  Outbox DEAD, pool timeout, OOM, restart or terminal lifecycle ownership.

Check zero-tolerance controls before performance. Any zero-tolerance failure
stops interpretation and A'.

## Attribution Boundary

Use the physical partition:

```text
RssAnon = jemalloc_allocated
        + (jemalloc_active - jemalloc_allocated)
        + (jemalloc_resident - jemalloc_active)
        + (RssAnon - jemalloc_resident)
```

Report `RssFile` and `RssShmem` separately and bridge process RSS, other
processes, file cache and kernel memory to cgroup `memory.current`. Python,
pool, cache, task, subscriber and replay ownership are overlays and must not be
added to the physical partition.

Strong admission requires at least 90% explanation, unknown bytes no more than
`min(10%, 8 MiB)`, two independent reproductions and the ADR 0032 sampled-stack
conditions when L2 is used.

Weak admission requires one owner at least 70%, category-known residual, no
lifecycle anomaly and conservative compliance using the lower of two measured
improvements minus noise. It also requires a new numbered append-only
ADR-0032 weak-admission addendum. That separate docs/evidence PR must include
residual classes/ratios, full calculation and two run IDs, summary paths and
package SHA256 values; only explicit `WEAK_ADMISSION_APPROVED`, Squash Merge
and protected-main 8/8 authorize remediation. Do not edit accepted ADR 0032.

If multiple owners exist, remediate the largest first and remeasure. Stop when
the conservative residual meets 1.10; do not change secondary owners merely
to increase explanatory completeness.

## Stops, Capacity And Evidence

- `DESIGN_REJECTED` means probe design/calibration cannot produce trustworthy
  data. ADR 0030 is design failure one; ADR 0032 failure is the second and
  final design failure under this process.
- `OWNER_UNRESOLVED` means data is trustworthy but no owner meets strong or
  weak admission. It is not design failure, but it stops product modification.
- `INFRA_ABORTED` means independently proven image, environment, Docker, disk
  or network failure. Retry the interrupted level for the same cause at most
  twice; a third abort requires an infrastructure report. It never appends
  design-failure count or `gate_c_attempts`.

Capacity remains 15/8/5 GiB. Before every round require at least 15 GiB free.
After every round, archive and verify the package, then mandatorily remove only
that round's temporary containers, network, PostgreSQL volume and archived
intermediate logs. Confirm zero project resources and restored admission
space before continuing. Below 8 GiB only manifest-proven unreferenced
temporary cleanup is allowed; below 5 GiB stop gracefully. Never prune or
delete historical formal volumes, core images or immutable evidence.

Normal image lock covers backend, frontend, migrate, provider, load generator
and supporting services. Diagnostic API uses a separate image role and digest.
Any normal service digest mismatch is `INFRA_ABORTED`. Diagnostic images may
not impersonate formal protected-main images.

Every diagnostic package records process version, dual baseline, source tree,
frozen hashes, environment, image locks, run ID, variable, samples, ledger,
controls, decision, redaction, manifest, package SHA256/reference and cleanup
receipt. Diagnostics, preflight, rollback and infrastructure aborts do not
append `gate_c_attempts`.

## Remediation And Formal Boundary

No remediation is allowed without strong admission or the merged weak
addendum. A future remediation uses a new exact-main
`codex/phase7-gate-c-twelfth-p2-<owner>-remediation` branch, one owner and one
ownership mechanism per PR, a behavior ADR, test-layer A/B/A' and all semantic
and quality gates.

Fresh validation is PreflightSmoke 20, then independent 200/500/1,000. Stop
before escalation if a zero-tolerance item fails, peak RSS exceeds matched
control by 10%, recovery residual exceeds control by 15%, or actual residual
exceeds 130% of the remediation ADR's conservative prediction. Do not run a
non-formal 2,000 diagnostic before Full.

Only after remediation, three CI chains 8/8 and fresh gradients pass may one
formal Full run execute 20/200/500/1000/2000 plus recovery. Only that Full may
append attempt 13. M3 and Gate D readiness require every frozen control in the
same run, immutable Release evidence, evidence PR merge and protected-main
8/8.

Do not modify migrations 0001-0010, RLS, `TenantContext`, SERIALIZABLE, C12,
identity derivation, Outbox atomicity, idempotency, partition order, threshold,
workload, timeout, grace period or aggregation. Force GC, restart, allocator
purge, pool disposal, periodic clearing, background janitors and inflated
baselines are prohibited. Gate D-G remain locked.
