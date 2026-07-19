<script setup lang="ts">
const props = withDefaults(defineProps<{ value: number; label?: string; detail?: string }>(), { label: "进度" })
const bounded = () => Math.min(100, Math.max(0, props.value))
</script>

<template>
  <div class="progress-block">
    <div class="progress-label">
      <span>{{ label }}</span>
      <strong>{{ Math.round(bounded()) }}%</strong>
    </div>
    <div class="progress-track" role="progressbar" :aria-valuenow="bounded()" aria-valuemin="0" aria-valuemax="100">
      <span class="progress-value" :style="{ width: `${bounded()}%` }" />
    </div>
    <small v-if="detail">{{ detail }}</small>
  </div>
</template>
