<script setup lang="ts">
import { AlertTriangle, ArrowLeft } from "@lucide/vue"
import { useRouter } from "vue-router"

const router = useRouter()
</script>

<template>
  <main class="status-page">
    <AlertTriangle :size="34" aria-hidden="true" />
    <h1>页面不可用</h1>
    <button class="secondary-button" type="button" @click="router.replace('/workspace')">
      <ArrowLeft :size="17" />返回工作台
    </button>
  </main>
</template>
