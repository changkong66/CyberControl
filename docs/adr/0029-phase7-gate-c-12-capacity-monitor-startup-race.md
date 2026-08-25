# ADR 0029: Phase 7 Gate C Twelfth Capacity Monitor Startup Race

Process Version: `Gate-C-12-v1.0`

- Status: Phase 0 infrastructure repair; no acceptance conclusion
- Formal Gate C attempt: no
- Acceptance claim: no
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Root-cause domain: capacity monitor startup ownership
- Capacity policy revision: `Gate-C-12-capacity-v1.1`

## Observed Failure

The first ADR 0026 calibration control on source
`9380e84eaeb5d77d692e35fca4db31dc0cf52a1f` stopped before any service or
load started. `Assert-CapacityAdmission` stored the synchronous host snapshot
as `lastCapacitySnapshot`, but that snapshot did not contain `state`. The
capacity monitor process had started but had not yet atomically written
`capacity-latest.json`. `Assert-CapacityMonitorHealthy` therefore read the
missing property under PowerShell StrictMode and raised:

`The property 'state' cannot be found on this object.`

This is a deterministic ownership race between the runner's startup snapshot
and the monitor's first sample. It is not a product, load, PostgreSQL, Keycloak
or Gate C acceptance failure. The run is classified `INFRA_ABORTED`, is not
added to `gate_c_attempts`, and leaves the formal state unchanged.

## Decision

Make the synchronous host snapshot conform to the same capacity-state contract
as monitor samples. It computes `NORMAL`, `WARNING` or `HARD_STOP` from the
unchanged `8 GiB` warning and `5 GiB` stop lines and records the schema,
thresholds and state before the monitor process can be observed.

Read state through an explicit validator. A missing or unknown state now fails
closed with a stable format error instead of an incidental StrictMode property
exception. A malformed atomically published monitor sample also fails closed.
No wait, retry, timeout, grace period, cleanup action or acceptance statistic is
changed.

## Falsifiable Verification

The regression executes the real PowerShell function definitions and proves:

1. `16`, `7` and `4 GiB` produce `NORMAL`, `WARNING` and `HARD_STOP`;
2. the startup snapshot remains valid when no `capacity-latest.json` exists;
3. a snapshot without `state` produces the explicit fail-closed error.

The next calibration must use a new source SHA, image lock, Compose project,
run directory and fresh PostgreSQL volume. Any recurrence before service start,
any invalid state accepted, or any change to the `15/8/5 GiB` policy rejects
this repair.

## Evidence Index

- Run ID: `gate-c-diagnostic-20260825T042339Z`
- Raw directory:
  `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c12-phase0-probe-calibration-9380e84-20260825/A/gate-c-diagnostic-20260825T042339Z-9380e84eaeb5`
- Corrected raw manifest SHA256:
  `337bfa712a03ac860566cf72d45fd2fb202996b6a107286b9f740e1261d67257`
- Immutable package SHA256:
  `f0f234952c84dc8794e7ddf916ed9232770cffc1289ac4979654075d32530db6`
- Repository package reference:
  `docs/diagnostics/phase7-gate-c-twelfth-phase0/capacity-monitor-startup-race.json`

The first external manifest remains preserved. Its individual file hashes are
valid, but its `total_bytes` aggregate is invalid because the generating
PowerShell projection did not enumerate ordered-hashtable properties. The
append-only `v2` manifest corrects only that aggregate and is authoritative.

## Semantic Boundary

This repair changes only Gate C Windows infrastructure tooling and its test.
It does not modify migrations `0001-0010`, RLS, `TenantContext`, SERIALIZABLE
transactions, C12 authorization, frozen thresholds, frozen workload, Outbox
atomicity, idempotency, lease, retry, partition ordering, signed cursors,
durable replay or product memory behavior. Gate D-G remain locked.
