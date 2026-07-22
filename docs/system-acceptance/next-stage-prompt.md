# Next Stage Prompt: Gate C Authenticated SSE Acceptance

```text
# CyberControl Phase 7 Gate C: 2,000 authenticated SSE acceptance

You are the release-quality architect for a single-maintainer, multi-tenant
trusted AI education platform. Work only from the real repository, real
PostgreSQL, real containers, real CI and retained evidence. Never fabricate a
commit, PR, CI result, metric, database result, load result or release state.

## Current accepted facts

- Gate B evaluated source: `7e2a1d7cc3efc55ce27044e10959c4f5889a85da`
- Gate B evaluated source tree: `c9821405359f59fee9fb993873ed3ba7f55e8b00`
- Gate B replay archive baseline: `a6024716ebbe2311daf73b9409fd84e9ed512f59`
- Gate B replay archive tree: `7cfd4171840d9d0b274f16c5d7ba70a8cc9402dc`
- PR #34 merged the Gate B academic evidence at
  `412085e1586e3d497e5e6f944d4f34e258896d8b`.
- PR #35 was retargeted to `main` and merged the C3 v2 remediation at the
  current main SHA. v1 compatibility remains preserved.
- PR #34 push/PR runs: `29886312423`, `29886314403`, both 8/8.
- PR #35 retargeted push/PR runs: `29886959510`, `29886962210`, both 8/8.
- Resulting main run: `29887219266`, 8/8.
- PR #36 archived the merged-main replay evidence at
  `a6024716ebbe2311daf73b9409fd84e9ed512f59`.
- PR #36 push/PR runs: `29888597039`, `29888658077`, both 8/8.
- PR #36 post-merge main run: `29888873754`, 8/8.
- Mainline Gate B report:
  `docs/system-acceptance/evidence/phase7-c3-mainline-replay.json`
- Mainline artifact manifest:
  `docs/system-acceptance/evidence/phase7-c3-mainline-replay-artifact-manifest.json`
- Mainline PostgreSQL environment:
  `docs/system-acceptance/evidence/phase7-c3-mainline-replay-postgres-environment.json`
- Report internal SHA256:
  `53097324fa556c593ed63d3721a9a3e9509a1088d5ef820ca18df954e5d3a18b`
- Report file SHA256:
  `de6fc5d9a99dcdbaba261351df6be53be732191c67146f5a3694015c6d486421`
- Artifact manifest SHA256:
  `0051e36d9f0da848a14e071a19b50551714bd171a6948ac6b8fe0d76d264e212`
- PostgreSQL environment SHA256:
  `eac9258d33c9cde87e3d451d736513248d953fe37e513532c4ced73987614e9e`
- Gate B result: 72/72 correct, all class precision/recall and abstention
  accuracy `1.0`, zero unsafe `CONTRADICTED -> SUPPORTED`, zero missing and
  nondeterministic results, FORCE RLS and changed-content replay controls passed.
- Replay used a fresh PostgreSQL 16.14 volume, restricted non-superuser roles,
  86 artifacts totaling 360,284 bytes, left `cybercontrol_release_postgres`
  untouched, and removed temporary resources.
- Formal project state remains `RELEASE_CANDIDATE`, not `SYSTEM_ACCEPTED`.

## Gate C: 2,000 authenticated SSE acceptance

Gate B and its evidence archive are complete. Gate C is the only newly unlocked
execution scope. Fetch the latest protected `main`, verify it is clean and its
most recent Release Quality Gates run is 8/8, then create a new `codex/`
acceptance branch from that exact SHA. Do not modify product behavior,
frozen contracts, migrations, RLS, SERIALIZABLE transactions, Outbox, C12,
Keycloak authority or the accepted C3 evidence while running the test.

### Before load

1. Define and commit an acceptance plan before generating load. It must state
   concurrency, ramp-up, test duration, request rate, payload sizes, timeout,
   reconnect policy, acceptable error rate, p95/p99 latency, memory ceiling,
   CPU ceiling, connection-pool ceiling, queue/Outbox lag ceiling and recovery
   time. Thresholds must be resource-aware and reproducible on the available
   host; do not invent production capacity claims from a laptop run.
2. Use real authenticated Bearer tokens and tenant claims. Never send
   `X-Tenant-ID`, subject, role or scope identity headers from clients.
3. Use real backend/SSE paths and real PostgreSQL. A mock stream may be used
   only as a separately labelled parser-unit fixture, never as load acceptance
   evidence.
4. Record image digests, source SHA, compose configuration hash, database image,
   volume name, migration head, host limits and test tool version.

### Required scenarios

- 2,000 authenticated SSE connections with controlled ramp-up.
- Heartbeat handling and normal completion.
- Forced disconnect and reconnect with `Last-Event-ID` recovery.
- Duplicate event and out-of-order delivery suppression.
- Slow consumers and bounded queue/memory behavior.
- At least two tenants with proof that events and cursors never cross tenants.
- Concurrent generation/publication activity while SSE clients are connected.
- Backend restart and client recovery, with no false success if recovery fails.

### Evidence and gate rule

1. Capture connection success/failure, reconnect success, event loss/duplication,
   per-tenant leakage, p50/p95/p99 latency, throughput, CPU, memory, pool use,
   queue depth, Outbox lag and service restarts.
2. Store raw machine-readable results, a SHA256 manifest and a concise report
   under `docs/system-acceptance/evidence/`.
3. Run the test at least once from the post-archive main source and bind every
   result to that source SHA and runtime image digests.
4. If any threshold fails or evidence is incomplete, keep the project at
   `RELEASE_CANDIDATE`, record the failure and stop. Do not unlock Gate D.
5. Only after Gate C evidence is merged through a protected PR with 8/8 CI may
   Gate D (minimum eight-hour soak) start.

## Locked scope

- Gate D soak, backup/restore and RPO/RTO, failure drills, sealed Provider
  integration, target deployment, WCAG/cross-browser and PII lifecycle work
  remain locked until their preceding gate is accepted.
- No new product features or frontend business pages may be mixed into an
  acceptance evidence PR.
- The final state may advance to `SYSTEM_ACCEPTED` only after every required
  gate has current reproducible evidence and protected-main CI.
```
