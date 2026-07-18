import { UserManager, WebStorageStateStore } from "oidc-client-ts"

import { oidcSettings } from "./config"
import type { OidcManagerLike, OidcUserLike } from "./types"

export const RETURN_TO_KEY = "cybercontrol:auth:return-to"

export class OidcSession {
  readonly manager: OidcManagerLike

  constructor(manager?: OidcManagerLike) {
    this.manager =
      manager ??
      (new UserManager({
        ...oidcSettings,
        userStore: new WebStorageStateStore({ store: window.sessionStorage }),
      }) as unknown as OidcManagerLike)
  }

  getUser(): Promise<OidcUserLike | null> {
    return this.manager.getUser()
  }

  async login(returnTo = "/workspace"): Promise<void> {
    const safeReturnTo = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/workspace"
    window.sessionStorage.setItem(RETURN_TO_KEY, safeReturnTo)
    await this.manager.signinRedirect({ state: { returnTo: safeReturnTo } })
  }

  async callback(url?: string): Promise<OidcUserLike> {
    return this.manager.signinCallback(url)
  }

  async silentRenew(): Promise<OidcUserLike> {
    return this.manager.signinSilent()
  }

  async logout(): Promise<void> {
    await this.manager.signoutRedirect({
      post_logout_redirect_uri: oidcSettings.post_logout_redirect_uri,
    })
  }

  async clear(): Promise<void> {
    await this.manager.removeUser()
  }

  consumeReturnTo(): string {
    const value = window.sessionStorage.getItem(RETURN_TO_KEY)
    window.sessionStorage.removeItem(RETURN_TO_KEY)
    return value && value.startsWith("/") && !value.startsWith("//") ? value : "/workspace"
  }
}

export const oidcSession = new OidcSession()
