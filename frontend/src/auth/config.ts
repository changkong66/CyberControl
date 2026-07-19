import type { UserManagerSettings } from "oidc-client-ts"

const authority = import.meta.env.VITE_OIDC_AUTHORITY ?? "http://localhost:8080/realms/cybercontrol"
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID ?? "cybercontrol-workbench"

export const oidcSettings: UserManagerSettings = {
  authority,
  client_id: clientId,
  redirect_uri:
    import.meta.env.VITE_OIDC_REDIRECT_URI ?? `${window.location.origin}/auth/callback`,
  post_logout_redirect_uri:
    import.meta.env.VITE_OIDC_POST_LOGOUT_REDIRECT_URI ?? `${window.location.origin}/login`,
  response_type: "code",
  scope: import.meta.env.VITE_OIDC_SCOPE ?? "openid profile email",
  automaticSilentRenew: true,
  loadUserInfo: false,
  monitorSession: false,
  filterProtocolClaims: true,
}
