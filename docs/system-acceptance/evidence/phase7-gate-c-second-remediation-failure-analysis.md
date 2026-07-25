# Phase 7 Gate C Second Remediation Failed Evidence Analysis

## Decision

Gate C remains **FAILED** for protected-main source
`7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8`. The project remains
`RELEASE_CANDIDATE`; Gate D through Gate G remain locked. This archive records
the real second-remediation rerun and does not reinterpret a failed threshold as
accepted.

## Bound Source And Environment

- Source commit: `7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8`
- Source tree: `c33f8ccdb077c923d8310c869e0bf9f1096cfd5b`
- Second remediation PR: [#47](https://github.com/changkong66/CyberControl/pull/47),
  Squash Merge `7ff03ce0c4af46aa33ce64ac3bc01af027cbbee8`
- Push, pull-request and protected-main Release Quality Gate runs:
  [30157996109](https://github.com/changkong66/CyberControl/actions/runs/30157996109),
  [30158060313](https://github.com/changkong66/CyberControl/actions/runs/30158060313)
  and [30158839398](https://github.com/changkong66/CyberControl/actions/runs/30158839398),
  each 8/8 successful
- Formal run directory:
  `D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260725T134112Z-7ff03ce0c4af`
- Compose project: `cybercontrol-gate-c-second-7ff03ce`
- Fresh PostgreSQL volume: `cybercontrol_gate_c_second_7ff03ce_20260725`
- Historical failed volume reused: `false`
- Threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Compose configuration SHA256:
  `e4a7abdcfc69d5653e576f4e760e9372c82b30d123c1762c02d17ac61d8d3063`
- Docker allocation: 16 CPUs, 7,958,880,256 bytes memory
- Single-host production capacity claim permitted: `false`

## Stage Results

The unchanged workload executed serially. `smoke-20`, `ramp-200`, `ramp-500`
and `ramp-1000` passed all stage checks. The final `gate-2000` stage reached
2,000 active authenticated streams and sustained them for 1,805 seconds, but
failed frozen checks.

| Frozen check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Connection success rate | 0.9840098401 | >= 0.995 | FAIL |
| Reconnect and durable replay success | 0.9685230024 | >= 0.999 | FAIL |
| Committed event loss | 1,700 | 0 | FAIL |
| Commit-to-client delivery p95 | 995 ms | <= 1,000 ms | PASS |
| Commit-to-client delivery p99 | 1,721 ms | <= 3,000 ms | PASS |
| Outbox lag p95 | 10,277.417 ms | <= 2,000 ms | FAIL |
| Outbox lag p99 | 11,538.743 ms | <= 5,000 ms | FAIL |
| Post-ramp API memory ratio | 1.480965 | <= 1.10 | FAIL |

Connection-establishment latency was observed at p95/p99 of 29,970/33,132 ms.
It is a diagnostic observation, not a substitute for the frozen
connection-success threshold.

The script stopped at the failed final stage. The final-stage monitor included
the configured 10-minute post-ramp observation before summarization. Database
terminal-state evidence was then captured by mounting only the retained isolated
PostgreSQL volume; the workload was not rerun.

## Passing Controls

- Peak active authenticated streams: 2,000
- Sustained duration: 1,805 seconds
- HTTP 5xx rate: 0
- Unexpected disconnect rate: 0
- Duplicate final render: 0
- Duplicate replay suppression: 100/100
- Cross-tenant event leakage: 0
- Invalid, tampered and cross-tenant cursor acceptance: 0
- Expired Keycloak token unexpected acceptance: 0
- Publisher successes/failures: 3,371/0
- Outbox `DEAD`: 0
- Database pool acquisition timeouts: 0
- Database pool checked-out peak/capacity: 7/90
- Host CPU p95/max: 27.6%/46.0%
- OOM or unplanned restart observations: 0
- API file descriptor peak/utilization: 2,036/0.001942
- Post-ramp API file descriptor ratio: 0.652174
- PostgreSQL migration head: `20260720_0010`
- Tenant tables with RLS and FORCE RLS: 74/74
- Append-only triggers: 57
- Foreign-tenant runtime visibility: 0
- Outbox terminal states: 222 `PUBLISHED`, zero `DEAD`

## Residual Runtime Findings

The second remediation retained zero duplicate final renders, zero cross-tenant
visibility, zero publisher failures and zero Outbox `DEAD` records. It improved
Outbox p95/p99 from the prior rerun's 13,703.788/14,728.932 ms to
10,277.417/11,538.743 ms and improved the post-ramp memory ratio from 1.660323
to 1.480965. Those improvements remain insufficient for acceptance.

The final-stage API log contains 14
`aclose(): asynchronous generator is already running` errors. Alongside the
connection, replay and loss failures, this is evidence that the single-owner
subscription-close protocol is not complete under the 2,000-stream coordinated
shutdown/reconnect population. It is not evidence of a tenant-isolation,
Outbox-atomicity or C12 publication defect.

The next remediation must use object-lifecycle and admission/replay timing
measurements to eliminate concurrent async-generator close ownership and to
bound the 2,000-stream connection/reconnect fanout. It must preserve the frozen
workload and thresholds and must not characterize this single-host result as a
production capacity claim.

## Evidence Package

- Package:
  `gate-c-20260725T134112Z-7ff03ce0c4af-second-remediation-failed-evidence-v1.zip`
- Package bytes: 1,964,853
- Package SHA256:
  `ce0e03ced13c27ce875574f8154cc217b7ab889ead59a5f1ea743b66bbad73d6`
- GitHub prerelease:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-second-remediation-failed-20260725-7ff03ce
- GitHub asset:
  https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-second-remediation-failed-20260725-7ff03ce/gate-c-20260725T134112Z-7ff03ce0c4af-second-remediation-failed-evidence-v1.zip
- Server digest:
  `sha256:ce0e03ced13c27ce875574f8154cc217b7ab889ead59a5f1ea743b66bbad73d6`
- GitHub Release immutable: `false`; integrity is bound by the protected Git
  archive, Release tag and matching local/server SHA256
- Finalizer: `tests/load/gate_c/finalize.py`
- JWT-like secret scan: passed
- Secrets directory present after finalization: `false`

## Next Boundary

Create a third scoped Gate C remediation PR. Do not modify migrations
`0001-0010`, frozen contracts, trust boundaries, RLS, transaction semantics,
Outbox atomicity, C12 semantics, workload or thresholds. Do not start Gate D
until a new protected-main build passes a fresh isolated-volume Gate C run and
its independent success-evidence PR is merged through 8/8 CI.
