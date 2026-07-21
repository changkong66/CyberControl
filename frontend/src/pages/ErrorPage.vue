<script setup lang="ts">
import { AlertTriangle, ArrowLeft } from "@lucide/vue"
import { useRouter } from "vue-router"
import { useI18n } from "vue-i18n"
import LocaleSwitcher from "../shared/components/LocaleSwitcher.vue"
import { useAuthStore } from "../stores/auth"

const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()
</script>

<template>
  <main class="status-page">
    <div class="public-locale-row"><LocaleSwitcher /></div>
    <AlertTriangle :size="34" aria-hidden="true" />
    <h1>{{ t("statusPage.errorTitle") }}</h1>
    <p>{{ t("statusPage.errorDescription") }}</p>
    <button class="secondary-button" type="button" @click="router.replace(auth.authenticated ? '/workspace' : '/login')">
      <ArrowLeft :size="17" />{{ t(auth.authenticated ? "statusPage.backToWorkspace" : "statusPage.backToLogin") }}
    </button>
  </main>
</template>
