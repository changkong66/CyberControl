import type { VerificationChallengeReceiptV1 } from "@liyans/contracts"
import { computed, onScopeDispose, ref } from "vue"

import { createPayloadIdempotency } from "./idempotency"

export function useChallengeState(scope: string) {
  const receipt = ref<VerificationChallengeReceiptV1 | null>(null)
  const verified = ref(false)
  const code = ref("")
  const remainingSeconds = ref(0)
  const requestOperation = createPayloadIdempotency(`${scope}-request`)
  const verifyOperation = createPayloadIdempotency(`${scope}-verify`)
  let timer: ReturnType<typeof setInterval> | null = null

  const canRequest = computed(() => remainingSeconds.value <= 0)

  function stopTimer(): void {
    if (timer) clearInterval(timer)
    timer = null
  }

  function startTimer(seconds: number): void {
    stopTimer()
    remainingSeconds.value = Math.max(0, seconds)
    if (!remainingSeconds.value) return
    timer = setInterval(() => {
      remainingSeconds.value = Math.max(0, remainingSeconds.value - 1)
      if (!remainingSeconds.value) stopTimer()
    }, 1000)
  }

  function acceptReceipt(next: VerificationChallengeReceiptV1): void {
    receipt.value = next
    verified.value = next.state === "VERIFIED"
    startTimer(next.resend_after_seconds)
    requestOperation.complete()
  }

  function acceptVerification(next: VerificationChallengeReceiptV1): void {
    receipt.value = next
    verified.value = next.state === "VERIFIED"
    verifyOperation.complete()
  }

  function reset(): void {
    stopTimer()
    receipt.value = null
    verified.value = false
    code.value = ""
    remainingSeconds.value = 0
    requestOperation.reset()
    verifyOperation.reset()
  }

  onScopeDispose(stopTimer)

  return {
    receipt,
    verified,
    code,
    remainingSeconds,
    canRequest,
    requestKeyFor: requestOperation.keyFor,
    verifyKeyFor: verifyOperation.keyFor,
    acceptReceipt,
    acceptVerification,
    reset,
  }
}
