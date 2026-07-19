<script setup lang="ts">
import { Activity, CheckCircle2, ClipboardList, FileDown, RefreshCw, Search, ShieldAlert, ShieldCheck } from "@lucide/vue"
import type { ClaimV1, EvidenceRefV1, RiskLevel, VerificationModule } from "@liyans/contracts"
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"

import type { JsonObject, RevisionHistoryItem, VerificationSnapshot } from "../api/types"
import { useAppServices } from "../app/services"
import { useAuthStore } from "../stores/auth"
import { tenantCacheKey } from "../shared/cache"
import ErrorState from "../shared/components/ErrorState.vue"
import EvidencePanel from "../shared/components/EvidencePanel.vue"
import HashValue from "../shared/components/HashValue.vue"
import LoadingState from "../shared/components/LoadingState.vue"
import MetricTile from "../shared/components/MetricTile.vue"
import PageHeader from "../shared/components/PageHeader.vue"
import ProgressBar from "../shared/components/ProgressBar.vue"
import ReleaseController from "../shared/components/ReleaseController.vue"
import RevisionDiff from "../shared/components/RevisionDiff.vue"
import RiskBadge from "../shared/components/RiskBadge.vue"
import StatusBadge from "../shared/components/StatusBadge.vue"
import TraceValue from "../shared/components/TraceValue.vue"

const services = useAppServices()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const verificationInput = ref(typeof route.query.id === "string" ? route.query.id : "")
const verificationId = ref(verificationInput.value)
const snapshot = ref<VerificationSnapshot | null>(null)
const revisions = ref<RevisionHistoryItem[]>([])
const selectedRevisionId = ref<string | null>(null)
const evidence = ref<EvidenceRefV1[]>([])
const selectedClaimId = ref<string | null>(null)
const riskFilter = ref<"ALL" | RiskLevel>("ALL")
const loading = ref(false)
const actionLoading = ref(false)
const errorMessage = ref<string | null>(null)
const traceId = ref<string | null>(null)
const streamEvents = ref<JsonObject[]>([])
const streamAbort = ref<AbortController | null>(null)
let pollTimer: number | null = null

const modules: Array<{ code: string; module?: VerificationModule; label: string }> = [
  { code: "C1", label: "状态控制面" }, { code: "C2", module: "C2_RAG", label: "本地 RAG" },
  { code: "C3", module: "C3_ACADEMIC", label: "公式与学术" }, { code: "C4", module: "C4_GRAPH", label: "图谱结构" },
  { code: "C5", module: "C5_QUIZ", label: "题库严谨性" }, { code: "C6", module: "C6_CODE", label: "代码仿真" },
  { code: "C7", module: "C7_EXTENSION", label: "资料溯源" }, { code: "C8", label: "两轮修订" },
  { code: "C9", module: "C9_SECURITY", label: "注入安全" }, { code: "C10", module: "C10_PRIVACY", label: "隐私合规" },
  { code: "C11", module: "C11_COMPLIANCE", label: "供应链" }, { code: "C12", label: "发布闸门" },
]
const stateOrder = ["ACCEPTED", "SNAPSHOT_VALIDATING", "CLAIM_EXTRACTING", "CLAIMS_READY", "MODULE_DISPATCHING", "VERIFYING", "AGGREGATING", "REVISION_PLANNING", "REVISION_WAITING", "REVERIFYING", "RELEASE_PENDING", "RELEASED"]
const terminalStates = new Set(["BLOCKED", "REVIEW_REQUIRED", "RELEASE_PENDING", "RELEASED", "FAILED", "EXPIRED", "CANCELLED"])
const progress = computed(() => {
  const state = snapshot.value?.state.current_state
  if (!state) return 0
  if (["BLOCKED", "REVIEW_REQUIRED", "FAILED", "EXPIRED", "CANCELLED"].includes(state)) return 100
  const index = stateOrder.indexOf(state)
  return index < 0 ? 0 : (index / (stateOrder.length - 1)) * 100
})
const riskByClaim = computed(() => new Map((snapshot.value?.risks ?? []).map((risk) => [risk.claim_id, risk])))
const verdictByClaim = computed(() => new Map((snapshot.value?.claim_verdicts ?? []).map((verdict) => [verdict.claim_id, verdict])))
const filteredClaims = computed(() => (snapshot.value?.claims ?? []).filter((claim) => riskFilter.value === "ALL" || riskByClaim.value.get(claim.claim_id)?.level === riskFilter.value))
const selectedClaim = computed<ClaimV1 | null>(() => snapshot.value?.claims.find((claim) => claim.claim_id === selectedClaimId.value) ?? null)
const highestRisk = computed<RiskLevel | null>(() => {
  const weights: Record<RiskLevel, number> = { LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 }
  return (snapshot.value?.risks ?? []).reduce<RiskLevel | null>((current, risk) => !current || weights[risk.level] > weights[current] ? risk.level : current, null)
})
const completedModules = computed(() => new Set((snapshot.value?.module_results ?? []).map((result) => result.module)))
const activeModuleRuns = computed(() => new Map((snapshot.value?.module_runs ?? []).map((run) => [run.module, run])))
const releaseAllowed = computed(() => snapshot.value?.report?.decision === "RELEASE" || snapshot.value?.report?.decision === "RELEASE_WITH_DISCLOSURE")
const recentIds = ref<string[]>([])
const selectedRevision = computed(() => revisions.value.find((item) => item.revision_cycle_id === selectedRevisionId.value) ?? null)
const canExecute = computed(() => auth.hasScope("topic4:verification:execute"))
const canRelease = computed(() => auth.hasScope("topic4:release:write"))

