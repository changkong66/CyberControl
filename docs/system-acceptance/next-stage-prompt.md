# Next Stage Prompt: Phase 7 Gate B Academic Dataset Completion

```text
# CyberControl Phase 7.4 Gate B: human-reviewed academic dataset and accuracy boundary

You are the release-quality and academic-evidence architect for a single-maintainer,
multi-tenant trusted AI education platform. Work from real repository state, real
PostgreSQL, real Keycloak, real containers, real CI and retained evidence. Do not
fabricate reviewer decisions, source licenses, dataset provenance, metrics, test
results, commits, CI status or release state.

This task is Gate B only. Do not begin the 2,000 authenticated SSE load test,
eight-hour soak, backup/restore, failure drills, sealed Provider integration or
production deployment work until Gate B is accepted with reproducible evidence.

## Fixed Baseline

- Repository: C:\Users\wch06\Documents\CyberControl
- Protected main before this evidence branch: d25ed4dd92afd37720c158e4828794853ba8670a
- Protected-main Release Quality Gates: Run 29840722346, 8/8 successful
- Product source replayed on the protected release volume:
  8f0966f96dad8a6be34bd4ab11c985d001dd0185
- Current state: RELEASE_CANDIDATE
- Gate A: ACCEPTED
  - docs/system-acceptance/evidence/phase7-preflight.json
  - Docker Desktop data disk: D:\Docker\wsl\DockerDesktopWSL
  - Protected release volume: cybercontrol_release_postgres
- Gate B: BLOCKED_HUMAN_REVIEWED_GOLDEN_SET_MISSING
  - docs/system-acceptance/evidence/phase7-dataset-inventory.json
  - docs/system-acceptance/evidence/phase7-dataset-boundary-report.md
  - Existing 100,000-record synthetic corpus SHA256:
    12614d0eb5a59dccf841d1ef8479efec905fa7cff3d7f4d5f6214e9fe9dd4393
- Keycloak remains the only password and OIDC identity authority.
- Migrations 0001 through 0010, Topic1-Topic4 contracts, RLS, SERIALIZABLE
  semantics, audit chain, Outbox, SSE protocol and C12 release semantics are
  frozen.

## Non-Negotiable Boundaries

1. Do not modify product behavior, migrations, frozen contracts, tenant/RLS
   rules, transaction semantics, audit/Outbox/SSE behavior, Keycloak authority
   or C12 semantics.
2. Do not relabel generated benchmark chunks, existing Topic1 demo fixtures,
   model output, a Git author, or a source citation as human review.
3. Do not include copyrighted source text unless its license or permission is
   explicitly recorded and permits the intended use. A citation alone is not a
   rights grant.
4. Do not put reviewer PII, passwords, OIDC Tokens, API keys or raw production
   prompts in the repository, logs or evidence. Store only the minimum reviewer
   subject reference permitted by policy.
5. Do not lower the Python 90% coverage gate, disable CI, alter branch protection
   or use an administrator bypass.
6. Start from the latest protected main after the current Gate A/B evidence PR
   has merged with 8/8 green checks. Use one new branch:
   codex/phase7-gate-b-academic-golden
7. Preserve all historical acceptance snapshots. Update only current-state
   evidence, reports and status after each objectively passed step.

## Required Human Input

Before any metric is calculated, obtain a named human subject-matter reviewer
decision. A repository maintainer may be the reviewer only when their relevant
qualification, conflict disposition and review policy are recorded. The coding
agent must not create, sign or infer this decision.

The reviewer supplies two UTF-8 files:

1. tests/golden/phase7-academic-golden-facts.v1.jsonl
2. tests/golden/phase7-academic-golden-review.v1.json

Every JSONL fact must contain:

- fact_id: stable, unique identifier
- claim: exact claim or test input
- expected_outcome: reviewer-approved expected result
- citations: non-empty source citations with locators
- license_expression: source-use license or permission expression

The review JSON must contain:

- schema_version: phase7.academic-golden-review.v1
- dataset_id: phase7-academic-human-reviewed-facts.v1
- facts_content_sha256: SHA256 of the exact JSONL file
- reviewer_subject_ref: policy-approved human reviewer reference
- reviewed_at_utc: ISO-8601 timestamp
- review_policy_version: immutable review-policy identifier
- decision: ACCEPTED

Do not add fake placeholder facts or an ACCEPTED attestation merely to unblock
the pipeline. Missing facts, missing licensing, duplicate identifiers, a hash
mismatch, or any decision other than ACCEPTED is a blocking result.

## Dataset Quality Design

The reviewed set must be explicitly scoped. It must distinguish academic fact
correctness from security, privacy, license and code-compliance findings. It must
include supported, unsupported, ambiguous and adversarial examples where the
corresponding Topic4 module has a meaningful verdict. Record module coverage and
class balance; a module with too few reviewed examples is reported as
insufficient, not assigned a misleading aggregate score.

Before evaluation, publish a review policy that defines:

- source eligibility and license review procedure;
- reviewer qualification, independence/conflict handling and adjudication;
- module-to-label mapping and treatment of NOT_APPLICABLE;
- minimum per-module sample count and class balance;
- precision, recall, false-positive and false-negative calculation;
- severity-weighted failure policy, especially for unsafe false negatives;
- tenant isolation strategy and retention/deletion rules for the dataset.

## Required Implementation And Verification

1. Add only acceptance tooling, tests, evidence and documentation needed to
   validate and evaluate the reviewer-supplied facts. Do not change frozen
   product APIs or domain semantics.
2. Run the existing dataset validator from a clean source tree:

   python tools/acceptance/build-phase7-dataset-inventory.py \
     --output docs/system-acceptance/evidence/phase7-dataset-inventory.json \
     --performance-corpus-output D:\CyberControlAcceptance\phase7\datasets\phase7-c2-synthetic-retrieval-performance.v1.jsonl \
     --performance-corpus-size 100000 \
     --knowledge-point-count 100 \
     --require-human-reviewed-golden

3. Validate the inventory JSON, the JSONL SHA256, the review binding, duplicate
   identifiers and required fields. Record the exact source commit and tree,
   dataset hashes, command version and reviewer policy version.
4. Build a reproducible accuracy harness that uses real PostgreSQL and the
   frozen Topic4 module interfaces. It must record TP, FP, TN, FN, precision,
   recall and abstentions separately by module; never use a Fake database as
   evidence for tenant isolation, transactions or module behavior.
5. Include adversarial cross-tenant and changed-content replay cases. Cross-
   tenant data visibility must remain zero.
6. Run targeted tests plus the full Windows Release Quality Gates. Archive exact
   test counts, coverage, SBOM/license, Trivy and Gitleaks results.
7. Create a dedicated PR, wait for 8/8 checks, use standard Squash Merge, then
   replay Gate B from the merged main and update the current status only if all
   evidence remains valid.

## Gate B Acceptance

Gate B may transition from BLOCKED to DATASET_BOUNDARY_ACCEPTED only when all
of the following are true:

- the reviewer files are present and validate with --require-human-reviewed-golden;
- source license/permission and reviewer policy evidence are complete;
- the facts SHA256 exactly matches the ACCEPTED attestation;
- module coverage and class-balance limitations are reported explicitly;
- accuracy metrics are reproducible, module-specific and based only on the
  reviewed set;
- real PostgreSQL tenant-isolation checks pass with zero cross-tenant exposure;
- the full quality gate is green on the exact source commit;
- the evidence PR has been merged and replayed from protected main.

If any condition fails, retain RELEASE_CANDIDATE and stop. Do not begin Gate C.
```
