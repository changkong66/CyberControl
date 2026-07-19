# Frontend API Guide

All calls are made through `WorkbenchApi` in
`frontend/src/api/facade.ts`. Pages must not concatenate endpoint paths or
call `fetch` directly.

## Required Headers

`ApiClient` owns `Authorization`, `X-Trace-ID` and `X-Session-ID`. `SseClient`
also owns `Last-Event-ID`. Mutating facade methods generate an
`Idempotency-Key` required by the frozen backend operation contracts. The
client rejects caller-supplied tenant, subject, role, scope, trace and session
headers.

Write controls are enabled only when the validated OIDC permission claim
contains the matching backend Scope:

| Operation | Required Scope |
| --- | --- |
| Refresh Topic2 memory | `topic2:memory:write` |
| Generate Topic2 path | `topic2:path:write` |
| Start Topic3 generation | `topic3:generation:write` |
| Requeue Topic4 verification | `topic4:verification:execute` |
| Submit human review | `topic4:review:write` |
| Derive/commit C12 release | `topic4:release:write` |

## Endpoint Groups

| Feature | Facade methods | Backend routes |
| --- | --- | --- |
| Topic1 | `listCourses`, `getCourseGraph`, `listGraphSnapshots` | `/internal/topic1/...` |
| Topic2 | profile, memory, path and context methods | `/internal/topic2/...` |
| Topic3 | generation, session, chunk methods | `/internal/topic3/...` |
| Topic3 stream | `services.sse.run` | `/internal/topic3/sse/stream` |
| Topic4 control | verification, claims, report, trace, evidence | `/internal/topic4/verifications/...` |
| Topic4 revision | `listRevisions`, `createRevision` | `/internal/topic4/revisions...` |
| C12 v2 | `deriveAuthorization`, `commitPublication` | `/internal/topic4/release/.../derive`, `/commit` |
| Human review | `listReviewTasks`, `submitReview` | `/internal/topic4/reviews/...` |
| Public events | `replayPublicEvents`, `services.sse.run` | `/internal/topic4/sse/...` |

The browser facade intentionally has no `createVerification` method and no
deprecated C12 v1 method.

## Envelope Handling

Topic1 returns `Topic1ApiEnvelopeV1.data`; Topic2-Topic4 return the frozen
`Topic3EnvelopeV1.payload`. `requireData` and `requirePayload` fail closed when
the expected section is absent. HTTP errors are represented by
`ApiClientError`, which retains the server trace ID and safe error code.

## Release Example

```ts
const derived = await services.workbench.deriveAuthorization({
  verification_id,
  requested_release_mode: "FULL_WITH_DISCLOSURE",
  requested_block_ids: [],
  ttl_seconds: 300,
})
await services.workbench.commitPublication(derived.data.authorization.authorization_id)
```

The example intentionally contains no Candidate, Report, TenantID or SHA
input. Those values are authoritative server facts.
