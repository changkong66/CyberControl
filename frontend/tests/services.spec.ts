import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createAppServices } from "../src/app/services"
import { oidcSession } from "../src/auth/session"
import type { OidcUserLike } from "../src/auth/types"
import { useAuthStore } from "../src/stores/auth"

const user: OidcUserLike = {
  access_token: "service-token",
  profile: {
    sub: "learner-001",
    tenant_id: "demo-academy",
    name: "Demo Learner",
    roles: ["learner"],
    permissions: "topic1:read",
  },
}

describe("application services", () => {
  beforeEach(() => setActivePinia(createPinia()))

  it("binds token, session and readiness clients to Pinia identity", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      expect(headers.get("authorization")).toBe("Bearer service-token")
      expect(headers.get("x-session-id")).toMatch(/^[0-9a-f-]{36}$/u)
      return new Response(
        JSON.stringify({ status: "ready", database: { status: "up" }, authentication: "configured" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      )
    }) as typeof fetch
    vi.stubGlobal("fetch", fetcher)
    vi.spyOn(oidcSession, "getUser").mockResolvedValue(user)
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore(pinia).applyUser(user)
    const services = createAppServices(pinia)
    const result = await services.api.readiness()
    expect(result.data.status).toBe("ready")
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it("clears cached identity after an authorization failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { error_code: "AUTH_REQUIRED", safe_message: "Authentication required." },
            trace_id: "e".repeat(32),
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    )
    vi.spyOn(oidcSession, "getUser").mockResolvedValue(user)
    const clear = vi.spyOn(oidcSession, "clear").mockResolvedValue(undefined)
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore(pinia)
    auth.applyUser(user)
    const services = createAppServices(pinia)
    await expect(services.api.requestEnvelope("/internal/topic4/verification")).rejects.toMatchObject({
      status: 401,
    })
    expect(auth.authenticated).toBe(false)
    expect(clear).toHaveBeenCalledOnce()
  })
})
