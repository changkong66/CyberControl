<script setup lang="ts">
import { BrainCircuit, CalendarClock, CircleAlert, Route, RefreshCw, Target, TrendingUp } from "@lucide/vue"
import type { Topic1CourseV1, Topic2LearningPathRecordV1, Topic2MemoryStateV1, Topic2StudentProfileV1 } from "@liyans/contracts"
import { computed, onMounted, ref, watch } from "vue"

import { useAppServices } from "../app/services"
import { useAuthStore } from "../stores/auth"
import ErrorState from "../shared/components/ErrorState.vue"
import LoadingState from "../shared/components/LoadingState.vue"
import MetricTile from "../shared/components/MetricTile.vue"
import PageHeader from "../shared/components/PageHeader.vue"
import StatusBadge from "../shared/components/StatusBadge.vue"
import TraceValue from "../shared/components/TraceValue.vue"

const services = useAppServices()
const auth = useAuthStore()
const courses = ref<Topic1CourseV1[]>([])
const courseId = ref("")
const profile = ref<Topic2StudentProfileV1 | null>(null)
const memory = ref<Topic2MemoryStateV1[]>([])
const path = ref<Topic2LearningPathRecordV1 | null>(null)
const goal = ref("掌握自动控制基础并完成工程案例")
const loading = ref(true)
const actionLoading = ref(false)
const errorMessage = ref<string | null>(null)
const traceId = ref<string | null>(null)

const learnerRef = computed(() => auth.user?.subject ?? "")
const canRefreshMemory = computed(() => auth.hasScope("topic2:memory:write"))
const canGeneratePath = computed(() => auth.hasScope("topic2:path:write"))
const dimensions = computed(() => profile.value ? [
  { label: "知识掌握", key: "knowledge_mastery", value: profile.value.knowledge_mastery, color: "#168477" },
  { label: "问题解决", key: "problem_solving_proficiency", value: profile.value.problem_solving_proficiency, color: "#3c82a8" },
  { label: "误区偏好", key: "misconception_preference", value: profile.value.misconception_preference, color: "#9d6c20" },
  { label: "学习节奏", key: "learning_pace", value: profile.value.learning_pace, color: "#8b5d9e" },
  { label: "遗忘速率", key: "forgetting_rate", value: profile.value.forgetting_rate, color: "#ba5d55" },
  { label: "目标倾向", key: "learning_goal_tendency", value: profile.value.learning_goal_tendency, color: "#4e9a78" },
] : [])
const highRiskMemory = computed(() => memory.value.filter((item) => item.risk_level === "HIGH" || item.risk_level === "CRITICAL"))
const pathNodes = computed(() => {
  const document = path.value?.snapshot.path_document
  if (!document || typeof document !== "object" || !Array.isArray((document as { nodes?: unknown }).nodes)) return []
  return (document as { nodes: Array<Record<string, unknown>> }).nodes
})
const radarPoints = computed(() => {
  const center = 150
  const radius = 105
  return dimensions.value.map((dimension, index) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / Math.max(dimensions.value.length, 1)
    const value = Math.max(0, Math.min(1, dimension.value))
    return { ...dimension, x: center + Math.cos(angle) * radius * value, y: center + Math.sin(angle) * radius * value, labelX: center + Math.cos(angle) * (radius + 28), labelY: center + Math.sin(angle) * (radius + 28) }
  })
})
const radarPolygon = computed(() => radarPoints.value.map((point) => `${point.x},${point.y}`).join(" "))

async function loadCourses(): Promise<void> {
  try {
    const result = await services.workbench.listCourses()
    courses.value = result.data
    if (!courseId.value && courses.value[0]) courseId.value = courses.value[0].course_id
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "课程加载失败。"
  }
}

