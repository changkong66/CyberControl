# ADR-0032: Gate C Twelfth Low-Interference RSS Attribution

- Status: Accepted only after this record is Squash Merged and protected-main
  Release Quality Gates pass 8/8
- Date: 2026-08-25
- Process version: `Gate-C-12-v1.0`
- Decision domain: non-acceptance P2 diagnostic design
- Product source SHA: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Engineering parent SHA: `5ae8637c46c741c8b6f079e22af3e2517bac7bb9`
- Engineering parent tree: `9c478ed3c22debf65fe3eb4fef92ee58982f233f`
- Protected-main parent CI: `32834020352`, 8/8
- Supersedes: no accepted behavior decision; follows rejected diagnostic ADR-0030

## Context And Decision Boundary

The eleventh formal Gate C attempt completed the frozen workload and failed
only API cgroup memory recovery: baseline `262144000`, recovery `371510477`
and peak `436941619` bytes produced ratio `1.417200 > 1.10`. Reaching the
frozen limit requires at least `83152077` bytes of verified recovery reduction
when calculated against that run. This is a sizing reference, not an owner
claim.

ADR-0030 rejected the first Gate-C-12 profiling activation protocol after its
Measurement arm returned HTTP 500 at `asyncpg -> ssl.load_cert_chain` about
10.231 seconds after activation. That evidence proves the protocol
inadmissible. It does not prove jemalloc, TLS, asyncpg or any product owner
caused either the HTTP 500 or the formal RSS residual.

This decision authorizes one final low-interference diagnostic design. It does
not authorize diagnostic execution until this document's PR is Squash Merged
and protected-main CI passes 8/8. It does not authorize a product fix,
PreflightSmoke, a formal Gate C attempt or Gate D-G.

ADR-0030 is design failure one. A structural failure of this design is design
failure two and ends new diagnostic-design work under `Gate-C-12-v1.0`.
Trusted but inconclusive data is `OWNER_UNRESOLVED`, not a design failure.

## D0 Authorization Checklist

D0 is complete only when all six artifacts below are present in this ADR and
the structured design record, reviewed in one docs-only PR, Squash Merged and
followed by protected-main CI 8/8:

1. S/R/P/F and A/M/A' variable matrix.
2. Exact interference formulas and zero-tolerance controls.
3. Mutually exclusive memory-ledger definitions.
4. Strong and weak attribution admission plus multi-owner cutoff.
5. `DESIGN_REJECTED`, `OWNER_UNRESOLVED` and `INFRA_ABORTED` paths.
6. Evidence, package, image-lock and cleanup contract.

Missing any item keeps diagnostics locked. A branch, local test, push CI or PR
CI alone cannot satisfy D0.

## Variable Matrix

The first calibration uses a diagnostic-only connection-churn harness with the
same Python, SQLAlchemy, asyncpg, TLS, DSN, jemalloc build and runtime user as
the API. Every arm creates 2,000 real TLS PostgreSQL connections at a fixed
maximum concurrency of 200 and admission rate of 50 connections per second.
Every arm uses an independent Compose project, network, run directory and
fresh PostgreSQL volume.

Each variable is tested as matched `A / M / A'`: A and A' execute the same
workload with the variable inactive, while M changes only the declared
variable. A' is prohibited after any zero-tolerance failure.

| ID | M-arm variable | Inactive controls | Single-variable purpose | Entry rule |
| --- | --- | --- | --- | --- |
| S | deliver the profiling control signal through the event loop, with a verified mallctl no-op | no signal | isolate signal and scheduling effects | first |
| R | execute only `prof.reset` | no reset | isolate reset and allocator bookkeeping | only after S passes |
| P | execute only `prof.active=true`, without reset | profiling inactive | isolate sampling activation | only after S passes |
| F | execute `prof.reset` then `prof.active=true` | both inactive | validate the required combined protocol | only if S, R and P independently pass and evidence requires F |

