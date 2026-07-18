import { defineStore } from "pinia"
import { ref } from "vue"

export interface Notice {
  id: string
  kind: "info" | "success" | "warning" | "error"
  message: string
}

export const useNotificationsStore = defineStore("notifications", () => {
  const notices = ref<Notice[]>([])

  function push(kind: Notice["kind"], message: string): string {
    const id = crypto.randomUUID()
    notices.value.push({ id, kind, message })
    return id
  }

  function dismiss(id: string): void {
    notices.value = notices.value.filter((notice) => notice.id !== id)
  }

  function clear(): void {
    notices.value = []
  }

  return { notices, push, dismiss, clear }
})
