import type { CandidateV1 } from "@liyans/contracts"

const UUID_PATTERN = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/iu

function uuidBytes(value: string): Uint8Array {
  if (!UUID_PATTERN.test(value)) throw new Error("Candidate ID is not a valid UUID.")
  const hex = value.replaceAll("-", "")
  return Uint8Array.from({ length: 16 }, (_, index) => Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16))
}

function formatUuid(bytes: Uint8Array): string {
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export async function uuidV5(namespace: string, name: string): Promise<string> {
  const input = new Uint8Array(16 + new TextEncoder().encode(name).length)
  input.set(uuidBytes(namespace), 0)
  input.set(new TextEncoder().encode(name), 16)
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-1", input))
  const result = digest.slice(0, 16)
  result[6] = (result[6]! & 0x0f) | 0x50
  result[8] = (result[8]! & 0x3f) | 0x80
  return formatUuid(result)
}

export function verificationIdForCandidate(candidate: CandidateV1): Promise<string> {
  return uuidV5(
    candidate.candidate_id,
    `topic4-verification:${candidate.candidate_version}:${candidate.candidate_sha256}`,
  )
}
