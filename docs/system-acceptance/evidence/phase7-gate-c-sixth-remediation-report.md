# Phase 7 Gate C Sixth Remediation Result

## Decision

- State: `FAILED`
- Formal state: `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Stop stage: `ramp-1000`
- Full frozen workload completed: `false`
- `gate-2000` executed: `false`
- Ten-minute recovery observation executed: `false`
- Single-host production capacity claim permitted: `false`

## Bound Source And Runtime

- Source commit: `a6979d760701271d579776b082dabe247ac6138b`
- Source tree: `52ba6cd9f1c532cedbfe27fbcaf8b206c5d02c3f`
- Sixth remediation PR: [#61](https://github.com/changkong66/CyberControl/pull/61)
- Protected-main CI: [Run 31538917814](https://github.com/changkong66/CyberControl/actions/runs/31538917814), attempt 1, 8/8
- Compose project: `cybercontrol-gate-c-sixth-a6979d7-20260811t214703z`
- Fresh PostgreSQL volume: `cybercontrol_gate_c_sixth_a6979d7_20260811t214703z`
- Forensic snapshot: `cybercontrol_gate_c_sixth_a6979d7_20260811t214703z_forensics`
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
| Commit-to-client p95 | `1,805 ms` | `<= 1,000 ms` | FAIL |
| Commit-to-client p99 | `7,190 ms` | `<= 3,000 ms` | FAIL |
| Outbox DEAD | `0` | `0` | PASS |
| Outbox lag p95 | `10,102.261 ms` | `<= 2,000 ms` | FAIL |
| Outbox lag p99 | `11,812.566 ms` | `<= 5,000 ms` | FAIL |
| Pool acquisition timeouts | `0` | `0` | PASS |
| OOM/unplanned restart | `0` | `0` | PASS |

The runner failed fast after `ramp-1000`. The 2,000-stream stage and fixed
recovery observation were not executed and cannot be inferred from partial
success.

## Terminal Database Evidence

- Migration head: `20260720_0010`
- Tenant tables with FORCE RLS: `74/74`
- Append-only triggers: `57`
- Foreign-tenant rows visible in adversarial read: `0`
- Outbox terminal state: `PUBLISHED=105`, `DEAD=0`
- The original failed volume was stopped before being copied from a read-only
  mount to the forensic volume.
- Both volumes contain `1,827` files with the same aggregate content SHA256:
  `afbdfa683a0921dbdaf49f78a3c879805a284a408d087346814881916bedfdad`.

## Resource And Cleanup Signals

- Connection-establishment p95/p99: `21,888/25,735 ms`
- Keycloak Token acquisition failures: `0`
- API CPU p95/max in one-core units: `128.502%/145.910%`
- Host CPU p95/max: `39.720%/50.100%`
- Peak API RSS: `314,677,658 bytes`
- Peak API file descriptors: `1,038`
- Final subscribers, closing owners, queued events, replay-cache events and
  replay tasks: `0/0/0/0/0`
- Async-generator `aclose()` race errors: `0`

The fixed recovery observation was not executed, so the final fail-fast gauges
are cleanup evidence but not a memory-recovery acceptance result.

## Immutable Package

- Release: [phase7-gate-c-sixth-remediation-failed-20260811-a6979d7](https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-sixth-remediation-failed-20260811-a6979d7)
- Release immutable: `true`
- Asset bytes: `2,170,353`
- Asset SHA256: `bb406ab73e7bc4532266f3274605402e28c356b58586ea20eee6648a54b5a18a`
- JWT, credential-marker and email scan matches: `0/0/0`

Gate D through Gate G remain locked.
