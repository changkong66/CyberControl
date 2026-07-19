<script setup lang="ts">
import { Bot, Code2, FileText, GitBranch, ListChecks, Play, RefreshCw, ShieldCheck, Sparkles, WandSparkles } from "@lucide/vue"
import type { CandidateV1, Topic1CourseV1, Topic1GraphContentV1, Topic3GenerationSessionV1 } from "@liyans/contracts"
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"

import { useAppServices } from "../app/services"
import { useAuthStore } from "../stores/auth"
import type { GenerationView, JsonObject, Topic3GenerationInput } from "../api/types"
import ErrorState from "../shared/components/ErrorState.vue"
import LoadingState from "../shared/components/LoadingState.vue"
import MarkdownPreview from "../shared/components/MarkdownPreview.vue"
import PageHeader from "../shared/components/PageHeader.vue"
import ProgressBar from "../shared/components/ProgressBar.vue"
import StatusBadge from "../shared/components/StatusBadge.vue"
import TraceValue from "../shared/components/TraceValue.vue"
import { verificationIdForCandidate } from "../shared/identifiers"

const services = useAppServices()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const courses = ref<Topic1CourseV1[]>([])
const courseId = ref(typeof route.query.course === "string" ? route.query.course : "")
const graph = ref<Topic1GraphContentV1 | null>(null)
const selectedKpIds = ref<string[]>(typeof route.query.kp === "string" ? [route.query.kp] : [])
const activeAgent = ref<"Lecturer" | "MindMap" | "Tester" | "CodeSandbox" | "Extension">("Lecturer")
const goal = ref("理解核心概念并完成一组可验证的工程练习")
const depth = ref<"FOUNDATION" | "EXAM_FOCUS" | "POSTGRADUATE" | "ENGINEERING">("FOUNDATION")
const parallelism = ref<1 | 3 | 5>(1)
const requestedResources = ref<Topic3GenerationInput["requested_resources"]>(["Lecturer_Doc", "MindMap", "Gradient_Quiz"])
const sessionId = ref(typeof route.query.session === "string" ? route.query.session : "")
const generation = ref<GenerationView | null>(null)
const eventLog = ref<JsonObject[]>([])
const submitting = ref(false)
const errorMessage = ref<string | null>(null)
const traceId = ref<string | null>(null)
const verificationId = ref<string | null>(null)
const streamAbort = ref<AbortController | null>(null)
let pollTimer: number | null = null

const agents = [
  { key: "Lecturer" as const, label: "讲师", resource: "Lecturer_Doc" as const, icon: FileText, description: "分层讲义与误区提醒" },
  { key: "MindMap" as const, label: "思维导图", resource: "MindMap" as const, icon: GitBranch, description: "知识拓扑与 Mermaid 结构" },
  { key: "Tester" as const, label: "题库练习", resource: "Gradient_Quiz" as const, icon: ListChecks, description: "题干、答案与诊断练习" },
  { key: "CodeSandbox" as const, label: "代码仿真", resource: "Simulation_Code" as const, icon: Code2, description: "Python / MATLAB 控制实验" },
  { key: "Extension" as const, label: "拓展资料", resource: "Extension_Material" as const, icon: WandSparkles, description: "论文、标准与工程案例" },
]
const selectedAgent = computed(() => agents.find((agent) => agent.key === activeAgent.value) ?? agents[0])
const selectedBlockType = computed(() => ({ Lecturer: "MARKDOWN", MindMap: "MERMAID", Tester: "QUIZ", CodeSandbox: "CODE", Extension: "EXTENSION" }[activeAgent.value]))
const selectedCandidates = computed(() => generation.value?.candidates.filter((candidate) => candidate.provenance.agent === activeAgent.value) ?? [])
const session = computed<Topic3GenerationSessionV1 | null>(() => generation.value?.session ?? null)
const completedTasks = computed(() => generation.value?.tasks.filter((task) => task.state === "SUCCEEDED").length ?? 0)
const progress = computed(() => generation.value ? (completedTasks.value / Math.max(generation.value.tasks.length, 1)) * 100 : 0)
const canGenerate = computed(() => auth.hasScope("topic3:generation:write"))

function toggleResource(resource: Topic3GenerationInput["requested_resources"][number]): void {
  requestedResources.value = requestedResources.value.includes(resource)
    ? requestedResources.value.filter((item) => item !== resource)
    : [...requestedResources.value, resource]
}

async function loadCourses(): Promise<void> {
  try {
    const result = await services.workbench.listCourses()
    courses.value = result.data
    if (!courseId.value && courses.value[0]) courseId.value = courses.value[0].course_id
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "课程加载失败。"
  }
}

