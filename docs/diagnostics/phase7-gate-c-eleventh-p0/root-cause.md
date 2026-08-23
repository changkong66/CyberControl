# Gate C Eleventh P0 Root-Cause Record

Process Version: `Gate-C-11-v1.0`

## Scope

This record addresses only the tenth-run P0 boundary: smoke delivery p99
`6,850 ms`, monitor completeness `31/39`, and seven `/metrics` read timeouts.
It does not claim that stale ninth-run P1 Outbox or P2 RSS failures still exist.
The formal state remains `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

## Causal Evidence

The parent `PlatformMetrics.render()` synchronously initiated task-stack,
object-graph, tracemalloc snapshot, process-map, allocator, and Prometheus
serialization work on the API event loop. The immutable tenth-run timestamps
align all seven monitor timeouts with diagnostic windows lasting 10.24 to 12.19
seconds. Four publisher calls above 3 seconds also occurred within those
windows and account for exactly 40 client delivery observations above 3 seconds.

The deterministic test harness has Git blob
`98797e4daba3427dc9a1d1eebdd6b19aa41f2fa3`:

| Arm | Implementation | Passed | Failed | Exit |
| --- | --- | ---: | ---: | ---: |
| A | parent `16bab5d` | 9 | 5 | 1 |
| B | candidate `ea5ce1b` | 14 | 0 | 0 |
| A' | independent parent `16bab5d` | 9 | 5 | 1 |

A used the committed failing-test head `4ffe48e`, whose product implementation
remained the parent. B and A' loaded the same test blob over their respective
implementation heads. A' was a separate detached worktree, not a candidate
revert.

## Candidate Boundary

The candidate makes `/metrics` render the current registry without initiating
heavy heap diagnostics. One application-owned sampler performs diagnostics;
it cannot overlap itself and is cancelled and awaited first during coordinated
shutdown. Task inventory stays on the event loop and yields every 64 tasks;
object inventory, tracemalloc snapshot, and process-map reads run in a worker.
Completed values survive a failed sample while bounded success and staleness
gauges expose the failure.

All diagnostic value, stage, and outcome labels are allowlisted and fixed.
Tenant, subject, cursor, Token, event ID, and task name values cannot become
Prometheus labels. Scrape allocator refresh and registry rendering are measured
separately from diagnostic collection.

## Real Collector Measurement

The expanded candidate diagnostic retained 200,000 local objects with a
128-byte payload per object. This is an operation-level diagnostic and is not a
Gate C client-scale claim. Tracemalloc current memory was `44,929,512` bytes.
Collection took `4.3581012` seconds, of which the tracemalloc snapshot took
`4.2072045` seconds and object inventory took `0.1498891` seconds. A 5 ms
heartbeat produced 209 samples and observed maximum event-loop lag
`0.2290000` seconds.

This measurement disproves the assumption that moving work to a thread makes
GIL effects zero. It does show that total worker duration and event-loop delay
are distinct, now independently observable quantities. Fresh container Smoke
must still disprove delivery and monitor regressions under the real service heap.

## Stop Boundary

Deterministic A/B/A' proved the ownership defect, and the complete local quality
suite plus three independent fresh-resource Smoke scenarios subsequently
passed at candidate `97e1b75fff6c21418ad939edeaa9a0676c35c043`. This closes
M1 only and is not Gate C acceptance. Protected-main merge, post-merge CI,
disposable preflight and a fresh complete formal run remain required. Any
semantic, security, zero-tolerance, monitor, or delivery failure rejects the
formal run. Gate D-G remain locked.
