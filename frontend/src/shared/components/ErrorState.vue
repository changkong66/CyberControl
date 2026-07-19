<script setup lang="ts">
import { AlertTriangle, RefreshCw } from "@lucide/vue"

defineProps<{ message: string; retryable?: boolean }>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="state-row state-error" role="alert">
    <AlertTriangle :size="20" aria-hidden="true" />
    <span>{{ message }}</span>
    <button v-if="retryable" class="icon-button" type="button" title="重试" @click="$emit('retry')">
      <RefreshCw :size="17" />
    </button>
  </div>
</template>
