# ADR 0026 A' Infrastructure Abort

Process Version: `Gate-C-11-v1.0`

## Decision

The A' arm of the ADR 0026 diagnostic was classified as `INFRA_ABORTED`.
The required 600-second recovery observation did not complete because the D:
evidence volume reached the hard disk-capacity redline at approximately 0.60
GiB free. This is an environment interruption, not a product failure and not
a Gate C result.

The A' Compose containers and network were stopped with Compose `down` without
the volume flag. The A' PostgreSQL volume, runtime volume, raw run directory
and all captured logs/results remain preserved. No historical image, volume,
Release, package or diagnostic snapshot was deleted, pruned or overwritten.

## Observed Boundary

The completed `ramp-200` stage recorded 400 SSE requests with zero failures.
The real Locust result was delivery p95/p99 `700/740 ms`. The monitor wrote 154
samples and its last sample was captured at
`2026-08-24T06:55:42.470602Z`; the fixed recovery window was incomplete.
The last observed sample reported API process RSS/USS/PSS
`249065472/237023232/241590272` bytes, FD `31`, zero lifecycle gauges, zero
active application PostgreSQL connections and Outbox `PUBLISHED=26`. These are
last observations only and are not a recovery conclusion.

The run is bound to source commit
`ff4f3b9d33ef608772f8c499d8e906e215bc0daf`, tree
`17cb9892a18f927f08ca3feb344b5024965eb9a0`, product source
`a57d0ce57427804ede3f3c620fda2a93b3a300ff`, Compose configuration SHA256
`c4357cd098f80521aa6ed74d747167a6a8ac9bad0e5d02862ef36ad12bc59de4`, and
the ADR 0026 profiling image digest recorded in the JSON evidence.

The raw run contains 25 files totaling 11,788,328 bytes. Their sizes and
SHA256 values are recorded in
`adr0026-aprime-infra-abort-raw-manifest.json`. The credentials file is
referenced only by hash; no credential, Token, identity header or PII is
published in this record.

## Consequences

This arm is invalid for A/measurement/A' comparison. It does not establish an
RSS owner, does not unfreeze P2, does not append `gate_c_attempts`, and does
not authorize a product remediation or formal Gate C replay. The formal state
remains `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`, and Gate D-G remain locked.

No new diagnostic run may start while the D: disk hard redline remains. A
future A' retry must use a new Compose project, run directory and fresh
PostgreSQL volume after an approved non-destructive environment action; this
incomplete arm must never be reused.
