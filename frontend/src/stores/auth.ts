import { defineStore } from "pinia"
import { computed, ref } from "vue"

import { userToIdentity } from "../auth/claims"
import { oidcSession, type OidcSession } from "../auth/session"
import type { AuthenticatedUser, OidcUserLike } from "../auth/types"
import { clearAllTenantCaches } from "../shared/cache"
import { useSessionStore } from "./session"
import { useTenantStore } from "./tenant"

export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthenticatedUser | null>(null)
  const status = ref<"idle" | "loading" | "ready" | "error">("idle")
  const errorMessage = ref<string | null>(null)
  const initialized = ref(false)
  const authenticated = computed(() => user.value !== null)

  function applyUser(oidcUser: OidcUserLike): AuthenticatedUser {
    const next = userToIdentity(oidcUser)
    if (
      user.value &&
      (user.value.tenantId !== next.tenantId || user.value.subject !== next.subject)
    ) {
      clearAllTenantCaches()
    }
    user.value = next
    useTenantStore().setIdentity(next.tenantId, next.displayName)
    useSessionStore().rotate()
    status.value = "ready"
    errorMessage.value = null
    return next
  }

  async function restore(session: OidcSession = oidcSession): Promise<void> {
    if (initialized.value) return
    status.value = "loading"
    try {
      const existing = await session.getUser()
      if (existing) applyUser(existing)
      else status.value = "idle"
    } catch (error) {
      status.value = "error"
      errorMessage.value = error instanceof Error ? error.message : "无法恢复登录状态。"
    } finally {
      initialized.value = true
    }
  }

  async function login(returnTo?: string, session: OidcSession = oidcSession): Promise<void> {
    status.value = "loading"
    errorMessage.value = null
    try {
      await session.login(returnTo)
    } catch (error) {
      status.value = "error"
      errorMessage.value = error instanceof Error ? error.message : "登录请求失败。"
    }
  }

  async function completeCallback(session: OidcSession = oidcSession): Promise<string> {
    status.value = "loading"
    try {
      const callbackUser = await session.callback()
      applyUser(callbackUser)
      return session.consumeReturnTo()
    } catch (error) {
      status.value = "error"
      errorMessage.value = error instanceof Error ? error.message : "登录回调无效。"
      throw error
    }
  }

  async function logout(session: OidcSession = oidcSession): Promise<void> {
    clearLocalState()
    await session.logout()
  }

  function clearLocalState(): void {
    clearAllTenantCaches()
    user.value = null
    useTenantStore().clear()
    useSessionStore().clear()
    status.value = "idle"
    errorMessage.value = null
  }

  function hasScope(scope: string): boolean {
    return user.value?.scopes.includes(scope) ?? false
  }

  function hasAllScopes(scopes: readonly string[]): boolean {
    return scopes.every((scope) => hasScope(scope))
  }

  return {
    user,
    status,
    errorMessage,
    initialized,
    authenticated,
    restore,
    login,
    completeCallback,
    logout,
    clearLocalState,
    hasScope,
    hasAllScopes,
    applyUser,
  }
})
