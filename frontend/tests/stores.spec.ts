import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it } from "vitest"

import { useNotificationsStore } from "../src/stores/notifications"
import { useSessionStore } from "../src/stores/session"
import { useTenantStore } from "../src/stores/tenant"

describe("application stores", () => {
  beforeEach(() => setActivePinia(createPinia()))

  it("rotates and clears workflow session identities", () => {
    const session = useSessionStore()
    const first = session.sessionId
    const second = session.rotate()
    expect(second).not.toBe(first)
    expect(window.sessionStorage.getItem("cybercontrol:session-id")).toBe(second)
    session.clear()
    expect(session.active).toBe(false)
  })

  it("exposes a read-only tenant view", () => {
    const tenant = useTenantStore()
    tenant.setIdentity("demo-academy", "Demo Academy")
    expect(tenant.available).toBe(true)
    expect(tenant.displayName).toBe("Demo Academy")
    tenant.clear()
    expect(tenant.available).toBe(false)
  })

  it("queues and dismisses notices deterministically", () => {
    const notifications = useNotificationsStore()
    const first = notifications.push("info", "Connected")
    notifications.push("warning", "Degraded")
    expect(notifications.notices).toHaveLength(2)
    notifications.dismiss(first)
    expect(notifications.notices).toHaveLength(1)
    notifications.clear()
    expect(notifications.notices).toEqual([])
  })
})
