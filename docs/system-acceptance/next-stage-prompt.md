# CyberControl Phase 7 Gate C P2 Round 4 Diagnostic Archive Closure

Process Version: `Gate-C-11-v1.0`

Work only from real protected-main, GitHub Actions, Docker, PostgreSQL,
Keycloak-issued Tokens and immutable evidence in
`C:/Users/wch06/Documents/CyberControl`. Do not fabricate source, tests, CI,
Tokens, images, volumes, metrics, packages or acceptance decisions. Gate D-G
remain locked.

## Current Audited Boundary

- Verified protected-main engineering baseline:
  `ff4f3b9d33ef608772f8c499d8e906e215bc0daf`
- Engineering tree: `17cb9892a18f927f08ca3feb344b5024965eb9a0`
- ADR 0026 product source:
  `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Product tree: `963fcf73113e39a1e5868fae3957f4adfc102a4c`
- Last formally evaluated Gate C source:
  `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Last formally evaluated tree:
  `f721fca017c247aee93765d5f11fcbc37e12fcfc`
- Protected-main Release Quality Gates:
  [Run 32692818024](https://github.com/changkong66/CyberControl/actions/runs/32692818024),
  8/8
- Frozen threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`
- Formal state:
  `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`

PR #88 closed round-3 status, PR #89 defined ADR 0026, and PR #90 added the
approved profiling capability. Their push, pull-request and protected-main
Release Quality Gate chains all passed 8/8.

## Proven Round 4 Boundary

The valid real A2/measurement/A' diagnostic used one profiling image digest,
real Keycloak issuance, two tenants, twenty subjects, independent Compose
projects, fresh PostgreSQL volumes, the frozen 200-stream stage, a 300-second
idle baseline and 600-second recovery.

A2 and A' were stable controls. The measurement arm exceeded the predefined
interference limits:

| Metric | Control median | Measurement | Limit | Result |
| --- | ---: | ---: | ---: | --- |
| Connection p95 | 614ms | 702ms | <=1.10x | 1.143322x, rejected |
| Delivery p95 | 44ms | 53ms | <=1.10x | 1.204545x, rejected |
| API CPU p95 | 22.69 | 25.32 | <=1.10x | 1.11591x, rejected |
| RSS delta | 19,103,744 B | 32,808,960 B | difference <=8,388,608 B | +13,705,216 B, rejected |

The profile is real but inadmissible for selecting a product owner. Do not
infer a cache, pool, allocator, serializer, task, frame or SSE lifecycle cause
from it. P2 behavior changes and formal Gate C replay remain frozen.

The first A' attempt is `INFRA_ABORTED` because D: free space fell to about
0.60 GiB during recovery. It is not a valid control or formal attempt. The
valid retry used a new environment. All five PostgreSQL volumes remain
preserved, all Compose projects have zero remaining containers/networks, and
no prune or historical deletion occurred.

Immutable diagnostic package:

- Release: [phase7-gate-c-11-p2-adr0026-measurement-rejected-20260824-v1](https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-adr0026-measurement-rejected-20260824-v1)
- Release ID: `375536270`
- Asset ID: `527281489`
- Bytes: `86286`
- SHA256:
  `97b3203f98b3783dfdbbe7e66be64f8e05eac1c62befc567a2f0215df4b22410`
- GitHub server digest: exact match
- Immutable prerelease: true

## Phase 0: Close The Evidence PR

The current branch is docs/evidence-only:

`codex/phase7-gate-c-eleventh-p2-round4-evidence`

1. Verify that it changes only round-4 diagnostic evidence, the separately
   preserved A' infrastructure-abort record, package reference and four
   current-state documents.
2. Validate every JSON file, Git diff whitespace, source/tree and frozen-hash
   bindings, immutable Release size/digest, and credential/JWT/PII scans.
3. Verify `gate_c_attempts` still contains exactly 12 formal attempts and has
   no diagnostic or `INFRA_ABORTED` entry.
4. Push the branch and require push Release Quality Gates 8/8.
5. Create a ready pull request and require pull-request Release Quality Gates
   8/8.
6. Squash Merge only after green; then require the new protected-main Release
   Quality Gates run to pass 8/8.
7. Preserve every historical Release, image, volume, run directory and
   snapshot. Do not reset, stash, amend, prune, delete or overwrite them.

## Phase 1: Status-Only Closure

After the evidence PR merges and protected main passes 8/8, fetch that exact
main and create a docs-only branch:

`codex/phase7-gate-c-eleventh-p2-round4-status-closure`

Update only:

- `docs/system-acceptance/acceptance-status.json`
- `docs/system-acceptance/acceptance-report.md`
- `docs/system-acceptance/project-stage-audit.md`
- `docs/system-acceptance/next-stage-prompt.md`

Bind the evidence PR number, final head, Squash Merge SHA, push CI,
pull-request CI and post-merge protected-main CI. Set the round-4 archive
pending field to false, append the evidence merge to `baseline_history`, keep
`product_source_sha` unchanged, and keep `gate_c_attempts` at 12. Historical
snapshots must not be edited.

Require the status-only PR's push and pull-request Release Quality Gates 8/8,
Squash Merge and post-merge protected-main 8/8. A commit cannot contain its own
future merge SHA or CI, so the final merge and protected-main run remain
external GitHub attestations.

## Stop Rule

After status closure, stop P2 code modification. A new lower-interference
measurement design requires a separately reviewed ADR and explicit
authorization. Do not create a behavior candidate from the rejected profile,
do not start PreflightSmoke, and do not start a formal Gate C replay.

D: free space was approximately 10 GiB at package publication, below the last
formal environment's recorded capacity. This independently prohibits a formal
Gate C run until a non-destructive environment-capacity review passes.

Do not modify migrations 0001-0010, frozen contracts, RLS, `TenantContext`,
SERIALIZABLE transactions, C12, thresholds, workload, timeouts, aggregation or
Outbox atomicity. Do not fabricate JWTs or send tenant, subject, role or scope
identity headers. Do not start Gate D soak, DR, Provider acceptance,
production deployment, accessibility/privacy closure or new product work.
Gate D requires separate explicit authorization even if it later becomes
eligible.
