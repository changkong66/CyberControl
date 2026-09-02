# CyberControl Gate C Twelfth ADR-0033 Execution Boundary

Process Version: `Gate-C-12-v2.0`

Use only the real protected repository, exact source-bound images, Docker,
PostgreSQL, Keycloak-issued tokens and immutable evidence. Historical records
are append-only. Do not fabricate a source, CI run, image, token, metric,
package, owner or decision. Gate D-G remain locked.

## Current Verified Boundary

- Protected main: `b4b3c6eaf00f4c9f013fad8acfd2f0d9d2860211`
- Tree: `f21426de47935f043055519558bb0816095b509a`
- Protected-main CI: Run `33582128563`, 8/8
- Product source: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Last formal Gate C source: `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Frozen threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Formal attempts: 12
- `baseline_history`: 30 entries in this status snapshot

The eleventh formal run remains M2. Every stage, Outbox and zero-tolerance
control passed; the only failed control was API cgroup recovery ratio
`1.417200 > 1.10`. No accepted RSS owner exists.

## Immutable Predecessor Decision

ADR-0032 D1/S completed 2,000/2,000 real TLS connections, a 300-second idle
window and a 600-second recovery window. Its rejected cross-domain equation
produced:

```text
RssAnon             57,323,520
jemalloc resident   57,675,776
difference            -352,256
```

This remains `DESIGN_REJECTED`, design-failure ordinal two under
`Gate-C-12-v1.0`. It is not an infrastructure abort, owner conclusion or
permission to modify product code. ADR-0032 and all v1 evidence remain
immutable.

PR #110 closed that status as `841020d...`; its receipt SHA256 is
`09cbab9803ea6e984fc3e94ca4166ee0b5fe5f1b718a3d1e5a4cdf54168d6733`.
The immutable closure package SHA256 is
`9e1b988662ca8f59c59fc3de65ac49278c19e866bab1a66565b4d7a736687efe`.

## ADR-0033 Authorization

PR #111 passed push/PR/main Runs
`33581087504/33581119453/33582128563` at 8/8 and merged as the current main.
Its immutable receipt SHA256 is
`b01073c7191b919a3826940ef3027f44c645ea11a35f5a8bb11eedb75f844c96`.

ADR-0033 supersedes only ADR-0032's invalid measurement equation and
diagnostic stop scope. It introduces three orthogonal ledgers:

1. cgroup physical: current, anon, file, kernel and signed reconciliation;
2. Linux process: VmRSS, RssAnon, RssFile, RssShmem, PSS, USS and signed
   process reconciliation;
3. jemalloc accounting: allocated, active, resident, mapped, metadata,
   retained and arena count.

Cross-domain differences are signed, non-additive diagnostic signals. A
negative difference alone is not a structural failure and cannot prove an
owner.

## Mandatory Execution Order

1. Squash Merge this status PR, require protected-main 8/8, and generate its
   external post-merge receipt. Do not open an immediate recursive status PR.
2. From the resulting exact main, create one diagnostic-only implementation
   PR. Keep all capability default-off and preserve existing metrics and
   formal aggregation.
3. Implement five-sample bracketed variable `D` capture in this order:
   `process_before -> cgroup_before -> jemalloc epoch/stats -> cgroup_after ->
   process_after`.
4. Record five samples at 50 ms spacing. Each sample must complete within
   250 ms and the burst within two seconds. Retain median, min, max, MAD,
   before/after brackets and timestamps.
5. Read jemalloc `mapped` and `metadata`; enforce only same-domain allocator
   identities and process reconciliation. Do not rebuild a cross-domain
   physical partition.
6. Repair `SEQUENCE_FAILURE_REASON_MASKING` with safe property lookup and a
   stable fallback. Preserve the child classification and primary reason.
7. Require focused tests, all local gates, push/PR/main 8/8 and an immutable
   implementation closure receipt.
8. Generate fresh exact-main normal and diagnostic image locks, build receipt,
   execution context, capacity snapshot and D1-only readiness receipt.
9. Execute two independent `A/D/A'` sequences. Every arm uses a fresh Compose
   project, network and PostgreSQL volume and runs 2,000 TLS connections at
   concurrency 200 and 50/s, with 300-second idle and 600-second recovery.
10. Archive and verify each arm before mandatory cleanup. Recheck capacity and
    zero-running state before the next arm.

## D1 Gates

- A/A' drift for connection p95, delivery p95, CPU p95 and event-loop lag p95
  is at most 10%.
- D/control median for those metrics is at most 1.10.
- RSS interference is at most `max(8 MiB, 10% * abs(control RSS delta))`.
- Sample completeness is exactly 1.0 and every zero-tolerance control passes.
- Process RSS reconciliation is at most `max(1 MiB, 2% of VmRSS)`.
- Cgroup-current and RssAnon spread is at most
  `max(8 MiB, 10% of the five-sample median)`.
- Both independent sequences must pass. One pass is insufficient.

Classify failures only as `DESIGN_REJECTED`, `OWNER_UNRESOLVED` or
`INFRA_ABORTED` according to ADR-0033. One structural design failure stops new
design under v2. The same infrastructure cause may retry the interrupted level
at most twice and never increments `gate_c_attempts`.

## Locked Scope

- D2 remains locked until both D1 sequences pass.
- Product remediation remains locked until two independent D2 runs establish
  a strong owner or a separately merged weak-admission ADR.
- No PreflightSmoke or formal Full Gate C.
- No threshold, workload, recovery-window or statistical change.
- No migrations 0001-0010, RLS, TenantContext, SERIALIZABLE, C12, Outbox,
  idempotency, partition order or product-contract change.
- No forced GC, allocator purge, `malloc_trim`, restart, periodic cleanup,
  background janitor or inflated baseline.
- No Gate D-G work.

`gate_c_attempts` remains 12 because no formal Full occurred. Only a future
same-run Full PASS followed by immutable evidence and status closure can reach
M3.
