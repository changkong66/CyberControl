# Gate C Eleventh P2 Root-Cause Round 2

Process Version: `Gate-C-11-v1.0`

## Decision

Round 2 does not establish an actionable memory owner and does not authorize a
behavior change. Together with the rejected round-1 allocator-domain
hypothesis, this is the second unsuccessful P2 root-cause round. The process
rule therefore freezes P2 code modification and requires a new measurement
design before another candidate is allowed.

This diagnostic is not a formal Gate C attempt. It used a real 200-stream
stage, real Keycloak issuance, two tenants, twenty provisioned subjects, a
unique Compose project and a fresh PostgreSQL volume. The existing opt-in
memory sampler ran from process start, after a 300-second idle window, through
load and a separate 600-second recovery monitor.

## What The Data Proves

The baseline-to-recovery cgroup ratio was `1.222468`; process RSS ratio was
`1.185522`. RSS and anonymous RSS both grew `45,223,936` bytes while file RSS
was unchanged. USS/PSS grew `45,363,200/45,302,784` bytes. The residual is
private anonymous process memory, not a file-cache artifact.

Jemalloc allocated bytes grew `24,484,432`; its active-minus-allocated gap
grew `19,338,672`. Their sum is `43,823,104`, or `96.9025%` of the RSS delta.
Resident bytes grew `44,998,656`. The same accounting shape exists in the
formal 2,000-stream failure, where allocated growth plus gap growth explains
almost all anonymous RSS growth. This proves the remaining memory is visible
inside the configured process-start jemalloc arena as a combination of live
allocation and size-class/page slack.

It does not prove which application or library owner keeps the live allocation.
Tracemalloc current bytes grew only `7,173,112`, or `15.8613%` of RSS growth.
The sampler logged only the eight largest absolute groups and stored
`traceback[0]` rather than a full baseline-to-recovery traceback diff. The
largest changing record resolved to the long-lived Click invocation frame;
that is an outer ownership path, not a safe modification target.

## Lifecycle Disproofs

The following peak inventories all returned to zero:

| Inventory | Peak | Recovery final |
| --- | ---: | ---: |
| SSE subscribers | 200 | 0 |
| Owned streaming responses | 200 | 0 |
| Tenant-scoped streams | 200 | 0 |
| SSE subscriptions | 200 | 0 |
| Starlette requests | 402 | 0 |
| Uvicorn request cycles | 210 | 0 |

Asyncio tasks returned from `1,217` to the baseline `18`; task frames returned
from `1,224` to `25`. Queue and replay-task gauges remained zero. These results
disprove leaked SSE request/task/frame ownership as the material terminal
owner under this diagnostic. They do not prove the absence of library caches,
allocator metadata or untraced native allocations.

FDs ended at `29`, compared with a pre-stage sample of `21`; `29` matches the
stable terminal value in all three round-1 arms. The lower baseline was taken
before all long-lived listeners had reached their normal high-water state, so
the eight-descriptor delta is recorded but not claimed as an FD leak.

## Measurement Side Effects And Anomalies

The diagnostic sampler itself is too expensive for acceptance performance
claims. At peak it inspected `403,733` tracked objects and `1,217` tasks. A
sample incurred up to about `0.6` seconds of measured event-loop lag; full
samples took multiple seconds because object enumeration and tracemalloc
snapshot aggregation hold the GIL for substantial intervals. The diagnostic
stage therefore failed connection/sustain latency controls. This is expected
measurement interference and cannot be interpreted as a product regression or
as Gate C evidence.

The API database-pool gauge changed from zero to `-2` and remained there even
though PostgreSQL showed idle application connections and no pool timeout. A
negative checked-out gauge is invalid observation state. It prevents this run
from using that gauge as pool-return proof, but it does not establish retained
connection ownership. This anomaly requires a separate deterministic
observability investigation before the gauge is used in a future memory
experiment; it is not folded into an RSS candidate.

The database terminal state remained safe: migration `20260720_0010`, FORCE
RLS `74/74`, append-only triggers `57`, foreign-tenant visibility `0`, Outbox
`PUBLISHED=26`, and terminal `PENDING/CLAIMED/DEAD=0`. One PostgreSQL
serialization failure was retried under the existing SERIALIZABLE contract;
the stage recorded no workflow failure or pool timeout.

## Why No Candidate Is Permitted

Round 1 disproved `PYTHONMALLOC=malloc` as the material owner: changing the
small-object allocator domain moved accounting but did not materially reduce
total cgroup or RSS retention. Round 2 localized the residual to jemalloc
live allocation plus bin/page slack and disproved terminal SSE task ownership,
but its bounded absolute snapshots cannot identify the retaining code path.

Disabling SQLAlchemy or asyncpg caches, changing pool behavior, adding an
allocator purge, or changing jemalloc decay would each be a new unproven
variable. None is supported by a delta ownership trace in this evidence. The
project rules prohibit submitting such a speculative candidate, force-GC,
recovery-only trim, restart recovery, baseline changes or threshold changes.

## Required New Measurement Design

No implementation may start until a new root-cause report defines and reviews
a bounded, lower-interference design that can provide all of the following:

1. Baseline and recovery tracemalloc snapshots compared by complete innermost
   allocation traceback, with aggregate deltas rather than absolute top-N data.
2. Jemalloc allocation profiling or bin/extent deltas captured from process
   start, with profiler overhead measured independently.
3. Explicit inventories for SQLAlchemy compiled cache, asyncpg statement
   caches, connection-pool members, cursor encoder cache and Prometheus label
   state at the same timestamps.
4. A deterministic pool-gauge balance regression before the gauge is accepted
   as lifecycle evidence.
5. A control proving the profiler itself does not create the measured residual
   or materially distort the target workload.

This is a measurement specification, not authorization for a third P2
candidate. A new root-cause round requires explicit continuation after the
P2 freeze is acknowledged.

## Evidence Index

- Diagnostic run:
  `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c-11-p2-round2/gate-c-diagnostic-20260823T183106Z-b4eff6516601`
- Structured comparison: `round2-comparison.json`
- Source: `b4eff6516601412d995d3e119dbb7b148d820684`
- Source tree: `e69fbd56e02613c2ce48a7d2cc3a4404b972422e`
- Preserved PostgreSQL volume:
  `cybercontrol_gate_c_11_p2_round2_diag_20260824`
- Package reference: `round2-package-reference.json`
- Immutable package SHA256:
  `554dc9991f8844fb7193d8fefb8fee292e97f208dbc699c869e94e8320403498`
- Immutable Release:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-round2-20260824-v1

The formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; Gate D-G remain
locked. No formal replay, acceptance decision or Gate D work was started.
