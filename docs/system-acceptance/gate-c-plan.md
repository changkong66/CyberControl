# Phase 7 Gate C Authenticated SSE Acceptance Plan

Gate C validates 2,000 authenticated Topic 4 SSE connections from an immutable
protected-main build. It is not a production capacity certification.

The frozen thresholds are in `tests/load/gate-c-thresholds.v1.json`; the fixed
traffic shape is in `tests/load/gate-c-workload.v1.json`. Any change to either
file after an execution invalidates that execution and requires a new protected
PR before another run.

Execution is serial: 20, 200, 500, 1,000 and 2,000 connections. The final stage
must sustain 2,000 users for thirty minutes, followed by ten minutes of resource
recovery observation. The runner uses two tenants, ten real Keycloak subjects
per tenant, signed Bearer tokens and the existing Topic 4 stream. It never sends
`X-Tenant-ID`, `X-Subject-Ref`, role or scope identity headers.

Probe events are committed through the authenticated Topic 3 SSE publish API
with a `topic4.` event type so the existing Topic 4 projection is exercised.
Periodic real Topic 3 workflows provide transactional Outbox traffic. Each
stage first completes its full stable window and then performs one forced
disconnect/reconnect observation. A disjoint deterministic five percent sample
reconnects from the stage baseline cursor to force real duplicate replay; the
recorder must suppress those duplicates rather than count them as final renders.
Invalid cursors and tenant isolation are measured separately. The workflow
command uses the frozen `zh-CN` locale; five percent of client slots receive a
deterministic 100 ms slow-consumer delay, which retains processing headroom
below the 5 events/second/tenant burst rate.

The publisher retains one genuinely signed Keycloak token until its `exp` plus
the verifier clock-skew grace and verifies that the expired token is rejected
with 401. Token signing latency and SSE connection-establishment latency are
aggregated separately. Runtime pool capacity, checked-out connections,
acquisition-timeout counters, container file descriptors, memory, network I/O
and restart state are sampled throughout the run.

Raw tokens and local fixture passwords are stored only below the external run
directory's `secrets` folder and are deleted before evidence finalization.
Evidence contains only redacted metrics, hashes and immutable runtime identity.
