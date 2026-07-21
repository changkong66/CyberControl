<script setup lang="ts">
import { Languages } from "@lucide/vue"
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useRoute } from "vue-router"

import { normalizeLocale, setAppLocale, translate, type AppLocale } from "../../i18n"

const props = withDefaults(defineProps<{ compact?: boolean; modelValue?: AppLocale }>(), { compact: false })
const emit = defineEmits<{ "update:modelValue": [locale: AppLocale]; change: [locale: AppLocale] }>()
const { locale, t } = useI18n()
const route = useRoute()
const current = computed(() => props.modelValue ?? normalizeLocale(locale.value))

function change(event: Event): void {
  const next = setAppLocale((event.target as HTMLSelectElement).value)
  document.title = route.meta.titleKey ? `${translate(route.meta.titleKey)} | CyberControl` : "CyberControl"
  emit("update:modelValue", next)
  emit("change", next)
}
</script>

<template>
  <label class="locale-switcher" :class="{ compact }">
    <Languages :size="16" aria-hidden="true" />
    <span v-if="!compact">{{ t("locale.label") }}</span>
    <select :value="current" :aria-label="t('locale.label')" @change="change">
      <option value="zh-CN">{{ t("locale.zhCN") }}</option>
      <option value="zh-TW">{{ t("locale.zhTW") }}</option>
      <option value="en-US">{{ t("locale.enUS") }}</option>
    </select>
  </label>
</template>
