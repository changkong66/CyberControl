# Phase 7 Gate C Fourth Remediation Failed Evidence Analysis

## Decision

The fourth-remediation protected-main Gate C replay is **FAILED**. The project
remains `RELEASE_CANDIDATE`; Gate D through Gate G remain locked. The harness
stopped at the first failed frozen stage, so `gate-2000` and the ten-minute
post-ramp recovery observation were not executed and are not represented as
passed or completed.

## Bound Source And CI

- Source commit: `97bfa5fef7e1bb72cf711d1b93dcde2b7f3d9504`
- Source tree: `bad6b0f9e7008b934a54681f9f304a786ee9afe7`
- Fourth remediation PR:
  [#52](https://github.com/changkong66/CyberControl/pull/52), head
  `3c75c532bc8860debfe865eb08f63543fbd70eea`, Squash Merge `97bfa5f`
- Push CI:
  [Run 30195808808](https://github.com/changkong66/CyberControl/actions/runs/30195808808), 8/8
- Pull-request CI:
  [Run 30195810215](https://github.com/changkong66/CyberControl/actions/runs/30195810215), 8/8
- Protected-main CI:
  [Run 30196139462](https://github.com/changkong66/CyberControl/actions/runs/30196139462),
  attempt 2, 8/8. Attempt 1 failed while pulling `postgres:16-alpine` on the
  GitHub runner and did not establish a product-test failure.
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- `uv.lock` SHA256:
  `079da6bf96651f961eda7e2a3a634ecdd702d893629819e66f7af6f3c193dab8`
- `frontend/pnpm-lock.yaml` SHA256:
  `b285c5f06fbfdd3471baf9e46620224a6804e521202723cb57145589f2604a50`

## Environment Recovery And Formal Run

- Docker Desktop data VHDX:
  `D:\Docker\wsl\DockerDesktopWSL\disk\docker_data.vhdx`
- Docker Desktop / Engine: `4.80.0` / `29.6.1`
- Docker limits: `16` CPUs and `7,958,892,544` bytes memory
- D-drive capacity gate passed before execution with more than 40 GiB free.
- Run directory:
  `D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260808T083601Z-97bfa5fef7e1`
- Compose project: `cybercontrol-gate-c-97bfa5f-20260808t0840z`
- Fresh PostgreSQL volume:
  `cybercontrol_gate_c_97bfa5f_20260808t0840z`
- Fresh isolated volume: `true`; development, release and historical Gate C
  volumes reused: `false`
- Forensic copy used only for terminal evidence:
  `cybercontrol_gate_c_97bfa5f_20260808t0840z_forensics`
- The original failed volume was mounted read-only during the copy and was not
  started for post-failure inspection.
- Compose configuration SHA256:
  `62da355b25dec89ead1ab38e4a06d57bb424116edb1bc4e1c436642546953737`
- API image:
  `sha256:0a7e783f16202c6038f17224cf8730f5faa87da66a364de271e3aadfad16708a`
- PostgreSQL image:
  `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`
- Keycloak image:
  `sha256:2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0`
- Execution was single-host only; no production capacity claim is permitted.

## Frozen Result

`smoke-20`, `ramp-200` and `ramp-500` passed. `ramp-1000` reached 1,000
active authenticated streams and sustained them for 603 seconds, then failed
the following frozen controls:

| Control | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Commit-to-client p95 | `1,631 ms` | `<= 1,000 ms` | FAIL |
| Commit-to-client p99 | `6,132 ms` | `<= 3,000 ms` | FAIL |
| Outbox `DEAD` | `2` | `0` | FAIL |
| Outbox lag p95 | `6,292.587 ms` | `<= 2,000 ms` | FAIL |
| Outbox lag p99 | `8,712.164 ms` | `<= 5,000 ms` | FAIL |

Because the harness is fail-fast, the 2,000-connection stage and recovery
window were not executed. This archive therefore makes no 2,000-connection,
memory-recovery or production-capacity claim.

## Controls That Passed At 1,000 Streams

- Connection success rate: `1.0`
- Reconnect/durable replay success rate: `1.0`
- Committed event loss: `0`
- Duplicate final render: `0`
- Duplicate-replay suppression: `50/50`
- Cross-tenant leakage: `0`
- HTTP 5xx rate: `0`
- Unexpected disconnect rate: `0`
- Real Keycloak token acquisition failures: `0`
- PostgreSQL pool acquisition timeouts: `0`
- OOM or unplanned restart: `0`
- Final subscribers, queued events and replay-cache events: `0 / 0 / 0`
- Migration head: `20260720_0010`
- Tenant tables with FORCE RLS: `74/74`
- Append-only triggers: `57`
- Runtime foreign-tenant visibility: `0`

Admission completed successfully, but connection-establishment p95/p99 rose
to `19,964/23,705 ms` at 1,000 streams. This is not the direct frozen failure
in this run, but it is a readiness signal that must be measured separately
from token issuance and not hidden by increasing client timeouts.

## Evidence-Backed Failure Boundary

The two terminal Outbox rows are both `topic3.workflow.finalized` events. Each
row reached `attempts=3` with `max_attempts=3` and entered `DEAD` with
`last_error_code=LIYAN-AUTH-FORBIDDEN`. API logs record the same two event IDs
failing all three deliveries between `09:00:11Z` and `09:00:17Z`.

This proves an authorization failure in the durable finalized-event delivery
path. It does not yet prove whether the defect originates in event-envelope
claims, service-subject authorization, tenant ContextVar propagation, the
publisher consumer boundary, or a policy mismatch. The next remediation must
instrument and test that chain without adding client identity headers,
weakening TenantContext, bypassing authorization or acknowledging publication
before the trusted consumer accepts it.

The database terminal snapshot reports `PUBLISHED=94`, `DEAD=2`, Outbox
p95/p99 `6292.587/8712.164 ms`, and zero cross-tenant visibility. The API
stage completed with host CPU p95/max `42.2%/56.7%`, peak API RSS
`301,465,600` bytes and peak API file descriptors `1,032`; no pool timeout,
OOM or unplanned restart occurred.

## Evidence Package

- Package:
  `gate-c-20260808T083601Z-97bfa5fef7e1-fourth-remediation-failed-evidence-v1.zip`
- Bytes: `1,881,710`
- SHA256:
  `9b2c4c116752197bf10dd1bc9d29409e59bdca1eca7be3cd4a0df1d1bef26f8d`
- GitHub prerelease:
  [phase7-gate-c-fourth-remediation-failed-20260808-97bfa5f](https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-fourth-remediation-failed-20260808-97bfa5f)
- Asset:
  [download evidence package](https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-fourth-remediation-failed-20260808-97bfa5f/gate-c-20260808T083601Z-97bfa5fef7e1-fourth-remediation-failed-evidence-v1.zip)
- Server digest:
  `sha256:9b2c4c116752197bf10dd1bc9d29409e59bdca1eca7be3cd4a0df1d1bef26f8d`
- JWT-like token scan: passed; secrets directory: absent

The immutable ZIP's automatically generated `gate-c-report.md` contains control
characters and unexpanded PowerShell expressions. The ZIP and its internal
manifest remain unchanged. The repository report is a disclosed normalized
derivative of the immutable summary and PostgreSQL evidence JSON and does not
change any metric or acceptance decision.

## Next Boundary

This is a failed Gate C evidence archive, not a capacity acceptance. The next
authorized work is a separately approved fifth scoped Gate C remediation that
fixes the finalized-event Outbox authorization path and the remaining delivery
latency, adds deterministic unit and real PostgreSQL regressions, and reruns the
unchanged Gate C workload on a new protected-main commit and fresh volume. Gate
D through Gate G remain locked.