No arm may change application routes, connection settings, TLS material,
allocator configuration, workload rate, timeout or recovery duration. A
failed variable is not combined with another variable to search for a pass.

The later diagnostic levels are:

- `L0 passive-ledger`: cgroup v2 memory files, `/proc` status/smaps_rollup/maps,
  FD counts, existing lifecycle gauges and existing pool/cache counters.
- `L1 bounded-inventory`: bounded jemalloc bin/extent summaries and bounded
  pool/cache/lifecycle inventory, with no object-graph or stack traversal.
- `L2 sampled-profile`: sampled jemalloc live allocation stacks with exact
  library digest and build ID.

L1 must pass its own 200-connection A/M/A' calibration before use at 500 or
1,000. L2 may start only after the S/R/P/F boundary required by its activation
protocol passes. `tracemalloc`, GC object scanning, task/frame stack capture,
heavy checkpoints and L2 sampled profiling are pairwise mutually exclusive.
Only L0 may accompany any one active probe. L1 and L2 are never enabled
together.

## Interference Gate

For scalar metric `x`, define:

```text
control_median(x) = median(A(x), A'(x))
control_drift(x) = abs(A(x) - A'(x)) / max(abs(control_median(x)), epsilon(x))
measurement_ratio(x) = M(x) / max(control_median(x), epsilon(x))
rss_interference = abs(M(rss_delta) - control_median(rss_delta))
rss_limit = max(8388608, 0.10 * abs(control_median(rss_delta)))
```

`epsilon` is fixed before execution: 1 ms for latency and event-loop lag and
0.01 one-core units for CPU. It prevents division by zero; it is not fitted to
results. For a zero-valued event-loop-lag control, M may add no more than 1 ms.

All conditions must pass:

- A/A' control drift for connection p95, delivery p95, API CPU p95 and
  event-loop lag p95 is at most 0.10.
- M/control median for the same metrics is at most 1.10.
- RSS interference is at most `rss_limit`.
- Micro-harness sample completeness is exactly 1.0; real API and L1
  calibration completeness is at least 0.95.
- Two independent matched runs reproduce a probe's pass before its data may
  support attribution.

The following are zero tolerance: HTTP 5xx, `Bad address`, committed event
loss, duplicate final render, cross-tenant leakage, invalid cursor acceptance,
Outbox `DEAD`, pool timeout, OOM, unplanned restart, semantic-regression test
failure, nonzero terminal subscriber/queue/replay/task/pool ownership and
evidence-integrity failure. Each level checks zero-tolerance controls before
performance. Any failure stops that arm and prohibits interpretation.

## Mutually Exclusive Memory Ledger

All snapshots use one synchronized monotonic timestamp and the same API PID
and cgroup. A snapshot with scope mismatch, counter reset, negative partition
or missing required input is invalid rather than coerced.

The physical API-process anonymous-memory partition is:

```text
allocator_payload       = jemalloc_allocated
allocator_slack         = jemalloc_active - jemalloc_allocated
allocator_resident_gap  = jemalloc_resident - jemalloc_active
non_jemalloc_anon       = RssAnon - jemalloc_resident
RssAnon                 = allocator_payload
                        + allocator_slack
                        + allocator_resident_gap
                        + non_jemalloc_anon
```

`RssFile` and `RssShmem` are reported separately. A cgroup bridge separately
reconciles API PID RSS, other process RSS, cgroup file cache, kernel memory and
a signed reconciliation residual to `memory.current`. Formal acceptance always
uses the frozen API cgroup ratio; process RSS/USS/PSS are attribution aids.

Python objects, tasks/frames, HTTP/DB pools, metric state, legal caches,
subscriber queues and replay buffers are ownership overlays on
`allocator_payload`; they are never added to the physical partition. Each
overlay object has one owner key and lifecycle state. The package reports both
physical bytes and logical ownership without summing them together.

Each accepted diagnostic records three windows: five-minute stable idle,
the final minute of the selected load level and ten-minute recovery. Deltas
use the same statistic and timestamp policy in every matched arm.

