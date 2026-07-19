import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test"

const authority = "http://localhost:8080/realms/cybercontrol"
const clientId = "cybercontrol-workbench"
const tenantId = "demo-academy"

const learnerScopes = [
  "topic1:read",
  "topic2:read",
  "topic2:profile:read",
  "topic2:memory:read",
  "topic2:path:read",
  "topic3:read",
  "topic3:sse:read",
  "topic4:read",
  "topic4:verification:read",
  "topic4:claim:read",
  "topic4:report:read",
  "topic4:revision:read",
  "topic4:trace:read",
  "topic4:sse:read",
]

const reviewerScopes = [
  ...learnerScopes,
  "topic2:profile:write",
  "topic2:memory:write",
  "topic2:path:write",
  "topic3:write",
  "topic3:generation:write",
  "topic3:generation:read",
  "topic3:generation:retry",
  "topic4:verification:execute",
  "topic4:rag:read",
  "topic4:review:read",
  "topic4:review:write",
  "topic4:release:read",
  "topic4:release:write",
]

function topic1Envelope(data: Record<string, unknown>): Record<string, unknown> {
  return {
    schema_version: "topic1.api-envelope.v1",
    request_id: crypto.randomUUID(),
    trace_id: "a".repeat(32),
    data,
  }
}

function topic3Envelope(payload: Record<string, unknown>): Record<string, unknown> {
  return {
    schema_version: "topic3.envelope.v1",
    envelope_id: crypto.randomUUID(),
    event_type: "e2e.result",
    message_kind: "RESULT",
    tenant_id: tenantId,
    session_id: crypto.randomUUID(),
    subject_ref: "e2e-user",
    correlation_id: crypto.randomUUID(),
    causation_id: null,
    sequence: 0,
    partition_key: "demo-academy:e2e",
    producer: { service: "frontend-e2e", instance_id: "playwright", build_version: "test" },
    delivery: { idempotency_key: crypto.randomUUID(), available_at: new Date().toISOString() },
    resource: null,
    trace_id: "b".repeat(32),
    span_id: null,
    created_at: new Date().toISOString(),
    error: null,
    payload,
  }
}

function identity(scopes: string[], role: string): Record<string, unknown> {
  return {
    access_token: "e2e-access-token",
    token_type: "Bearer",
    scope: "openid profile email",
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    session_state: "e2e-session",
    profile: {
      sub: `e2e-${role}`,
      name: role === "reviewer" ? "E2E Reviewer" : "E2E Learner",
      preferred_username: role,
      tenant_id: tenantId,
      roles: [role],
      permissions: scopes.join(" "),
    },
  }
}

async function installIdentity(context: BrowserContext, scopes: string[], role: string): Promise<void> {
  await context.addInitScript(
    ({ key, value }) => window.sessionStorage.setItem(key, JSON.stringify(value)),
    { key: `oidc.user:${authority}:${clientId}`, value: identity(scopes, role) },
  )
}

function course(): Record<string, unknown> {
  return {
    schema_version: "topic1.course.v1",
    course_id: "CRS_ATC_001",
    revision: 1,
    course_code: "ATC101",
    title: "自动控制原理",
    description: "E2E authoritative course",
    locale: "zh-CN",
    academic_level: "UNDERGRADUATE",
    credit_hours: 64,
    status: "ACTIVE",
    authority_sources: [],
    created_at: "2026-07-19T00:00:00Z",
    updated_at: "2026-07-19T00:00:00Z",
  }
}

