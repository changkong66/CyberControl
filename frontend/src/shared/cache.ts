const CACHE_PREFIX = "cybercontrol:tenant:"

export function tenantCacheKey(tenantId: string, name: string): string {
  return `${CACHE_PREFIX}${tenantId}:${name}`
}

export function clearTenantCaches(tenantId?: string): void {
  const keysToRemove: string[] = []
  for (let index = 0; index < window.sessionStorage.length; index += 1) {
    const key = window.sessionStorage.key(index)
    if (key && key.startsWith(CACHE_PREFIX) && (!tenantId || key.startsWith(`${CACHE_PREFIX}${tenantId}:`))) {
      keysToRemove.push(key)
    }
  }
  keysToRemove.forEach((key) => window.sessionStorage.removeItem(key))
}

export function clearAllTenantCaches(): void {
  clearTenantCaches()
}
