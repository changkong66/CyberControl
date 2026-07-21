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
  "account:profile:read",
  "account:profile:write",
  "account:contact:write",
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

const tenantAdminScopes = [
  ...learnerScopes,
  "account:admin:read",
  "account:admin:write",
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

function identityEnvelope(data: Record<string, unknown>): Record<string, unknown> {
  return {
    schema_version: "identity.api-envelope.v1",
    request_id: crypto.randomUUID(),
    trace_id: "c".repeat(32),
    data,
  }
}

function accountProfile(role = "learner", version = 1, locale = "zh-CN"): Record<string, unknown> {
  return {
    schema_version: "account.profile.v1",
    account_id: role === "tenant-admin" ? "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" : "11111111-1111-4111-8111-111111111111",
    tenant_id: tenantId,
    subject_ref: `user:${role}`,
    display_name: role === "tenant-admin" ? "E2E Tenant Admin" : "E2E Learner",
    preferred_locale: locale,
    email_hint: role === "tenant-admin" ? "a***@example.invalid" : "l***@example.invalid",
    email_verified: true,
    phone_hint: null,
    phone_verified: false,
    status: "ACTIVE",
    profile_version: version,
    created_at: "2026-07-21T00:00:00Z",
    updated_at: "2026-07-21T00:00:00Z",
  }
}

function accountAdmin(status = "ACTIVE", version = 1): Record<string, unknown> {
  return {
    ...accountProfile("learner", version),
    schema_version: "account.admin-view.v1",
    status,
    disabled_reason_code: status === "DISABLED" ? "POLICY_REVIEW" : null,
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
      name: role === "reviewer" ? "E2E Reviewer" : role === "tenant-admin" ? "E2E Tenant Admin" : "E2E Learner",
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

async function json(
  route: Route,
  document: Record<string, unknown>,
  status = 200,
): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(document) })
}

interface ObservedRequest {
  path: string
  body: Record<string, unknown> | null
  headers: Record<string, string>
}

