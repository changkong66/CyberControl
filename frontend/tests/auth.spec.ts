import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { userToIdentity } from "../src/auth/claims"
import { oidcSettings } from "../src/auth/config"
import { OidcSession, RETURN_TO_KEY } from "../src/auth/session"
import type { OidcManagerLike, OidcUserLike } from "../src/auth/types"
import { tenantCacheKey } from "../src/shared/cache"
import { useAuthStore } from "../src/stores/auth"
import { useTenantStore } from "../src/stores/tenant"

function oidcUser(
  tenantId = "demo-academy",
  permissions = "topic1:read topic4:read",
): OidcUserLike {
  return {
    access_token: "access-token",
    expires_at: 2_000_000_000,
    profile: {
      sub: "learner-001",
      name: "Demo Learner",
      email: "learner@example.invalid",
      tenant_id: tenantId,
      roles: ["learner"],
      permissions,
    },
  }
}

function manager(user: OidcUserLike | null): OidcManagerLike {
  return {
    getUser: vi.fn().mockResolvedValue(user),
    signinRedirect: vi.fn().mockResolvedValue(undefined),
    signinCallback: vi.fn().mockResolvedValue(user),
    signinSilent: vi.fn().mockResolvedValue(user),
    signoutRedirect: vi.fn().mockResolvedValue(undefined),
    removeUser: vi.fn().mockResolvedValue(undefined),
  } as OidcManagerLike
}

describe("OIDC identity and stores", () => {
  beforeEach(() => setActivePinia(createPinia()))

  it("uses OIDC discovery instead of incomplete static provider metadata", () => {
    expect(oidcSettings.authority).toBe("http://localhost:8080/realms/cybercontrol")
    expect(oidcSettings.scope).toBe("openid profile email")
    expect(oidcSettings.metadata).toBeUndefined()
  })

  it("derives tenant, roles and scopes from validated OIDC claims", () => {
    const identity = userToIdentity(oidcUser())
    expect(identity.tenantId).toBe("demo-academy")
    expect(identity.roles).toEqual(["learner"])
    expect(identity.scopes).toContain("topic4:read")
    expect(() => userToIdentity(oidcUser("invalid tenant"))).toThrow(/tenant identity/u)
  })

  it("stores a safe return path and delegates PKCE redirects", async () => {
    const fakeManager = manager(oidcUser())
    const session = new OidcSession(fakeManager)
    await session.login("//external.example")
    expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBe("/workspace")
    expect(fakeManager.signinRedirect).toHaveBeenCalledWith({ state: { returnTo: "/workspace" } })
    expect(session.consumeReturnTo()).toBe("/workspace")
    await session.login("/verification")
    expect(session.consumeReturnTo()).toBe("/verification")
    expect(await session.callback()).toEqual(oidcUser())
    expect(await session.silentRenew()).toEqual(oidcUser())
    await session.clear()
    expect(fakeManager.removeUser).toHaveBeenCalledOnce()
  })

  it("restores identity and clears every tenant cache after a tenant change", async () => {
    const auth = useAuthStore()
    await auth.restore(new OidcSession(manager(oidcUser())))
    expect(auth.authenticated).toBe(true)
    expect(useTenantStore().tenantId).toBe("demo-academy")

    const cacheKey = tenantCacheKey("demo-academy", "verification")
    window.sessionStorage.setItem(cacheKey, "cached")
    auth.applyUser(oidcUser("second-academy"))
    expect(window.sessionStorage.getItem(cacheKey)).toBeNull()
    expect(auth.hasAllScopes(["topic1:read", "topic4:read"])).toBe(true)
  })

  it("clears local state before redirecting to logout", async () => {
    const auth = useAuthStore()
    const fakeManager = manager(oidcUser())
    const session = new OidcSession(fakeManager)
    await auth.restore(session)
    await auth.logout(session)
    expect(auth.authenticated).toBe(false)
    expect(fakeManager.signoutRedirect).toHaveBeenCalledOnce()
  })

  it("handles empty and failed OIDC sessions without retaining identity", async () => {
    const auth = useAuthStore()
    await auth.restore(new OidcSession(manager(null)))
    expect(auth.status).toBe("idle")

    setActivePinia(createPinia())
    const failedAuth = useAuthStore()
    const failedManager = manager(null)
    failedManager.getUser = vi.fn().mockRejectedValue(new Error("OIDC offline"))
    await failedAuth.restore(new OidcSession(failedManager))
    expect(failedAuth.status).toBe("error")
    expect(failedAuth.errorMessage).toContain("OIDC offline")
  })

  it("records redirect and callback failures", async () => {
    const auth = useAuthStore()
    const failedManager = manager(null)
    failedManager.signinRedirect = vi.fn().mockRejectedValue(new Error("redirect failed"))
    await auth.login("/workspace", new OidcSession(failedManager))
    expect(auth.status).toBe("error")

    failedManager.signinCallback = vi.fn().mockRejectedValue(new Error("callback failed"))
    await expect(auth.completeCallback(new OidcSession(failedManager))).rejects.toThrow(
      "callback failed",
    )
  })
})
