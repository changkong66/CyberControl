import type {
  AccountAdminViewV1,
  AccountProfileV1,
  VerificationChallengeReceiptV1,
} from "@liyans/contracts"
import { describe, expect, it, vi } from "vitest"

import {
  ApiClient,
  ApiClientError,
  redactSensitiveDetails,
  redactSensitiveText,
} from "../src/api/client"
import { WorkbenchApi } from "../src/api/facade"
import { isIdentityConflict, localizedIdentityError } from "../src/identity/errors"

const now = "2026-07-21T00:00:00Z"

function envelope(data: Record<string, unknown>): Record<string, unknown> {
  return {
    schema_version: "identity.api-envelope.v1",
    request_id: "11111111-1111-4111-8111-111111111111",
    trace_id: "a".repeat(32),
    data,
  }
}

function response(data: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(envelope(data)), {
    status,
    headers: { "Content-Type": "application/json", "X-Trace-ID": "b".repeat(32) },
  })
}

function profile(tenantId = "demo-academy"): AccountProfileV1 {
  return {
    schema_version: "account.profile.v1",
    account_id: "22222222-2222-4222-8222-222222222222",
    tenant_id: tenantId,
    subject_ref: "user:learner",
    display_name: "Learner",
    preferred_locale: "zh-CN",
    email_hint: "l***@example.invalid",
    email_verified: true,
    phone_hint: null,
    phone_verified: false,
    status: "ACTIVE",
    profile_version: 1,
    created_at: now,
    updated_at: now,
  }
}

function admin(): AccountAdminViewV1 {
  return { ...profile(), schema_version: "account.admin-view.v1", disabled_reason_code: null }
}

function challenge(state: "PENDING" | "VERIFIED" = "PENDING"): VerificationChallengeReceiptV1 {
  return {
    schema_version: "verification-challenge.receipt.v1",
    challenge_id: "33333333-3333-4333-8333-333333333333",
    channel: "EMAIL",
    purpose: "REGISTER",
    state,
    delivery_hint: "l***@example.invalid",
    expires_at: now,
    resend_after_seconds: 60,
  }
}

describe("identity API boundary", () => {
  it("omits Bearer identity from public registration and validates the frozen contracts", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      expect(headers.get("authorization")).toBeNull()
      expect(headers.get("idempotency-key")).toBe("identity-request-000000000000000000")
      expect(headers.has("x-tenant-id")).toBe(false)
      return response({ challenge: challenge() }, 202)
    }) as typeof fetch
    const api = new WorkbenchApi(
      new ApiClient({ baseUrl: "http://localhost", fetcher, getAccessToken: () => "must-not-leak" }),
    )
    const result = await api.requestRegistrationChallenge(
      { channel: "EMAIL", purpose: "REGISTER", identifier: "learner@example.invalid" },
      "identity-request-000000000000000000",
    )
    expect(result.data.challenge_id).toBe(challenge().challenge_id)
  })

  it("requires authentication and rejects cross-tenant identity documents", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("authorization")).toBe("Bearer token")
      return response({ profile: profile("other-academy") })
    }) as typeof fetch
    const api = new WorkbenchApi(
      new ApiClient({ baseUrl: "http://localhost", fetcher, getAccessToken: () => "token" }),
      () => "demo-academy",
    )
    await expect(api.getAccountProfile()).rejects.toThrow(/trusted tenant boundary/u)

    const noTokenFetcher = vi.fn() as unknown as typeof fetch
    const noTokenApi = new WorkbenchApi(new ApiClient({ fetcher: noTokenFetcher }))
    await expect(noTokenApi.getAccountProfile()).rejects.toMatchObject({ status: 401 })
    expect(noTokenFetcher).not.toHaveBeenCalled()
  })

  it("validates tenant account lists and exact status mutation payloads", async () => {
    const requests: Array<{ path: string; body: unknown; key: string | null }> = []
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname
      requests.push({
        path,
        body: init?.body ? JSON.parse(String(init.body)) as unknown : null,
        key: new Headers(init?.headers).get("idempotency-key"),
      })
      return path.endsWith("/disable") ? response({ account: { ...admin(), status: "DISABLED", profile_version: 2 } }) : response({ accounts: [admin()] })
    }) as typeof fetch
    const api = new WorkbenchApi(
      new ApiClient({ baseUrl: "http://localhost", fetcher, getAccessToken: () => "token" }),
      () => "demo-academy",
    )
    expect((await api.listTenantAccounts()).data).toHaveLength(1)
    await api.setTenantAccountEnabled(
      admin().account_id,
      false,
      { expected_version: 1, reason_code: "POLICY_REVIEW" },
      "identity-status-0000000000000000000",
    )
    expect(requests[1]).toMatchObject({
      path: `/internal/tenant/accounts/${admin().account_id}/disable`,
      body: { expected_version: 1, reason_code: "POLICY_REVIEW" },
      key: "identity-status-0000000000000000000",
    })
  })

  it("fails closed for malformed successful identity envelopes", async () => {
    const client = new ApiClient({
      baseUrl: "http://localhost",
      getAccessToken: () => "token",
      fetcher: vi.fn().mockResolvedValue(response({ profile: { account_id: "invalid" } })) as typeof fetch,
    })
    await expect(new WorkbenchApi(client).getAccountProfile()).rejects.toThrow(/contract is invalid/u)
  })

  it("redacts secrets and PII from errors without hiding stable error codes", () => {
    const details = redactSensitiveDetails({
      error: { error_code: "LIYAN-IDENTITY-CHALLENGE-INVALID" },
      email: "person@example.com",
      nested: { access_token: "eyJheader.payload.signature", phone: "+14155551234" },
    }) as Record<string, unknown>
    expect(JSON.stringify(details)).not.toContain("person@example.com")
    expect(JSON.stringify(details)).not.toContain("+14155551234")
    expect(JSON.stringify(details)).toContain("LIYAN-IDENTITY-CHALLENGE-INVALID")
    expect(redactSensitiveText("contact person@example.com with +14155551234")).toBe(
      "contact [REDACTED] with [REDACTED]",
    )
    const error = new ApiClientError(400, "CODE", "person@example.com failed", null, details)
    expect(error.message).not.toContain("person@example.com")
  })

  it("localizes stable identity errors and detects CAS conflicts", () => {
    expect(
      localizedIdentityError(
        new ApiClientError(
          400,
          "LIYAN-IDENTITY-CHALLENGE-EXPIRED",
          "Expired",
          "a".repeat(32),
        ),
        "errors.generic",
      ),
    ).toContain("无效或已过期")
    expect(
      isIdentityConflict(
        new ApiClientError(409, "LIYAN-IDENTITY-ACCOUNT-CONFLICT", "Conflict", null),
      ),
    ).toBe(true)
    expect(isIdentityConflict(new Error("network"))).toBe(false)
  })
})
