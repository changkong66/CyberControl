# Phase 7 Gate C Mainline Replay Result

- State: FAILED
- Formal state: RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED
- Source commit: 64792b0420f436d18beea2a301bd4017bc7e7a82
- Source tree: 61da331c23a5d5b6988aff70d0db5455732886cc
- Compose project: cybercontrol-gate-c-tenth-main-64792b-20260815050434
- PostgreSQL volume: cybercontrol_gate_c_tenth_main_64792b_20260815050434
- Threshold SHA256: d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855
- Workload SHA256: 38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea

## Execution Boundary

The real Keycloak provisioning created two tenants and twenty principals. The
unchanged smoke-20 stage completed with twenty authenticated SSE clients for
121 sustained seconds. Its frozen stage summary failed, so the required stop
rule prevented ramp-200, ramp-500, ramp-1000, gate-2000 and the fixed recovery
observation from starting. No partial result is treated as Gate C acceptance.

## Failed Controls

| Control | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Smoke delivery p99 | 6850 ms | <= 3000 ms | FAIL |
| Smoke monitor complete sample rate | 0.7948717949 | >= 0.95 | FAIL |

Smoke delivery p95 was 439 ms. Connection and reconnect/replay success were
1.0/1.0. Committed event loss, duplicate final rendering, cross-tenant leakage,
HTTP 5xx, Outbox DEAD and pool acquisition timeouts were zero in the completed
stage. These local passes do not override the two failures or unexecuted stages.

The monitor collected 39 samples, of which 31 were complete. Seven incomplete
rows recorded /metrics ReadTimeout and one final row recorded Docker
CalledProcessError. This is retained as an evidence-readiness failure.

## Database And Lifecycle Boundary

PostgreSQL migration head was 20260720_0010, FORCE RLS covered 74/74 tenant
tables, append-only triggers numbered 57 and foreign-tenant visibility was zero.
Terminal Outbox state was PUBLISHED=25 with no PENDING, CLAIMED or DEAD row. The
partial-run Outbox lag sample was 6714.479/9373.942 ms p95/p99.

Because gate-2000 and the fixed recovery observation did not execute, no
post-ramp RSS recovery or terminal lifecycle conclusion is asserted.

## Decision

This is a real failed partial Gate C run. Preserve the package and volume,
retain PHASE7_GATE_C_FAILED_GATE_D_LOCKED and stop. Gate D-G remain locked.
