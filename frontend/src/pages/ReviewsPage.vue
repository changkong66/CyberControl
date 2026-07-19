<script setup lang="ts">
import { AlertTriangle, CheckCircle2, Clock3, RefreshCw, Scale, ShieldAlert, UserCheck } from "@lucide/vue"
import type { HumanReviewTaskV1, ReviewDecision } from "@liyans/contracts"
import { computed, onMounted, ref } from "vue"

import { ApiClientError } from "../api/client"
import type { VerificationSnapshot } from "../api/types"
import { useAppServices } from "../app/services"
import { useAuthStore } from "../stores/auth"
import ErrorState from "../shared/components/ErrorState.vue"
import HashValue from "../shared/components/HashValue.vue"
import LoadingState from "../shared/components/LoadingState.vue"
import PageHeader from "../shared/components/PageHeader.vue"
import RiskBadge from "../shared/components/RiskBadge.vue"
import StatusBadge from "../shared/components/StatusBadge.vue"
import TraceValue from "../shared/components/TraceValue.vue"

const services = useAppServices()
const auth = useAuthStore()
const tasks = ref<HumanReviewTaskV1[]>([])
const selectedTaskId = ref<string | null>(null)
const verification = ref<VerificationSnapshot | null>(null)
const decision = ref<ReviewDecision>("APPROVE")
const rationale = ref("")
const disclosureCodes = ref("")
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref<string | null>(null)
const successMessage = ref<string | null>(null)
const traceId = ref<string | null>(null)

const selectedTask = computed(() => tasks.value.find((task) => task.review_task_id === selectedTaskId.value) ?? null)
const nonWaivable = computed(() => selectedTask.value?.non_waivable_finding_ids ?? [])
const selectedClaims = computed(() => {
  if (!selectedTask.value || !verification.value) return []
  return verification.value.claims.filter((item) => selectedTask.value?.claim_ids.includes(item.claim_id))
})
const canReview = computed(() => auth.hasScope("topic4:review:write"))

async function loadTasks(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const result = await services.workbench.listReviewTasks("OPEN")
    tasks.value = result.data
    traceId.value = result.traceId
    if (!selectedTaskId.value || !tasks.value.some((task) => task.review_task_id === selectedTaskId.value)) selectedTaskId.value = tasks.value[0]?.review_task_id ?? null
    await loadSelectedVerification()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "审核任务加载失败。"
  } finally { loading.value = false }
}

async function loadSelectedVerification(): Promise<void> {
  if (!selectedTask.value) { verification.value = null; return }
  try {
    const result = await services.workbench.getVerification(selectedTask.value.verification_id)
    verification.value = result.data
    traceId.value = result.traceId
  } catch (error) {
    verification.value = null
    errorMessage.value = error instanceof Error ? error.message : "核验详情加载失败。"
  }
}

async function selectTask(identifier: string): Promise<void> {
  selectedTaskId.value = identifier
  successMessage.value = null
  await loadSelectedVerification()
}

async function submitDecision(): Promise<void> {
  if (!canReview.value || !selectedTask.value || !verification.value || !rationale.value.trim()) return
  submitting.value = true
  errorMessage.value = null
  successMessage.value = null
  try {
    const result = await services.workbench.submitReview(selectedTask.value.verification_id, {
      review_task_id: selectedTask.value.review_task_id,
      decision: decision.value,
      rationale: rationale.value.trim(),
      disclosure_codes: disclosureCodes.value.split(/[\s,]+/u).map((item) => item.trim()).filter(Boolean),
      waived_finding_ids: [],
      expected_task_version: selectedTask.value.version_cas,
      expected_state_version: verification.value.state.state_version,
    })
    traceId.value = result.traceId
    successMessage.value = "审核决策已作为不可变记录提交。"
    rationale.value = ""
    disclosureCodes.value = ""
    await loadTasks()
  } catch (error) {
    if (error instanceof ApiClientError && error.status === 409) {
      errorMessage.value = "任务已被其他审核会话更新，已自动刷新最新 CAS 状态。"
      await loadTasks()
    } else errorMessage.value = error instanceof Error ? error.message : "审核决策提交失败。"
  } finally { submitting.value = false }
}

onMounted(loadTasks)
</script>

