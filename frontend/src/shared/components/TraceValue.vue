<script setup lang="ts">
import { Fingerprint } from "@lucide/vue"
import HashValue from "./HashValue.vue"

defineProps<{ value?: string | null }>()
</script>

<template>
  <div class="trace-value">
    <Fingerprint :size="15" aria-hidden="true" />
    <HashValue :value="value" label="TraceID" />
  </div>
</template>
