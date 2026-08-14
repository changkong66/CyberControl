# Phase 7 Gate C Eighth-Remediation Mainline Replay

## Decision

State: `FAILED`

Formal state remains:
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

All five authenticated SSE stages passed their stage-local controls in one
fresh-volume run, and the fixed ten-minute recovery observation completed. The
final aggregate still failed the frozen Outbox p95 and post-ramp RSS-recovery
controls. A stage-local pass cannot override either aggregate failure. Gate D-G
remain locked.

## Binding

- Source/tree: `4f0a7670782c5002a2da6e429c0428d8fef29153` /
  `d79b15fce52b8a8b9afe4be361cfbcbba4c7ddc9`
- Eighth remediation PR: [#66](https://github.com/changkong66/CyberControl/pull/66),
  Squash Merge `4f0a7670782c5002a2da6e429c0428d8fef29153`
- PR #66 push/PR/main CI: Runs
  [31629029809](https://github.com/changkong66/CyberControl/actions/runs/31629029809),
  [31629100666](https://github.com/changkong66/CyberControl/actions/runs/31629100666) and
  [31629561293](https://github.com/changkong66/CyberControl/actions/runs/31629561293),
  each 8/8
- Run: `gate-c-20260812T190722Z-4f0a7670782c`
- Compose project: `cybercontrol-gate-c-eighth-4f0a767-20260813`
- Fresh PostgreSQL volume: `cybercontrol_gate_c_eighth_4f0a767_20260813`
- Threshold/workload SHA256: `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855` /
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Single-host production capacity claim permitted: `false`

## Workload Result

| Stage | Active | Sustained | Delivery p95/p99 | Result |
| --- | ---: | ---: | ---: | --- |
| smoke-20 | 20 | 181s | 27/127ms | PASS |
| ramp-200 | 200 | 304s | 52/224ms | PASS |
| ramp-500 | 500 | 304s | 235/349ms | PASS |
| ramp-1000 | 1,000 | 605s | 425/633ms | PASS |
| gate-2000 | 2,000 | 1,804s | 788/1042ms | PASS |

At 2,000 streams, connection and reconnect/replay success were `1.0/1.0`.
Committed event loss, duplicate final render, cross-tenant leakage, HTTP 5xx,
unexpected disconnects, pool timeouts, publisher failures and Outbox `DEAD`
were all zero. The expired real Keycloak Token and invalid cursor were rejected.

## Failed Final Controls

- Outbox p95: `2247.346ms`, required `<=2000ms`.
- Outbox p99: `3438.55ms`, required `<=5000ms` and passed.
- API RSS recovery ratio: `1.393027`, required `<=1.10`.
- Container RSS first/last/peak: `264660582 / 368679322 / 435054182` bytes.
- Process PSS first/last: `300299264 / 407353344` bytes.
- Process USS first/last: `297070592 / 404389888` bytes.
- Anonymous RSS first/last: `259416064 / 363573248` bytes.
- File RSS was unchanged at `48758784` bytes; map count was `615 -> 619`.

## Lifecycle Residual

The final 30 recovery monitor samples continuously reported
`subscribers=1` and `subscribers_live=1`. Closing owners, queued events/bytes,
replay buffers/caches and replay tasks were zero. This subscriber residual is
not currently a frozen finalizer check, but it violates the required terminal
lifecycle boundary and is a candidate retaining owner. It is disclosed without
changing the formal two-check failure decision.

API file descriptors returned from 29 to 29 after peaking at 2,039 against a
1,048,576 limit. Logs contained no `aclose()` race, traceback, error, pool
timeout, OOM or unplanned restart.

## PostgreSQL Terminal State

- Migration head: `20260720_0010`
- Tenant/FORCE RLS tables: `74/74`
- Append-only triggers: `57`
- Outbox: `PUBLISHED=223`, terminal `PENDING/CLAIMED/DEAD=0`
- Foreign-tenant visible rows: `0`
- Maximum database connections: `19`
- Pool checked-out maximum/capacity/timeouts: `11/90/0`

## Evidence

The run manifest contains 110 entries and has SHA256
`86073d65d31a61fcf41f422ad1283fac711ca7a277edf580b38802780d6ccf68`.
The redacted raw package is an immutable GitHub Release asset with SHA256
`b22f81bbcd42fb5dab0c9bc64891fe8b49888663ab9c0f13260b1de313802ff1`.
The original PostgreSQL volume and read-only-derived forensic volume remain
preserved.

An earlier immutable Release, ID `369509815`, was created without an asset. It
cannot be modified or deleted under immutable-release policy and is retained as
an explicit audit exception. The valid evidence asset is attached only to
Release ID `369510663`.
