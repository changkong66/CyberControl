# Phase 7 Gate C Eleventh Replay Failure Analysis

Process Version: `Gate-C-11-v1.0`

## Evidence Binding

- Formal classification: `FORMAL_GATE_C_ATTEMPT`
- Product source and engineering baseline:
  `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Source tree: `f721fca017c247aee93765d5f11fcbc37e12fcfc`
- Run: `gate-c-20260823T144052Z-5fcb917b6388`
- Compose project: `gatec11formal5fcb917`
- Preserved PostgreSQL volume:
  `cybercontrol_gate_c_eleventh_5fcb917_20260823`
- Threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`

## Proven Result Boundary

All five unchanged stages completed and passed their stage controls:
`smoke-20` sustained 20 streams for 180 seconds, `ramp-200` sustained 200 for
304 seconds, `ramp-500` sustained 500 for 303 seconds, `ramp-1000` sustained
1,000 for 604 seconds, and `gate-2000` sustained 2,000 for 1,804 seconds. The
fixed ten-minute recovery observation also completed. This is milestone M2,
not Gate C acceptance.

The sole failed frozen final control was memory recovery. API cgroup memory was
262,144,000 bytes in the first 2,000-stage sample, 436,941,619 bytes at peak
and 371,510,477 bytes in the final recovery sample. The resulting ratio was
`1.417200`, above the frozen `1.10` maximum. Process RSS was
307,265,536/416,342,016/481,173,504 bytes at first/final/peak; USS was
295,247,872/405,143,552/468,893,696 bytes and PSS was
298,700,800/409,633,792/472,241,152 bytes. This run proves retained memory but
does not by itself identify Python heap, native allocator, mappings or another
owner. No forced collection, trim, restart, baseline change or aggregation
change was used.

The previously conditional P1 Outbox concern was disproved on this source.
Created-to-published p95/p99 was `1879.698/2898.555ms`, within the frozen
`2000/5000ms` limits. Terminal Outbox state was `PUBLISHED=226`, with no
`PENDING`, `CLAIMED` or `DEAD` row. No P1 code change is justified by this run.

At 2,000 streams, delivery p95/p99 was `758/1077ms`, monitor completeness was
`491/495=0.991919`, connection and reconnect/replay success were `1.0/1.0`,
and committed loss, duplicate final rendering, cross-tenant leakage, invalid
cursor acceptance, HTTP 5xx, unexpected disconnect, pool timeout, Outbox
`DEAD`, OOM and unplanned restart were all zero. Terminal subscriber, closing,
queue, replay-buffer, replay-cache and replay-task gauges were zero. API file
descriptors were 29/30/2038 at first/final/peak, with a final ratio of
`1.034483` and limit 1,048,576.

PostgreSQL remained at migration `20260720_0010`, FORCE RLS `74/74`, 57
append-only triggers and zero foreign-tenant visibility. Security probes
returned 401 for unauthenticated/invalid Token requests and 400 for tampered or
cross-tenant cursors; a valid cursor returned 200.

## Next Root-Cause Boundary

P2 may open because this current protected-main formal run proves Outbox passed
while the unchanged recovery RSS ratio failed. The next remediation must remain
single-variable and first distinguish reachable Python objects, task/frame or
exception retention, metric state, HTTP/DB pools, serialization buffers,
subscriber/replay lifecycle, memory mappings and native allocator behavior.
The disproof metric remains API cgroup recovery memory `<=1.10` of the frozen
first 2,000-stage sample after the unchanged ten-minute recovery, with all
terminal lifecycle gauges at zero and every passed control preserved.

Gate C remains failed. Gate D-G remain locked.
