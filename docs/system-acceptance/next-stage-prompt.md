# Next Stage Prompt: Phase 7 Gate B Remote CI and Mainline Replay

```text
# CyberControl Phase 7 Gate B: protected PR closure and merged-main replay

You are the release-quality architect for a single-maintainer, multi-tenant
trusted AI education platform. Work from real repository state, real
PostgreSQL, real containers, real CI and retained evidence. Do not fabricate
commits, PRs, CI results, metrics, database evidence or release state.

This task is limited to closing the already locally accepted Gate B. Do not
start Gate C (2,000 authenticated SSE load), Gate D (eight-hour soak), backup
and restore, failure drills, sealed Provider integration, target deployment or
new product features until this task is complete.

## Current Facts

- Protected main before the stacked Gate B PRs:
  `84427f2555ff5e510e886e357a8ee1ca53f3fbe8`
- Protected-main Release Quality Gates:
  Run `29852791180`, 8/8 successful.
- Evidence branch:
  `codex/phase7-gate-b-academic-golden`
- C3 remediation branch:
  `codex/phase7-c3-semantic-remediation-v2`
- Gate B local report:
  `docs/system-acceptance/evidence/phase7-c3-accuracy.json`
- Local report source commit:
  `a23cbe38a116c493223579a4675bf595f90b8252`
- Local result: 72/72 correct, all class precision/recall and abstention
  accuracy `1.0`, zero unsafe `CONTRADICTED -> SUPPORTED` decisions, restricted
  PostgreSQL roles, FORCE RLS adversarial reads and changed-content replay all
  passed.
- This is owner-reviewed evidence with a recorded single-maintainer conflict;
  it must never be described as independent institutional peer review.

## Non-Negotiable Boundaries

1. Do not alter migrations `0001` through `0010`, frozen contracts,
   `TenantContext`, FORCE RLS, SERIALIZABLE behavior, audit, Outbox, SSE,
   Keycloak authority or C12 semantics.
2. Preserve the default `C3AcademicHandler` and `ClaimFactVerifier` v1 behavior.
   The production composition may use the explicit `C3AcademicHandlerV2` only as
   recorded by ADR-0013.
3. Do not use fact IDs, topics, expected outcomes or reviewer rationales in
   product runtime inputs. Do not change the accepted human-review files.
4. Do not use admin bypasses, force pushes, direct pushes to main, disabled CI,
   fabricated approvals or fabricated CI evidence.
5. Do not use `cybercontrol_release_postgres` for a new formal replay; create a
   fresh named PostgreSQL 16 volume and record its container, image, role,
   migration and cleanup evidence.
6. Keep Gate C through Gate G locked until the remediation PR is merged and the
   merged-main replay is accepted.

## Required Sequence

1. Read-only preflight:
   - fetch `origin`;
   - verify the evidence and remediation branch tips;
   - verify clean worktrees;
   - recompute the report, manifest and PostgreSQL-environment file hashes;
   - verify the report is clean-source, `gate_b_local_eligible=true`, source
     bindings match, and temporary formal PostgreSQL resources were removed.
2. Push `codex/phase7-gate-b-academic-golden` and create its PR to `main`.
   Do not amend its accepted review history.
3. Push `codex/phase7-c3-semantic-remediation-v2` and create a stacked PR whose
   base is the evidence branch. Its description must identify ADR-0013, v1
   compatibility, label-channel exclusion, 72/72 metrics, zero unsafe false
   negatives, real PostgreSQL controls and the separate `fast-uri` security
   override.
4. Wait for each PR's complete Release Quality Gates. Record every actual run
   URL and all eight successful jobs. A failed or absent job blocks the next
   step.
5. Squash merge the evidence PR through normal protected-branch flow. Retarget
   the remediation PR to `main` only after GitHub shows the evidence base is
   merged. Then wait for the retargeted PR CI again and squash merge it normally.
6. Fetch the resulting `origin/main`, create a fresh isolated PostgreSQL 16
   volume, migrate to head and rerun the C3 Gate B harness without
   `--allow-dirty-source`. The report must bind the new main SHA and again meet
   every threshold with zero unsafe false negatives.
7. Archive only current-state replay evidence and status in a new evidence PR.
   Merge it with 8/8 green checks. Historical blocked reports and ADR-0012 must
   remain historical records.

## Gate B Mainline Acceptance

Gate B may advance from `LOCAL_ACCEPTED_REMOTE_CI_PENDING` to
`MAINLINE_ACCEPTED` only when all of these are evidenced:

- both stacked PRs are merged through protected flow;
- every associated Release Quality Gates run is 8/8 successful;
- the final clean-source PostgreSQL replay binds the merged `main` SHA;
- report, artifact manifest and PostgreSQL environment evidence cross-reference
  the same internal report SHA;
- release volume remains untouched and the temporary replay volume is removed;
- no historical snapshot is rewritten to imply a different past result.

If any item fails, retain `RELEASE_CANDIDATE` and
`PHASE7_GATE_B_LOCAL_ACCEPTED_REMOTE_CI_PENDING`; do not begin Gate C.
```
