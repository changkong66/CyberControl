# Phase 7 Gate C Seventh-Remediation Mainline Replay

## Decision

State: `FAILED`

Formal state remains:
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

All five authenticated SSE stages passed their stage-local controls in one
fresh-volume run. The final aggregate still failed the frozen Outbox p95 and
post-ramp memory-recovery controls. A complete workload is not accepted when
any final control fails. Gate D-G remain locked.

## Binding

- Source/tree: `fa5b4bd92e4b56704f70b63416906a10c54e0ee1` /
  `a9f020fd5cceb7a094439ad4c4089b63d3b473a7`
- Protected-main CI: Run 31593377181, attempt 1, 8/8
- Run: `gate-c-20260812T120720Z-fa5b4bd92e4b`
- Compose project: `cybercontrol-gate-c-seventh-fa5b4bd-20260812`
- Fresh PostgreSQL volume: `cybercontrol_gate_c_seventh_fa5b4bd_20260812`
- Threshold/workload SHA256: `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855` /
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Single-host production capacity claim permitted: `false`

## Workload Result

| Stage | Active | Sustained | Delivery p95/p99 | Result |
| --- | ---: | ---: | ---: | --- |
| smoke-20 | 20 | 181s | 24/40ms | PASS |
| ramp-200 | 200 | 304s | 46/163ms | PASS |
| ramp-500 | 500 | 305s | 239/404ms | PASS |
| ramp-1000 | 1,000 | 604s | 416/609ms | PASS |
| gate-2000 | 2,000 | 1,803s | 781/990ms | PASS |

At 2,000 streams, connection and reconnect/replay success were `1.0/1.0`.
Committed event loss, duplicate final render, cross-tenant leakage, HTTP 5xx,
publisher failures and Outbox `DEAD` were all zero. The expired real Keycloak
Token was rejected, and all 100 duplicate-replay clients were suppressed
without final duplicates.

## Failed Final Controls

- Outbox p95: `2225.796ms`, required `<=2000ms`.
- Outbox p99: `3026.102ms`, required `<=5000ms` and passed.
- API RSS recovery ratio: `1.492792`, required `<=1.10`.
- API RSS first/last/peak: `276404634 / 412614656 / 448371098` bytes.

The final subscriber, close-owner, queue, replay buffer/cache and replay-task
gauges were all zero. API file descriptors returned from 29 to 30 after peaking
at 2,039 against a 1,048,576 limit. The logs contained zero `aclose()` races,
tracebacks, errors, pool timeouts, OOMs or unplanned restarts. Those facts narrow
the memory investigation but do not satisfy the recovery threshold.

## PostgreSQL Terminal State

- Migration head: `20260720_0010`
- Tenant/FORCE RLS tables: `74/74`
- Outbox: `PUBLISHED=221`, `DEAD=0`
- Foreign-tenant visible rows: `0`
- Maximum application connections: `21`
- Pool checked-out maximum/timeouts: `6/0`

## Evidence

The redacted raw package is an immutable GitHub prerelease asset with SHA256
`a01a16fdfc4f50f14b0a74a234a9e5f332ab20a29451c49096b6f7901236f2fd`.
The original PostgreSQL volume and a read-only-derived forensic copy remain
preserved. No prior Gate C package or snapshot was changed.
