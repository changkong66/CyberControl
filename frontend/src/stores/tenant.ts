import { defineStore } from "pinia"
import { computed, ref } from "vue"

export const useTenantStore = defineStore("tenant", () => {
  const tenantId = ref<string | null>(null)
  const displayName = ref<string | null>(null)
  const initialized = ref(false)
  const available = computed(() => initialized.value && tenantId.value !== null)

  function setIdentity(nextTenantId: string | null, nextDisplayName: string | null): void {
    tenantId.value = nextTenantId
    displayName.value = nextDisplayName
    initialized.value = true
  }

  function clear(): void {
    setIdentity(null, null)
  }

  return { tenantId, displayName, initialized, available, setIdentity, clear }
})