<template>
  <section class="page-section">
    <PageHeader title="人工审核" description="高风险内容复核、CAS 并发控制与不可变审核决策">
      <template #actions><button class="secondary-button" type="button" :disabled="loading" @click="loadTasks"><RefreshCw :size="16" :class="{ spin: loading }" />刷新队列</button></template>
    </PageHeader>
    <ErrorState v-if="errorMessage" :message="errorMessage" retryable @retry="loadTasks" />
    <div v-if="successMessage" class="success-band"><CheckCircle2 :size="20" /><div><strong>{{ successMessage }}</strong><span>TraceID：{{ traceId }}</span></div></div>
    <LoadingState v-if="loading && !tasks.length" label="正在加载人工审核队列" />
    <div v-if="!loading && !tasks.length" class="empty-state review-empty"><UserCheck :size="30" /><strong>审核队列为空</strong><span>当前租户没有 OPEN 状态的高风险任务。</span></div>

    <div v-if="tasks.length" class="review-layout">
      <section class="panel review-queue"><div class="panel-heading"><div><h2>待审核队列</h2><p>{{ tasks.length }} 条 OPEN 任务</p></div><ShieldAlert :size="18" /></div><div class="review-task-list"><button v-for="task in tasks" :key="task.review_task_id" type="button" :class="{ active: selectedTaskId === task.review_task_id }" @click="selectTask(task.review_task_id)"><div><RiskBadge :level="task.risk_level" /><StatusBadge :value="task.state" /></div><strong>{{ task.candidate_id }} · v{{ task.candidate_version }}</strong><span>{{ task.reason_codes.join(' · ') }}</span><small><Clock3 :size="13" />截止 {{ new Date(task.due_at).toLocaleString('zh-CN') }}</small></button></div></section>

      <section class="panel review-detail"><div class="panel-heading"><div><h2>审核详情</h2><p>风险、证据、修订和状态快照统一核对</p></div><Scale :size="18" /></div><template v-if="selectedTask && verification"><div class="review-summary"><div><span>Verification</span><strong>{{ selectedTask.verification_id }}</strong></div><div><span>当前状态</span><StatusBadge :value="verification.state.current_state" /></div><div><span>风险级别</span><RiskBadge :level="selectedTask.risk_level" /></div><div><span>状态 CAS</span><code>task {{ selectedTask.version_cas }} / state {{ verification.state.state_version }}</code></div></div><div class="review-findings"><h3>触发原因</h3><span v-for="reason in selectedTask.reason_codes" :key="reason" class="soft-tag warning-tag">{{ reason }}</span><div v-if="nonWaivable.length" class="non-waivable"><AlertTriangle :size="16" /><div><strong>不可豁免 Finding</strong><p>{{ nonWaivable.join(' · ') }}</p></div></div></div><div class="review-claims"><h3>关联 Claim</h3><article v-for="claim in selectedClaims" :key="claim.claim_id"><strong>{{ claim.statement }}</strong><small>{{ claim.claim_kind }} · {{ claim.block_id }}</small><HashValue :value="claim.claim_sha256" label="Claim SHA" /></article></div><HashValue :value="selectedTask.candidate_sha256" label="Candidate SHA" /></template></section>

      <aside class="panel review-decision"><div class="panel-heading"><div><h2>提交决策</h2><p>决策将绑定审核人、TraceID 与当前 CAS。</p></div><UserCheck :size="18" /></div><label>审核结果<select v-model="decision" :disabled="!canReview"><option value="APPROVE">APPROVE · 通过</option><option value="APPROVE_WITH_DISCLOSURE">APPROVE_WITH_DISCLOSURE · 披露后通过</option><option value="REVISE">REVISE · 退回修订</option><option value="BLOCK">BLOCK · 阻断</option></select></label><label>审核依据<textarea v-model="rationale" rows="6" maxlength="65536" :disabled="!canReview" placeholder="说明证据判断、风险边界和决策依据" /></label><label v-if="decision === 'APPROVE_WITH_DISCLOSURE'">披露代码<input v-model="disclosureCodes" type="text" :disabled="!canReview" placeholder="多个代码以逗号分隔" /></label><div class="review-policy"><ShieldAlert :size="15" /><span>{{ canReview ? '不可豁免 Finding 不会被前端加入 waived_finding_ids。' : '当前身份缺少 topic4:review:write，仅可查看审核任务。' }}</span></div><button class="primary-button full-width" type="button" :disabled="submitting || !canReview || !selectedTask || !rationale.trim()" @click="submitDecision"><UserCheck :size="16" />{{ submitting ? '提交中' : '提交不可变决策' }}</button></aside>
    </div>
    <TraceValue :value="traceId" />
  </section>
</template>
