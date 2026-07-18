# Topic4 Asset Manifest

## 1. Baseline and Acceptance

- Protected main base: `6922cd3e6cf6a014f7c5a7e0436596d97fcc71df`
- Accepted Topic4 commit: `8d143ba43ae78f3b66ab8d691d1513f03f8baa2d`
- Remote acceptance run: `29634407475`
- Branch: `codex/topic4-verifier-runtime`

## 2. Contract Assets

- Python authority models:
  `packages/contracts-python/src/liyans_contracts/topic4_c1.py` through
  `topic4_c12.py`, plus `topic4_common.py`, `topic4_registry.py`, and
  `verification.py`.
- JSON Schema authority: `schemas/*.schema.json`, including verification,
  graph, quiz, code, and extension result schemas.
- TypeScript generated surface:
  `packages/contracts-ts/src/generated/contracts.ts` and `index.ts`.
- Go generated surface: `packages/contracts-go/contracts/contracts.go`.
- Contract catalog: `config/contract-catalog.json` with 64
  `CODED_TOPIC4_FROZEN` entries.

## 3. Database Assets

Migrations:

- `backend/migrations/versions/20260716_0007_create_topic_4_verifier_control_plane.py`
- `backend/migrations/versions/20260716_0008_create_topic_4_knowledge_evidence_runtime.py`
- `backend/migrations/versions/20260716_0009_create_topic_4_revision_release_.py`

The 41 Topic4 tenant tables are:

1. `topic4_verifications`
2. `topic4_verification_states`
3. `topic4_claims`
4. `topic4_claim_risks`
5. `topic4_dispatch_plans`
6. `topic4_module_runs`
7. `topic4_module_results`
8. `topic4_claim_verdicts`
9. `topic4_aggregation_results`
10. `topic4_verification_reports`
11. `topic4_human_review_tasks`
12. `topic4_human_review_decisions`
13. `topic4_source_documents`
14. `topic4_source_document_versions`
15. `topic4_embedding_profiles`
16. `topic4_knowledge_base_versions`
17. `topic4_knowledge_chunks`
18. `topic4_formula_signatures`
19. `topic4_index_build_manifests`
20. `topic4_knowledge_base_activations`
21. `topic4_query_plans`
22. `topic4_retrieval_runs`
23. `topic4_evidence_refs`
24. `topic4_evidence_bundles`
25. `topic4_revision_cycles`
26. `topic4_revision_plans`
27. `topic4_revision_patches`
28. `topic4_security_findings`
29. `topic4_pii_findings`
30. `topic4_tokenized_values`
31. `topic4_privacy_tenant_results`
32. `topic4_sbom_manifests`
33. `topic4_sbom_components`
34. `topic4_vulnerability_records`
35. `topic4_build_provenance`
36. `topic4_acceptance_reports`
37. `topic4_acceptance_gate_results`
38. `topic4_release_authorizations`
39. `topic4_release_authorization_consumptions`
40. `topic4_publication_batches`
41. `topic4_public_stream_events`

## 4. Runtime Source Assets

- C1: `backend/src/liyans/domains/verification/`
- C2: `backend/src/liyans/domains/knowledge/`
- C3: `backend/src/liyans/domains/academic/`
- C4: `backend/src/liyans/domains/graph/`
- C5: `backend/src/liyans/domains/quiz/`
- C6: `backend/src/liyans/domains/code/`
- C7: `backend/src/liyans/domains/extension/`
- C8: `backend/src/liyans/domains/revision/`
- C9: `backend/src/liyans/domains/security/`
- C10: `backend/src/liyans/domains/privacy/`
- C11: `backend/src/liyans/domains/compliance/`
- C12: `backend/src/liyans/domains/release/`
- Topic4 composition: `backend/src/liyans/domains/verification/runtime.py`
- REST/SSE routes: `backend/src/liyans/api/routes/topic4.py`
- Application lifecycle assembly: `backend/src/liyans/main.py`
- Database model registration: `backend/src/liyans/infrastructure/database/topic4.py`

## 5. Test and Benchmark Assets

- Unit and security suites: `backend/tests/test_topic4_*.py`
- PostgreSQL control plane: `backend/tests/integration/test_postgres_topic4.py`
- PostgreSQL knowledge and recovery:
  `backend/tests/integration/test_postgres_topic4_knowledge.py` and
  `test_postgres_topic4_database_restart.py`.
- PostgreSQL C12: `backend/tests/integration/test_postgres_topic4_release.py`.
- End-to-end runtime and concurrency:
  `backend/tests/integration/test_postgres_topic4_runtime.py`.
- Shared real database fixture support:
  `backend/tests/integration/topic4_runtime_support.py`.
- API tests: `backend/tests/test_topic4_api.py`.
- C2 benchmark: `backend/benchmarks/topic4_c2_retrieval.py` and
  `docs/topic4/c2-100k-benchmark.json`.

## 6. Governance and Evidence Assets

- Per-module architecture, status, report, and unlock records under
  `docs/topic4/c1/` through `docs/topic4/c12/`.
- Top-level architecture, acceptance status, report, and this manifest under
  `docs/topic4/`.
- Performance, recovery, security, and end-to-end evidence under
  `docs/topic4/test-report/`.
- Conditional frontend certificate:
  `docs/topic4/c12/frontend-unlock.md`.
