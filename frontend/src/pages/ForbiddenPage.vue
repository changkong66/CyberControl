<script setup lang="ts">
import { ArrowLeft, LockKeyhole } from "@lucide/vue"
import { useRouter } from "vue-router"

const router = useRouter()
</script>

<template>
  <main class="status-page">
    <LockKeyhole :size="34" aria-hidden="true" />
    <h1>无权限访问</h1>
    <button class="secondary-button" type="button" @click="router.replace('/workspace')">
      <ArrowLeft :size="17" />返回工作台
    </button>
  </main>
</template>
