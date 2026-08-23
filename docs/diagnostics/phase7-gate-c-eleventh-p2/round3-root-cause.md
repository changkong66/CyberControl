# Gate C Eleventh P2 Measurement-Design Round 3

Process Version: `Gate-C-11-v1.0`

## Decision

ADR 0025's measurement design is rejected because the profiler materially
changed both the workload and the RSS residual it was intended to explain. The
complete traceback diff is real, but it is not admissible evidence for a
product behavior change. P2 product-code changes remain frozen.

This was a diagnostic A/measurement/A' experiment, not a formal Gate C attempt.
It used real Keycloak issuance, two tenants, twenty provisioned subjects, the
frozen 200-stream stage, unique Compose projects, fresh PostgreSQL volumes and
the fixed 300-second idle plus 600-second recovery windows. It made no
acceptance claim and did not update `gate_c_attempts`.

## Execution Boundary

The first A attempt stopped before load because the isolated worktree virtual
environment lacked the locked `load` extra and therefore `psutil`. It is
classified `INFRA_ABORTED`; no load or checkpoint ran. Its container/network
resources and temporary credentials were removed, while its PostgreSQL volume
and abort record were preserved.

After synchronizing the locked environment, A2 and A' independently completed
the same 200-stream stage and fixed recovery. A' used a full no-cache rebuild;
its image digest differs from A2 as expected, while source commit, source tree,
lock files and product content remain bound to the same protected main.

## A / Measurement / A' Results

| Metric | A2 | Measurement | A' | Control median |
| --- | ---: | ---: | ---: | ---: |
| Stage passed | yes | no | yes | n/a |
| Connection p95 (ms) | 657 | 17,989 | 689 | 673 |
| Delivery p95 (ms) | 44 | 1,175 | 47 | 45.5 |
| Delivery p99 (ms) | 208 | 4,048 | 184 | 196 |
| API CPU p95 (one-core units) | 25.18 | 101.98 | 25.15 | 25.165 |
| Monitor completeness | 194/194 | 187/192 | 194/194 | 1.0 |
| Sustained seconds | 304 | 285 | 304 | 304 |
| Process RSS delta (bytes) | 31,113,216 | see below | 30,113,792 | 30,613,504 |
| FD baseline/recovery/peak | 21/29/230 | 21/29/233 | 21/29/230 | n/a |

The measurement connection p95 is `26.7296x` the control median and delivery
p95 is `25.8242x` the control median. Both exceed ADR 0025's maximum `+10%`
interference. API CPU p95 is `4.0523x` the control median. Five monitor samples
were incomplete, and the stage did not sustain the required 304 seconds.

## RSS Disproof

The synchronized checkpoint pre-capture values grew from `257,576,960` to
`316,911,616` bytes, a `59,334,656`-byte RSS delta. The A2/A' control median is
`30,613,504` bytes. The measurement delta differs by `28,721,152` bytes; ADR
0025 permitted only `max(8 MiB, 10% of control) = 8,388,608` bytes.

The external measurement monitor reports a smaller endpoint delta because its
baseline endpoint overlaps the baseline checkpoint's own memory increase. That
sampling contamination is itself evidence that the design does not provide an
independent baseline. The synchronized pre-capture values are used for the
formal interference check.

The baseline and recovery checkpoints completed in `5.649232` and `7.326742`
seconds. They generated `5,241` complete traceback groups. Tracemalloc current
growth was `6,709,457` bytes, while jemalloc allocated/active/resident growth
was `53,598,568/64,643,072/62,009,344` bytes. These values cannot be assigned
to a production owner because enabling tracemalloc from process start changed
CPU, latency, monitor behavior and the residual itself beyond the predefined
limits.

## Preserved Semantics

All completed arms preserved connection and reconnect/replay success at `1.0`.
Committed loss, duplicate final render, cross-tenant leakage, HTTP 5xx and
Outbox `DEAD` remained zero. Terminal subscribers, queues, replay buffers,
replay caches and replay tasks were zero. API pool gauges returned to zero;
PostgreSQL had no active application session at the final monitor sample. No
OOM or restart occurred.

These controls show that the rejected profiler did not weaken the protected
functional and security semantics. They do not turn the diagnostic into Gate C
acceptance and do not prove the formal 2,000-stream RSS recovery control.

## Why No Candidate Is Permitted

The allocation output contains plausible Python and library traceback groups,
including SQLAlchemy, asyncpg, streaming and task-queue paths. Selecting one of
them would be speculative because the measurement arm is not behaviorally
equivalent to its controls. Changing caches, pools, allocator settings,
streaming ownership or decay based on this data would violate the predeclared
causality rule.

Under ADR 0025's stop condition, the correct outcome is to archive the
measurement-design failure and keep P2 frozen. Another product candidate,
formal Gate C replay or Gate D work is prohibited until a newly reviewed
low-interference measurement design exists and is independently authorized.

## Evidence Index

- Protected main: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Protected-main tree: `963fcf73113e39a1e5868fae3957f4adfc102a4c`
- Product source: `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Protected-main CI:
  https://github.com/changkong66/CyberControl/actions/runs/32667597681
- A infra abort:
  `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c-11-p2-adr0025-aba-20260824/A/gate-c-diagnostic-20260823T213855Z-a57d0ce57427`
- A2 control:
  `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c-11-p2-adr0025-aba-20260824/A2/gate-c-diagnostic-20260823T214537Z-a57d0ce57427`
- Measurement arm:
  `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c-11-p2-adr0025-aba-20260824/measurement/gate-c-diagnostic-20260823T220844Z-a57d0ce57427`
- A' control:
  `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c-11-p2-adr0025-aba-20260824/A-prime/gate-c-diagnostic-20260823T223248Z-a57d0ce57427`
- Structured comparison: `round3-comparison.json`
- Immutable package reference: `round3-package-reference.json`
- Immutable package SHA256:
  `10fb9477558ad203e1163198d8e28a941d16d922b6919d2711fdf6f69e22d92b`
- Immutable Release:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-adr0025-measurement-rejected-20260824-v1

The formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; Gate D-G remain
locked. No formal replay or acceptance decision was started.