function asRecord(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as JsonObject : null
}

function candidateText(value: unknown): string | null {
  const candidate = asRecord(value)
  if (!candidate) return typeof value === "string" ? value : null
  const blocks = Array.isArray(candidate.blocks) ? candidate.blocks : []
  if (!blocks.length) return JSON.stringify(candidate, null, 2)
  return blocks
    .map((rawBlock) => {
      const block = asRecord(rawBlock)
      if (!block) return ""
      const content = asRecord(block.content)
      const title = typeof block.title === "string" ? `## ${block.title}\n` : ""
      if (!content) return `${title}${JSON.stringify(block, null, 2)}`
      const preferred = ["markdown", "text", "summary", "source", "mermaid", "code"]
        .map((key) => content[key])
        .find((item): item is string => typeof item === "string")
      return `${title}${preferred ?? JSON.stringify(content, null, 2)}`
    })
    .filter(Boolean)
    .join("\n\n")
}

function revisionText(revision: RevisionHistoryItem | null, side: "before" | "after"): string | null {
  if (!revision) return null
  const document = asRecord(revision.document) ?? revision
  const keys = side === "after"
    ? ["after", "after_content", "revised_content", "candidate"]
    : ["before", "before_content", "base_content", "original_candidate"]
  for (const key of keys) {
    const value = document[key]
    if (typeof value === "string") return value
    const rendered = candidateText(value)
    if (rendered) return rendered
  }
  return null
}

function recentKey(): string | null {
  return auth.user?.tenantId ? tenantCacheKey(auth.user.tenantId, "recent-verifications") : null
}

function loadRecent(): void {
  const key = recentKey()
  if (!key) return
  try { recentIds.value = JSON.parse(window.sessionStorage.getItem(key) ?? "[]") as string[] } catch { recentIds.value = [] }
}

function remember(identifier: string): void {
  const key = recentKey()
  if (!key) return
  recentIds.value = [identifier, ...recentIds.value.filter((item) => item !== identifier)].slice(0, 8)
  window.sessionStorage.setItem(key, JSON.stringify(recentIds.value))
}

async function loadVerification(): Promise<void> {
  if (!verificationId.value.trim()) return
  loading.value = true
  errorMessage.value = null
  try {
    const [snapshotResult, revisionResult] = await Promise.all([
      services.workbench.getVerification(verificationId.value.trim()),
      services.workbench.listRevisions(verificationId.value.trim()),
    ])
    snapshot.value = snapshotResult.data
    revisions.value = revisionResult.data
    selectedRevisionId.value = revisionResult.data[0]?.revision_cycle_id ?? null
    traceId.value = snapshotResult.traceId
    selectedClaimId.value = snapshot.value.claims[0]?.claim_id ?? null
    remember(verificationId.value.trim())
    void router.replace({ path: route.path, query: { id: verificationId.value.trim() } })
  } catch (error) {
    snapshot.value = null
    revisions.value = []
    selectedRevisionId.value = null
    errorMessage.value = error instanceof Error ? error.message : "核验记录加载失败。"
  } finally {
    loading.value = false
  }
}

