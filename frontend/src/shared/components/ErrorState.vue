<script setup lang="ts">
import { AlertTriangle, RefreshCw } from "@lucide/vue"
import { useI18n } from "vue-i18n"

defineProps<{ message: string; retryable?: boolean }>()
defineEmits<{ retry: [] }>()
const { t } = useI18n()
</script>

<template>
  <div class="state-row state-error" role="alert">
    <AlertTriangle :size="20" aria-hidden="true" />
    <span>{{ message }}</span>
    <button v-if="retryable" class="icon-button" type="button" :title="t('common.retry')" :aria-label="t('common.retry')" @click="$emit('retry')">
      <RefreshCw :size="17" />
    </button>
  </div>
</template>
