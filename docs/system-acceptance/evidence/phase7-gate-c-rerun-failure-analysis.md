# Phase 7 Gate C Remediation Rerun Failed Evidence Analysis

## Decision

Gate C remains **FAILED** for protected-main source
`efa5ff159fad49ac3e16f4f11f90499a3e7ab61c`. The project remains
`RELEASE_CANDIDATE`; Gate D through Gate G remain locked. This archive records
the real remediation rerun and does not reinterpret any failed threshold as
accepted.

## Bound Source And Environment

- Source commit: `efa5ff159fad49ac3e16f4f11f90499a3e7ab61c`
- Source tree: `6378f7c2ba11e20dce1c3c728d868e2aed489e60`
- Remediation PR: [#40](https://github.com/changkong66/CyberControl/pull/40),
  Squash Merge `8c204342d46cdd8bf134b3978968f41b81e239e9`
- Isolated-volume runner PR:
  [#41](https://github.com/changkong66/CyberControl/pull/41), Squash Merge
  `efa5ff159fad49ac3e16f4f11f90499a3e7ab61c`
- Post-merge protected-main CI:
  [Run 30126848516](https://github.com/changkong66/CyberControl/actions/runs/30126848516),
  8/8 successful
- Formal run directory:
  `D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260724T211823Z-efa5ff159fad`
- Compose project: `cybercontrol-gate-c-rerun-efa5ff1`
- Fresh PostgreSQL volume: `cybercontrol_gate_c_rerun_efa5ff1_20260725`
- Historical failed volume reused: `false`
- Threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Compose configuration SHA256:
  `74ad9c889a06899d5cbfcf3aeab590dd3acd9c9c8f84048bd0bd9abe333730bf`
- Docker allocation: 16 CPUs, 7,958,880,256 bytes memory
- Single-host production capacity claim permitted: `false`

## Stage Results

The unchanged workload executed serially. `smoke-20`, `ramp-200`, `ramp-500`
and `ramp-1000` passed all stage checks. The final `gate-2000` stage reached
2,000 active authenticated streams and sustained them for 1,804 seconds, but
failed four frozen checks.

| Frozen check | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Connection success rate | 0.9891196835 | >= 0.995 | FAIL |
| Reconnect and durable replay success | 0.9784735812 | >= 0.999 | FAIL |
| Committed event loss | 350 | 0 | FAIL |
| Commit-to-client delivery p95 | 1,183 ms | <= 1,000 ms | FAIL |
| Commit-to-client delivery p99 | 1,805 ms | <= 3,000 ms | PASS |
| Outbox lag p95 | 13,703.788 ms | <= 2,000 ms | FAIL |
| Outbox lag p99 | 14,728.932 ms | <= 5,000 ms | FAIL |
| Post-ramp API memory ratio | 1.660323 | <= 1.10 | FAIL |

The initial and planned reconnect establishment latency reached p95/p99 of
19,521/21,713 ms. These latency values are diagnostic observations; they are
not substituted for the frozen connection-success or delivery thresholds.

## Passing Controls

- Peak active authenticated streams: 2,000
- Sustained duration: 1,804 seconds
- HTTP 5xx rate: 0
- Unexpected disconnect rate: 0
- Duplicate final render: 0
- Duplicate replay suppression: 100/100
- Cross-tenant event leakage: 0
- Invalid or cross-tenant cursor acceptance: 0
- Expired Keycloak token unexpected acceptance: 0
- Publisher failures: 0
- Outbox `DEAD`: 0
- Database pool acquisition timeouts: 0
- Database pool checked-out peak/capacity: 8/90
- Host CPU p95/max: 48.5%/61.4%
- Host CPU breach duration above 95%: 0 seconds
- OOM or unplanned restart observations: 0
- API file descriptor peak/utilization: 2,039/0.001945
- Post-ramp API file descriptors returned to 30
- PostgreSQL migration head: `20260720_0010`
- Tenant tables with RLS and FORCE RLS: 74/74
- Append-only triggers: 57
- Foreign-tenant runtime visibility: 0
- Outbox terminal states: 222 `PUBLISHED`, zero `DEAD`

## Residual Runtime Findings

The first remediation materially improved duplicate replay suppression from
88/100 to 100/100, removed publisher failures, reduced committed event loss
from 590 to 350, and improved the post-ramp memory ratio from 1.933333 to
1.660323. Those improvements are not sufficient for acceptance.

At the coordinated 2,000-client shutdown, the API log recorded repeated
`RuntimeError: aclose(): asynchronous generator is already running` failures.
The run also captured a SQLAlchemy connection-termination `CancelledError`.
File descriptors returned to baseline, but API resident memory remained above
the frozen recovery ratio. The next remediation must therefore address
coordinated async-generator ownership, reconnect admission/replay completion,
subscriber-state reclamation, Outbox throughput and retained memory under the
unchanged workload.

## Evidence Package

- Package:
  `gate-c-20260724T211823Z-efa5ff159fad-rerun-failed-evidence-v1.zip`
- Package bytes: 1,888,203
- Package SHA256:
  `21a0bf5e7c8ef30869bcf277582408d179b451e658f48a9c6b18f6a87bd27cb8`
- GitHub prerelease:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-rerun-failed-20260725-efa5ff1
- GitHub asset:
  https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-rerun-failed-20260725-efa5ff1/gate-c-20260724T211823Z-efa5ff159fad-rerun-failed-evidence-v1.zip
- Server digest:
  `sha256:21a0bf5e7c8ef30869bcf277582408d179b451e658f48a9c6b18f6a87bd27cb8`
- GitHub Release immutable: `false`; integrity is bound by the protected Git
  archive, Release tag and matching local/server SHA256
- Finalizer: `tests/load/gate_c/finalize.py`
- JWT-like secret scan: passed
- Secrets directory present after finalization: `false`

## Next Boundary

Create a second scoped Gate C remediation PR. Do not change migrations
`0001-0010`, frozen contracts, trust boundaries, RLS, transaction semantics,
Outbox atomicity, C12 semantics, workload or thresholds. Do not start Gate D
until a new protected-main build passes a fresh isolated-volume Gate C run and
its independent success-evidence PR is merged through 8/8 CI.
