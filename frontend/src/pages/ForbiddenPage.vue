<script setup lang="ts">
import { ArrowLeft, LockKeyhole } from "@lucide/vue"
import { useRouter } from "vue-router"
import { useI18n } from "vue-i18n"
import LocaleSwitcher from "../shared/components/LocaleSwitcher.vue"

const router = useRouter()
const { t } = useI18n()
</script>

<template>
  <main class="status-page">
    <div class="public-locale-row"><LocaleSwitcher /></div>
    <LockKeyhole :size="34" aria-hidden="true" />
    <h1>{{ t("statusPage.forbiddenTitle") }}</h1>
    <p>{{ t("statusPage.forbiddenDescription") }}</p>
    <button class="secondary-button" type="button" @click="router.replace('/workspace')">
      <ArrowLeft :size="17" />{{ t("statusPage.backToWorkspace") }}
    </button>
  </main>
</template>
