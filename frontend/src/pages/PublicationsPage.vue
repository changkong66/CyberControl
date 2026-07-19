<script setup lang="ts">
import { Archive, CheckCircle2, RefreshCw, Search, Send, ShieldCheck } from "@lucide/vue"
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import type { JsonObject, PublicationHistoryItem } from "../api/types"
import { useAppServices } from "../app/services"
import { useAuthStore } from "../stores/auth"
import ErrorState from "../shared/components/ErrorState.vue"
import HashValue from "../shared/components/HashValue.vue"
import LoadingState from "../shared/components/LoadingState.vue"
import MetricTile from "../shared/components/MetricTile.vue"
import PageHeader from "../shared/components/PageHeader.vue"
import ReleaseController from "../shared/components/ReleaseController.vue"
import StatusBadge from "../shared/components/StatusBadge.vue"
import TraceValue from "../shared/components/TraceValue.vue"

const services = useAppServices()
const auth = useAuthStore()
const verificationId = ref("")
const search = ref("")
const records = ref<PublicationHistoryItem[]>([])
const events = ref<JsonObject[]>([])
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const traceId = ref<string | null>(null)
const streamAbort = ref<AbortController | null>(null)
const canRelease = computed(() => auth.hasScope("topic4:release:write"))

const filteredRecords = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase()
  if (!needle) return records.value
  return records.value.filter((record) => JSON.stringify(record).toLocaleLowerCase().includes(needle))
})
const committedCount = computed(() => records.value.filter((record) => String(record.document?.state ?? "").includes("COMMITTED") || record.table?.includes("publication")).length)
const authorizationCount = computed(() => records.value.filter((record) => record.table?.includes("authorization")).length)

function field(record: PublicationHistoryItem, key: string): string {
  const value = record.document?.[key]
  return value === undefined || value === null ? "—" : String(value)
}

async function loadHistory(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const result = await services.workbench.listPublicationHistory(verificationId.value.trim() || undefined)
    records.value = result.data
    traceId.value = result.traceId
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "发布历史加载失败。"
  } finally { loading.value = false }
}

async function connectStream(): Promise<void> {
  streamAbort.value?.abort()
  const controller = new AbortController()
  streamAbort.value = controller
  try {
    await services.sse.run("/internal/topic4/sse/stream", {
      streamKey: "publications",
      signal: controller.signal,
      onEvent: (event) => {
        const data = typeof event.data === "object" && event.data !== null ? event.data as JsonObject : { value: event.data }
        events.value = [...events.value.slice(-9), { ...data, event_type: event.eventType, sequence: event.sequence ?? undefined }]
        void loadHistory()
      },
    })
  } catch (error) {
    if (!controller.signal.aborted && error instanceof Error) errorMessage.value = error.message
  }
}

onMounted(async () => { await loadHistory(); void connectStream() })
onBeforeUnmount(() => streamAbort.value?.abort())
</script>

<template>
  <section class="page-section">
    <PageHeader title="可信发布" description="C12 一次性授权、SERIALIZABLE 原子提交与公共事件归档">
      <template #actions><button class="secondary-button" type="button" :disabled="loading" @click="loadHistory"><RefreshCw :size="16" :class="{ spin: loading }" />刷新归档</button></template>
    </PageHeader>

    <div class="metric-grid metric-grid-four">
      <MetricTile label="归档记录" :value="records.length" detail="Append-Only 记录" :icon="Archive" tone="positive" />
      <MetricTile label="授权记录" :value="authorizationCount" detail="一次性凭证" :icon="ShieldCheck" />
      <MetricTile label="发布事务" :value="committedCount" detail="服务端原子提交" :icon="Send" />
      <MetricTile label="实时事件" :value="events.length" detail="当前会话已接收" :icon="CheckCircle2" />
    </div>

    <section class="panel publication-command-panel"><div class="panel-heading"><div><h2>发布授权入口</h2><p>输入已进入 RELEASE_PENDING 的 Verification ID，所有 SHA 与允许区块由服务端派生。</p></div><ShieldCheck :size="19" /></div><div class="publication-command"><label><Search :size="16" /><input v-model.trim="verificationId" type="text" placeholder="Verification ID" /></label><button class="secondary-button" type="button" :disabled="!verificationId" @click="loadHistory">筛选历史</button></div><ReleaseController v-if="verificationId" :api="services.workbench" :verification-id="verificationId" :disabled="!canRelease" /></section>

    <ErrorState v-if="errorMessage" :message="errorMessage" retryable @retry="loadHistory" />
    <LoadingState v-if="loading && !records.length" label="正在加载发布归档" />

    <section class="panel publication-history-panel"><div class="panel-heading"><div><h2>发布审计归档</h2><p>授权、消费、发布快照与公共事件按创建时间统一呈现。</p></div><label class="search-field"><Search :size="15" /><input v-model="search" type="search" placeholder="检索记录、SHA、TraceID" /></label></div><div v-if="filteredRecords.length" class="publication-ledger"><article v-for="record in filteredRecords" :key="`${record.table}-${record.record_id}`"><div class="ledger-rail"><span /></div><div class="ledger-content"><header><div><strong>{{ record.table }}</strong><small>{{ record.record_id }}</small></div><StatusBadge :value="field(record, 'state')" /></header><dl class="property-list compact-properties"><div><dt>Verification</dt><dd>{{ field(record, 'verification_id') }}</dd></div><div><dt>Authorization</dt><dd>{{ field(record, 'authorization_id') }}</dd></div><div><dt>Candidate</dt><dd>{{ field(record, 'candidate_id') }}</dd></div><div><dt>创建时间</dt><dd>{{ record.created_at ? new Date(record.created_at).toLocaleString('zh-CN') : '—' }}</dd></div></dl><HashValue :value="record.record_sha256" label="Record SHA" /></div></article></div><div v-else class="empty-state compact-empty"><Archive :size="25" />暂无发布归档</div></section>

    <section v-if="events.length" class="panel public-events-panel"><div class="panel-heading"><div><h2>公共 SSE 事件</h2><p>断线后按租户游标恢复，重复事件不会再次渲染。</p></div><span class="stream-state"><span class="live-dot active" />已连接</span></div><ol class="event-list"><li v-for="(event, index) in events" :key="`${String(event.sequence ?? 'event')}-${index}`"><span>{{ event.event_type ?? 'topic4.event' }}</span><code>{{ event.sequence ?? '—' }}</code><small>{{ JSON.stringify(event).slice(0, 180) }}</small></li></ol></section>
    <TraceValue :value="traceId" />
  </section>
</template>
