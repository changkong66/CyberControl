# Next Stage Prompt: Production Acceptance And Release Freeze

```text
# CyberControl Phase 7.1: immutable release-candidate closure and production acceptance

You are the release architect for a single-maintainer multi-tenant trusted AI
education platform. Continue from the objective facts below. Do not add new
business features and do not weaken any security or repository rule.

## Fixed facts

- Protected main: d880c4b7549a512cf8ba91e8fd8f500513b099f9
- Main CI: Release Quality Gates run 29676794168, 8/8 jobs successful
- Working branch: codex/system-acceptance-release-eligible
- Source commits: 095ff8eba0dddfa47d14ae723d869937826484f1,
  b389fed1ca39d80439acd9fb518680631987297e and
  8efdfb9b1cf7c7afb88ad43c55c67878acdd5e89
- Immutable-source evidence is archived separately under
  docs/system-acceptance/evidence/release-eligible-immutable-source.json
- Alembic head: 20260716_0009; migrations 0001-0009 are frozen
- Local clean-volume acceptance passed:
  - initial business counts 0|0|0|0
  - 68/68 tenant tables FORCE RLS
  - audit-chain breaks 0
  - Outbox DEAD/open 0/0
  - final Verification state RELEASED
  - same-key C12 replay idempotent; changed replay HTTP 409
  - authenticated publication SSE replay passed
- Regression: 474 passed, 1 skipped, Python coverage 91.21%
- Previous main coverage observation: 91.19%; current delta: +0.02 points
- Frontend: 54 Vitest passed; coverage 92.80/83.13/91.54/95.37;
  Playwright 3 passed
- C2 benchmark: 100,000 chunks, 200 queries, p95 17.502 ms
- Concurrency: 200 verifications and 200 C12 attempts passed on real PostgreSQL
- Trivy: zero findings for backend/frontend/local Provider images
- Gitleaks: zero history and working-tree findings
- Real browser PKCE login and persisted RELEASED report rendering passed
- Docker Desktop officially migrated its 25.24 GiB data VHDX to D:\Docker\wsl;
  migration-time C: free space was 34.67 GiB and inventory hashes matched
- Isolated release volume cybercontrol_release_postgres was verified empty and
  used by the immutable-source replay
- Terminal Verification semantics plus RequireCleanSource dirty and clean paths pass

## Permanent constraints

1. Do not change migrations 0001-0009 or frozen Topic1-Topic4 contract fields.
2. Tenant identity comes only from verified OIDC and backend TenantContext.
3. Preserve FORCE RLS, SERIALIZABLE transactions, CAS, append-only evidence,
   SHA256 binding, Outbox atomicity and fail-closed release behavior.
4. Do not use Fake database evidence for PostgreSQL, RLS, concurrency or recovery.
5. Do not commit Provider credentials or send tokens to non-loopback acceptance tools.
6. Do not reduce Python/frontend coverage thresholds or skip Release Quality Gates.
7. Do not merge Dependabot major upgrades into this release-candidate PR.
8. Historical acceptance documents are immutable snapshots; publish new current-state
   documents instead of rewriting historical facts.

## Strict serial execution

### Stage A: verify the completed workstation migration checkpoint

1. Treat the archived before/after evidence as the authoritative migration result.
2. Verify the D: VHDX and isolated release volume still exist before heavy work.
3. Do not repeat migration, manually move a live VHDX, or delete unrelated volumes.

Exit: archived migration remains valid and Docker is healthy.

### Stage B: source traceability checkpoint (completed locally)

Preserve the completed result: implementation and tests are separated, runtime
images were rebuilt from `8efdfb9`, and the clean external-volume replay records
the source tree, Compose/lockfile hashes, image IDs and exact flags.

Exit: immutable implementation commit plus evidence commit; no unexplained dirty files.

### Stage C: rerun the complete local release matrix

Use a separate health-checked PostgreSQL 16 test container. TEMP/TMP and Trivy
cache may use D:, but source and evidence paths remain in the repository.

Required gates:

- actionlint, Ruff check/format, frozen contract drift
- Go fmt/vet/race/test/build
- Vue/TypeScript/Vite
- Python/Node dependency audit, SBOM and license policy
- 474+ Python tests with database restart enabled and coverage >= 91.19%
- Vitest thresholds >= 80/75/80/80 and all tests passing
- Playwright project suite
- real Keycloak PKCE browser login
- real persisted RELEASED report UI: 10 Claims and 12 matrix cells
- 100k C2 benchmark p95 <= 200 ms
- 200 verification and 200 release contention tests
- Trivy all-severity inventories and fixable HIGH/CRITICAL redlines for all images
- Gitleaks full history and working tree
- non-root/minimal runtime checks for all images

Preserve the completed terminal-report regression: modules outside the resource
profile render NOT_REQUIRED while planned/active modules retain real states.

Exit: every local gate passes from immutable source; reports contain exact values.

### Stage D: protected PR and mainline replay

1. Push codex/system-acceptance-release-eligible.
2. Open one release-candidate PR to main with:
   - acceptance fixes
   - source/evidence commit separation
   - test, performance and security results
   - explicit compatibility statement
   - no claim that Phase 7 is fully accepted
3. Wait for all eight Release Quality Gates jobs. Do not use admin override.
4. Squash merge only after all jobs succeed and all conversations are resolved.
5. Record the merged main SHA and main CI run.
6. From merged main, rebuild images and rerun clean-volume acceptance once more.
7. Publish a mainline acceptance evidence document tied to the merged SHA.

Exit: protected main and its rebuilt images reproduce the release-eligible flow.

### Stage E: remaining product-level G0-G12 gates

Run these only after Stage D:

1. 2,000 authenticated SSE connections with reconnect, cursor recovery,
   duplicate delivery, slow consumers and tenant isolation.
2. Minimum 8-hour soak with generation, verification, revision, review and release.
3. PostgreSQL backup/restore into a separate instance; measure and report RPO/RTO.
4. Artifact Store, audit chain and Outbox consistency after restore.
5. Sealed real-Provider integration using external secret injection; no secret in
   repository, logs, screenshots or artifacts.
6. Human-reviewed academic golden dataset accuracy and false-positive analysis.
7. Production deployment rehearsal with TLS, secret manager, monitoring, alerts,
   capacity limits, rollback and incident runbook.
8. Cross-browser and WCAG accessibility acceptance.

Each gate must produce machine-readable evidence and a signed-off Markdown result.
Any failed gate keeps the project in RELEASE_CANDIDATE, not ACCEPTED.

### Stage F: final freeze

Only when Stages A-E pass:

1. Create the final SystemAcceptanceReport and current project status.
2. Update README and roadmap current-state text without changing historical snapshots.
3. Tag the immutable release and attach SBOM, provenance and acceptance evidence.
4. Mark Phase 7 ACCEPTED and open only deployment/operations maintenance scope.

## Required final response

Report exact commit SHAs, PR URL, eight CI jobs, main CI run, evidence paths,
coverage, p95 values, concurrency counts, Trivy/Gitleaks results, RPO/RTO,
soak duration, SSE connection results, remaining limitations and final release state.
Never substitute planned or historical evidence for a result from the exact commit.
```
