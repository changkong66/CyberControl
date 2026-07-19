import { describe, expect, it, vi } from "vitest"

import { ApiClient } from "../src/api/client"
import { WorkbenchApi } from "../src/api/facade"
import { newIdempotencyKey, requireData, requirePayload } from "../src/api/types"

function topic3(payload: Record<string, unknown>) {
  return {
    schema_version: "topic3.envelope.v1",
    envelope_id: "00000000-0000-4000-8000-000000000001",
    event_type: "topic4.test.result",
    message_kind: "RESULT",
    tenant_id: "demo-academy",
    session_id: "00000000-0000-4000-8000-000000000002",
    subject_ref: "learner-001",
    correlation_id: "00000000-0000-4000-8000-000000000003",
    causation_id: null,
    sequence: 0,
    partition_key: "demo-academy:test",
    producer: { service: "frontend-test", instance_id: "test", build_version: "1" },
    delivery: { idempotency_key: "test", available_at: "2026-07-19T00:00:00Z" },
    resource: null,
    trace_id: "a".repeat(32),
    span_id: null,
    created_at: "2026-07-19T00:00:00Z",
    error: null,
    payload,
  }
}

function response(document: unknown): Response {
  return new Response(JSON.stringify(document), {
    status: 200,
    headers: { "Content-Type": "application/json", "X-Trace-ID": "b".repeat(32) },
  })
}

describe("WorkbenchApi", () => {
  it("unwraps Topic1 course data without changing the frozen envelope", async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe("http://localhost/internal/topic1/courses")
      return response({
        schema_version: "topic1.api-envelope.v1",
        request_id: "request-1",
        trace_id: "c".repeat(32),
        data: { courses: [{ course_id: "ATC", title: "自动控制原理" }] },
      })
    }) as typeof fetch
    const api = new WorkbenchApi(new ApiClient({ baseUrl: "http://localhost", fetcher }))
    const result = await api.listCourses()
    expect(result.data[0]?.course_id).toBe("ATC")
    expect(result.traceId).toBe("b".repeat(32))
  })

  it("uses only the server-derived v2 release endpoints and operation idempotency", async () => {
    const requests: Array<{ url: string; headers: Headers; body: string }> = []
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      requests.push({ url: String(input), headers: new Headers(init?.headers), body: String(init?.body ?? "") })
      if (String(input).endsWith("/derive")) return response(topic3({ authorization: { authorization_id: "auth-1" } }))
      return response(topic3({ batch: { publication_batch_id: "batch-1" }, public_event: {}, public_artifact: {}, state: "RELEASED" }))
    }) as typeof fetch
    const api = new WorkbenchApi(new ApiClient({ baseUrl: "http://localhost", fetcher }))
    await api.deriveAuthorization(
      { verification_id: "verification-1", requested_release_mode: "FULL", requested_block_ids: [], ttl_seconds: 300 },
      "derive-operation-000000000000000000000000000000",
    )
    await api.commitPublication("auth-1", "commit-operation-000000000000000000000000000000")
    expect(requests.map((item) => item.url)).toEqual([
      "http://localhost/internal/topic4/release/authorizations/derive",
      "http://localhost/internal/topic4/release/publications/commit",
    ])
    requests.forEach((item) => {
      expect(item.headers.get("idempotency-key")).toMatch(/^(derive|commit)-operation-/u)
      expect(item.headers.has("x-tenant-id")).toBe(false)
    })
    expect(JSON.parse(requests[1]?.body ?? "{}")).toEqual({ authorization_id: "auth-1" })
  })

  it("reuses a caller-owned idempotency key for a retryable mutation", async () => {
    const keys: string[] = []
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      keys.push(new Headers(init?.headers).get("idempotency-key") ?? "")
      return response(topic3({ authorization: { authorization_id: "auth-1" } }))
    }) as typeof fetch
    const api = new WorkbenchApi(new ApiClient({ baseUrl: "http://localhost", fetcher }))
    await api.deriveAuthorization(
      { verification_id: "verification-1", requested_release_mode: "FULL", requested_block_ids: [], ttl_seconds: 300 },
      "stable-operation-key-000000000000000000000000000000",
    )
    await api.deriveAuthorization(
      { verification_id: "verification-1", requested_release_mode: "FULL", requested_block_ids: [], ttl_seconds: 300 },
      "stable-operation-key-000000000000000000000000000000",
    )
    expect(keys).toEqual([
      "stable-operation-key-000000000000000000000000000000",
      "stable-operation-key-000000000000000000000000000000",
    ])
  })

  it("builds tenant-scoped query strings for review and publication reads", async () => {
    const urls: string[] = []
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      urls.push(String(input))
      return response(topic3({ tasks: [], records: [] }))
    }) as typeof fetch
    const api = new WorkbenchApi(new ApiClient({ baseUrl: "http://localhost", fetcher }))
    await api.listReviewTasks("OPEN")
    await api.listPublicationHistory("verification 1")
    expect(urls[0]).toContain("/internal/topic4/reviews/tasks?state=OPEN")
    expect(urls[1]).toContain("verification_id=verification+1")
  })
})

