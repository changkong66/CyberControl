# Phase 7 Gate C Eleventh Mainline Replay Report

Process Version: `Gate-C-11-v1.0`

## Decision

- State: `FAILED`
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Milestone: `M2`
- Gate D eligibility: `false`
- Failed frozen control: `memory_recovery`

## Mainline And Environment

- Source/baseline: `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Tree: `f721fca017c247aee93765d5f11fcbc37e12fcfc`
- Protected-main CI: Run `32645162420`, 8/8
- Formal run: `gate-c-20260823T144052Z-5fcb917b6388`
- Compose: `gatec11formal5fcb917`
- PostgreSQL volume: `cybercontrol_gate_c_eleventh_5fcb917_20260823`
- Real Keycloak-issued Tokens: two tenants, twenty principals
- Build: all source images built from the exact mainline without `-SkipBuild`

## Results

| Control | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Completed stages | 20/200/500/1000/2000 + recovery | all | pass |
| Delivery p95/p99 at 2,000 | 758/1077 ms | <=1000/3000 ms | pass |
| Monitor completeness | 491/495 (0.991919) | >=0.95 | pass |
| Outbox p95/p99 | 1879.698/2898.555 ms | <=2000/5000 ms | pass |
| Recovery memory ratio | 1.417200 | <=1.10 | **fail** |
| FD first/final/peak | 29/30/2038 | observed, not exhausted | pass |
| Connection/reconnect | 1.0/1.0 | frozen thresholds | pass |
| Loss/duplicates/leakage/invalid cursor | 0/0/0/0 | zero | pass |
| HTTP 5xx/pool timeout/Outbox DEAD | 0/0/0 | zero | pass |
| OOM/unplanned restart | 0/0 | zero | pass |

API cgroup memory was 262,144,000 bytes at the frozen first sample,
371,510,477 bytes after recovery and 436,941,619 bytes at peak. Every terminal
SSE subscriber, close, queue, replay and cache gauge was zero, so no acceptance
claim or specific ownership conclusion is inferred from the aggregate ratio.

PostgreSQL evidence recorded migration `20260720_0010`, FORCE RLS `74/74`, 57
append-only triggers, foreign-tenant visibility zero and terminal Outbox
`PUBLISHED=226` with no open or dead rows.

The formal run directory and PostgreSQL volume are preserved and must never be
reused. The immutable external package and Release are indexed separately in
the package metadata file. No Gate D-G work is authorized.