function graph(): Record<string, unknown> {
  return {
    course: course(),
    knowledge_points: [
      {
        kp_id: "KP_E2E_001",
        course_id: "CRS_ATC_001",
        revision: 1,
        title: "传递函数",
        aliases: [],
        summary: "系统输入输出关系的数学表示。",
        learning_objectives: ["识别传递函数"],
        category: "FOUNDATION",
        difficulty_level: 2,
        difficulty_score: 0.35,
        topology_level: 0,
        topology_weight: 1,
        estimated_minutes: 30,
        formula_signatures: [],
        tags: ["模型"],
        status: "ACTIVE",
        authority_sources: [],
        created_at: "2026-07-19T00:00:00Z",
        updated_at: "2026-07-19T00:00:00Z",
      },
    ],
    prerequisites: [],
    misconceptions: [],
    textbooks: [],
    textbook_sections: [],
    textbook_mappings: [],
    golden_questions: [],
  }
}

async function json(route: Route, document: Record<string, unknown>): Promise<void> {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(document) })
}

async function installApiMocks(page: Page): Promise<{ releaseRequests: Array<{ path: string; body: string }> }> {
  const releaseRequests: Array<{ path: string; body: string }> = []
  await page.route("**/health/ready", (route) =>
    json(route, {
      status: "ready",
      database: { status: "up", latency_ms: 1 },
      authentication: "configured",
      task_queue_running: true,
      message_bus_open: true,
      outbox_publisher: "healthy",
      sse_notification_bridge: "connected",
    }),
  )
  await page.route("**/internal/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname

    if (path.endsWith("/sse/stream")) {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
        body: `: heartbeat\n\nid: e2e-1\nevent: topic4.test\ndata: {"tenant_id":"${tenantId}","sequence":1}\n\n`,
      })
      return
    }

    if (path === "/internal/topic1/courses") {
      await json(route, topic1Envelope({ courses: [course()] }))
      return
    }
    if (path.endsWith("/graph")) {
      await json(route, topic1Envelope({ graph: graph() }))
      return
    }
    if (path.endsWith("/snapshots")) {
      await json(route, topic1Envelope({ snapshots: [{ snapshot_id: "snapshot-1", course_id: "CRS_ATC_001", graph_version: 1, content: graph(), content_sha256: "c".repeat(64), node_count: 1, edge_count: 0, created_by_subject: "e2e", frozen_at: "2026-07-19T00:00:00Z" }] }))
      return
    }
    if (path.includes("/profiles/latest")) {
      await json(route, topic3Envelope({ profile: { profile_id: "profile-1", learner_ref: "e2e-learner", course_id: "CRS_ATC_001", profile_version: 1, policy_version: "test", knowledge_mastery: 0.72, problem_solving_proficiency: 0.65, misconception_preference: 0.2, learning_pace: 0.6, forgetting_rate: 0.3, learning_goal_tendency: 0.8, confidence_score: 0.7, activity_count: 4, profile_document: {}, content_sha256: "d".repeat(64), frozen_at: "2026-07-19T00:00:00Z", features: [], audit_event_id: "audit-1", created_by_subject: "e2e-learner" } }))
      return
    }
    if (path.endsWith("/memory")) {
      await json(route, topic3Envelope({ memory_states: [] }))
      return
    }
    if (path.endsWith("/paths/latest")) {
      await json(route, topic3Envelope({ learning_path: { snapshot: { node_count: 0, path_document: { nodes: [] } } } }))
      return
    }
    if (path === "/internal/topic4/health") {
      await json(route, topic3Envelope({ ready: true, verification_task_registered: true, local_rag: "enabled", external_embedding: "prohibited", release_isolation: "SERIALIZABLE" }))
      return
    }
    if (path.endsWith("/release/history")) {
      await json(route, topic3Envelope({ records: [] }))
      return
    }
    if (path.endsWith("/reviews/tasks")) {
      await json(route, topic3Envelope({ tasks: [] }))
      return
    }
    if (path.endsWith("/release/authorizations/derive")) {
      releaseRequests.push({ path, body: request.postData() ?? "" })
      await json(route, topic3Envelope({ authorization: { authorization_id: "authorization-1", verification_id: "verification-1", report_id: "report-1", candidate_id: "candidate-1", candidate_version: 1, candidate_sha256: "e".repeat(64), report_sha256: "f".repeat(64), release_mode: "FULL", allowed_block_ids: [], issued_at: "2026-07-19T00:00:00Z", expires_at: "2099-07-19T00:00:00Z", one_time_use: true } }))
      return
    }
    if (path.endsWith("/release/publications/commit")) {
      releaseRequests.push({ path, body: request.postData() ?? "" })
      await json(route, topic3Envelope({ batch: {}, public_event: {}, public_artifact: {}, state: "RELEASED" }))
      return
    }
    if (path.includes("/verifications/") && path.endsWith("/revisions")) {
      await json(route, topic3Envelope({ revisions: [] }))
      return
    }
    await json(route, topic3Envelope({ sessions: [], claims: [], evidence: [], events: [], records: [], tasks: [] }))
  })
  return { releaseRequests }
}

