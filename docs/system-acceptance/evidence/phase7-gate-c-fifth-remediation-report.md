# Phase 7 Gate C Fifth Remediation Result

## Decision

- State: `FAILED`
- Formal state: `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Stop stage: `ramp-1000`
- Full frozen workload completed: `false`
- `gate-2000` executed: `false`
- Ten-minute recovery observation executed: `false`
- Single-host production capacity claim permitted: `false`

## Bound Source And Runtime

- Source commit: `76cd099a034a395a89b26496c0d40e0673aaa97d`
- Source tree: `ffb7c72b3156f1dc271b5b0ec1afc2ce3f2c6870`
- Protected-main CI: Run 31264518015, attempt 1, 8/8
- Compose project: `cybercontrol-gate-c-fifth-76cd099-20260808t154325z`
- Fresh PostgreSQL volume:
  `cybercontrol_gate_c_fifth_76cd099_20260808t154325z`
- Real Keycloak subjects: `20` across two tenants
- Peak active authenticated streams: `1,000`
- Sustained duration: `603 seconds`

## Frozen Control Results

| Control | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Connection success | `1.0` | `>= 0.995` | PASS |
| Reconnect/replay success | `1.0` | `>= 0.999` | PASS |
| Committed event loss | `0` | `0` | PASS |
| Duplicate final renders | `0` | `0` | PASS |
| Cross-tenant leakage | `0` | `0` | PASS |
| HTTP 5xx | `0` | `<= 0.1%` | PASS |
| Commit-to-client p95 | `1,532 ms` | `<= 1,000 ms` | FAIL |
| Commit-to-client p99 | `4,985 ms` | `<= 3,000 ms` | FAIL |
| Outbox DEAD | `0` | `0` | PASS |
| Outbox lag p95 | `5,830.700 ms` | `<= 2,000 ms` | FAIL |
| Outbox lag p99 | `8,434.789 ms` | `<= 5,000 ms` | FAIL |
| Pool acquisition timeouts | `0` | `0` | PASS |
| OOM/unplanned restart | `0` | `0` | PASS |

The stage runner failed fast on commit-to-client latency before the global
PostgreSQL lag controls were evaluated. The independent forensic snapshot
therefore records the additional Outbox p95/p99 failures without changing the
original stage result.

## Terminal Database Evidence

- Migration head: `20260720_0010`
- Tenant tables with FORCE RLS: `74/74`
- Append-only triggers: `57`
- Foreign-tenant rows visible in adversarial read: `0`
- Outbox terminal state: `PUBLISHED=103`, `DEAD=0`
- Both tenants reached their final durable SSE sequence with no cross-tenant
  visibility.
- The original failed volume was copied read-only to
  `cybercontrol_gate_c_fifth_76cd099_20260808t154325z_forensics` for terminal
  inspection.

The fifth remediation fixed the prior `topic3.workflow.finalized`
authorization failure. Valid finalized events were durably accepted and no
Outbox row entered `DEAD`.

## Resource And Cleanup Signals

- Connection-establishment p95/p99: `19,166/22,324 ms`
- Keycloak Token acquisition failures: `0`
- API CPU p95/max in one-core units: `127.604%/131.840%`
- Host CPU p95/max: `36.220%/66.900%`
- Peak API RSS: `297,271,296 bytes`
- Peak API file descriptors: `1,038`
- Final subscribers, queued events, replay-cache events and replay tasks:
  `0/0/0/0`
- Closing subscription owners at fail-fast capture: `826`

The fixed recovery observation was not executed, so the closing-owner value is
a remediation signal and is not a memory-recovery acceptance result.

Gate D through Gate G remain locked.
