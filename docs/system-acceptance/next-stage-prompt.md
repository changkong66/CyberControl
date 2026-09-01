# CyberControl Gate C Twelfth D1 Design Rejection Closure

Process Version: `Gate-C-12-v1.0`

Use only the real protected repository, GitHub Actions, source-bound images,
Docker, PostgreSQL, Keycloak-issued tokens and immutable evidence. Do not
fabricate a source, CI run, image, token, volume, metric, package, owner or
decision. Historical evidence is append-only. Gate D-G remain locked.

## Audited Parent Boundary

- Verified protected main represented by this snapshot:
  `44ff28af5b54b574aa8a6fd3f62f2d258244fd74`
- Tree: `e72cab3d31f83a6071141623661b08fb9e48eed6`
- Protected-main CI: Run `33533885658`, 8/8
- Product source: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Last formal Gate C source: `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Frozen threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Formal state:
  `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Formal attempts: 12
- `baseline_history`: 29 entries after this status snapshot, ending at PR #109

The eleventh formal run remains M2. All workload stages, Outbox and
zero-tolerance controls passed; the only failed control was API cgroup recovery
ratio `1.417200 > 1.10`. No accepted RSS owner exists.

## Trusted Readiness Boundary

PRs #105-#108 closed target-two governance and corrected only diagnostic
orchestration/readiness tooling. All push, pull-request and protected-main
chains passed 8/8 and each merge has an immutable post-merge closure receipt.

Exact source `260913a964ee8afbdbfbc073e89090f551b7cc67`, tree
`8748b79cf25d31ea158825312ac19eb7b1107e27`, passed
`GATE_C12_TRUSTED_FOUNDATION_VERIFIED_D1_READY` with scope `D1_ONLY`:

- normal lock SHA256:
  `0c366407ee1baeaa85a9e8c87f4bc529d2618734749169b2e1780db5c9a20f58`
- diagnostic lock SHA256:
  `c79df22c2e78b37f4292745d1bd8b0e7438172dea504d510749cfb8daff1e8de`
- build receipt SHA256:
  `29b3401895797a3d050e51f3a4008136e713c292c4298413e2577643171b7843`
- readiness receipt SHA256:
  `6cb60d55e8ab21c008b82d34828f656de11b24a80c62bcbea87977fd0e095609`
- readiness Release/package:
  `380635279` /
  `8bd3be496b0ca0d137812aef887eb652783f9a239eeb9a0dfa71197966e2f961`

This proves that the D1 failure below is not caused by stale source, image
mismatch, missing readiness, Docker migration or capacity admission.

## Binding D1 Decision

D1/S sequence `adr0032-s-sequence-20260901T155159Z-3637d0e0`, arm
`adr0032-s-a-20260901T155200Z-f160628c`, completed:

- 2,000 requested and 2,000 successful real TLS connections;
- 300-second idle and 600-second recovery windows;
- sample completeness `1.0`;
- source-bound instrumentation-ready evidence;
- zero OOM and zero unplanned restart.

The accepted physical ledger failed its nonnegative-partition invariant:

```text
Recovery RssAnon              57,323,520
jemalloc resident             57,675,776
non_jemalloc_anon               -352,256
```

The arm failure is `BoundedMemoryInventoryRejected`. The binding classification
is `DESIGN_REJECTED`, design-failure ordinal two. It is not `INFRA_ABORTED` and
not `OWNER_UNRESOLVED`. No RSS owner, owner share or remediation prediction may
be inferred from this run.

ADR 0032 states that its structural failure is the second and final design
failure under `Gate-C-12-v1.0`. New diagnostic-design work under this process
version is stopped. Do not run a second S sequence, R/P/F, L1, L2, D2,
remediation validation, PreflightSmoke or formal Full.

## Immutable Evidence

Design-rejection Release `380653216` contains the 35,912-byte package with
matching local/server SHA256
`94bfd0a483f56a4789588c8fd2968b140acbcb1142744730cec0cb239f32a093`.
Nested arm and sequence package SHA256 values are
`a138ac27a8d899a7d8ad27e2dc2e05b1d6fb0e9add0d53e5fcc72e1631fcd475`
and `ca2c99b3d2a2a817d5672e63a86d402afd48c13c945cde5612e856b76cf8ed06`.

Evidence PR #109 passed push/PR/main Runs
`33531776126/33532803157/33533885658` at 8/8 and Squash Merged as the parent
main above. Its post-merge closure receipt SHA256 is
`239ec2f0cdc64548bfc1ca64557ac90625e9f1edbdde5cdef5f475206f2dfe9a`.

The sequence wrapper later read a missing `reason` property and masked the
primary arm error in its own summary. Append-only correction evidence records
`SEQUENCE_FAILURE_REASON_MASKING`; it does not change the classification. Any
future process version must repair this P1 defect and add a regression test
before authorizing execution.

## Only Allowed Next Scope

1. Squash Merge this D1 design-rejection status PR.
2. Require its protected-main Release Quality Gates to pass 8/8.
3. Generate the status PR's external post-merge closure receipt and preserve
   its SHA256 without recursively opening another immediate status PR.
4. Reconfirm product source, formal state, 12 attempts, Docker zero-running
   state, capacity and historical formal volumes.
5. Submit a separate governance proposal only if the project owner chooses to
   define a new process version. Such a proposal must preserve all historical
   classifications and cannot retroactively relax ADR 0032.

A future governance proposal is not diagnostic authorization. Before any new
execution it must explicitly define a new process version, a replacement ADR,
the physical-ledger reconciliation/noise model, sample-clock alignment,
observer-interference gate, failure budget, evidence schema and migration from
the old read-only evidence. It must pass push/PR/main 8/8 and receive its own
external closure receipt.

## Locked Scope

- No third diagnostic design under `Gate-C-12-v1.0`.
- No D1 continuation or D2 attribution.
- No product behavior change or lifecycle remediation.
- No weak-admission addendum because no trusted owner data exists.
- No PreflightSmoke or formal Gate C Full.
- No threshold, workload, recovery-window or statistical change.
- No migration 0001-0010, RLS, `TenantContext`, SERIALIZABLE, C12, Outbox,
  idempotency or partition-order change.
- No force GC, allocator purge, restart, pool disposal, periodic clearing,
  background janitor or inflated baseline.
- No Gate D-G work.

`gate_c_attempts` remains 12 because no formal Full occurred. The formal state
remains `PHASE7_GATE_C_FAILED_GATE_D_LOCKED`. Only a future same-run Full PASS,
followed by immutable evidence and status closure, can reach M3.
