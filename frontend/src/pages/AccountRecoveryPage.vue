<script setup lang="ts">
import { ArrowLeft, KeyRound, ShieldCheck } from "@lucide/vue"
import { useI18n } from "vue-i18n"
import { RouterLink } from "vue-router"

import LocaleSwitcher from "../shared/components/LocaleSwitcher.vue"
import { useAuthStore } from "../stores/auth"

const { t } = useI18n()
const auth = useAuthStore()
</script>

<template>
  <main class="identity-public-page">
    <div class="public-locale-row"><LocaleSwitcher /></div>
    <section class="identity-auth-surface recovery-surface" aria-labelledby="recovery-title">
      <header class="identity-brand-header"><span class="auth-mark"><ShieldCheck :size="28" /></span><div><strong>CyberControl</strong><span>{{ t("app.tagline") }}</span></div></header>
      <div class="recovery-icon"><KeyRound :size="30" /></div>
      <div class="identity-title-block"><h1 id="recovery-title">{{ t("recovery.title") }}</h1><p>{{ t("recovery.description") }}</p></div>
      <p class="security-note recovery-note"><ShieldCheck :size="16" />{{ t("recovery.note") }}</p>
      <button class="primary-button full-width" type="button" :disabled="auth.status === 'loading'" @click="auth.recover('/account/profile')"><KeyRound :size="17" />{{ auth.status === "loading" ? t("recovery.working") : t("recovery.action") }}</button>
      <p v-if="auth.errorMessage" class="form-message error" role="alert">{{ auth.errorMessage }}</p>
      <RouterLink class="text-link" :to="{ name: 'login' }"><ArrowLeft :size="15" />{{ t("recovery.backToLogin") }}</RouterLink>
    </section>
  </main>
</template>
