<script setup lang="ts">
import { LogIn, ShieldCheck } from "@lucide/vue"
import { computed } from "vue"
import { useRoute } from "vue-router"

import { useAuthStore } from "../stores/auth"

const route = useRoute()
const auth = useAuthStore()
const returnTo = computed(() => (typeof route.query.returnTo === "string" ? route.query.returnTo : "/workspace"))
</script>

<template>
  <main class="auth-page">
    <div class="auth-brand">
      <span class="auth-mark"><ShieldCheck :size="30" /></span>
      <div>
        <h1>CyberControl</h1>
        <p>可信教育工作台</p>
      </div>
    </div>
    <button class="primary-button login-button" type="button" :disabled="auth.status === 'loading'" @click="auth.login(returnTo)">
      <LogIn :size="18" />
      <span>使用统一身份登录</span>
    </button>
    <p v-if="auth.errorMessage" class="auth-error" role="alert">{{ auth.errorMessage }}</p>
  </main>
</template>