async function loadGraph(): Promise<void> {
  if (!courseId.value) return
  try {
    graph.value = (await services.workbench.getCourseGraph(courseId.value)).data
    if (!selectedKpIds.value.length) selectedKpIds.value = graph.value.knowledge_points.slice(0, 1).map((item) => item.kp_id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "知识点加载失败。"
  }
}

async function refreshGeneration(): Promise<void> {
  if (!sessionId.value) return
  try {
    const result = await services.workbench.getGeneration(sessionId.value)
    generation.value = result.data
    traceId.value = result.traceId
    const resultDocument = generation.value.session.result
    if (resultDocument && typeof resultDocument === "object" && "verification_id" in resultDocument) verificationId.value = String(resultDocument.verification_id)
    if (["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"].includes(generation.value.session.state) && pollTimer !== null) {
      window.clearInterval(pollTimer)
      pollTimer = null
    }
  } catch (error) {
    if (!generation.value) errorMessage.value = error instanceof Error ? error.message : "生成状态加载失败。"
  }
}

async function connectStream(): Promise<void> {
  if (!sessionId.value) return
  streamAbort.value?.abort()
  const controller = new AbortController()
  streamAbort.value = controller
  try {
    await services.sse.run("/internal/topic3/sse/stream", {
      streamKey: `generation:${sessionId.value}`,
      signal: controller.signal,
      onHeartbeat: () => undefined,
      onEvent: (event) => {
        const data = typeof event.data === "object" && event.data !== null ? event.data as JsonObject : { value: event.data }
        eventLog.value = [...eventLog.value.slice(-19), { ...data, sequence: event.sequence ?? undefined, event_type: event.eventType }]
        const candidateVerification = data.verification_id ?? (typeof data.payload === "object" && data.payload !== null ? (data.payload as JsonObject).verification_id : undefined)
        if (typeof candidateVerification === "string") verificationId.value = candidateVerification
        void refreshGeneration()
      },
      onError: () => undefined,
    })
  } catch (error) {
    if (!controller.signal.aborted && error instanceof Error) errorMessage.value = error.message
  }
}

function startPolling(): void {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(() => { void refreshGeneration() }, 2500)
}

async function trackSession(): Promise<void> {
  if (!sessionId.value) return
  startPolling()
  await refreshGeneration()
  void connectStream()
}

async function submitGeneration(): Promise<void> {
  if (!canGenerate.value || !courseId.value || !selectedKpIds.value.length || !auth.user?.subject || !requestedResources.value.length) return
  submitting.value = true
  errorMessage.value = null
  eventLog.value = []
  verificationId.value = null
  try {
    const command: Topic3GenerationInput = {
      operation_id: crypto.randomUUID(),
      generation_session_id: crypto.randomUUID(),
      learner_ref: auth.user.subject,
      course_id: courseId.value,
      target_kp_ids: selectedKpIds.value,
      requested_resources: requestedResources.value,
      lecturer_depth: depth.value,
      learning_goal: goal.value.trim(),
      locale: "zh-CN",
      max_parallelism: parallelism.value,
      allow_partial: true,
      requested_at: new Date().toISOString(),
    }
    const result = await services.workbench.createGeneration(command)
    sessionId.value = command.generation_session_id
    traceId.value = result.traceId
    void router.replace({ path: "/agents", query: { course: courseId.value, session: sessionId.value } })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "生成任务提交失败。"
  } finally {
    submitting.value = false
  }
}

async function openVerification(candidate: CandidateV1): Promise<void> {
  try {
    const identifier = await verificationIdForCandidate(candidate)
    verificationId.value = identifier
    await router.push({ path: "/verification", query: { id: identifier } })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "无法定位候选资源对应的核验记录。"
  }
}

watch(courseId, loadGraph)
watch(sessionId, (value) => { if (value) void trackSession() })
watch(() => route.query.session, (value) => {
  const next = typeof value === "string" ? value : ""
  if (next !== sessionId.value) sessionId.value = next
})
onMounted(async () => { await loadCourses(); await loadGraph(); if (sessionId.value) await trackSession() })
onBeforeUnmount(() => { streamAbort.value?.abort(); if (pollTimer !== null) window.clearInterval(pollTimer) })
</script>

<template>
  <section class="page-section">
    <PageHeader title="智能体协同" description="Topic3 五大专业智能体以 Blueprint 与 SSE 流式运行时协同生成">
      <template #actions><StatusBadge :value="session?.state ?? 'IDLE'" :label="session?.state ?? '待启动'" /></template>
    </PageHeader>

    <div class="agent-layout">
      <aside class="panel agent-sidebar">
        <div class="panel-heading"><div><h2>生成配置</h2><p>选择知识点与目标资源</p></div><Bot :size="18" /></div>
        <label>课程<select v-model="courseId"><option v-for="course in courses" :key="course.course_id" :value="course.course_id">{{ course.title }}</option></select></label>
        <fieldset class="selection-fieldset"><legend>目标知识点</legend><label v-for="point in graph?.knowledge_points" :key="point.kp_id" class="check-row"><input v-model="selectedKpIds" type="checkbox" :value="point.kp_id" /><span>{{ point.title }}</span><small>难度 {{ point.difficulty_level }}</small></label><span v-if="!graph" class="muted-value">正在加载知识点</span></fieldset>
        <label>学习目标<textarea v-model="goal" rows="3" maxlength="240" /></label>
        <label>讲解深度<select v-model="depth"><option value="FOUNDATION">基础理解</option><option value="EXAM_FOCUS">考试重点</option><option value="POSTGRADUATE">研究生进阶</option><option value="ENGINEERING">工程实践</option></select></label>
        <label>并行度<select v-model.number="parallelism"><option :value="1">串行稳定</option><option :value="3">3 路并行</option><option :value="5">5 路并行</option></select></label>
        <fieldset class="selection-fieldset"><legend>请求资源</legend><label v-for="agent in agents" :key="agent.resource" class="check-row"><input :checked="requestedResources.includes(agent.resource)" type="checkbox" @change="toggleResource(agent.resource)" /><span>{{ agent.label }}</span></label></fieldset>
        <button class="primary-button full-width" type="button" :disabled="submitting || !canGenerate || !selectedKpIds.length || !requestedResources.length" @click="submitGeneration"><Play :size="16" />{{ submitting ? "提交中" : "启动协同生成" }}</button>
        <p v-if="!canGenerate" class="security-note"><ShieldCheck :size="14" />当前身份仅可读取生成记录，缺少 topic3:generation:write。</p>
        <p class="security-note"><ShieldCheck :size="14" />候选生成后由 Topic4 自动核验，前端不生成权威哈希。</p>
      </aside>

      <div class="agent-main">
        <nav class="agent-tabs" aria-label="智能体类型"><button v-for="agent in agents" :key="agent.key" type="button" :class="{ active: activeAgent === agent.key }" @click="activeAgent = agent.key"><component :is="agent.icon" :size="17" /><span>{{ agent.label }}</span><small>{{ agent.resource }}</small></button></nav>
        <section class="panel stream-panel">
          <div class="panel-heading"><div><h2>{{ selectedAgent.label }}工作台</h2><p>{{ selectedAgent.description }} · 流式事件由 Outbox/SSE 提供</p></div><div class="stream-state"><span class="live-dot" :class="{ active: !!sessionId }" />{{ sessionId ? "流式监听中" : "等待任务" }}</div></div>
          <ProgressBar v-if="generation" label="协同任务完成度" :value="progress" :detail="`${completedTasks} / ${generation.tasks.length} 个 Agent 任务完成`" />
          <LoadingState v-if="submitting" label="正在提交协同生成任务" />
          <div v-if="selectedCandidates.length" class="candidate-list"><article v-for="candidate in selectedCandidates" :key="`${candidate.candidate_id}-${candidate.candidate_version}`" class="candidate-view"><div class="candidate-header"><div><strong>{{ candidate.provenance.agent }} · v{{ candidate.candidate_version }}</strong><small>{{ candidate.candidate_id }}</small></div><StatusBadge :value="candidate.status" /></div><template v-for="block in candidate.blocks" :key="block.block_id"><div v-if="block.block_type === selectedBlockType" class="candidate-block"><MarkdownPreview v-if="block.block_type === 'MARKDOWN' || block.block_type === 'EXTENSION'" :source="String((block.content as JsonObject).markdown ?? (block.content as JsonObject).summary ?? JSON.stringify(block.content, null, 2))" /><pre v-else-if="block.block_type === 'CODE'" class="code-view"><code>{{ JSON.stringify((block.content as JsonObject).files ?? (block.content as JsonObject).source ?? block.content, null, 2) }}</code></pre><pre v-else class="structured-view"><code>{{ JSON.stringify(block.content, null, 2) }}</code></pre></div></template><div class="candidate-footer"><span>内容 SHA</span><code>{{ candidate.candidate_sha256 }}</code><button class="secondary-button" type="button" @click="openVerification(candidate)"><ShieldCheck :size="15" />查看核验</button></div></article></div>
          <div v-else class="empty-state agent-empty"><Sparkles :size="30" /><strong>{{ sessionId ? "等待候选资源落库" : "配置一次生成任务" }}</strong><span>生成内容会在这里按事件顺序增量出现，完成后自动进入 Topic4 核验链路。</span></div>
        </section>
        <section v-if="eventLog.length" class="panel event-panel"><div class="panel-heading"><div><h2>实时事件</h2><p>最近 20 条事件，按服务端序列去重。</p></div><RefreshCw :size="17" /></div><ol class="event-list"><li v-for="(event, index) in eventLog" :key="`${String(event.sequence ?? 'event')}-${index}`"><span>{{ event.event_type ?? "message" }}</span><code>{{ event.sequence ?? "—" }}</code><small>{{ JSON.stringify(event).slice(0, 180) }}</small></li></ol></section>
        <TraceValue :value="traceId" />
      </div>
    </div>
  </section>
</template>
