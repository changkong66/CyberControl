# ADR-0033: Gate C Twelfth Domain-Separated RSS Attribution

Process Version: `Gate-C-12-v2.0`

- Status: Candidate until Squash Merge and protected-main quality gates pass 8/8
- Date: 2026-09-02
- Decision domain: non-acceptance P2 diagnostic governance and measurement
- Product source SHA: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Engineering parent SHA: `841020d0f97737adf925950792f3bb4f0dc8df2e`
- Engineering parent tree: `d5e07269d971236674e48d2d7bee99c1bf131d3b`
- Protected-main parent CI: `33540046732`, 8/8
- Supersedes: ADR-0032 measurement equation and diagnostic stop only

## Context

ADR-0032 correctly stopped after its D1/S control arm completed 2,000 TLS
connections but produced an invalid physical partition. At recovery,
`RssAnon=57323520` and `jemalloc resident=57675776` yielded a signed difference
of `-352256` bytes. The result was `DESIGN_REJECTED`, design-failure ordinal 2,
and no RSS owner was established.

The rejected equation assumed that jemalloc `stats.resident` was a strict
physical subset of Linux `RssAnon`. That assumption is not valid. Jemalloc
refreshes allocator accounting through an epoch and reports allocator-owned
mapped/resident accounting, while Linux reports page residency from a
different subsystem and at a different instant. Mapping semantics, lazy page
state, metadata and sampling skew can make either counter larger without
implying corrupt data or a product leak.

This ADR starts a separately versioned governance cycle. It does not rewrite
ADR-0032 or its evidence. It authorizes implementation and calibration of one
replacement measurement contract only after this PR is merged and
protected-main CI passes 8/8. It does not authorize product remediation,
PreflightSmoke, a formal Full run or Gate D-G.

## Decision

Replace the false cross-domain physical partition with three orthogonal
ledgers. Values from different ledgers are never added together and a signed
cross-domain difference is never treated as an owner.

### Cgroup Physical Ledger

The formal residual remains cgroup v2 `memory.current`. The bounded diagnostic
records these top-level explanatory counters from the same cgroup:

```text
cgroup_current
cgroup_anon
cgroup_file
cgroup_kernel
cgroup_unclassified_signed = current - anon - file - kernel
```

`sock`, `slab`, page tables and kernel stack are reported as non-additive
drill-downs because they can be included in a top-level category. The signed
unclassified term is a reconciliation signal, not automatically an error.

### Linux Process Ledger

The API process lane records `VmRSS`, `RssAnon`, `RssFile`, `RssShmem`, PSS,
USS, swap, FD count and map count. The same `/proc/self/status` read provides
the RSS components. The process reconciliation is:

```text
process_rss_reconciliation_signed = VmRSS - RssAnon - RssFile - RssShmem
```

At L1, `/proc/self/smaps` mappings are classified into mutually exclusive VMA
classes such as heap, stack, named anonymous, unnamed private anonymous,
file-backed private and shared mappings. VMA classes partition Linux mapping
RSS only; they do not claim allocator ownership.

### Jemalloc Accounting Ledger

After one explicit epoch refresh, the allocator lane records `allocated`,
`active`, `resident`, `mapped`, `metadata`, `retained` and arena count. Only
same-domain identities are enforced:

```text
allocator_slack = active - allocated
allocator_resident_gap = resident - active
allocated + allocator_slack = active
active + allocator_resident_gap = resident
```

`mapped`, `metadata` and `retained` remain explanatory counters and are not
added to `resident` without a documented jemalloc identity.

### Cross-Domain Comparison

The package reports `jemalloc_resident_minus_rss_anon_signed`, together with
both source intervals and the sampling uncertainty. It is explicitly
`NON_ADDITIVE_CROSS_DOMAIN`. Negative or positive values do not invalidate a
snapshot. They cannot satisfy strong or weak owner admission by themselves.

## Bounded Bracketed Sampling

Variable `D` calibrates the replacement domain snapshot. A Measurement arm
captures five samples; A and A' retain the existing minimal control capture.
Every Measurement sample uses this fixed order:

```text
t0 -> process_before -> cgroup_before -> jemalloc_epoch_and_stats
   -> cgroup_after -> process_after -> t1
```