## Layered Attribution

Diagnostics advance from L0 to L1 to L2 and from 200 to 500 to 1,000 only.
There is no non-formal 2,000-connection diagnostic before the next Full Gate C
attempt. Each level uses fresh resources and must archive and clean up before
the next level starts.

The diagnostic first classifies the formal residual among Python-owned live
payload, native allocator slack/fragmentation, middleware/pool/cache high
water, non-jemalloc anonymous mappings and cgroup-only residual. It then
selects only the lowest-cost probe capable of splitting the dominant category.
Batch disconnect, timeout/cancellation and bounded connection surge may be
tested one at a time after the normal lifecycle run; each is a separate
A/M/A' variable and cannot alter the frozen formal workload.

### Strong Admission

Strong admission requires all of:

- at least 90% of recovery residual bytes reconciled by the mutually exclusive
  physical ledger;
- truly unknown bytes at most `min(10% of recovery residual, 8388608)`;
- one actionable owner reproduced in two independent matched runs;
- for L2, at least 90% of sampled bytes resolve above jemalloc and the
  candidate stack has at least ten independent samples and at least 20% of
  sampled live bytes;
- a positive, evidence-derived conservative reduction and recovery prediction.

### Weak Admission

Weak admission is permitted only when:

- one actionable owner accounts for at least 70% of recovery residual in two
  independent matched runs;
- all remaining bytes are classified allocator/kernel alignment,
  fragmentation or legitimate stable high water, not missing or corrupt data;
- no growing object, task, FD, pool, subscriber or lifecycle anomaly remains;
- the lower measured owner reduction across the two runs, minus the declared
  measurement-noise bound, conservatively predicts compliance with 1.10.

Weak admission is not a runtime discretion. It requires a new numbered,
append-only `ADR-0032 Weak-Admission Addendum` in a separate docs/evidence PR,
expected to be ADR-0033 if no earlier record consumes that number. The addendum
must reference this ADR and supersede only its admission decision; this
accepted file remains immutable. It must record residual classes, bytes,
percentages, stable reproduction, the complete conservative-reduction formula
and inputs, and two run IDs, summary paths and package SHA256 values. Only an
explicit `WEAK_ADMISSION_APPROVED` decision, Squash Merge and protected-main
8/8 authorize remediation. A PR comment or verbal approval is insufficient.

### Multi-Owner Cutoff

When several owners are proven, fix only the largest owner first. Rebuild the
fresh ledger after its independent remediation merges. If the remaining
conservative residual satisfies 1.10, stop and do not modify secondary owners.
Otherwise process the next owner by descending share in a separate PR. Owners
must never be combined into one remediation variable.

## Remediation And Prediction Boundary

Any admitted remediation uses
`codex/phase7-gate-c-twelfth-p2-<owner>-remediation`, based on exact current
protected main. One PR changes one ownership mechanism and includes a new
behavior ADR, impact matrix and test-layer A/B/A' evidence. Positive release
tests and negative cancellation, timeout, abnormal disconnect, double-close,
pool/session return, FD, tenant isolation, idempotency, ordering and Outbox
atomicity tests remain mandatory. Push, PR and main CI must each pass 8/8 and
Python coverage must remain at least 90%.

The remediation ADR must state positive
`predicted_recovery_residual_bytes`. At each fresh 200/500/1,000 validation:

```text
prediction_deviation_ratio =
  actual_recovery_residual_bytes / predicted_recovery_residual_bytes
```

If the actual residual exceeds `1.30 * predicted_recovery_residual_bytes`,
stop and return to attribution. Also stop if matched peak RSS exceeds its
control by more than 10% or recovery residual exceeds its control by more than
15%. Zero-tolerance controls are evaluated first.

Force GC, pool disposal, allocator purge, `malloc_trim`, process restart,
background janitors, periodic clearing, prewarming to inflate baseline,
cache-limit changes without ownership evidence and changes to threshold,
workload, timeout, grace period or aggregation are prohibited.

