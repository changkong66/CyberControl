<script setup lang="ts">
import type { Component } from "vue"

defineProps<{
  label: string
  value: string | number
  detail?: string
  icon?: Component
  tone?: "neutral" | "positive" | "warning" | "critical"
}>()
</script>

<template>
  <article class="metric-tile" :class="`metric-${tone ?? 'neutral'}`">
    <div class="metric-tile-label">
      <component :is="icon" v-if="icon" :size="16" aria-hidden="true" />
      <span>{{ label }}</span>
    </div>
    <strong>{{ value }}</strong>
    <small v-if="detail">{{ detail }}</small>
  </article>
</template>
