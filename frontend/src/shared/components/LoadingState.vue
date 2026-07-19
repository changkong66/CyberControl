<script setup lang="ts">
import { LoaderCircle } from "@lucide/vue"

withDefaults(defineProps<{ label?: string }>(), { label: "正在加载" })
</script>

<template>
  <div class="state-row" role="status">
    <LoaderCircle class="spin" :size="20" aria-hidden="true" />
    <span>{{ label }}</span>
  </div>
</template>
