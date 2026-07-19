<script setup lang="ts">
import { ShieldCheck } from "@lucide/vue"
import type { EvidenceRefV1 } from "@liyans/contracts"
import HashValue from "./HashValue.vue"

defineProps<{ evidence: EvidenceRefV1[] }>()
</script>

<template>
  <section class="evidence-panel">
    <div class="section-title-row">
      <div>
        <h2>权威证据链</h2>
        <p>仅展示服务端持久化证据引用，内容哈希用于核对，不作为客户端授权依据。</p>
      </div>
      <ShieldCheck :size="20" aria-hidden="true" />
    </div>
    <div v-if="evidence.length" class="evidence-list">
      <article v-for="item in evidence" :key="item.evidence_ref_id" class="evidence-row">
        <div class="evidence-main">
          <strong>{{ item.source_document_id }}</strong>
          <span>{{ item.section_id }} · 知识块 {{ item.knowledge_chunk_id }}</span>
        </div>
        <HashValue :value="item.excerpt_sha256" label="Excerpt SHA" />
        <span class="evidence-citation">{{ item.citation }}</span>
      </article>
    </div>
    <div v-else class="empty-state compact-empty">暂无证据引用</div>
  </section>
</template>
