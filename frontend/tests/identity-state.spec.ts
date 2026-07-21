import { effectScope } from "vue"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useChallengeState } from "../src/identity/challenge"
import { createPayloadIdempotency } from "../src/identity/idempotency"
import {
  normalizeContact,
  validContact,
  validDisplayName,
  validPassword,
  validVerificationCode,
} from "../src/identity/validation"

describe("identity form state", () => {
  afterEach(() => vi.useRealTimers())

  it("normalizes contacts exactly like the frozen backend contract", () => {
    expect(normalizeContact("EMAIL", " User@Example.COM ")).toBe("user@example.com")
    expect(normalizeContact("PHONE", "+1 (415) 555-1234")).toBe("+14155551234")
    expect(validContact("EMAIL", "user@example.com")).toBe(true)
    expect(validContact("PHONE", "+14155551234")).toBe(true)
    expect(validVerificationCode("123456")).toBe(true)
    expect(validPassword("12345678")).toBe(true)
    expect(validDisplayName("Learner")).toBe(true)
  })

  it("reuses idempotency keys for identical retries and rotates them when payloads change", () => {
    const operation = createPayloadIdempotency("test-operation")
    const first = operation.keyFor({ nested: { value: 1 }, channel: "EMAIL" })
    expect(operation.keyFor({ channel: "EMAIL", nested: { value: 1 } })).toBe(first)
    expect(operation.keyFor({ channel: "EMAIL", nested: { value: 2 } })).not.toBe(first)
    const changed = operation.keyFor({ channel: "EMAIL", nested: { value: 2 } })
    operation.complete()
    expect(operation.keyFor({ channel: "EMAIL", nested: { value: 2 } })).not.toBe(changed)
  })

  it("rotates challenge keys after accepted operations and changed verification codes", () => {
    vi.useFakeTimers()
    const scope = effectScope()
    const state = scope.run(() => useChallengeState("test"))
    expect(state).toBeDefined()
    if (!state) return
    const request = { channel: "EMAIL", purpose: "REGISTER", identifier: "learner@example.invalid" }
    const firstRequestKey = state.requestKeyFor(request)
    const firstVerifyKey = state.verifyKeyFor({ challenge_id: "33333333-3333-4333-8333-333333333333", code: "000000" })
    state.acceptReceipt({
      challenge_id: "33333333-3333-4333-8333-333333333333",
      channel: "EMAIL",
      purpose: "REGISTER",
      state: "PENDING",
      delivery_hint: "l***@example.invalid",
      expires_at: "2026-07-21T00:05:00Z",
      resend_after_seconds: 2,
    })
    expect(state.requestKeyFor(request)).not.toBe(firstRequestKey)
    expect(state.verifyKeyFor({ challenge_id: "33333333-3333-4333-8333-333333333333", code: "000000" })).toBe(firstVerifyKey)
    expect(state.verifyKeyFor({ challenge_id: "33333333-3333-4333-8333-333333333333", code: "123456" })).not.toBe(firstVerifyKey)
    expect(state.canRequest.value).toBe(false)
    vi.advanceTimersByTime(2000)
    expect(state.canRequest.value).toBe(true)
    const acceptedVerifyKey = state.verifyKeyFor({ challenge_id: "33333333-3333-4333-8333-333333333333", code: "123456" })
    state.acceptVerification({ ...state.receipt.value!, state: "VERIFIED" })
    expect(state.verified.value).toBe(true)
    expect(state.verifyKeyFor({ challenge_id: "33333333-3333-4333-8333-333333333333", code: "123456" })).not.toBe(acceptedVerifyKey)
    state.code.value = "123456"
    state.reset()
    expect(state.receipt.value).toBeNull()
    expect(state.code.value).toBe("")
    expect(state.canRequest.value).toBe(true)
    scope.stop()
  })
})
