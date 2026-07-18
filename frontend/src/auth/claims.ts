import type { AuthenticatedUser, ClaimValue, OidcUserLike } from "./types"

const TENANT_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/

function claimStrings(value: ClaimValue): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && item.length > 0)
  }
  if (typeof value === "string") {
    return value
      .split(/\s+/u)
      .map((item) => item.trim())
      .filter(Boolean)
  }
  return []
}

function claimString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null
}

export function userToIdentity(user: OidcUserLike): AuthenticatedUser {
  const subject = claimString(user.profile.sub)
  const tenantId = claimString(user.profile.tenant_id)
  if (!subject || !tenantId || !TENANT_PATTERN.test(tenantId)) {
    throw new Error("The validated OIDC profile has no usable tenant identity.")
  }

  const displayName =
    claimString(user.profile.name) ?? claimString(user.profile.preferred_username) ?? subject
  const email = claimString(user.profile.email)
  const scopes = claimStrings(user.profile.permissions)
  const roles = claimStrings(user.profile.roles)

  return {
    subject,
    tenantId,
    displayName,
    email,
    roles: [...new Set(roles)].sort(),
    scopes: [...new Set(scopes)].sort(),
    accessTokenExpiresAt: typeof user.expires_at === "number" ? user.expires_at : null,
  }
}
