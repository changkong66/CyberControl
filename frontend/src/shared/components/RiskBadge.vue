<script setup lang="ts">
import type { RiskLevel } from "@liyans/contracts"

const labels: Record<RiskLevel, string> = {
  LOW: "低风险",
  MEDIUM: "中风险",
  HIGH: "高风险",
  CRITICAL: "极高风险",
}

defineProps<{ level?: RiskLevel | null }>()
</script>

<template>
  <span v-if="level" class="status-badge" :class="`risk-${level.toLowerCase()}`" :title="`核验风险：${labels[level]}`">
    <span class="status-dot" aria-hidden="true" />
    {{ labels[level] }}
  </span>
  <span v-else class="muted-value">未分级</span>
</template>