async function loadEvidence(): Promise<void> {
  evidence.value = []
  if (!selectedClaimId.value) return
  try { evidence.value = (await services.workbench.listEvidence(selectedClaimId.value)).data }
  catch { evidence.value = [] }
}

async function executeVerification(): Promise<void> {
  if (!canExecute.value || !verificationId.value) return
  actionLoading.value = true
  errorMessage.value = null
  try {
    const result = await services.workbench.executeVerification(verificationId.value)
    traceId.value = result.traceId
    await loadVerification()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "核验任务重新入队失败。"
  } finally { actionLoading.value = false }
}

async function connectStream(): Promise<void> {
  streamAbort.value?.abort()
  const controller = new AbortController()
  streamAbort.value = controller
  try {
    await services.sse.run("/internal/topic4/sse/stream", {
      streamKey: verificationId.value ? `verification:${verificationId.value}` : "verification:public",
      signal: controller.signal,
      onEvent: (event) => {
        const data = typeof event.data === "object" && event.data !== null ? event.data as JsonObject : { value: event.data }
        streamEvents.value = [...streamEvents.value.slice(-11), { ...data, event_type: event.eventType, sequence: event.sequence ?? undefined }]
        if (!verificationId.value || data.verification_id === verificationId.value || data.authorization_id) void loadVerification()
      },
    })
  } catch (error) {
    if (!controller.signal.aborted && error instanceof Error) errorMessage.value = error.message
  }
}

function moduleState(module: { code: string; module?: VerificationModule }): string {
  if (module.code === "C1") return snapshot.value?.state.current_state ? "SUCCEEDED" : "PENDING"
  if (module.code === "C8") return revisions.value.length ? "SUCCEEDED" : "SKIPPED"
  if (module.code === "C12") return snapshot.value?.state.current_state === "RELEASED" ? "SUCCEEDED" : snapshot.value?.state.current_state === "RELEASE_PENDING" ? "RUNNING" : "PENDING"
  if (!module.module) return "PENDING"
  if (completedModules.value.has(module.module)) return "SUCCEEDED"
  return activeModuleRuns.value.get(module.module)?.state ?? "PENDING"
}

function printReport(): void { window.print() }

watch(selectedClaimId, loadEvidence)
watch(() => route.query.id, (value) => { if (typeof value === "string" && value !== verificationId.value) { verificationInput.value = value; verificationId.value = value; void loadVerification() } })
onMounted(async () => {
  loadRecent()
  if (verificationId.value) await loadVerification()
  void connectStream()
  pollTimer = window.setInterval(() => {
    const state = snapshot.value?.state.current_state
    if (verificationId.value && (!state || !terminalStates.has(state))) void loadVerification()
  }, 5000)
})
onBeforeUnmount(() => { streamAbort.value?.abort(); if (pollTimer !== null) window.clearInterval(pollTimer) })
</script>

