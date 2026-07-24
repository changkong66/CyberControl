# Phase 7 Gate C Failed Evidence Analysis

## Decision

Gate C is FAILED for protected-main source 63d62f071176185da33c195dbdf682186b3e8c9e. The project remains
RELEASE_CANDIDATE; Gate D through Gate G remain locked. This file archives the
failed result and does not reinterpret it as accepted.

## Bound Source

- Source commit: 63d62f071176185da33c195dbdf682186b3e8c9e
- Source tree: c544c4a4ffb81eff0b79a3d38c2b06d7df1feb7a
- Formal run directory: D:\CyberControlAcceptance\phase7\gate-c\gate-c-20260724T120822Z-63d62f071176
- Evidence package: gate-c-20260724T120822Z-63d62f071176-failed-evidence-v1.zip
- Evidence package bytes: 1913634
- GitHub release asset: https://github.com/changkong66/CyberControl/releases/download/phase7-gate-c-failed-20260724-63d62f0/gate-c-20260724T120822Z-63d62f071176-failed-evidence-v1.zip
- Evidence package SHA256: ed3e3357f2a54368513cc0364416202d9fb2a086db95f5346184f72bb7b5d48c
- GitHub asset digest: sha256:ed3e3357f2a54368513cc0364416202d9fb2a086db95f5346184f72bb7b5d48c
- GitHub Release immutability: false; integrity is bound by the protected Git archive, Release tag and matching local/server SHA256
- Finalize tool: tests/load/gate_c/finalize.py
- JWT scan during finalization: passed
- Secrets directory present: False

## Passing Controls

- Peak active authenticated streams: 2000
- Sustained duration seconds: 1804
- HTTP 5xx rate: 0.0
- Unexpected disconnect rate: 0.0
- Duplicate final render: 0
- Cross-tenant leakage: 0
- Delivery latency p95/p99 ms: 965 / 1490
- Expired signed Keycloak Token rejected: 1
- Outbox DEAD: 0
- Pool acquisition timeouts: 0.0
- Database pool checked-out peak/capacity: 11.0 / 90.0
- API file descriptor max/utilization: 2043.0 / 0.001948
- Host CPU p95/max percent: 29.6 / 55.0
- OOM or unplanned restart observations: 0
- Foreign-tenant runtime visibility: 0
- Invalid cursor acceptance: 0

## Failed Frozen Checks

- Global failed checks: all_stages, memory_recovery, outbox_p95, outbox_p99
- Stage failed checks: gate-2000.connection_success, gate-2000.duplicate_replay_suppression, gate-2000.event_loss, gate-2000.publisher, gate-2000.reconnect
- Connection success rate: 0.9925558312655087; required at least 0.995
- Reconnect and Last-Event-ID replay success: 0.9852216748768473; required at least 0.999
- Committed event loss: 590; required 0
- Duplicate replay suppression: 88/100; required all attempts suppressed
- Publisher failures: 1; required 0
- Outbox lag p95/p99 ms: 10522.787 / 11662.747; required at most 2000 / 5000
- Post-ramp memory ratio: 1.933333; required at most 1.10

## Operational Finding

The run reached the 2,000-stream target on a single host but failed frozen
reliability and recovery thresholds. Runtime shutdown diagnostics captured SSE
async-generator cancellation defects, including ContextVar reset from a
different context, SQLAlchemy cancellation during connection termination and
non-checked-in connection cleanup. Those observations require a separate
remediation PR before any Gate C rerun.

## Next Boundary

Open a scoped remediation PR for SSE cancellation/context cleanup, replay safety
and Outbox-lag recovery. Do not change Gate C thresholds and do not start Gate D
until a fresh Gate C execution from a new protected-main baseline passes.
