<script setup lang="ts">
import { computed } from "vue"

const props = defineProps<{
  before?: string | null
  after?: string | null
  beforeLabel?: string
  afterLabel?: string
}>()
const beforeLines = computed(() => (props.before ? props.before.split(/\r?\n/u) : []))
const afterLines = computed(() => (props.after ? props.after.split(/\r?\n/u) : []))
</script>

<template>
  <div v-if="before || after" class="diff-grid">
    <section>
      <header><span>{{ beforeLabel ?? "修订前" }}</span><small v-if="before">{{ beforeLines.length }} 行</small></header>
      <pre v-if="before"><code><span v-for="(line, index) in beforeLines" :key="`before-${index}`" class="diff-line diff-remove">{{ line || " " }}
</span></code></pre>
      <div v-else class="diff-unavailable">服务端未在当前列表接口返回基线正文。</div>
    </section>
    <section>
      <header><span>{{ afterLabel ?? "修订后" }}</span><small v-if="after">{{ afterLines.length }} 行</small></header>
      <pre v-if="after"><code><span v-for="(line, index) in afterLines" :key="`after-${index}`" class="diff-line diff-add">{{ line || " " }}
</span></code></pre>
      <div v-else class="diff-unavailable">服务端未在当前列表接口返回修订正文。</div>
    </section>
  </div>
  <div v-else class="empty-state compact-empty">当前接口只返回不可变修订元数据，未提供可展示的正文差异。</div>
</template>
