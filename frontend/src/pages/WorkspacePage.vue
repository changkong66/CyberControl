<script setup lang="ts">
import { Activity, ArrowRight, Bot, Database, KeyRound, Network, RefreshCw, Route, ShieldCheck } from "@lucide/vue"
import { computed, onMounted, ref } from "vue"
import { useRouter } from "vue-router"

import type { Topic4HealthView } from "../api/types"

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
const router = useRouter()
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const readiness = ref<Record<string, unknown> | null>(null)
const topic4 = ref<Topic4HealthView | null>(null)
const courseCount = ref(0)
const traceId = ref<string | null>(null)
const ready = computed(() => readiness.value?.status === "ready")

const workflows = [
  { path: "/knowledge", title: "权威知识图谱", description: "浏览先修拓扑、教材映射和冻结快照", icon: Network, scope: "topic1:read" },
  { path: "/learning", title: "自适应学习", description: "查看六维画像、记忆风险和学习路径", icon: Route, scope: "topic2:read" },
  { path: "/agents", title: "智能体协同", description: "启动五类 Agent 的 SSE 流式生成任务", icon: Bot, scope: "topic3:read" },
  { path: "/verification", title: "可信核验", description: "追踪 C1-C12 证据、修订和发布状态", icon: ShieldCheck, scope: "topic4:read" },
]
const visibleWorkflows = computed(() => workflows.filter((item) => auth.hasScope(item.scope)))

async function refresh(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const [healthResult, topic4Result, coursesResult] = await Promise.all([
      services.api.readiness(),
      services.workbench.topic4Health(),
      services.workbench.listCourses(),
    ])
    readiness.value = healthResult.data
    topic4.value = topic4Result.data
    courseCount.value = coursesResult.data.length
    traceId.value = healthResult.traceId
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "健康检查失败。"
  } finally { loading.value = false }
}

onMounted(refresh)
</script>

<template>
  <section class="page-section">
    <PageHeader title="工作台" :description="`${auth.user?.displayName ?? '学习者'}，当前租户的可信学习链路状态如下。`">
      <template #actions><button class="secondary-button" type="button" :disabled="loading" @click="refresh"><RefreshCw :class="{ spin: loading }" :size="16" />刷新状态</button></template>
    </PageHeader>
    <LoadingState v-if="loading && !readiness" label="正在检查完整服务链路" />
    <ErrorState v-else-if="errorMessage" :message="errorMessage" retryable @retry="refresh" />
    <template v-else>
      <div class="metric-grid metric-grid-four">
        <MetricTile label="平台状态" :value="ready ? 'READY' : 'DEGRADED'" detail="API 与基础设施" :icon="Activity" :tone="ready ? 'positive' : 'warning'" />
        <MetricTile label="权威课程" :value="courseCount" detail="当前租户可见" :icon="Network" />
        <MetricTile label="本地 RAG" :value="String(topic4?.local_rag ?? 'unknown')" detail="无外部 Embedding" :icon="ShieldCheck" tone="positive" />
        <MetricTile label="发布隔离" :value="String(topic4?.release_isolation ?? 'unknown')" detail="C12 原子事务" :icon="Database" />
      </div>
      <section class="workflow-band"><div class="section-title-row"><div><h2>核心工作流</h2><p>从权威知识与个性化画像进入生成、核验和可信发布。</p></div><StatusBadge :value="ready ? 'READY' : 'DEGRADED'" /></div><div class="workflow-links"><button v-for="item in visibleWorkflows" :key="item.path" type="button" @click="router.push(item.path)"><component :is="item.icon" :size="19" /><div><strong>{{ item.title }}</strong><span>{{ item.description }}</span></div><ArrowRight :size="17" /></button></div></section>
      <section class="readiness-panel system-readiness"><div class="readiness-summary" :class="ready ? 'is-ready' : 'is-degraded'"><Activity :size="22" /><div><strong>{{ ready ? '系统就绪' : '服务降级' }}</strong><span>当前会话只读取 Token 内可信租户上下文</span></div></div><dl class="readiness-list"><div><dt><Database :size="18" />数据库</dt><dd>{{ (readiness?.database as Record<string, unknown>)?.status }}</dd></div><div><dt><KeyRound :size="18" />身份服务</dt><dd>{{ readiness?.authentication }}</dd></div><div><dt><Bot :size="18" />任务队列</dt><dd>{{ readiness?.task_queue_running ? 'running' : 'stopped' }}</dd></div><div><dt><ShieldCheck :size="18" />Topic4</dt><dd>{{ topic4?.ready ? 'ready' : 'degraded' }}</dd></div></dl></section>
      <TraceValue :value="traceId" />
    </template>
  </section>
</template>
