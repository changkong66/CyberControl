<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"

import LoadingState from "../shared/components/LoadingState.vue"
import ErrorState from "../shared/components/ErrorState.vue"
import { useAuthStore } from "../stores/auth"

const router = useRouter()
const auth = useAuthStore()
const failed = ref(false)

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
    <ErrorState v-if="failed" message="登录回调校验失败。" />
    <LoadingState v-else label="正在校验身份" />
  </main>
</template>