<template>
  <section class="page-section">
    <PageHeader title="可信核验" description="C1-C12 十二维核验、证据溯源、修订闭环与原子发布">
      <template #actions><button v-if="snapshot" class="secondary-button" type="button" :disabled="actionLoading || !canExecute" @click="executeVerification"><RefreshCw :size="16" :class="{ spin: actionLoading }" />重新入队</button></template>
    </PageHeader>

    <div class="verification-search"><label><Search :size="17" /><input v-model.trim="verificationInput" type="text" placeholder="输入 Verification ID" @keyup.enter="verificationId = verificationInput; loadVerification()" /></label><button class="primary-button" type="button" :disabled="loading || !verificationInput" @click="verificationId = verificationInput; loadVerification()"><ShieldCheck :size="16" />查询核验</button><div v-if="recentIds.length" class="recent-links"><span>最近：</span><button v-for="identifier in recentIds" :key="identifier" type="button" @click="verificationInput = identifier; verificationId = identifier; loadVerification()">{{ identifier.slice(0, 8) }}</button></div></div>
    <LoadingState v-if="loading" label="正在加载核验快照" />
    <ErrorState v-if="errorMessage" :message="errorMessage" retryable @retry="loadVerification" />
    <div v-if="!snapshot && !loading" class="empty-state verification-empty"><ShieldAlert :size="32" /><strong>选择一条核验记录</strong><span>核验编号来自 Topic3 自动消费链路或可信发布事件，前端不会自行构造 Verification Request。</span></div>

    <template v-if="snapshot">
      <div class="metric-grid metric-grid-four">
        <MetricTile label="当前状态" :value="snapshot.state.current_state" :detail="`CAS v${snapshot.state.state_version}`" :icon="Activity" tone="positive" />
        <MetricTile label="Claim 数量" :value="snapshot.claims.length" detail="全部事实断言" :icon="ClipboardList" />
        <MetricTile label="最高风险" :value="highestRisk ?? '未分级'" detail="高危内容自动熔断" :icon="ShieldAlert" :tone="highestRisk === 'CRITICAL' || highestRisk === 'HIGH' ? 'critical' : 'neutral'" />
        <MetricTile label="最终判定" :value="snapshot.report?.decision ?? '待聚合'" detail="服务端报告结论" :icon="CheckCircle2" />
      </div>
      <section class="panel lifecycle-panel"><div class="panel-heading"><div><h2>核验生命周期</h2><p>{{ snapshot.state.reason_code }} · 修订轮次 {{ snapshot.state.revision_round }}/2</p></div><StatusBadge :value="snapshot.state.current_state" /></div><ProgressBar label="全链路进度" :value="progress" :detail="`状态版本 ${snapshot.state.state_version}，所有转换均为 Append-Only`" /><div class="lifecycle-steps"><span v-for="state in stateOrder" :key="state" :class="{ active: state === snapshot.state.current_state, complete: stateOrder.indexOf(state) < stateOrder.indexOf(snapshot.state.current_state) }">{{ state.replaceAll('_', ' ') }}</span></div></section>

      <section class="panel matrix-panel"><div class="panel-heading"><div><h2>十二维核验矩阵</h2><p>专项模块与横切安全门禁统一聚合。</p></div><ShieldCheck :size="19" /></div><div class="verification-matrix"><article v-for="module in modules" :key="module.code"><strong>{{ module.code }}</strong><span>{{ module.label }}</span><StatusBadge :value="moduleState(module)" /></article></div></section>

      <div class="verification-layout">
        <section class="panel claims-panel"><div class="panel-heading"><div><h2>Claim 任务</h2><p>选择断言查看风险、判定与本地证据。</p></div><select v-model="riskFilter"><option value="ALL">全部风险</option><option value="LOW">低风险</option><option value="MEDIUM">中风险</option><option value="HIGH">高风险</option><option value="CRITICAL">极高风险</option></select></div><div class="claim-list"><button v-for="claim in filteredClaims" :key="claim.claim_id" type="button" :class="{ active: selectedClaimId === claim.claim_id }" @click="selectedClaimId = claim.claim_id"><div><span>{{ claim.claim_kind }} · #{{ claim.ordinal + 1 }}</span><RiskBadge :level="riskByClaim.get(claim.claim_id)?.level" /></div><strong>{{ claim.statement }}</strong><small>{{ verdictByClaim.get(claim.claim_id)?.verdict ?? '等待判定' }} · {{ Math.round((verdictByClaim.get(claim.claim_id)?.confidence ?? 0) * 100) }}%</small></button><div v-if="!filteredClaims.length" class="empty-state compact-empty">没有匹配的 Claim</div></div></section>
        <aside class="panel claim-detail-panel"><div class="panel-heading"><div><h2>Claim 详情</h2><p>服务端不可变记录</p></div><RiskBadge :level="selectedClaimId ? riskByClaim.get(selectedClaimId)?.level : null" /></div><template v-if="selectedClaim"><p class="claim-statement">{{ selectedClaim.statement }}</p><dl class="property-list"><div><dt>类型</dt><dd>{{ selectedClaim.claim_kind }} / {{ selectedClaim.claim_subtype }}</dd></div><div><dt>区块</dt><dd>{{ selectedClaim.block_id }}</dd></div><div><dt>JSON Pointer</dt><dd>{{ selectedClaim.json_pointer }}</dd></div><div><dt>判定</dt><dd>{{ verdictByClaim.get(selectedClaim.claim_id)?.verdict ?? '等待' }}</dd></div></dl><HashValue :value="selectedClaim.claim_sha256" label="Claim SHA" /><HashValue :value="selectedClaim.record_sha256" label="Record SHA" /></template><div v-else class="empty-state compact-empty">选择 Claim 查看详情</div></aside>
      </div>

      <EvidencePanel :evidence="evidence" />

      <section class="panel revisions-panel">
        <div class="panel-heading">
          <div><h2>C8 修订历史</h2><p>最多两轮，仅新增版本；完整修订补丁由服务端 Agent 与 Artifact Store 产生。</p></div>
          <StatusBadge :value="revisions.length ? 'COMPLETED' : 'NOT_REQUIRED'" />
        </div>
        <div v-if="revisions.length" class="revision-timeline">
          <button
            v-for="revision in revisions"
            :key="String(revision.revision_cycle_id ?? revision.created_at)"
            class="revision-timeline-item"
            :class="{ active: selectedRevisionId === revision.revision_cycle_id }"
            type="button"
            @click="selectedRevisionId = revision.revision_cycle_id ?? null"
          >
            <span class="timeline-dot" />
            <span>
              <span class="revision-item-heading"><strong>第 {{ revision.revision_round ?? '—' }} 轮修订</strong><StatusBadge :value="revision.state" /></span>
              <span class="revision-item-copy">候选 {{ revision.candidate_id }} · 基线版本 v{{ revision.base_candidate_version }}</span>
              <HashValue :value="revision.base_candidate_sha256" label="Base Candidate SHA" />
              <time>{{ revision.created_at ? new Date(revision.created_at).toLocaleString('zh-CN') : '—' }}</time>
            </span>
          </button>
        </div>
        <div v-else class="empty-state compact-empty">当前报告无需修订。浏览器不会构造 RevisionPatch 或 Artifact 引用。</div>
        <div v-if="selectedRevision" class="revision-diff-panel">
          <div class="section-title-row"><div><h3>版本差异</h3><p>仅渲染服务端返回的不可变内容；客户端不生成补丁、SHA 或 Artifact 引用。</p></div><StatusBadge :value="selectedRevision.state" /></div>
          <RevisionDiff :before="revisionText(selectedRevision, 'before')" :after="revisionText(selectedRevision, 'after')" />
        </div>
      </section>

      <section v-if="snapshot.report" class="panel report-panel printable-report"><div class="panel-heading"><div><h2>可信核验报告</h2><p>报告与候选内容由服务端 SHA256 双向绑定。</p></div><button class="secondary-button print-hidden" type="button" @click="printReport"><FileDown :size="16" />导出 PDF</button></div><div class="report-summary"><div><span>报告编号</span><strong>{{ snapshot.report.report_id }}</strong></div><div><span>聚合判定</span><StatusBadge :value="snapshot.report.decision" /></div><div><span>知识库版本</span><code>{{ snapshot.report.knowledge_base_version }}</code></div><div><span>完成时间</span><time>{{ new Date(snapshot.report.completed_at).toLocaleString('zh-CN') }}</time></div></div><HashValue :value="snapshot.report.candidate_sha256" label="Candidate SHA" /><HashValue :value="snapshot.report.report_sha256" label="Report SHA" /></section>

      <ReleaseController v-if="releaseAllowed && snapshot.state.current_state !== 'RELEASED'" :api="services.workbench" :verification-id="verificationId" :disabled="!canRelease" />
      <section v-else-if="snapshot.state.current_state === 'RELEASED'" class="success-band"><CheckCircle2 :size="22" /><div><strong>该资源已经通过 C12 原子发布</strong><span>授权已消费，状态快照为 RELEASED。</span></div></section>
      <TraceValue :value="traceId ?? snapshot.state.trace_id" />
    </template>
  </section>
</template>