test("learner can traverse workbench surfaces without client identity headers", async ({ page }) => {
  await installIdentity(page.context(), learnerScopes, "learner")
  await installApiMocks(page)
  const observedHeaders: Record<string, string>[] = []
  page.on("request", (request) => {
    if (request.url().includes("/internal/") || request.url().includes("/health/")) observedHeaders.push(request.headers())
  })

  for (const path of ["/workspace", "/knowledge", "/learning", "/agents", "/verification"]) {
    await page.goto(path)
    await expect(page.locator("h1")).toBeVisible()
  }
  await page.goto("/learning")
  await expect(page.getByRole("button", { name: "重新规划路径" })).toBeDisabled()
  await page.goto("/agents")
  await expect(page.getByText(/缺少 topic3:generation:write/u)).toBeVisible()
  await expect(page.getByRole("button", { name: "启动协同生成" })).toBeDisabled()
  await page.goto("/reviews")
  await expect(page).toHaveURL(/\/forbidden(?:\?|$)/u)

  for (const headers of observedHeaders) {
    expect(headers["x-tenant-id"]).toBeUndefined()
    expect(headers["x-subject-ref"]).toBeUndefined()
    expect(headers["x-role"]).toBeUndefined()
    expect(headers["x-roles"]).toBeUndefined()
    expect(headers["x-scope"]).toBeUndefined()
    expect(headers["x-scopes"]).toBeUndefined()
  }
  expect(observedHeaders.some((headers) => headers.authorization === "Bearer e2e-access-token")).toBe(true)
})

test("reviewer performs a server-derived C12 v2 publication", async ({ page }) => {
  await installIdentity(page.context(), reviewerScopes, "reviewer")
  const { releaseRequests } = await installApiMocks(page)
  await page.goto("/publications")
  await page.getByPlaceholder("Verification ID").fill("verification-1")
  await page.getByRole("button", { name: "筛选历史" }).click()
  await page.getByRole("button", { name: "派生一次性授权" }).click()
  await expect(page.getByText("服务端授权已派生")).toBeVisible()
  await page.getByRole("button", { name: "提交原子发布" }).click()
  await expect(page.getByText("已完成原子发布")).toBeVisible()
  await expect(page.getByText("RELEASED", { exact: true })).toBeVisible()

  expect(releaseRequests).toHaveLength(2)
  expect(JSON.parse(releaseRequests[0]?.body ?? "{}")).toEqual({
    verification_id: "verification-1",
    requested_release_mode: "FULL",
    requested_block_ids: [],
    ttl_seconds: 300,
  })
  expect(JSON.parse(releaseRequests[1]?.body ?? "{}")).toEqual({ authorization_id: "authorization-1" })
})

test("reviewer starts Topic3 generation without blocking on the SSE loop", async ({ page }) => {
  await installIdentity(page.context(), reviewerScopes, "reviewer")
  await installApiMocks(page)
  await page.goto("/agents")
  await page.getByRole("button", { name: "启动协同生成" }).click()
  await expect(page).toHaveURL(/\/agents\?course=CRS_ATC_001&session=[0-9a-f-]{36}$/u)
  await expect(page.getByRole("button", { name: "启动协同生成" })).toBeEnabled()
})
