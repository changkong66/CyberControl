<script setup lang="ts">
const props = defineProps<{ value: string | null | undefined; label?: string }>()

const normalized = () => (props.value ?? "UNKNOWN").toLowerCase().replaceAll("_", "-")
</script>

<template>
  <span class="status-badge" :class="`status-${normalized()}`">
    <span class="status-dot" aria-hidden="true" />
    {{ label ?? value ?? "未知" }}
  </span>
</template>
