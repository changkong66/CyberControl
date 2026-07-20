# CyberControl System Acceptance Report

## Decision

Protected `main` revision `40c9a590614d3fb57011061fac02669d86946240` is
accepted as a **release candidate**. PR #25, its pull-request CI, the merge push
CI and a clean external-volume merged-main replay all passed. It is not yet a
production release because the final 2,000-SSE, soak, disaster-recovery, sealed
Provider, deployment, accessibility and privacy-lifecycle gates remain open.

Formal state: `RELEASE_CANDIDATE`.

## Evaluated Baseline

- Protected `main`: `40c9a590614d3fb57011061fac02669d86946240`
- Merged PR: [#25](https://github.com/changkong66/CyberControl/pull/25)
- PR CI: [Run 29729566019](https://github.com/changkong66/CyberControl/actions/runs/29729566019), 8/8 jobs successful
- Protected-main CI: [Run 29729849367](https://github.com/changkong66/CyberControl/actions/runs/29729849367), 8/8 jobs successful
- Evidence branch: `codex/system-acceptance-mainline-evidence`
- Evidence branch base: `40c9a590614d3fb57011061fac02669d86946240`
- Implementation commit: `095ff8eba0dddfa47d14ae723d869937826484f1`
- Test commit: `b389fed1ca39d80439acd9fb518680631987297e`
- Working-tree state after the follow-up evidence commit: clean
- Alembic head: `20260716_0009`; no migration was added or changed

## Docker Storage Migration

Docker Desktop completed its supported GUI disk-image migration to
`D:\Docker\wsl\DockerDesktopWSL\disk\docker_data.vhdx`. The migrated VHDX is
25.24 GiB. At the migration checkpoint, `C:` had 34.67 GiB free and `D:` had
60.32 GiB free. The 38-image and 38-volume inventory digests matched their
pre-migration values, all 19 containers remained registered, and the preserved
PostgreSQL release record remained `RELEASED` with no RLS, audit-chain, Outbox or
publication invariant regression.

The external volume `cybercontrol_release_postgres` was verified empty before the
immutable-source replay and was the actual PostgreSQL data mount for that run.
No development volume was deleted or reset.

## Acceptance Fixes

1. Removed the unsupported Keycloak 26.7.0 top-level `userProfile` realm import
   field so clean realm import starts deterministically.
2. Added a Topic1-derived, local-only C2 source and active BM25/Faiss index
   bootstrap for a release-eligible acceptance dataset.
3. Kept C11 fail-closed for code Claims while returning `NOT_APPLICABLE` for
   persisted, immutable non-code Claims.
4. Increased C2 SERIALIZABLE retry capacity from 3 to 8 attempts for startup
   contention without weakening isolation.
5. Made C9 and C10 depend on persisted C2 evidence in the verification DAG.
6. Aligned the local fixture Provider output with the frozen Topic1-derived
   evidence instead of producing negation-driven false contradictions.
7. Connected Topic4 internal Outbox events to the durable tenant SSE bridge;
   public publication remains on its dedicated public projection.
8. Added authenticated SSE verification with a loopback-only URL allowlist to
   prevent accidental Bearer Token disclosure.
9. Normalized modules outside a terminal Verification resource profile to
   `NOT_REQUIRED` while preserving real `PENDING` and `RUNNING` work.
10. Added focused Settings, hot-configuration, database-health and SSE recovery
    tests, recovering the Python coverage observation above the prior 91.19%.
11. Added fail-closed `-RequireCleanSource` acceptance startup validation and
    immutable Compose, lockfile and runtime-image build fingerprints.

## Clean PostgreSQL Flow

The runner used the protected external volume `cybercontrol_release_postgres`, ran
all nine migrations, and asserted initial representative business counts
`0|0|0|0` before seeding. The authoritative merged-main replay was generated at
`2026-07-20T09:08:44Z` from protected `main`.

| Stage | Result |
| --- | --- |
| OIDC | learner and reviewer Tokens issued by local Keycloak for `demo-academy` |
| Topic1/Topic2 | course, graph, learner profile and memory/path bootstrap passed |
| C2 | local index `READY`; one Topic1-derived authority chunk active |
| Topic3 | Lecturer generation `COMPLETED`; immutable Candidate persisted |
| Topic4 | 10 Claims; C2/C3/C9/C10 all `SUPPORTED`; C11 all `NOT_APPLICABLE` |
| Aggregation | report decision `RELEASE`; state `RELEASE_PENDING` |
| C12 | server-derived one-time authorization consumed atomically |
| Replay | same key returned the same immutable batch; changed replay returned HTTP 409 |
| Final state | `RELEASED` |
| SSE | publication reached durable replay and authenticated Bearer stream |

Immutable identifiers:

- Candidate: `b6b48f47-d7eb-54fb-810f-8edc821e16c2`
- Verification: `4107ee7a-69b7-5789-8cbd-6a8de75f6f06`
- Report: `d0ba0bd7-36fe-55d2-a8f6-cfaa6f5e6f02`
- Authorization: `95352684-89d8-500a-a374-51bcb3d92e61`
- Publication batch: `3fed024a-8627-5b84-ab30-1b8261b2e247`
- Public event: `acb34f23-f2b8-51be-a897-543a9fe2674b`

## Source Replay Fingerprints

- Evidence: `evidence/release-eligible-immutable-source.json`
- Source commit: `8efdfb9b1cf7c7afb88ad43c55c67878acdd5e89`
- Source tree: `45ab301b75c764f866ac376d2d181d15d86faa2d`
- Compose config SHA256: `62bcce826ad654884b52c05ce881954dd60ccc7f5dc49f2ad67e121390bf0741`
- `uv.lock` SHA256: `3254ba70e5484cd795f7635025d5550a7e70b10797a9b4b811267076ed08bbb3`
- `frontend/pnpm-lock.yaml` SHA256: `aa6245402301eea803783e0f23691aee1b1c792d26f6d564f9e1d4e14e2128ab`
- Backend image: `sha256:dc0839825a13bc4eb6ba0837572059471ad159d48bf57c534e03438e841d5a1f`
- Frontend image: `sha256:9015b822294ff61507f34aa1effd6d5eb04caf17f313ebbce4b09ab683afe98e`
- Mock Provider image: `sha256:bbba49ce183ae9e1f630f61e87bc437812b3d8d82d115816dc4c999920319d53`

## Mainline Replay Fingerprints

- Evidence: `evidence/release-eligible-mainline.json`
- Source commit: `40c9a590614d3fb57011061fac02669d86946240`
- Source tree: `d898d2c9c9005bb011aa0464453787c370d2d7b4`
- Compose config SHA256: `a56f83de9c5071ef48c6e4cb088a2f79c948351435b6eba11d7716026985e55c`
- Backend image: `sha256:3c5a80254204c422d659dfdcf187257b2102e98f6f0b3807e8b5c402e52f6dea`
- Frontend image: `sha256:2502b976d1a4e37be17fb046102eb98308a74d9a7da8c33b524f5836058b280e`
- Mock Provider image: `sha256:d5b17d3f2efbdb5a05a3343df5456fa8fdf50074bb3687e8faa59d2a007303ff`

## Database Invariants

- Tenant tables with `tenant_id`: 68
- Tables with RLS and FORCE RLS: 68
- Append-only triggers: 55
- Audit hash-chain breaks: 0
- Outbox `DEAD`: 0
- Outbox `PENDING` or `CLAIMED`: 0
- Foreign-tenant visible Topic4 verifications: 0
- Authorization consumptions: exactly 1
- Committed publication batches for the authorization: exactly 1
- Public stream events for the authorization: exactly 1

## Regression And Coverage

| Gate | Result |
| --- | --- |
| Ruff check and format | passed |
| Frozen contract generation and drift | passed |
| Alembic upgrade/downgrade/upgrade and model drift | passed |
| Go fmt/vet/race/test/build | passed |
| Vue/TypeScript/Vite | passed |
| Python deterministic unit set | 413 passed, 1 skipped, 61 deselected |
| Full PostgreSQL regression | 474 passed, 1 skipped |
| Python coverage | 91.21%, hard threshold 90% |
| Database restart persistence probe | passed against the isolated PostgreSQL container |
| Vitest | 54 passed |
| Frontend coverage | 92.80% statements, 83.13% branches, 91.54% functions, 95.37% lines |
| Playwright project suite | 3 passed |

The one skipped Python test is the existing Windows symbolic-link compatibility
case. The database restart test was executed against a health-checked real
PostgreSQL container and passed together with the immediately following C2 tests.

The current 91.21% coverage is 0.02 percentage points above the prior 91.19%
observation and remains above the configured 90% CI hard gate. The complete local
quality script also passed actionlint, contract regeneration, Go race/build,
dependency audits, CycloneDX/license policy, non-root minimal runtime, Trivy and
full-history plus working-tree Gitleaks.

`-RequireCleanSource` was verified both to reject a dirty worktree without Docker
side effects and to accept the clean immutable source used for the replay.

## Performance And Concurrency

- C2 local RAG: 100,000 chunks, 200 measured queries, p50 14.543 ms,
  p95 17.502 ms, p99 20.646 ms, maximum 22.124 ms; threshold 200 ms.
- C2 benchmark peak working set: 1,258.695 MiB; serialized index 216.968 MiB.
- 200 concurrent verification requests produced 200 distinct reports without
  lost tasks or duplicate Claim IDs.
- 200 concurrent C12 attempts converged on one authorization consumption and one
  immutable publication result.
- The 25-sample committed replay p95 assertion passed the 300 ms threshold. The
  existing test records threshold success, not the exact sample percentile.

## Security And Supply Chain

- Trivy 0.70.0, checksum verified, reported zero vulnerabilities at all severities
  for the backend, frontend and local fixture Provider runtime images.
- Gitleaks scanned 91 reachable commits and the working tree with no findings.
- Python and Node dependency audits passed.
- Python and Node CycloneDX generation and license policy validation passed.
- Runtime identities passed: backend `10001:10001`, frontend `65532:65532`,
  local Provider `10002:10002`.
- Runtime images contain no test runner, package manager, source workspace or
  disallowed build tool checked by the release gate.
- PR, push and protected-main Release Quality Gates each completed all eight jobs.

## Browser Acceptance

Real Google Chrome via Playwright completed Keycloak PKCE login as the reviewer.
Desktop 1440x900 and mobile 390x844 had no framework overlay, console warning or
error, unexpected failed request, or horizontal overflow. The mobile sidebar
stabilized at `x=0`, width `248px`.

The browser loaded the real persisted Verification by ID and rendered:

- state `RELEASED` and report decision `RELEASE`;
- 10 Claim rows;
- all 12 matrix cells;
- six service-derived SHA views;
- the C12 atomic-publication success band.

Resource-profile modules absent from a terminal Lecturer dispatch now render as
`NOT_REQUIRED`. Planned modules and active execution continue to render their
real `PENDING` or `RUNNING` state. The regression is covered by Vitest.

## Evidence

- [Clean-volume evidence](evidence/release-eligible.json)
- [Immutable-source release replay](evidence/release-eligible-immutable-source.json)
- [Merged-main release replay](evidence/release-eligible-mainline.json)
- [100k C2 benchmark](evidence/topic4-c2-100k.json)
- [Browser shell acceptance](evidence/browser-acceptance.json)
- [Release-eligible report UI](evidence/release-eligible-ui.json)
- [Desktop workspace](evidence/screenshots/workspace-desktop.png)
- [Desktop verification](evidence/screenshots/verification-desktop.png)
- [Release-eligible verification](evidence/screenshots/verification-release-eligible.png)
- [Mobile workspace](evidence/screenshots/workspace-mobile.png)

## Release Blockers

1. Execute 2,000 authenticated SSE connections with reconnect, cursor recovery,
   duplicate suppression, slow consumers and cross-tenant isolation evidence.
2. Complete the minimum 8-hour soak and backup/restore disaster-recovery gates.
3. Complete sealed Provider, production deployment, cross-browser/WCAG and PII
   lifecycle acceptance before moving from `RELEASE_CANDIDATE` to `SYSTEM_ACCEPTED`.
