import { newIdempotencyKey } from "../api/types"

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize)
  if (typeof value !== "object" || value === null) return value

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalize(item)]),
  )
}

export function createPayloadIdempotency(scope: string) {
  let key = newIdempotencyKey(scope)
  let fingerprint: string | null = null

  function keyFor(payload: unknown): string {
    const nextFingerprint = JSON.stringify(canonicalize(payload))
    if (fingerprint !== null && fingerprint !== nextFingerprint) {
      key = newIdempotencyKey(scope)
    }
    fingerprint = nextFingerprint
    return key
  }

  function complete(): void {
    key = newIdempotencyKey(scope)
    fingerprint = null
  }

  return { keyFor, complete, reset: complete }
}
