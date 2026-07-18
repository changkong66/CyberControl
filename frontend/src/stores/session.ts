import { defineStore } from "pinia"
import { computed, ref } from "vue"

function newSessionId(): string {
  return crypto.randomUUID()
}

export const useSessionStore = defineStore("session", () => {
  const sessionId = ref(window.sessionStorage.getItem("cybercontrol:session-id") ?? newSessionId())
  const active = computed(() => sessionId.value.length > 0)

  function rotate(): string {
    sessionId.value = newSessionId()
    window.sessionStorage.setItem("cybercontrol:session-id", sessionId.value)
    return sessionId.value
  }

  function clear(): void {
    window.sessionStorage.removeItem("cybercontrol:session-id")
    sessionId.value = ""
  }

  if (sessionId.value) {
    window.sessionStorage.setItem("cybercontrol:session-id", sessionId.value)
  }

  return { sessionId, active, rotate, clear }
})
