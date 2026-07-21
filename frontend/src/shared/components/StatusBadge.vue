<script setup lang="ts">
import { useI18n } from "vue-i18n"

const props = defineProps<{ value: string | null | undefined; label?: string }>()
const { t } = useI18n()

const normalized = () => (props.value ?? "UNKNOWN").toLowerCase().replaceAll("_", "-")
</script>

<template>
  <span class="status-badge" :class="`status-${normalized()}`">
    <span class="status-dot" aria-hidden="true" />
    {{ label ?? value ?? t("common.unknown") }}
  </span>
</template>
