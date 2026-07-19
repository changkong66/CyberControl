# Frontend Demonstration Guide

## Start

1. Start the frozen local stack and local fixture Provider:

   ```powershell
   docker compose -f infra/docker-compose.yml up --build -d
   ```

2. Confirm `http://localhost:8000/health/ready` returns `200`.
3. Seed Topic1, Topic2, five deterministic Topic3 candidates, and their
   projected Topic4 identifiers:

   ```powershell
   .\tools\windows\bootstrap-frontend-demo.ps1
   ```

4. Run `pnpm --dir frontend dev --host 127.0.0.1 --port 5174` for a live source view, or use the Compose frontend at `http://localhost:5173`.
5. Open the local Keycloak login and use `learner` / `learner-local-only` or
   `reviewer` / `reviewer-local-only`.

The local realm accepts `localhost:5173`, `localhost:5174` and
`127.0.0.1:5174` callback URLs. Credentials in the realm are development-only
and must never be reused outside the local environment.

## Walkthrough

1. **工作台**: verify API readiness, local RAG and SERIALIZABLE release status.
2. **知识拓扑**: select a course, inspect a frozen graph snapshot, search a knowledge point and open its authority metadata.
3. **学习路径**: inspect six profile dimensions, memory risk and the current adaptive path.
4. **智能体协同**: select knowledge points, choose agent resources, submit a generation request and observe authenticated SSE events.
5. **可信核验**: paste a server-issued Verification ID, inspect the lifecycle, module matrix, Claim and evidence chain.
6. **人工审核**: sign in as reviewer, choose an OPEN task and submit a CAS-bound decision with rationale.
7. **可信发布**: enter a Verification ID whose report allows release, derive the one-time v2 authorization, then commit it once.

The fixture Provider proves the frontend and Topic3 provider boundary without
contacting a vendor. Topic4 remains fail-closed: a Candidate without all local
RAG, security, privacy, and compliance evidence may end in `BLOCKED` or
`REVIEW_REQUIRED`. Such a result must not be converted into a fake
release-ready record.

## Safety Demonstration

- Inspect network request headers and confirm there is no `X-Tenant-ID`,
  `X-Subject-Ref`, role or scope header.
- Change the browser account and confirm session tenant caches are cleared.
- Reuse an expired or consumed authorization and verify the backend safe error
  is shown without a client-side retry loop.
- Disconnect the network during an SSE stream and confirm the cursor is resumed
  without duplicate event rendering.

## Existing Volume Note

The seed JSON is UTF-8 and contains correct Chinese labels. A PostgreSQL volume
created by an older manual import may already contain question-mark replacement
text. Append-only Topic1 records are not overwritten by the bootstrap script.
Use a fresh Compose project/volume for clean visual evidence instead of editing
or deleting frozen records in place.
