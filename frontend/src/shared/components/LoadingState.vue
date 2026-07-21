<script setup lang="ts">
import { LoaderCircle } from "@lucide/vue"
import { computed } from "vue"
import { useI18n } from "vue-i18n"

const props = defineProps<{ label?: string }>()
const { t } = useI18n()
const resolvedLabel = computed(() => props.label ?? t("common.loading"))
</script>

<template>
  <div class="state-row" role="status">
    <LoaderCircle class="spin" :size="20" aria-hidden="true" />
    <span>{{ resolvedLabel }}</span>
  </div>
</template>
