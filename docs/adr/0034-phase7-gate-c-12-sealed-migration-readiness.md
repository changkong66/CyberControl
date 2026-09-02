# ADR-0034: Gate C 12 Sealed Migration Evidence Readiness

Process Version: `Gate-C-12-v2.0`

- Status: Candidate until Squash Merge and protected-main quality gates pass 8/8
- Date: 2026-09-02
- Decision domain: non-acceptance infrastructure evidence compatibility
- Product source SHA: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Engineering parent SHA: `6a74f95d90f9d95b09bad3bc8d2243af2016f209`
- Engineering parent tree: `e1e7b6d2656b651f7a270e4220a9cf2eec78e066`
- Protected-main parent CI: `33592376710`, 8/8

## Context

The Docker storage migration was executed, validated and sealed under
`Gate-C-12-v1.0`. Its immutable report must retain that process version.
Relabeling the historical report as v2 would break append-only audit semantics.

The v2 D1 readiness implementation incorrectly required the migration report
itself to declare `Gate-C-12-v2.0`. No truthful artifact could satisfy that
condition: a newly labeled document would not be the original migration
evidence, while the original evidence correctly remains v1.

## Decision

The v2 readiness gate accepts only the sealed v1 migration report and validates
its complete safety boundary before binding the report by SHA-256. The report
must have:

- schema `cybercontrol.docker-migration-validation.v1` and process version
  `Gate-C-12-v1.0`;
- classification `NON_ACCEPTANCE_INFRASTRUCTURE_VERIFICATION` and result
  `MIGRATION_VALIDATED`;
- passing environment checks and zero running containers at validation time;
- `formal_volume_result=PASS`, no formal state change and no Gate C attempt;
- no unexplained object difference;
- the exact five hash-bound source documents used by the migration validator.

The newly generated readiness receipt remains `Gate-C-12-v2.0`, records the
sealed migration process version explicitly and binds the complete historical
report by SHA-256. The digest and 13/13 formal-volume result must also match the
append-only migration binding in the accepted status snapshot. It does not
rewrite or supersede the migration evidence.

## Boundaries

This decision changes only D1 readiness evidence validation. It does not alter
Docker state, product source, migrations, business or security semantics,
thresholds, workload, formal state or `gate_c_attempts`. It authorizes no D2,
product remediation, PreflightSmoke, Full Gate C or Gate D-G work.

## Verification

Focused tests must prove that the real sealed migration report passes and that
process relabeling, failed volume validation, failed environment checks,
running containers, unexplained differences and invalid source hashes are all
rejected. Push, pull-request and protected-main quality chains must pass 8/8
before a new source-bound image lock or D1 readiness receipt is generated.
