<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import LoadingState from "../shared/components/LoadingState.vue"
import ErrorState from "../shared/components/ErrorState.vue"
import { useAuthStore } from "../stores/auth"

const router = useRouter()
const auth = useAuthStore()
const failed = ref(false)
const { t } = useI18n()

onMounted(async () => {
  try {
    const returnTo = await auth.completeCallback()
    await router.replace(returnTo)
  } catch {
    failed.value = true
  }
})
</script>

<template>
  <main class="auth-page">
    <ErrorState v-if="failed" :message="t('auth.callbackFailed')" />
    <LoadingState v-else :label="t('auth.callbackLoading')" />
  </main>
</template>
