# ADR 0031: Gate C Capacity Probe Temp Portability

Process Version: `Gate-C-12-v1.0`

- Status: Phase 0 test-harness repair; no acceptance conclusion
- Formal Gate C attempt: no
- Acceptance claim: no
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Root-cause domain: capacity monitor regression portability
- Failed push CI: Run `32826905086`
- Failed source SHA: `305d490561a98d115ca58d73d9711cf05f047097`
- Failed source tree: `0866eb41ac0679400f2e3b14a8ecdfe65928e2af`
- Product source SHA: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`

## Observed Failure

The first push CI for the Phase 0 infrastructure branch failed the same test in
the deterministic unit job and in the PostgreSQL full-regression job:

`test_gate_c_capacity_startup_snapshot_closes_monitor_race`.

The generated PowerShell probe assigned `$ResultsRoot = $env:TEMP`. The Ubuntu
GitHub runner's non-interactive PowerShell process exposed an empty `TEMP`
value. `Update-LatestCapacitySnapshot` consequently called
`[IO.Path]::GetFullPath("")`, which failed before the capacity-state assertions
ran. The unit job reported one failure. The PostgreSQL job reported `793`
passes, the same one failure and `91.81%` coverage. No PostgreSQL migration,
Keycloak integration, product behavior or coverage redline failed.

## Decision

Use `[IO.Path]::GetTempPath()` inside the generated probe and fail explicitly if
the platform API returns an empty value. Use that path for both `$ResultsRoot`
and the deliberately absent run directory. The Python regression removes
`TEMP` and `TMP` from the child process environment, proving the probe no longer
depends on either shell variable.

Do not change the production Gate C runner's required `ResultsRoot` parameter,
capacity state computation, monitor timing, cleanup path or `15/8/5 GiB`
policy. This repair is limited to the cross-platform test harness.

## Falsifiable Verification

The repair is rejected if any of the following occurs:

1. the focused test fails with `TEMP` and `TMP` absent;
2. the full deterministic unit suite fails on GitHub Ubuntu;
3. the PostgreSQL full regression or 90% coverage redline fails;
4. any test bypasses the real PowerShell function definitions; or
5. any product, workload, threshold or acceptance file changes with the repair.

The failed push run is immutable evidence and is not rerun as proof of the new
commit. A new push event must execute all eight jobs for the repaired head.

## Semantic Boundary

No migration `0001-0010`, RLS, `TenantContext`, SERIALIZABLE transaction, C12
authorization, frozen threshold, frozen workload, Outbox atomicity,
idempotency, lease, retry, partition ordering, signed cursor, durable replay,
memory behavior or acceptance aggregation changes. Gate D-G remain locked.