Samples are separated by 50 ms. Each sample must complete within 250 ms and
the full five-sample burst within 2 seconds. A domain value is the median of
the five samples. The package also records minimum, maximum, median absolute
deviation and the before/after bracket. No timestamp is fabricated as an
atomic cross-subsystem read.

A sample is structurally invalid only when:

- the PID, cgroup, source or image binding changes;
- a required same-domain counter is missing or negative;
- `allocated > active` or `active > resident`;
- the process RSS reconciliation exceeds `max(1 MiB, 2% of VmRSS)`;
- a sample exceeds 250 ms, the burst exceeds 2 seconds, or required sample
  count is not five;
- the within-burst spread for cgroup current or process RssAnon exceeds
  `max(8 MiB, 10% of its median)` at an idle or recovery window;
- evidence integrity or a zero-tolerance control fails.

Cross-domain disagreement is not in this list.

## D1 Calibration

D1 executes two independent `A / D / A'` sequences. Every arm uses 2,000 real
TLS PostgreSQL connections, maximum concurrency 200, admission rate 50/s,
five-minute idle and ten-minute recovery. Every arm has a fresh Compose
project, network and PostgreSQL volume and is archived and destroyed before
the next arm starts.

The existing interference formulas remain frozen:

- A/A' control drift for connection p95, delivery p95, CPU p95 and event-loop
  lag p95 is at most 10%;
- D/control median for those metrics is at most 1.10;
- RSS interference is at most `max(8 MiB, 10% * abs(control RSS delta))`;
- sample completeness is exactly 1.0;
- all zero-tolerance controls are zero.

Both independent sequences must pass. One passing sequence is insufficient.

## D2 Attribution Boundary

D2 first explains the formal cgroup recovery delta by the cgroup physical
lane. Process and allocator lanes then provide non-additive evidence for the
dominant cgroup category. An owner requires a causal, source-bound signal in
two independent runs, such as a lifecycle count, VMA class, bounded inventory
or sampled allocation stack moving with the cgroup residual.

Strong admission still requires at least 90% explained residual and unknown
bytes no greater than `min(10% residual, 8 MiB)`. Weak admission still
requires one actionable owner of at least 70%, known remainder classes, no
lifecycle anomaly and a separately merged append-only ADR approval. Sampling
uncertainty is counted as unknown, never subtracted to improve admission.

When several owners are proven, only the largest owner is eligible for the
first remediation. Remeasure after that remediation and stop if the frozen
1.10 target is conservatively satisfied.

## Failure State Machine

- `DESIGN_REJECTED`: same-domain invariant, bounded-sampling, interference or
  evidence-integrity failure. One structural failure stops new design under
  `Gate-C-12-v2.0`.
- `OWNER_UNRESOLVED`: trusted measurements complete but no owner meets strong
  or weak admission. It does not authorize product modification.
- `INFRA_ABORTED`: independently proven Docker, image, environment, storage or
  network interruption. The same cause may retry the interrupted level at
  most twice and never increments `gate_c_attempts`.

The sequence wrapper must preserve the child `reason` when present and use a
stable fallback when absent. A wrapper exception must not mask the primary
classification.

## Evidence And Compatibility

Every new artifact records `Gate-C-12-v2.0`, exact source/tree, frozen input
hashes, dual image lock, build receipt, sample order and timestamps, raw
samples, three ledgers, uncertainty, decision, redaction result, package hash
and cleanup receipt. Historical v1 artifacts remain unchanged and keep their
original process version.

The implementation is diagnostic-only and default-off. Existing metric names,
labels and formal Gate C aggregation remain unchanged. The formal workload,
threshold, recovery window and API cgroup metric remain frozen at SHA256
`38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`,
`d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
and ratio limit 1.10.

## Red Lines

This ADR does not modify migrations 0001-0010, RLS, TenantContext,
SERIALIZABLE transactions, C12 authorization, Outbox atomicity, idempotency,
partition order or product contracts. It does not authorize forced GC,
allocator purge, `malloc_trim`, process restart, janitors, threshold changes,
baseline inflation or longer recovery. `gate_c_attempts` remains 12 and Gate
D-G remain locked.

## Exit

After this ADR and its structured record are Squash Merged and protected-main
CI passes 8/8, only the exact diagnostic implementation and D1 `D`
calibration are authorized. D2 remains locked until two independent D1
sequences pass. Product remediation remains locked until an owner satisfies
the applicable admission rule.