async function loadLearningData(): Promise<void> {
  if (!learnerRef.value || !courseId.value) {
    loading.value = false
    return
  }
  loading.value = true
  errorMessage.value = null
  try {
    const [profileResult, memoryResult, pathResult] = await Promise.allSettled([
      services.workbench.getLatestProfile(learnerRef.value, courseId.value),
      services.workbench.getMemoryStates(learnerRef.value, courseId.value),
      services.workbench.getLearningPath(learnerRef.value, courseId.value),
    ])
    if (profileResult.status === "fulfilled") { profile.value = profileResult.value.data; traceId.value = profileResult.value.traceId }
    else profile.value = null
    if (memoryResult.status === "fulfilled") memory.value = memoryResult.value.data
    else memory.value = []
    if (pathResult.status === "fulfilled") path.value = pathResult.value.data
    else path.value = null
    if (!profile.value && !path.value && !memory.value.length) errorMessage.value = "当前学习租户还没有画像快照。"
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "学习数据加载失败。"
  } finally {
    loading.value = false
  }
}

async function refreshMemory(): Promise<void> {
  if (!canRefreshMemory.value || !learnerRef.value || !courseId.value) return
  actionLoading.value = true
  errorMessage.value = null
  try {
    const result = await services.workbench.refreshMemory(learnerRef.value, courseId.value)
    traceId.value = result.traceId
    await loadLearningData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "记忆状态刷新失败。"
  } finally {
    actionLoading.value = false
  }
}

async function regeneratePath(): Promise<void> {
  if (!canGeneratePath.value || !learnerRef.value || !courseId.value || !goal.value.trim()) return
  actionLoading.value = true
  errorMessage.value = null
  try {
    const result = await services.workbench.generateLearningPath(learnerRef.value, courseId.value, goal.value.trim())
    traceId.value = result.traceId
    await loadLearningData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "学习路径生成失败。"
  } finally {
    actionLoading.value = false
  }
}

watch(courseId, loadLearningData)
onMounted(async () => { await loadCourses(); await loadLearningData() })
</script>

