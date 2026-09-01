# Gate C12 Target Two D1/S Design Rejection

Process Version: `Gate-C-12-v1.0`

## Decision

ADR-0032's final low-interference design is `DESIGN_REJECTED`. This is design
failure two under the accepted ADR. New diagnostic-design work under
`Gate-C-12-v1.0` is stopped. D2 attribution, product remediation,
PreflightSmoke, formal Full Gate C and Gate D-G remain locked.

This was not a formal Gate C run. `gate_c_attempts` remains 12, product source
remains `a57d0ce57427804ede3f3c620fda2a93b3a300ff`, and the formal state remains
`PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.

## Valid Execution Boundary

The run used exact main `260913a964ee8afbdbfbc073e89090f551b7cc67`, tree
`8748b79cf25d31ea158825312ac19eb7b1107e27`, diagnostic image digest
`sha256:0ef56e8b3ccdab3e4ced3abc1c93dcb270088973f6e56a50e91ee7c3ccea6d88`,
image-lock SHA256 `c79df22c2e78b37f4292745d1bd8b0e7438172dea504d510749cfb8daff1e8de`
and build-receipt SHA256
`29b3401895797a3d050e51f3a4008136e713c292c4298413e2577643171b7843`.

The A control arm emitted its source-bound readiness marker, completed the
fixed 300-second idle and 600-second recovery windows, and established 2,000
of 2,000 real TLS PostgreSQL connections with sample completeness 1.0. It had
no OOM or unplanned restart. The failure therefore occurred after readiness
and is not `INFRA_ABORTED`.

## Structural Failure

The baseline physical partition was valid:

```text
RssAnon                    49,987,584
jemalloc allocated         45,875,680
jemalloc active            46,612,480
jemalloc resident          49,811,456
RssAnon - resident            176,128
```

The recovery partition was not valid:

```text
RssAnon                    57,323,520
jemalloc allocated         52,889,000
jemalloc active            54,329,344
jemalloc resident          57,675,776
RssAnon - resident           -352,256
```

ADR-0032 requires every mutually exclusive physical component to be
nonnegative. The real recovery snapshot violated that invariant and the arm
correctly failed closed with `BoundedMemoryInventoryRejected`. No bytes were
clamped, rounded or reclassified, and no RSS owner conclusion is authorized.

## Append-Only Correction

The arm package and classification are authoritative. The sequence wrapper
then attempted to read a missing `reason` property from the arm summary under
PowerShell strict mode. Its own failure summary consequently records that
secondary wrapper error instead of the primary ledger rejection. Historical
files remain unchanged; append-only addendum SHA256
`a000fd31c55c0407efa4c0e2814f92ee3edb96a5b357af0686fc042d541b23b2`
binds the correction. The secondary defect is tracked as
`SEQUENCE_FAILURE_REASON_MASKING`; it did not change the primary
`DESIGN_REJECTED` classification.

## Evidence

- Arm run: `adr0032-s-a-20260901T155200Z-f160628c`; package SHA256
  `a138ac27a8d899a7d8ad27e2dc2e05b1d6fb0e9add0d53e5fcc72e1631fcd475`.
- Sequence: `adr0032-s-sequence-20260901T155159Z-3637d0e0`; package SHA256
  `ca2c99b3d2a2a817d5672e63a86d402afd48c13c945cde5612e856b76cf8ed06`.
- Complete outer package: 35,912 bytes, SHA256
  `94bfd0a483f56a4789588c8fd2968b140acbcb1142744730cec0cb239f32a093`.
- Immutable GitHub prerelease:
  [phase7-gate-c12-target2-d1-s-design-rejected-20260902-260913a-v1](https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c12-target2-d1-s-design-rejected-20260902-260913a-v1).
- Local and server asset size and SHA256 match exactly.

The run-specific Compose project, network, PostgreSQL volume, TLS private
material and archived intermediates were removed only after package
verification. Zero project resources remain; no prune or historical-volume
deletion occurred.
