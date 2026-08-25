# ADR 0027: Phase 7 Gate C Twelfth Capacity Policy Revision

Process Version: `Gate-C-12-v1.0`

Capacity Policy Revision: `Gate-C-12-capacity-v1.1`

- Status: Operational policy revision; no acceptance conclusion
- Formal Gate C attempt: no
- Acceptance claim: no
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Supersedes: the `28 GiB` Phase 0 capacity admission rule for new runs only
- Historical rule: preserved in all prior metadata and evidence

## Decision

The host free-space admission line for new Gate C Phase 0, diagnostic,
preflight and formal-run setup is reduced from `28 GiB` to `15 GiB` by explicit
operator authorization. This revision does not change the frozen thresholds,
the workload, the aggregation method, the evidence retention policy or any
product, security, identity, database, Outbox or streaming semantic.

Every new run records both `process_version` and this capacity policy revision,
as well as the measured free bytes and GiB at startup. Historical runs retain
their original capacity rule and are never relabeled.

## Runtime Protection

- `<15 GiB`: reject run setup before creating a new Compose project or
  PostgreSQL volume.
- `<8 GiB`: write the measured capacity guard state and block stage escalation
  pending an explicitly authorized, non-destructive cleanup. A five-second
  guard records the warning continuously; the runner does not delete
  historical images, volumes, containers, releases or evidence.
- `<5 GiB`: hard-stop the run through the existing failure/diagnostic cleanup
  path. The guard sends a normal stop request only to one-off containers owned
  by the current Compose project, then preserves the run directory and
  evidence. It never removes a volume, image, Release or historical object.

The `8 GiB` and `5 GiB` protections remain stricter runtime safeguards; lowering
the admission line is not permission to consume the remaining space without
control. A capacity stop is an infrastructure interruption, not a Gate C
acceptance result and not a `gate_c_attempts` entry.

## Audit Binding

The runner writes `capacity_policy_revision`, `capacity_admission_gib`,
`capacity_warning_gib`, `capacity_stop_gib`, `capacity_at_start` and the latest
capacity snapshot into execution, environment/failure and final metadata. The
continuous guard adds an append-only sample stream and explicit warning,
hard-stop and monitor-exit records. This ADR is append-only. A later policy
change must create a new ADR and revision.

This revision does not authorize Gate D-G, soak, disaster recovery, provider
acceptance, production deployment or any product work.