<template>
  <section class="page-section">
    <PageHeader title="自适应学习" description="Topic2 六维画像、记忆衰减与个性化学习路径">
      <template #actions>
        <button class="secondary-button" type="button" :disabled="loading || actionLoading" @click="loadLearningData"><RefreshCw :size="16" :class="{ spin: loading }" />刷新画像</button>
      </template>
    </PageHeader>

    <div class="toolbar-row">
      <label class="field-inline"><Route :size="16" />课程
        <select v-model="courseId"><option v-for="course in courses" :key="course.course_id" :value="course.course_id">{{ course.title }}</option></select>
      </label>
      <div class="learner-context"><span>学习者</span><strong>{{ learnerRef || "未登录" }}</strong></div>
      <button class="secondary-button toolbar-action" type="button" :disabled="actionLoading || !canRefreshMemory || !courseId" @click="refreshMemory"><RefreshCw :size="16" />刷新记忆状态</button>
    </div>

    <div v-if="!courses.length" class="empty-state learning-empty">
      <Route :size="32" />
      <strong>当前租户暂无学习课程</strong>
      <span>画像与路径只展示服务端为当前 OIDC 身份返回的快照，不使用跨租户或本地伪造数据。</span>
    </div>

    <LoadingState v-if="loading && !profile && !path" label="正在加载个性化学习状态" />
    <ErrorState v-if="errorMessage" :message="errorMessage" retryable @retry="loadLearningData" />
    <template v-if="!loading || profile || path">
      <div class="metric-grid metric-grid-four">
        <MetricTile label="画像版本" :value="profile ? `v${profile.profile_version}` : '—'" detail="增量冻结快照" :icon="BrainCircuit" tone="positive" />
        <MetricTile label="掌握度" :value="profile ? `${Math.round(profile.knowledge_mastery * 100)}%` : '—'" detail="知识掌握维度" :icon="TrendingUp" />
        <MetricTile label="待复习" :value="highRiskMemory.length" detail="高遗忘风险知识点" :icon="CalendarClock" :tone="highRiskMemory.length ? 'warning' : 'positive'" />
        <MetricTile label="路径节点" :value="path?.snapshot.node_count ?? 0" detail="当前个性化顺序" :icon="Route" />
      </div>

      <div class="learning-grid">
        <section class="panel radar-panel">
          <div class="panel-heading"><div><h2>六维能力画像</h2><p>每个维度来自服务端增量聚合与冻结快照。</p></div><BrainCircuit :size="18" /></div>
          <div v-if="profile" class="radar-wrap">
            <svg viewBox="0 0 300 300" aria-label="六维学习能力雷达图" role="img">
              <polygon v-for="ring in [0.25,0.5,0.75,1]" :key="ring" :points="dimensions.map((_, index) => `${150 + Math.cos(-Math.PI / 2 + (Math.PI * 2 * index) / 6) * 105 * ring},${150 + Math.sin(-Math.PI / 2 + (Math.PI * 2 * index) / 6) * 105 * ring}`).join(' ')" fill="none" stroke="#d7e5de" stroke-width="1" />
              <line v-for="(_, index) in dimensions" :key="`axis-${index}`" x1="150" y1="150" :x2="150 + Math.cos(-Math.PI / 2 + (Math.PI * 2 * index) / 6) * 105" :y2="150 + Math.sin(-Math.PI / 2 + (Math.PI * 2 * index) / 6) * 105" stroke="#d7e5de" />
              <polygon :points="radarPolygon" fill="rgba(22,132,119,0.18)" stroke="#168477" stroke-width="2" />
              <circle v-for="point in radarPoints" :key="point.key" :cx="point.x" :cy="point.y" r="4" fill="#168477" />
              <text v-for="point in radarPoints" :key="`${point.key}-label`" :x="point.labelX" :y="point.labelY" text-anchor="middle">{{ point.label }}</text>
            </svg>
            <div class="radar-legend"><div v-for="dimension in dimensions" :key="dimension.key"><span :style="{ background: dimension.color }" />{{ dimension.label }}<strong>{{ Math.round(dimension.value * 100) }}</strong></div></div>
          </div>
          <div v-else class="empty-state compact-empty">暂无画像快照</div>
        </section>

        <section class="panel memory-panel">
          <div class="panel-heading"><div><h2>记忆衰减</h2><p>艾宾浩斯风险状态与下一次复习时间。</p></div><CalendarClock :size="18" /></div>
          <div v-if="memory.length" class="memory-list"><article v-for="item in memory.slice(0, 8)" :key="item.memory_state_id" class="memory-row"><div class="memory-title"><strong>{{ item.kp_id }}</strong><StatusBadge :value="item.risk_level" /></div><div class="memory-bar"><span :style="{ width: `${Math.round(item.retrievability * 100)}%` }" /></div><div class="memory-meta"><span>可提取度 {{ Math.round(item.retrievability * 100) }}%</span><time>{{ new Date(item.next_review_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) }} 复习</time></div></article></div>
          <div v-else class="empty-state compact-empty">暂无记忆状态</div>
        </section>
      </div>

      <section class="panel path-panel">
        <div class="panel-heading"><div><h2>动态学习路径</h2><p>路径排序同时考虑掌握缺口、遗忘风险、目标匹配与先修就绪度。</p></div><Target :size="18" /></div>
        <div class="path-controls"><label>当前目标<input v-model="goal" type="text" maxlength="240" /></label><button class="primary-button" type="button" :disabled="actionLoading || !canGeneratePath || !courseId || !goal.trim()" @click="regeneratePath"><Route :size="16" />重新规划路径</button></div>
        <p v-if="!canGeneratePath" class="security-note"><CircleAlert :size="14" />当前身份仅可查看学习路径，缺少 topic2:path:write。</p>
        <div v-if="pathNodes.length" class="path-timeline"><article v-for="(node, index) in pathNodes" :key="String(node.kp_id ?? index)" class="path-node"><div class="path-index">{{ Number(node.order ?? index + 1) }}</div><div class="path-node-body"><div><strong>{{ node.title ?? node.kp_id }}</strong><StatusBadge :value="String(node.tier ?? 'FOUNDATION')" /></div><p>{{ node.rationale_codes instanceof Array ? node.rationale_codes.join(" · ") : "系统根据当前画像排序" }}</p><div class="path-node-meta"><span>{{ node.estimated_minutes ?? 0 }} 分钟</span><span>优先级 {{ Math.round(Number(node.priority_score ?? 0) * 100) }}%</span></div></div></article></div>
        <div v-else class="empty-state compact-empty"><Route :size="24" />暂无个性化路径，请先完成画像初始化。</div>
      </section>
      <TraceValue :value="traceId" />
    </template>
  </section>
</template>
