# Phase 7 Gate C Ninth-Remediation Mainline Replay

## Decision

State: `FAILED`

Formal state remains:
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

The complete frozen workload and fixed ten-minute recovery observation ran on
protected-main source `993ed9719dfb363238fe3c2f075f1d7e7e269b40` using a fresh
PostgreSQL volume. All five stages passed their stage-local controls. The final
aggregate still failed the frozen Outbox p95 and post-ramp memory controls.
Stage-local passes do not override either frozen failure. Gate D-G remain
locked.

## Binding

- Source/tree: `993ed9719dfb363238fe3c2f075f1d7e7e269b40` /
  `8dcbe0c2c23b618c851acc9e4b5de4dd4f3681c5`
- Ninth remediation PR: [#72](https://github.com/changkong66/CyberControl/pull/72),
  Squash Merge `993ed9719dfb363238fe3c2f075f1d7e7e269b40`
- PR #72 push/PR/main CI: Runs
  [31818504209](https://github.com/changkong66/CyberControl/actions/runs/31818504209),
  [31818567543](https://github.com/changkong66/CyberControl/actions/runs/31818567543)
  and [31819184923](https://github.com/changkong66/CyberControl/actions/runs/31819184923),
  each returned 8/8 successful jobs
- Run directory:
  `D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260814T163148Z-993ed9719dfb`
- Compose project: `cybercontrol-gate-c-ninth-993ed97-20260815`
- Fresh PostgreSQL volume: `cybercontrol_gate_c_ninth_993ed97_20260815`
- Threshold/workload SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855` /
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Compose config SHA256:
  `1bdc70714c3c0d50d5e492403d64ba3d96703f1a85bd3bba204b4b5c5a444b4c`

## Workload Result

| Stage | Active | Sustained | Delivery p95/p99 | Result |
| --- | ---: | ---: | ---: | --- |
| smoke-20 | 20 | 181s | 27/116ms | PASS |
| ramp-200 | 200 | 304s | 49/215ms | PASS |
| ramp-500 | 500 | 304s | 242/396ms | PASS |
| ramp-1000 | 1,000 | 604s | 440/622ms | PASS |
| gate-2000 | 2,000 | 1,805s | 811/1070ms | PASS |

At 2,000 streams, connection and reconnect/replay success were `1.0/1.0`.
Committed event loss, duplicate final rendering, cross-tenant leakage, HTTP
5xx, pool acquisition timeouts, publisher failures and Outbox `DEAD` were zero.
The real expired-token probe was rejected and invalid cursor acceptance was
zero. The final lifecycle gauges for subscribers, close owners, queues, replay
cache and replay tasks were zero in the final recovery samples.

## Failed Final Controls

- Outbox p95: `3102.698ms`, required `<=2000ms`.
- Outbox p99: `3935.444ms`, required `<=5000ms` and passed.
- API post-ramp memory ratio: `1.416064`, required `<=1.10`.
- API container memory first/last/peak: `261095424 / 369727898 /
  437256192` bytes.
- API process RSS first/last/peak: `307769344 / 413544448 / 482349056` bytes.
- API process PSS first/last: `299011072 / 406998016` bytes.
- API process USS first/last: `295653376 / 402649088` bytes.
- Anonymous RSS first/last: `257699840 / 363474944` bytes; file RSS stayed
  at `50069504` bytes; map count changed from `2097` to `4286`.

The API file descriptors returned from `29` to `29` after peaking at `2037`.
The API one-core CPU p95/max were `101.81/127.65`. There were no OOMs,
unplanned restarts, pool timeouts, asynchronous-generator close races or
traceback/error log records in the final runtime evidence.

## PostgreSQL Terminal State

- Migration head: `20260720_0010`
- Tenant tables and FORCE RLS tables: `74/74`
- Append-only triggers: `57`
- Outbox: `PUBLISHED=223`, terminal `PENDING/CLAIMED/DEAD=0`
- Foreign-tenant visible rows: `0`
- Gate C SSE rows: alpha `3795` and beta `3792`; both maximum sequence values
  were `3937`
- Database roles `liyans_app`, `liyans_dispatcher` and `liyans_migrator` were
  non-superuser and had no RLS bypass flag

## Evidence

The raw manifest contains `110` entries, is `19432` bytes and has SHA256
`a2ad048f177729b8a8c09a10bc357d5660dcdd75e4bea2284da271512ffaf9f0`.
The run contains `111` files and `54758210` bytes. The redacted raw package
is an immutable GitHub Release asset of `5481915` bytes with SHA256
`d6b5454dad9c4b9471415211b5f212efc6f73c8f90358af2743f363f87362ea3`:
[download evidence package](https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-ninth-remediation-failed-20260814-993ed97-evidence-v1/gate-c-20260814T163148Z-993ed9719dfb-ninth-remediation-failed-evidence-v1.zip).
GitHub Release ID is `370734489` and asset ID is `514719132`; the asset digest
matches the package SHA256. The credential/JWT/PII scan passed and the secrets
directory is absent.
