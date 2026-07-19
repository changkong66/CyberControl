<script setup lang="ts">
import { Check, Copy } from "@lucide/vue"
import { ref } from "vue"

const props = defineProps<{ value?: string | null; label?: string }>()
const copied = ref(false)

async function copy(): Promise<void> {
  if (!props.value) return
  await navigator.clipboard?.writeText(props.value)
  copied.value = true
  window.setTimeout(() => (copied.value = false), 1200)
}
</script>

<template>
  <div class="hash-value">
    <span v-if="label" class="hash-label">{{ label }}</span>
    <code>{{ value || "未提供" }}</code>
    <button v-if="value" class="icon-button icon-button-light" type="button" :title="copied ? '已复制' : '复制哈希'" :aria-label="copied ? '已复制' : '复制哈希'" @click="copy">
      <Check v-if="copied" :size="14" />
      <Copy v-else :size="14" />
    </button>
  </div>
</template>
