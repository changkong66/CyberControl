const CACHE_PREFIX = "cybercontrol:tenant:"
const SSE_CURSOR_PREFIX = "cybercontrol:sse:"
const TENANT_SCOPED_PREFIXES = [CACHE_PREFIX, SSE_CURSOR_PREFIX] as const

export function tenantCacheKey(tenantId: string, name: string): string {
  return `${CACHE_PREFIX}${tenantId}:${name}`
}

export function clearTenantCaches(tenantId?: string): void {
  const keysToRemove: string[] = []
  for (let index = 0; index < window.sessionStorage.length; index += 1) {
    const key = window.sessionStorage.key(index)
    const belongsToTenant = tenantId
      ? key?.startsWith(`${CACHE_PREFIX}${tenantId}:`) ||
        key?.startsWith(`${SSE_CURSOR_PREFIX}${encodeURIComponent(tenantId)}:`)
      : true
    if (key && TENANT_SCOPED_PREFIXES.some((prefix) => key.startsWith(prefix)) && belongsToTenant) {
      keysToRemove.push(key)
    }
  }
  keysToRemove.forEach((key) => window.sessionStorage.removeItem(key))
}

export function clearAllTenantCaches(): void {
  clearTenantCaches()
}