async function installApiMocks(
  page: Page,
  role = "learner",
): Promise<{
  releaseRequests: Array<{ path: string; body: string }>
  identityRequests: ObservedRequest[]
}> {
  const releaseRequests: Array<{ path: string; body: string }> = []
  const identityRequests: ObservedRequest[] = []
  let profileState = accountProfile(role)
  let accountState = accountAdmin()

  await page.route("**/api/auth/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const body = request.postDataJSON() as Record<string, unknown> | null
    identityRequests.push({ path, body, headers: request.headers() })
    if (request.headers().authorization) {
      await json(
        route,
        { error: { error_code: "TEST_AUTH_LEAK", safe_message: "Public request carried authentication." }, trace_id: "d".repeat(32) },
        400,
      )
      return
    }
    if (path.endsWith("/verification-challenges/verify")) {
      await json(
        route,
        identityEnvelope({
          challenge: {
            schema_version: "verification-challenge.receipt.v1",
            challenge_id: "33333333-3333-4333-8333-333333333333",
            channel: "EMAIL",
            purpose: "REGISTER",
            state: "VERIFIED",
            delivery_hint: "e***@example.invalid",
            expires_at: "2099-07-21T00:05:00Z",
            resend_after_seconds: 60,
          },
        }),
      )
      return
    }
    if (path.endsWith("/verification-challenges")) {
      const channel = body?.channel === "PHONE" ? "PHONE" : "EMAIL"
      await json(
        route,
        identityEnvelope({
          challenge: {
            schema_version: "verification-challenge.receipt.v1",
            challenge_id: "33333333-3333-4333-8333-333333333333",
            channel,
            purpose: "REGISTER",
            state: "PENDING",
            delivery_hint: channel === "PHONE" ? "+1******1234" : "e***@example.invalid",
            expires_at: "2099-07-21T00:05:00Z",
            resend_after_seconds: 60,
          },
        }),
        202,
      )
      return
    }
    if (path.endsWith("/register/email") || path.endsWith("/register/phone")) {
      await json(
        route,
        identityEnvelope({
          registration: {
            schema_version: "registration.receipt.v1",
            registration_id: "44444444-4444-4444-8444-444444444444",
            account_id: "11111111-1111-4111-8111-111111111111",
            state: "COMPLETED",
            preferred_locale: String(body?.preferred_locale ?? "zh-CN"),
            login_required: true,
            created_at: "2026-07-21T00:00:00Z",
          },
        }),
        201,
      )
      return
    }
    await route.abort("failed")
  })

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
    const body = request.postDataJSON() as Record<string, unknown> | null

    if (path.startsWith("/internal/accounts/") || path.startsWith("/internal/tenant/")) {
      identityRequests.push({ path, body, headers: request.headers() })
      if (!request.headers().authorization) {
        await json(
          route,
          { error: { error_code: "LIYAN-AUTH-REQUIRED", safe_message: "Authentication required." }, trace_id: "d".repeat(32) },
          401,
        )
        return
      }
      if (path === "/internal/accounts/me" && request.method() === "GET") {
        await json(route, identityEnvelope({ profile: profileState }))
        return
      }
      if (path === "/internal/accounts/me" && request.method() === "PATCH") {
        profileState = {
          ...profileState,
          display_name: String(body?.display_name ?? profileState.display_name),
          preferred_locale: String(body?.preferred_locale ?? profileState.preferred_locale),
          profile_version: Number(profileState.profile_version) + 1,
          updated_at: "2026-07-21T00:10:00Z",
        }
        await json(route, identityEnvelope({ profile: profileState }))
        return
      }
      if (path === "/internal/accounts/me/verification-challenges") {
        const channel = body?.channel === "PHONE" ? "PHONE" : "EMAIL"
        await json(
          route,
          identityEnvelope({
            challenge: {
              schema_version: "verification-challenge.receipt.v1",
              challenge_id: "55555555-5555-4555-8555-555555555555",
              channel,
              purpose: channel === "PHONE" ? "CHANGE_PHONE" : "CHANGE_EMAIL",
              state: "PENDING",
              delivery_hint: channel === "PHONE" ? "+1******5678" : "n***@example.invalid",
              expires_at: "2099-07-21T00:05:00Z",
              resend_after_seconds: 60,
            },
          }),
          202,
        )
        return
      }
      if (path === "/internal/accounts/me/verification-challenges/verify") {
        await json(
          route,
          identityEnvelope({
            challenge: {
              schema_version: "verification-challenge.receipt.v1",
              challenge_id: "55555555-5555-4555-8555-555555555555",
              channel: "EMAIL",
              purpose: "CHANGE_EMAIL",
              state: "VERIFIED",
              delivery_hint: "n***@example.invalid",
              expires_at: "2099-07-21T00:05:00Z",
              resend_after_seconds: 60,
            },
          }),
        )
        return
      }
      if (path === "/internal/accounts/me/contact") {
        profileState = {
          ...profileState,
          email_hint: "n***@example.invalid",
          email_verified: true,
          profile_version: Number(profileState.profile_version) + 1,
          updated_at: "2026-07-21T00:12:00Z",
        }
        await json(route, identityEnvelope({ profile: profileState }))
        return
      }
      if (path === "/internal/tenant/accounts") {
        await json(route, identityEnvelope({ accounts: [accountState] }))
        return
      }
      if (path.endsWith("/audit")) {
        await json(
          route,
          identityEnvelope({
            audit_entries: [
              {
                schema_version: "identity.audit-entry.v1",
                event_id: "66666666-6666-4666-8666-666666666666",
                sequence: 1,
                action: "IDENTITY_ACCOUNT_STATUS_CHANGED",
                outcome: "SUCCEEDED",
                actor_ref: "user:tenant-admin",
                target_ref: `account:${String(accountState.account_id)}`,
                trace_id: "d".repeat(32),
                metadata: {},
                occurred_at: "2026-07-21T00:00:00Z",
                previous_hash: "0".repeat(64),
                event_hash: "e".repeat(64),
                hash_algorithm: "SHA-256",
              },
            ],
          }),
        )
        return
      }
      if (path.endsWith("/disable")) {
        accountState = accountAdmin("DISABLED", Number(accountState.profile_version) + 1)
        await json(route, identityEnvelope({ account: accountState }))
        return
      }
      if (path.endsWith("/restore")) {
        accountState = accountAdmin("ACTIVE", Number(accountState.profile_version) + 1)
        await json(route, identityEnvelope({ account: accountState }))
        return
      }
      if (path.startsWith("/internal/tenant/accounts/")) {
        await json(route, identityEnvelope({ account: accountState }))
        return
      }
    }

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
  return { releaseRequests, identityRequests }
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

