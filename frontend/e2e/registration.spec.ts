import { expect, test, type Page, type Route } from "@playwright/test"

test.use({ trace: "off", screenshot: "off", video: "off" })

interface ObservedRequest {
  path: string
  body: Record<string, unknown> | null
  headers: Record<string, string>
}

function identityEnvelope(data: Record<string, unknown>): Record<string, unknown> {
  return {
    schema_version: "identity.api-envelope.v1",
    request_id: crypto.randomUUID(),
    trace_id: "c".repeat(32),
    data,
  }
}

async function json(
  route: Route,
  document: Record<string, unknown>,
  status = 200,
): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(document) })
}

async function installRegistrationMocks(page: Page): Promise<ObservedRequest[]> {
  const requests: ObservedRequest[] = []
  let activeChannel: "EMAIL" | "PHONE" = "EMAIL"
  await page.route("**/api/auth/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const body = request.postDataJSON() as Record<string, unknown> | null
    requests.push({ path, body, headers: request.headers() })

    if (request.headers().authorization) {
      await json(
        route,
        {
          error: {
            error_code: "TEST_AUTH_LEAK",
            safe_message: "Public request carried authentication.",
          },
          trace_id: "d".repeat(32),
        },
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
            channel: activeChannel,
            purpose: "REGISTER",
            state: "VERIFIED",
            delivery_hint: activeChannel === "PHONE" ? "+1******1234" : "e***@example.invalid",
            expires_at: "2099-07-21T00:05:00Z",
            resend_after_seconds: 60,
          },
        }),
      )
      return
    }
    if (path.endsWith("/verification-challenges")) {
      activeChannel = body?.channel === "PHONE" ? "PHONE" : "EMAIL"
      await json(
        route,
        identityEnvelope({
          challenge: {
            schema_version: "verification-challenge.receipt.v1",
            challenge_id: "33333333-3333-4333-8333-333333333333",
            channel: activeChannel,
            purpose: "REGISTER",
            state: "PENDING",
            delivery_hint: activeChannel === "PHONE" ? "+1******1234" : "e***@example.invalid",
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
  return requests
}

test("anonymous user registers without leaking identity headers or secrets to logs", async ({ page }) => {
  const identityRequests = await installRegistrationMocks(page)
  const consoleMessages: string[] = []
  page.on("console", (message) => consoleMessages.push(message.text()))

  await page.goto("/register?invitation_token=" + "i".repeat(32))
  await expect(page).toHaveURL(/\/register$/u)
  await page.locator(".locale-switcher select").selectOption("en-US")
  await expect(page.getByRole("heading", { name: "Create a learner account" })).toBeVisible()

  await page.getByLabel("Email address").fill("e2e-new@example.invalid")
  await page.getByRole("button", { name: "Send verification code" }).click()
  await expect(page.getByText(/verification code was sent/u)).toBeVisible()
  await page.getByLabel("Six-digit verification code").fill("123456")
  await page.getByRole("button", { name: "Verify code" }).click()
  await expect(page.getByText("Contact verified")).toBeVisible()
  await page.getByLabel("Display name").fill("E2E New Learner")
  await page.getByLabel("Password", { exact: true }).fill("StrongPass123")
  await page.getByLabel("Confirm password").fill("StrongPass123")
  await page.getByRole("checkbox").nth(0).check()
  await page.getByRole("checkbox").nth(1).check()
  await page.getByRole("button", { name: "Create account" }).click()

  await expect(page).toHaveURL(/\/login\?registered=1$/u)
  await expect(page.getByText(/account is ready/u)).toBeVisible()
  expect(identityRequests.map((request) => request.path)).toEqual([
    "/api/auth/verification-challenges",
    "/api/auth/verification-challenges/verify",
    "/api/auth/register/email",
  ])
  for (const request of identityRequests) {
    expect(request.headers.authorization).toBeUndefined()
    expect(request.headers["idempotency-key"]).toMatch(/^identity-/u)
    expect(request.headers["x-tenant-id"]).toBeUndefined()
    expect(request.headers["x-subject-ref"]).toBeUndefined()
    expect(request.headers["x-role"]).toBeUndefined()
    expect(request.headers["x-scope"]).toBeUndefined()
  }
  const consoleText = consoleMessages.join(" ")
  expect(consoleText).not.toContain("e2e-new@example.invalid")
  expect(consoleText).not.toContain("StrongPass123")
  expect(consoleText).not.toContain("123456")
})

test("anonymous user can register by normalized phone without identity headers", async ({ page }) => {
  const identityRequests = await installRegistrationMocks(page)
  await page.goto("/register")
  await page.locator(".locale-switcher select").selectOption("en-US")
  await page.getByRole("button", { name: "Phone" }).click()
  await page.getByLabel("Phone number").fill("+1 (415) 555-1234")
  await page.getByRole("button", { name: "Send verification code" }).click()
  await page.getByLabel("Six-digit verification code").fill("654321")
  await page.getByRole("button", { name: "Verify code" }).click()
  await page.getByLabel("Display name").fill("E2E Phone Learner")
  await page.getByLabel("Password", { exact: true }).fill("StrongPass123")
  await page.getByLabel("Confirm password").fill("StrongPass123")
  await page.getByRole("checkbox").nth(0).check()
  await page.getByRole("checkbox").nth(1).check()
  await page.getByRole("button", { name: "Create account" }).click()

  await expect(page).toHaveURL(/\/login\?registered=1$/u)
  expect(identityRequests.map((request) => request.path)).toEqual([
    "/api/auth/verification-challenges",
    "/api/auth/verification-challenges/verify",
    "/api/auth/register/phone",
  ])
  expect(identityRequests[0]?.body).toMatchObject({
    channel: "PHONE",
    identifier: "+14155551234",
  })
  expect(identityRequests[2]?.body).toMatchObject({ phone: "+14155551234" })
  for (const request of identityRequests) {
    expect(request.headers.authorization).toBeUndefined()
    expect(request.headers["x-tenant-id"]).toBeUndefined()
    expect(request.headers["x-subject-ref"]).toBeUndefined()
  }
})
