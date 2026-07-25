# Phase 7 Gate C Third Remediation Failed Evidence Analysis

## Decision

The third-remediation Gate C rerun remains **FAILED**. The project remains
`RELEASE_CANDIDATE`; Gate D through Gate G remain locked. This document records
the real protected-main rerun and does not reinterpret any failed threshold as
accepted.

## Bound Source And CI

- Source commit: `01595ae2634cb8114dfb9c591114048cba3864fd`
- Source tree: `e319baaec6f1ba40e4d4069b6e0f78bf37b27bb0`
- Remediation PR: [#50](https://github.com/changkong66/CyberControl/pull/50),
  Squash Merge `01595ae2634cb8114dfb9c591114048cba3864fd`
- Push CI: [Run 30171031219](https://github.com/changkong66/CyberControl/actions/runs/30171031219), 8/8
- Pull-request CI: [Run 30171054312](https://github.com/changkong66/CyberControl/actions/runs/30171054312), 8/8
- Protected-main CI: [Run 30171222537](https://github.com/changkong66/CyberControl/actions/runs/30171222537), 8/8
- Python/real PostgreSQL/real Keycloak local result: `680 passed, 1 skipped`,
  `92.14%` coverage
- Frontend Vitest: `72 passed`; Playwright: `8 passed`
- Frozen thresholds SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`

## Formal Run

- Run directory:
  `D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260725T192105Z-01595ae2634c`
- Compose project: `cybercontrol-gate-c-third-20260725-192105`
- Fresh PostgreSQL volume: `cybercontrol_gate_c_third_20260725t192105z`
- Fresh isolated volume: `true`; prior Gate C and development volumes reused: `false`
- Compose configuration SHA256:
  `3937fa84d0a75388b2ef1854dedec27f5853a3ac9cd505cbfec4539e03cb3289`
- API image: `sha256:efa35d7afbf3b940dff3ece94045d36aba17ccdb9c9841ca7108046754acb954`
- PostgreSQL image: `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`
- Keycloak image: `sha256:2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0`
- Execution was single-host only; no production capacity claim is permitted.

## Frozen Result

The `smoke-20`, `ramp-200`, `ramp-500` and `ramp-1000` stages passed. The
`gate-2000` stage reached 2,000 active authenticated streams and sustained them
for 1,804 seconds. It failed the following frozen controls:

| Control | Observed | Required | Result |
| --- | ---: | ---: | --- |
| Connection success rate | `0.9900990099` | `>= 0.995` | FAIL |
| Reconnect/durable replay success | `0.9803921569` | `>= 0.999` | FAIL |
| Committed event loss | `1,350` | `0` | FAIL |
| Commit-to-client p95 | `1,830 ms` | `<= 1,000 ms` | FAIL |
| Commit-to-client p99 | `3,267 ms` | `<= 3,000 ms` | FAIL |
| Outbox lag p95 | `12,149.778 ms` | `<= 2,000 ms` | FAIL |
| Outbox lag p99 | `14,295.416 ms` | `<= 5,000 ms` | FAIL |
| Post-ramp API memory ratio | `1.388368` | `<= 1.10` | FAIL |

The stage counters recorded `4,040` connection attempts and `4,000`
successes, including `2,040` reconnect attempts and `2,000` reconnect
successes. The 100 duplicate-replay clients were the lagging population: 50
per tenant finished at ordinal 982 for `gate-c-alpha` or 981 for
`gate-c-beta`, while the publisher final ordinal was 995 for both tenants.
The resulting durable continuity deficit is 1,350 committed events. Final
duplicate rendering remained zero.

## Controls That Passed

- Cross-tenant leakage: `0`
- Invalid, tampered and cross-tenant cursor acceptance: `0`
- HTTP 5xx rate: `0`
- Unexpected disconnect rate: `0`
- Duplicate final render: `0`
- Duplicate replay suppression: `100/100`
- Publisher failures: `0`
- Outbox `DEAD`: `0`
- PostgreSQL pool acquisition timeouts: `0`
- OOM or unplanned restart: `0`
- Migration head: `20260720_0010`
- Tenant tables with FORCE RLS: `74/74`
- Append-only triggers: `57`
- Runtime foreign-tenant visibility: `0`
- Real Keycloak token acquisition failures: `0`

The third remediation did eliminate the previously observed
`aclose(): asynchronous generator is already running` error. The final
monitor sample reported `closing_subscriptions=0`, `replay_tasks=0`, and
`replay_buffer_bytes=0`. It nevertheless retained `17` subscribers, `82`
queued events, and a replay cache of `1,085` events / `629,343` bytes at the
end of the recovery observation. API RSS moved from `279,445,504` bytes at the
first final-stage sample to `387,973,120` bytes at the last sample, matching
the failing post-ramp ratio.

## Evidence Package

- Package:
  `gate-c-20260725T192105Z-01595ae2634c-third-remediation-failed-evidence-v1.zip`
- Bytes: `3,502,256`
- SHA256:
  `027e4c47e2ef10b381a7e48b0b342eebd54f40f8b4fca259f35216917f4a3403`
- GitHub prerelease:
  [phase7-gate-c-third-remediation-failed-20260725-01595ae](https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-third-remediation-failed-20260725-01595ae)
- Asset:
  [download evidence package](https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-third-remediation-failed-20260725-01595ae/gate-c-20260725T192105Z-01595ae2634c-third-remediation-failed-evidence-v1.zip)
- Server digest: `sha256:027e4c47e2ef10b381a7e48b0b342eebd54f40f8b4fca259f35216917f4a3403`
- JWT-like token scan: passed; secrets directory: absent

## Next Boundary

This is a failed Gate C evidence archive, not a capacity acceptance. The next
authorized work is a separately approved fourth scoped remediation based on
the retained connection-admission, duplicate-replay continuity, Outbox
latency and post-ramp memory evidence. It must start from the protected main
that contains this archive, preserve the frozen workload and thresholds, and
repeat Gate C on a new isolated volume. Gate D must not start.
