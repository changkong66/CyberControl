import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it } from "vitest"

import { createWorkbenchRouter } from "../src/app/router"
import type { OidcUserLike } from "../src/auth/types"
import { useAuthStore } from "../src/stores/auth"

function reviewer(permissions: string): OidcUserLike {
  return {
    access_token: "token",
    profile: {
      sub: "reviewer-001",
      tenant_id: "demo-academy",
      name: "Demo Reviewer",
      roles: ["reviewer"],
      permissions,
    },
  }
}

describe("route guards", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/")
  })

  it("redirects anonymous users to login without leaking tenant headers", async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore(pinia)
    auth.initialized = true
    const router = createWorkbenchRouter(pinia)
    await router.push("/verification")
    expect(router.currentRoute.value.name).toBe("login")
    expect(router.currentRoute.value.query.returnTo).toBe("/verification")
  })

  it("blocks a route when the authenticated token lacks its scope", async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore(pinia)
    auth.applyUser(reviewer("topic1:read topic4:read"))
    auth.initialized = true
    const router = createWorkbenchRouter(pinia)
    await router.push("/reviews")
    expect(router.currentRoute.value.name).toBe("forbidden")
  })

  it("allows a reviewer with the required scope", async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore(pinia)
    auth.applyUser(reviewer("topic1:read topic4:read topic4:review:read"))
    auth.initialized = true
    const router = createWorkbenchRouter(pinia)
    await router.push("/reviews")
    expect(router.currentRoute.value.name).toBe("reviews")
  })
})
