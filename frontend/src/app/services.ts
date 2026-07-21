import type { Pinia } from "pinia"
import { inject, type InjectionKey } from "vue"

import { ApiClient } from "../api/client"
import { WorkbenchApi } from "../api/facade"
import { oidcSession, type OidcSession } from "../auth/session"
import { SseClient } from "../streaming/sse"
import { useAuthStore } from "../stores/auth"
import { useSessionStore } from "../stores/session"
import { useTenantStore } from "../stores/tenant"

export interface AppServices {
  api: ApiClient
  workbench: WorkbenchApi
  sse: SseClient
  oidc: OidcSession
}

export const appServicesKey: InjectionKey<AppServices> = Symbol("cybercontrol-app-services")

export function createAppServices(pinia: Pinia): AppServices {
  const auth = useAuthStore(pinia)
  const session = useSessionStore(pinia)
  const tenant = useTenantStore(pinia)
  const accessToken = async () => (await oidcSession.getUser())?.access_token ?? null
  const clearRejectedIdentity = (): void => {
    auth.clearLocalState()
    void oidcSession.clear()
  }

  const api = new ApiClient({
    getAccessToken: accessToken,
    getSessionId: () => session.sessionId || null,
    onAuthorizationFailure: clearRejectedIdentity,
  })

  return {
    oidc: oidcSession,
    api,
    workbench: new WorkbenchApi(api, () => tenant.tenantId),
    sse: new SseClient({
      getAccessToken: accessToken,
      getSessionId: () => session.sessionId || null,
      getTenantId: () => tenant.tenantId,
      onAuthorizationFailure: clearRejectedIdentity,
    }),
  }
}

export function useAppServices(): AppServices {
  const services = inject(appServicesKey)
  if (!services) throw new Error("Application services are unavailable.")
  return services
}