describe("typed response helpers", () => {
  it("fails closed when a trusted envelope section is absent", () => {
    expect(requirePayload({ payload: { ok: true } }, "test")).toEqual({ ok: true })
    expect(requireData({ data: { ok: true } }, "test")).toEqual({ ok: true })
    expect(() => requirePayload({}, "test")).toThrow(/no payload/u)
    expect(() => requireData({}, "test")).toThrow(/no data/u)
    expect(newIdempotencyKey("scope")).toMatch(/^scope-[0-9a-f-]{36}$/u)
  })
})

describe("WorkbenchApi endpoint coverage", () => {
  it("keeps every business path behind the typed facade", async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/internal/topic1/")) {
        if (url.endsWith("/courses")) return response({ schema_version: "topic1.api-envelope.v1", request_id: "1", trace_id: "a".repeat(32), data: { courses: [] } })
        if (url.includes("/graph")) return response({ schema_version: "topic1.api-envelope.v1", request_id: "1", trace_id: "a".repeat(32), data: { graph: { course: {}, knowledge_points: [], prerequisites: [] } } })
        return response({ schema_version: "topic1.api-envelope.v1", request_id: "1", trace_id: "a".repeat(32), data: { snapshots: [] } })
      }
      let payload: Record<string, unknown> = {}
      if (url.includes("/profiles/latest")) payload = { profile: {} }
      else if (url.includes("/profiles")) payload = { profiles: [] }
      else if (url.endsWith("/memory")) payload = { memory_states: [] }
      else if (url.endsWith("/paths/latest")) payload = { learning_path: {} }
      else if (url.endsWith("/generations")) payload = { sessions: [] }
      else if (url.includes("/streams/") && url.includes("/chunks")) payload = { chunks: [] }
      else if (url.includes("/reviews/tasks")) payload = { tasks: [] }
      else if (url.includes("/release/history")) payload = { records: [] }
      else if (url.includes("/sse/replay")) payload = { events: [] }
      else if (url.includes("/claims/") && url.endsWith("/evidence")) payload = { evidence: [] }
      else if (url.endsWith("/claims")) payload = { claims: [] }
      else if (url.endsWith("/report")) payload = { report: {} }
      else if (url.endsWith("/health")) payload = { ready: true, local_rag: "enabled", external_embedding: "prohibited", release_isolation: "SERIALIZABLE", verification_task_registered: true }
      else if (url.includes("/release/authorizations/derive")) payload = { authorization: {} }
      else if (url.includes("/release/publications/commit")) payload = { batch: {}, public_event: {}, public_artifact: {}, state: "RELEASED" }
      else if (url.includes("/verifications/")) payload = { verification: {}, state: {}, claims: [], risks: [], dispatch_plan: null, module_runs: [], module_results: [], claim_verdicts: [], aggregation: null, report: null, review_task: null }
      return response(topic3(payload))
    }) as typeof fetch
    const api = new WorkbenchApi(new ApiClient({ baseUrl: "http://localhost", fetcher }))

    await api.getCourseGraph("course")
    await api.listGraphSnapshots("course")
    await api.getLatestProfile("learner", "course")
    await api.getProfileHistory("learner", "course")
    await api.getMemoryStates("learner", "course")
    await api.getLearningPath("learner", "course")
    await api.getAgentContext("learner", "course")
    await api.refreshMemory("learner", "course")
    await api.generateLearningPath("learner", "course", "goal")
    await api.createGeneration({ operation_id: "op", generation_session_id: "session", learner_ref: "learner", course_id: "course", target_kp_ids: [], requested_resources: ["Lecturer_Doc"], learning_goal: "goal", requested_at: new Date().toISOString() })
    await api.getGeneration("session")
    await api.listGenerations("learner", "course")
    await api.listStreamChunks("stream")
    await api.topic4Health()
    await api.getVerification("verification")
    await api.executeVerification("verification")
    await api.listClaims("verification")
    await api.getReport("verification")
    await api.listEvidence("claim")
    await api.getTrace("trace")
    await api.listRevisions("verification")
    await api.createRevision({ request: {} as never, patches: [], prompt_bundle_version: "v1" })
    await api.listReviewTasks()
    await api.submitReview("verification", { review_task_id: "task", decision: "APPROVE", rationale: "ok", disclosure_codes: [], waived_finding_ids: [], expected_task_version: 1, expected_state_version: 1 })
    await api.replayPublicEvents(-1)
    expect(fetcher.mock.calls.length).toBeGreaterThan(20)
  })
})
