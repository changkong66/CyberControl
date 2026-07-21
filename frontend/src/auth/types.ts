export type ClaimValue = string | string[] | undefined

export interface OidcProfile {
  sub?: unknown
  name?: unknown
  preferred_username?: unknown
  email?: unknown
  tenant_id?: unknown
  roles?: ClaimValue
  permissions?: ClaimValue
  [key: string]: unknown
}

export interface OidcUserLike {
  access_token: string
  profile: OidcProfile
  expires_at?: number
  scopes?: string[]
}

export interface OidcManagerLike {
  getUser(): Promise<OidcUserLike | null>
  signinRedirect(args?: {
    state?: Record<string, string>
    ui_locales?: string
    prompt?: string
    extraQueryParams?: Record<string, string | number | boolean>
  }): Promise<void>
  signinCallback(url?: string): Promise<OidcUserLike>
  signinSilent(): Promise<OidcUserLike>
  signoutRedirect(args?: { post_logout_redirect_uri?: string }): Promise<void>
  removeUser(): Promise<void>
}

export interface AuthenticatedUser {
  subject: string
  tenantId: string
  displayName: string
  email: string | null
  roles: readonly string[]
  scopes: readonly string[]
  accessTokenExpiresAt: number | null
}