## Outcome State Machine

- `DESIGN_REJECTED`: calibration interference, unstable probe or structural
  inability to produce trustworthy data. It consumes the second and final
  design-failure slot. Archive evidence and stop new designs.
- `OWNER_UNRESOLVED`: probes ran within gates but no actionable owner met
  strong or weak admission, or residual is legal stable high water with no
  defect. It does not consume a design-failure slot. Archive a composition
  report and stop product modification; threshold changes are outside this
  process and are not implicitly authorized.
- `INFRA_ABORTED`: image mismatch, Docker/environment drift, disk or network
  fault unrelated to product behavior. It does not alter design count,
  attribution count or `gate_c_attempts`. After correcting the same cause,
  retry only the interrupted level at most twice. A third same-cause abort
  stops work and requires an infrastructure report.

An instrumentation crash is `DESIGN_REJECTED`, not `INFRA_ABORTED`, unless
independent evidence proves an external infrastructure cause. Diagnostic
design failure and owner non-resolution therefore cannot be interchanged to
evade either stop rule.

## Image And Evidence Contract

Normal images use the all-service lock for backend, frontend, migrate,
provider, load generator and supporting services. The diagnostic API has a
separate role and digest derived from the same source and normal backend build
inputs. Every manifest records `{source_sha, product_source_sha, image_role,
build_receipt_sha256, digest}`. A diagnostic image cannot be labeled or used
as protected-main formal input. Preflight and Full use the same verified normal
all-service digests; any mismatch is `INFRA_ABORTED`.

Every run directory contains process version, run ID, classification, dual
baseline, source tree, frozen input hashes, normal and diagnostic locks,
environment fingerprint, variable matrix, monotonic timestamps, raw samples,
ledger, controls, decision, redaction result, manifest, package SHA256,
package reference and cleanup receipt. Formal attempts alone append
`gate_c_attempts`.

After every diagnostic or validation round, first archive and verify the
redacted package and repository reference, then remove that round's temporary
containers, network, PostgreSQL volume and archived intermediate logs. Verify
zero project resources remain and D: again meets the 15 GiB admission floor
before starting the next round. Below 8 GiB only manifest-proven unreferenced
temporary resources may be removed; below 5 GiB stop gracefully. `docker
prune`, historical formal-volume deletion, core-image deletion and evidence
rewrite are permanently prohibited.

## Evidence Index

- Structured D0 design:
  `docs/diagnostics/phase7-gate-c-twelfth-p2/adr0032-design-authorization.json`
- ADR-0030 rejection:
  `docs/adr/0030-phase7-gate-c-12-jemalloc-calibration-rejection.md`
- Structured rejection:
  `docs/diagnostics/phase7-gate-c-twelfth-p2/calibration-rejection.json`
- Rejected package reference:
  `docs/diagnostics/phase7-gate-c-twelfth-p2/package-reference.json`
- Rejected package SHA256:
  `99d6fb8ed47950ea142def94c2fd3a6388ec0091e517ee6737ad5d2cdff7d423`
- Frozen threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`

No future diagnostic run, package, owner or result exists at D0. Such fields
must be appended by later evidence records and must not be fabricated here.

## Semantic Impact And Stop Rule

This is a docs-only measurement authorization. It does not modify migrations
0001-0010, RLS, `TenantContext`, SERIALIZABLE transactions, C12, identity
derivation, Outbox atomicity, idempotency, partition order, threshold,
workload, timeout, grace period or aggregation. It preserves product source
`a57d0ce...`, formal source `5fcb917b...`, M2, twelve formal attempts and
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

After D0 external closure, only implementation and calibration of this exact
design are eligible. No behavior remediation begins without strong admission
or a merged weak-admission addendum. No PreflightSmoke or Full begins before a
separately merged remediation and its complete CI chain. Gate D-G remain
locked even if Gate C later becomes eligible.
