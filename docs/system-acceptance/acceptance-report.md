# CyberControl System Acceptance Report

## Decision

Protected `main` revision `bc9836532f6300e91dc7c0a906b07dabe754c138` is
accepted as a **release candidate**. The Keycloak-backed identity backend, its
runtime Outbox integration, two remote PR workflows, the protected-main
workflow and a clean external-volume mainline replay all passed.

Formal state: `RELEASE_CANDIDATE`.

The project is not `SYSTEM_ACCEPTED`. Final high-load SSE, soak, disaster
recovery, sealed Provider, production deployment, accessibility and privacy
lifecycle evidence remains open.

## Evaluated Baseline

- Protected `main`: `bc9836532f6300e91dc7c0a906b07dabe754c138`
- Identity backend PR: [#27](https://github.com/changkong66/CyberControl/pull/27)
- Identity acceptance PR: [#28](https://github.com/changkong66/CyberControl/pull/28)
- PR #28 push CI: [Run 29800780508](https://github.com/changkong66/CyberControl/actions/runs/29800780508), 8/8
- PR #28 pull-request CI: [Run 29800825295](https://github.com/changkong66/CyberControl/actions/runs/29800825295), 8/8
- Protected-main CI: [Run 29801095074](https://github.com/changkong66/CyberControl/actions/runs/29801095074), 8/8
- Alembic head: `20260720_0010`
- Historical migrations `0001` through `0009`: unchanged
- Mainline evidence: [identity-mainline.json](evidence/identity-mainline.json)
- Evidence SHA256: `f0ee985feac9cebf229fc018d0b864b5bfb861805f7778eeef142da97ffd8ab8`

## Closure Delivered

### Identity Boundary

- Keycloak remains the only password, password-hash and OIDC subject authority.
- Email and E.164 phone registration use versioned contracts, hashed challenges,
  idempotency, bounded retries and compensation/reconciliation.
- The application stores encrypted contact projections and keyed lookup digests,
  never passwords, password hashes, usable verification codes or Keycloak tokens.
- New accounts receive learner access only; tenant administration is
  server-authorized and cannot be requested by the client.
- Six additive identity tables use FORCE RLS; append-only registration and
  consent evidence, audit events and transactional Outbox records are active.
- Reconciliation uses a least-privilege tenant catalog and claim-token CAS for
  restart-safe external-side-effect recovery.

### Runtime Defect Found By Real Replay

The first identity-aware clean-volume replay failed closed. Two identity Outbox
messages reached `DEAD` and the next message in one ordered partition remained
`PENDING` because no identity event handler was registered in application
lifespan.

The fix adds a catalog for all nine identity event types and registers them with
the existing tenant-scoped, durable SSE projection. An AST drift test proves the
catalog matches every identity event emitted by `IdentityService`, and a message
bus test proves every catalog event dispatches. The acceptance redline was not
weakened. The successful replay ended with 29 published, zero open and zero dead
Outbox messages.

## Clean External-Volume Replay

The protected external volume `cybercontrol_release_postgres` was confirmed
unused, recreated with its original release-acceptance labels, and mounted as
the PostgreSQL data directory. No development volume was deleted.

The runner asserted representative initial business counts `0|0|0|0|0` before
seeding and then executed:

`registration -> OIDC login -> Topic1 -> Topic2 -> Topic3 -> C1-C12 -> C12 release -> authenticated SSE`

| Stage | Result |
| --- | --- |
| Registration | email challenge verified; registration `COMPLETED` |
| OIDC | registered user logged in through Keycloak |
| Authorization | registered account learner-only; tenant admin API returned 403 |
| Administration | tenant-admin could view the new account projection |
| Topic1/Topic2 | authoritative graph and learner bootstrap passed |
| Topic3 | Lecturer generation `COMPLETED`; immutable Candidate persisted |
| Topic4 | 10 Claims; report decision `RELEASE` |
| C12 | server-derived one-time authorization committed atomically |
| Replay defense | same key idempotent; changed replay returned HTTP 409 |
| Final state | `RELEASED` |
| SSE | durable replay and authenticated Bearer stream passed |

Immutable identifiers for this replay:

- Registration: `e5c242d3-1fd2-4079-a81a-e0336db0db30`
- Account: `17d2cc50-7517-4a5a-86ca-d600c11d37a4`
- Candidate: `54a5f85b-bead-5ed0-9b6a-213e1f2d8466`
- Verification: `52023f09-c6fe-5f8b-91f7-e318d6c3295e`
- Report: `52d77cf5-4ea9-55fc-bd5e-cb2ff8e703d4`
- Authorization: `225e81d2-e645-5c1a-96cb-d4bf9bc69c20`
- Publication batch: `c6b11b51-6b08-5839-a5bf-3a42f0757dfd`
- Public event: `80fb8da9-98e9-5388-8e50-f9b09ce590a9`

## Source And Runtime Fingerprints

- Source tree: `5aa4bbe4234d2dca85d7560081fe67d60d219b25`
- Compose config SHA256: `f12990ca5db459daa30fc289a7c2d7c787384c5bf4d3616ebfa7dbec13e4a8ca`
- `uv.lock` SHA256: `a8785433e7f7f5889cca945ebc445f432e352e281caf57bd84b117a0cbb56ecb`
- `frontend/pnpm-lock.yaml` SHA256: `aa6245402301eea803783e0f23691aee1b1c792d26f6d564f9e1d4e14e2128ab`
- Backend image: `sha256:3a7ac7f9bc8c6d9b408f2a9427c71864b85fd813875a77d8caf68e773d895180`
- Frontend image: `sha256:b21551ecbcf7cbabb30b9e898a27f49531df909a007fd07d8f3c2484786551c0`
- Mock Provider image: `sha256:07ae57b6a86492c97d55e3f4490750c7645c1091af2714e296d8b61c094e3ddd`

## Database Invariants

- Tenant tables with `tenant_id`: 74
- Tables with RLS and FORCE RLS: 74
- Append-only triggers: 57
- Audit hash-chain breaks: 0
- Outbox `DEAD`: 0
- Outbox `PENDING` or `CLAIMED`: 0
- Outbox `PUBLISHED`: 29
- Foreign-tenant visible Topic4 verifications: 0
- Foreign-tenant visible identity accounts: 0
- Plaintext contact matches in encrypted identity columns: 0
- Authorization consumptions: exactly 1
- Committed publication batches: exactly 1
- Public publication stream events: exactly 1

## Quality And Security

| Gate | Result |
| --- | --- |
| Ruff and frozen contract drift | passed |
| Python deterministic suite | 449 passed, 1 skipped, 70 deselected |
| Full PostgreSQL/Keycloak suite | 519 passed, 1 skipped |
| Python coverage | 91.33%; hard threshold 90%; historical target 91.19% |
| Vitest | 54 passed |
| Frontend coverage | 92.80% statements, 83.13% branches, 91.54% functions, 95.37% lines |
| Playwright Chromium | 3 passed |
| Go fmt/vet/race/test/build | passed |
| Python and Node dependency audit | no known vulnerabilities |
| Gitleaks | push, PR and main remote gates passed |
| Trivy and container SBOM | push, PR and main remote gates passed |
| License policy and non-root runtime | push, PR and main remote gates passed |

The single skipped Python test remains the Windows symbolic-link compatibility
case. It is not a database, identity, RLS, transaction or release-path skip.

## Current Boundary

The backend identity capability and its mainline replay are complete. The next
allowed product PR is the frontend identity and internationalization layer:

- email and phone registration;
- self-service profile and verified contact changes;
- tenant account administration;
- Keycloak-delegated recovery;
- `zh-CN`, `zh-TW` and `en-US` application and login localization.

That PR may consume the frozen identity APIs but may not modify migration
`0010`, identity persistence, Keycloak authority, RLS, SERIALIZABLE transaction,
Outbox, SSE or Topic1-Topic4 semantics.

## Remaining Release Blockers

1. Merge the current evidence update through all protected-main gates.
2. Deliver and replay the frontend identity/i18n PR from merged main.
3. Execute 2,000 authenticated SSE connections with reconnect, cursor recovery,
   duplicate suppression, slow-consumer and tenant-isolation evidence.
4. Complete a minimum eight-hour soak and independent PostgreSQL backup/restore
   disaster-recovery exercise with measured RPO/RTO.
5. Complete sealed Provider, production deployment, TLS/secrets/monitoring,
   cross-browser/WCAG and PII retention/export/deletion acceptance.

Only after every blocker has evidence may the state advance to
`SYSTEM_ACCEPTED`.