test("learner edits profile, re-verifies contact, and remains blocked from tenant administration", async ({ page }) => {
  await installIdentity(page.context(), learnerScopes, "learner")
  const { identityRequests } = await installApiMocks(page, "learner")

  await page.goto("/account/profile")
  await expect(page.getByRole("heading", { name: "账户资料", exact: true }).first()).toBeVisible()
  await page.getByLabel("显示名称").fill("Updated Learner")
  await page.getByLabel("首选语言").selectOption("en-US")
  await page.getByRole("button", { name: "保存资料" }).click()
  await expect(page.getByText("Account profile updated.")).toBeVisible()
  await expect(page.locator("html")).toHaveAttribute("lang", "en-US")

  await page.getByLabel("New contact").fill("new-contact@example.invalid")
  await page.getByRole("button", { name: "Send change code" }).click()
  await page.getByLabel("Six-digit verification code").fill("123456")
  await page.getByRole("button", { name: "Verify and apply change" }).click()
  await expect(page.getByText("Verified contact updated.")).toBeVisible()

  await page.goto("/tenant/accounts")
  await expect(page).toHaveURL(/\/forbidden(?:\?|$)/u)
  await expect(page.getByRole("heading", { name: "Access denied" })).toBeVisible()
  const update = identityRequests.find(
    (request) => request.path === "/internal/accounts/me" && request.body !== null,
  )
  expect(update?.body).toEqual({
    display_name: "Updated Learner",
    preferred_locale: "en-US",
    expected_version: 1,
  })
  expect(update?.headers.authorization).toBe("Bearer e2e-access-token")
  expect(update?.headers["x-tenant-id"]).toBeUndefined()
  const contactRequests = identityRequests.filter((request) =>
    request.path.startsWith("/internal/accounts/me/")
  )
  expect(contactRequests.map((request) => request.path)).toEqual([
    "/internal/accounts/me/verification-challenges",
    "/internal/accounts/me/verification-challenges/verify",
    "/internal/accounts/me/contact",
  ])
  expect(contactRequests[0]?.body).toMatchObject({
    channel: "EMAIL",
    purpose: "CHANGE_EMAIL",
    identifier: "new-contact@example.invalid",
  })
  expect(contactRequests[2]?.body).toMatchObject({
    channel: "EMAIL",
    identifier: "new-contact@example.invalid",
    expected_version: 2,
  })
  for (const request of contactRequests) {
    expect(request.headers.authorization).toBe("Bearer e2e-access-token")
    expect(request.headers["idempotency-key"]).toMatch(/^identity-/u)
    expect(request.headers["x-tenant-id"]).toBeUndefined()
  }
})

test("tenant administrator inspects audit and performs CAS disable and restore", async ({ page }) => {
  await installIdentity(page.context(), tenantAdminScopes, "tenant-admin")
  const { identityRequests } = await installApiMocks(page, "tenant-admin")

  await page.goto("/tenant/accounts")
  await expect(page.getByRole("heading", { name: "租户账户管理" })).toBeVisible()
  await page.getByRole("button", { name: /E2E Learner/u }).click()
  await expect(page.getByText("IDENTITY_ACCOUNT_STATUS_CHANGED")).toBeVisible()

  await page.getByRole("button", { name: "停用账户" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "停用账户" }).click()
  await expect(page.getByText("账户状态已更新。")).toBeVisible()
  await expect(page.getByRole("button", { name: "恢复账户" })).toBeVisible()

  await page.getByRole("button", { name: "恢复账户" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "恢复账户" }).click()
  await expect(page.getByRole("button", { name: "停用账户" })).toBeVisible()

  const mutations = identityRequests.filter(
    (request) => request.path.endsWith("/disable") || request.path.endsWith("/restore"),
  )
  expect(mutations.map((request) => request.body)).toEqual([
    { expected_version: 1, reason_code: "ADMIN_ACTION" },
    { expected_version: 2, reason_code: null },
  ])
  for (const request of mutations) {
    expect(request.headers.authorization).toBe("Bearer e2e-access-token")
    expect(request.headers["idempotency-key"]).toMatch(/^identity-account-status-/u)
    expect(request.headers["x-tenant-id"]).toBeUndefined()
    expect(request.headers["x-subject-ref"]).toBeUndefined()
  }
})

test("all three locales render the registration surface without mobile overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await installApiMocks(page)
  await page.goto("/register")

  const cases = [
    { locale: "zh-CN", heading: "创建学习者账户" },
    { locale: "zh-TW", heading: "建立學習者帳戶" },
    { locale: "en-US", heading: "Create a learner account" },
  ]
  for (const localeCase of cases) {
    await page.locator(".locale-switcher select").selectOption(localeCase.locale)
    await expect(page.getByRole("heading", { name: localeCase.heading })).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
    ).toBe(true)
    expect(await page.locator("body").innerText()).not.toMatch(/(?:register|profile|locale)\.[A-Za-z]/u)
  }
})
