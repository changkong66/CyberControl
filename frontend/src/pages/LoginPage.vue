<script setup lang="ts">
import { LogIn, ShieldCheck } from "@lucide/vue"
import { computed } from "vue"
import { useRoute } from "vue-router"
import { useI18n } from "vue-i18n"
import { RouterLink } from "vue-router"

import { useAuthStore } from "../stores/auth"
import LocaleSwitcher from "../shared/components/LocaleSwitcher.vue"

const route = useRoute()
const auth = useAuthStore()
const { t } = useI18n()
const returnTo = computed(() => (typeof route.query.returnTo === "string" ? route.query.returnTo : "/workspace"))
const registered = computed(() => route.query.registered === "1")
</script>

<template>
  <main class="identity-public-page">
    <div class="public-locale-row"><LocaleSwitcher /></div>
    <section class="identity-auth-surface login-surface">
      <div class="auth-brand">
        <span class="auth-mark"><ShieldCheck :size="30" /></span>
        <div><h1>CyberControl</h1><p>{{ t("app.tagline") }}</p></div>
      </div>
      <p v-if="registered" class="form-message success" role="status">{{ t("auth.registered") }}</p>
      <button class="primary-button login-button" type="button" :disabled="auth.status === 'loading'" @click="auth.login(returnTo)"><LogIn :size="18" /><span>{{ auth.status === "loading" ? t("auth.signingIn") : t("auth.signIn") }}</span></button>
      <nav class="auth-links" :aria-label="t('routes.login')"><RouterLink :to="{ name: 'register' }">{{ t("auth.createAccount") }}</RouterLink><RouterLink :to="{ name: 'account-recovery' }">{{ t("auth.forgotPassword") }}</RouterLink></nav>
      <p v-if="auth.errorMessage" class="auth-error" role="alert">{{ auth.errorMessage }}</p>
    </section>
  </main>
</template>
