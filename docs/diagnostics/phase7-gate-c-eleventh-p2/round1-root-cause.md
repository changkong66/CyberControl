# Gate C Eleventh P2 Root-Cause Round 1

Process Version: `Gate-C-11-v1.0`

## Scope

This is a non-formal 200-stream diagnostic. It does not claim 2,000-client
scale or Gate C acceptance. A, B and A' each used real Keycloak issuance, two
tenants, twenty provisioned subjects, a unique Compose project and a fresh
PostgreSQL volume. Each frozen `ramp-200` stage was followed by an additional
ten-minute read-only recovery monitor. No formal finalizer was called.

## Result

The round-1 hypothesis was rejected. Removing `PYTHONMALLOC=malloc` restored
CPython pymalloc while retaining the process-start jemalloc preload and its
one-arena decay configuration. This reduced the jemalloc
active-minus-allocated growth from `9,214,816` bytes in A and `7,641,872`
bytes in A' to `1,287,688` bytes in B. It did not materially reduce total
memory:

| Arm | Cgroup ratio | RSS ratio | Anonymous RSS delta | Final API pool gauge |
| --- | ---: | ---: | ---: | ---: |
| A | 1.195388 | 1.143331 | 31,506,432 | 0 |
| B | 1.213483 | 1.126844 | 28,217,344 | -1 |
| A' | 1.185319 | 1.137403 | 30,162,944 | 0 |

B therefore transferred most small-object accounting outside jemalloc rather
than releasing enough process memory. Its cgroup ratio was worse than both
controls, and the API pool gauge remained `-1` throughout recovery even though
PostgreSQL reported idle application connections and zero pool timeouts. The
candidate was reverted and was not escalated to a 2,000-stream diagnostic.

All three stages passed their frozen stage controls. Each recorded 400
connection/reconnect requests with zero failures. Terminal subscriber, queue
and replay gauges were zero and FDs ended at 29. The result rejects only the
allocator-domain explanation; it does not weaken those passed controls.

## Next Measurement

Round 2 must run the existing opt-in fixed-cardinality diagnostics from process
start on the unmodified parent allocator. It must compare tracemalloc current
and peak allocations, tracked object types, task/frame inventory, process maps
and jemalloc totals before load, at peak and through recovery. The purpose is
to determine whether the remaining live allocated bytes have reachable Python
owners or whether the dominant residual is native allocator high-water state.

## Evidence Index

- A: `gate-c-diagnostic-20260823T172157Z`
- B: `gate-c-diagnostic-20260823T174148Z`
- A': `gate-c-diagnostic-20260823T180320Z`
- Comparison: `round1-comparison.json`
- Local package SHA256:
  `24f9affca5033099bdcd8bae3622dc2ea00fef8c3bf844df6701fa1f930e2d2a`
- Immutable Release:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-aba-round1-20260824-v1

The formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; Gate D-G remain
locked.
