# Phase 7 Gate C Fourth Remediation Result

## Decision

- State: `FAILED`
- Formal state: `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Stop stage: `ramp-1000`
- Full frozen workload completed: `false`
- `gate-2000` executed: `false`
- Ten-minute recovery observation executed: `false`
- Single-host production capacity claim permitted: `false`

## Bound Source And Runtime

- Source commit: `97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504`
- Source tree: `bad6b0f9e7008b934a54681f9f304a786ee9afe7`
- Protected-main CI: Run 30196139462, attempt 2, 8/8
- Compose project: `cybercontrol-gate-c-97bfa5f-20260808t0840z`
- Fresh PostgreSQL volume:
  `cybercontrol_gate_c_97bfa5f_20260808t0840z`
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
| Commit-to-client p95 | `1,631 ms` | `<= 1,000 ms` | FAIL |
| Commit-to-client p99 | `6,132 ms` | `<= 3,000 ms` | FAIL |
| Outbox DEAD | `2` | `0` | FAIL |
| Outbox lag p95 | `6,292.587 ms` | `<= 2,000 ms` | FAIL |
| Outbox lag p99 | `8,712.164 ms` | `<= 5,000 ms` | FAIL |
| Pool acquisition timeouts | `0` | `0` | PASS |
| OOM/unplanned restart | `0` | `0` | PASS |

## Terminal Database Evidence

- Migration head: `20260720_0010`
- Tenant tables with FORCE RLS: `74/74`
- Append-only triggers: `57`
- Foreign-tenant rows visible in adversarial read: `0`
- Outbox terminal state: `PUBLISHED=94`, `DEAD=2`
- Both DEAD events: `topic3.workflow.finalized`, sequence `2`, attempts `3/3`
- Terminal error code: `LIYAN-AUTH-FORBIDDEN`

The failed events prove an authorization failure in durable finalized-event
delivery. The evidence does not yet identify the exact trusted-context or
policy boundary. Authorization must remain fail closed during remediation.

## Admission And Cleanup Signals

- Connection-establishment p95/p99: `19,964/23,705 ms`
- Keycloak Token acquisition failures: `0`
- Final subscribers: `0`
- Final queued events: `0`
- Final replay-cache events: `0`
- Host CPU p95/max: `42.2%/56.7%`
- Peak API RSS: `301,465,600 bytes`
- Peak API file descriptors: `1,032`

## Evidence Normalization Disclosure

The immutable raw ZIP contains an automatically generated `gate-c-report.md`
with control characters and unexpanded PowerShell expressions. The raw ZIP,
its SHA256, and its internal manifest are preserved unchanged. This repository
report is a normalized derivative generated from the immutable stage summary
and PostgreSQL evidence JSON. It changes no metric or acceptance decision.

The authoritative raw metrics remain:

- `phase7-gate-c-fourth-remediation-summary.json`
- `phase7-gate-c-fourth-remediation-database-evidence.json`
- raw package SHA256
  `9b2c4c116752197bf10dd1bc9d29409e59bdca1eca7be3cd4a0df1d1bef26f8d`

Gate D through Gate G remain locked.
