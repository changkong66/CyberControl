# Frontend Acceptance Report

## Current Revision

- Branch: `codex/frontend-workbench`
- Base: merged PR #19 main baseline `dccdc735f8fa6f82325abb4a18dcdac308eabed2`
- Frontend stack: Vue 3, Vite, TypeScript strict, Pinia, Vue Router, OIDC PKCE
- Backend changes: none

## Delivered Surfaces

- Shared status, risk, progress, hash, trace, evidence, report and release controls
- Topic1 knowledge graph, snapshot selector, searchable knowledge-point table
- Topic2 six-dimension radar, memory-risk list and adaptive path view
- Topic3 five-agent generation workspace with authenticated SSE updates
- Topic4 verification lifecycle, C1-C12 matrix, claims, evidence and report view
- C8 immutable revision timeline and controlled re-entry action
- C12 server-derived v2 authorization and atomic commit controls
- Human review queue with CAS-aware decision submission
- Publication ledger and public SSE event view
- Responsive desktop/mobile shell and print-to-PDF report styling

## Verification Evidence

| Check | Result |
| --- | --- |
| `pnpm typecheck` | PASS |
| `pnpm build` | PASS |
| Vitest | PASS, 49 tests |
| Frontend coverage | PASS, statements 92.91%, branches 83.16%, functions 91.30%, lines 95.36% |
| Playwright | PASS, 3 browser integration scenarios |
| OIDC learner PKCE login | PASS against local Keycloak |
| Workspace API readiness | PASS, HTTP 200 |
| Real Topic1/Topic2 data | PASS, 1 course, 13 knowledge points, 15 edges, profile v1, 13 memory states |
| Real Topic3 fixture generation | PASS, 5/5 Agent tasks and 5 persisted Candidates in sequential mode |
| Real Topic3→Topic4 consumer | PASS, 5 persisted verifications; four `BLOCKED`, one `REVIEW_REQUIRED` |
| Browser desktop render | PASS on knowledge, agents, verification, reviews and publications |
| Browser mobile render | PASS on learning at 390x844, no horizontal overflow |
| Browser console after login | PASS, no application errors across six business surfaces |
| Static favicon in production build | included by `infra/frontend.Dockerfile` |

## Explicit Limitations

The current long-lived local PostgreSQL volume contains a legacy Topic1 import
whose Chinese labels were stored as question marks. The repository seed file is
correct UTF-8, and a fresh volume imported by
`tools/windows/bootstrap-frontend-demo.ps1` does not use that legacy path. The
append-only rule prevents silently rewriting the existing record.

The real five-Candidate run reached Topic4, but the current local evidence store
does not contain every C2/C9/C10/C11 prerequisite. The frozen backend therefore
blocked four records and sent the code Candidate to human review. A real C12
commit is not claimed for this dataset. The C12 v2 browser contract, one-time
derive/commit payload, forbidden identity headers, and `RELEASED` UI state are
covered by Playwright with API mocks; production acceptance still requires a
release-eligible persisted report.

Local Docker image rebuild and Trivy execution remain pending because the
Docker Desktop engine timed out during this work session. The CI workflow now
builds, checks non-root users, generates SBOMs, and scans backend, frontend, and
fixture Provider images; acceptance is not final until that remote job is green.
