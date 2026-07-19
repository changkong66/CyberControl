<script setup lang="ts">
import { BookOpen, Filter, Network, RefreshCw, Search, ShieldCheck, Sparkles } from "@lucide/vue"
import type { Topic1CourseV1, Topic1GraphContentV1, Topic1GraphSnapshotV1, Topic1KnowledgePointV1 } from "@liyans/contracts"
import { computed, onMounted, ref, watch } from "vue"
import { useRouter } from "vue-router"

import { useAppServices } from "../app/services"
import ErrorState from "../shared/components/ErrorState.vue"
import HashValue from "../shared/components/HashValue.vue"
import LoadingState from "../shared/components/LoadingState.vue"
import MetricTile from "../shared/components/MetricTile.vue"
import PageHeader from "../shared/components/PageHeader.vue"
import StatusBadge from "../shared/components/StatusBadge.vue"
import TraceValue from "../shared/components/TraceValue.vue"

const services = useAppServices()
const router = useRouter()
const courses = ref<Topic1CourseV1[]>([])
const courseId = ref("")
const graph = ref<Topic1GraphContentV1 | null>(null)
const snapshots = ref<Topic1GraphSnapshotV1[]>([])
const snapshotId = ref("")
const selectedKpId = ref<string | null>(null)
const query = ref("")
const difficulty = ref("ALL")
const loading = ref(true)
const graphLoading = ref(false)
const errorMessage = ref<string | null>(null)
const traceId = ref<string | null>(null)

const filteredPoints = computed(() => {
  const points = graph.value?.knowledge_points ?? []
  const needle = query.value.trim().toLocaleLowerCase()
  return points.filter((point) => {
    const matchesText = !needle || [point.title, point.summary, point.category, ...(point.tags ?? [])].join(" ").toLocaleLowerCase().includes(needle)
    const matchesDifficulty = difficulty.value === "ALL" || point.difficulty_level === Number(difficulty.value)
    return matchesText && matchesDifficulty
  })
})
const selectedPoint = computed(() => graph.value?.knowledge_points.find((point) => point.kp_id === selectedKpId.value) ?? null)
const selectedMappings = computed(() => graph.value?.textbook_mappings?.filter((item) => item.kp_id === selectedKpId.value) ?? [])
const activeSnapshot = computed(() => snapshots.value.find((item) => item.snapshot_id === snapshotId.value) ?? null)
const graphPoints = computed(() => {
  const points = graph.value?.knowledge_points ?? []
  const columns = Math.max(1, Math.max(...points.map((item) => item.topology_level), 0) + 1)
  const byLevel = new Map<number, Topic1KnowledgePointV1[]>()
  points.forEach((point) => byLevel.set(point.topology_level, [...(byLevel.get(point.topology_level) ?? []), point]))
  return points.map((point) => {
    const siblings = byLevel.get(point.topology_level) ?? []
    const index = siblings.findIndex((item) => item.kp_id === point.kp_id)
    return {
      point,
      x: 110 + (point.topology_level / Math.max(columns - 1, 1)) * 740,
      y: 70 + (index + 1) * (300 / Math.max(siblings.length + 1, 2)),
    }
  })
})
const pointPosition = computed(() => new Map(graphPoints.value.map((item) => [item.point.kp_id, item])))

async function loadCourses(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const result = await services.workbench.listCourses()
    courses.value = result.data
    traceId.value = result.traceId
    if (!courseId.value && courses.value[0]) courseId.value = courses.value[0].course_id
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "知识课程加载失败。"
  } finally {
    loading.value = false
  }
}

async function loadGraph(): Promise<void> {
  if (!courseId.value) return
  graphLoading.value = true
  errorMessage.value = null
  try {
    const [graphResult, snapshotResult] = await Promise.all([
      services.workbench.getCourseGraph(courseId.value),
      services.workbench.listGraphSnapshots(courseId.value),
    ])
    graph.value = graphResult.data
    snapshots.value = snapshotResult.data
    traceId.value = graphResult.traceId
    snapshotId.value = snapshots.value[0]?.snapshot_id ?? ""
    selectedKpId.value = graph.value.knowledge_points[0]?.kp_id ?? null
  } catch (error) {
    graph.value = null
    errorMessage.value = error instanceof Error ? error.message : "知识图谱加载失败。"
  } finally {
    graphLoading.value = false
  }
}

function selectSnapshot(): void {
  const snapshot = activeSnapshot.value
  if (snapshot) {
    graph.value = snapshot.content
    selectedKpId.value = snapshot.content.knowledge_points[0]?.kp_id ?? null
  }
}

function openGeneration(): void {
  const queryValue = selectedKpId.value ? { kp: selectedKpId.value, course: courseId.value } : { course: courseId.value }
  void router.push({ path: "/agents", query: queryValue })
}

function prerequisiteCount(point: Topic1KnowledgePointV1): number {
  return graph.value?.prerequisites.filter((edge) => edge.dependent_kp_id === point.kp_id).length ?? 0
}

watch(courseId, loadGraph)
watch(snapshotId, selectSnapshot)
onMounted(loadCourses)
</script>

<template>
  <section class="page-section">
    <PageHeader title="权威知识图谱" description="Topic1 冻结知识拓扑、先修依赖与教材权威来源">
      <template #actions>
        <button class="secondary-button" type="button" :disabled="loading || graphLoading" @click="loadCourses">
          <RefreshCw :size="16" :class="{ spin: loading || graphLoading }" />刷新
        </button>
      </template>
    </PageHeader>

    <LoadingState v-if="loading && !courses.length" label="正在加载权威课程" />
    <ErrorState v-else-if="errorMessage && !graph" :message="errorMessage" retryable @retry="loadCourses" />
    <template v-else>
      <div class="toolbar-row">
        <label class="field-inline"><BookOpen :size="16" />课程
          <select v-model="courseId">
            <option v-for="course in courses" :key="course.course_id" :value="course.course_id">{{ course.title }}</option>
          </select>
        </label>
        <label v-if="snapshots.length" class="field-inline"><ShieldCheck :size="16" />冻结快照
          <select v-model="snapshotId">
            <option v-for="snapshot in snapshots" :key="snapshot.snapshot_id" :value="snapshot.snapshot_id">v{{ snapshot.graph_version }} · {{ snapshot.node_count }} 节点</option>
          </select>
        </label>
        <button class="primary-button toolbar-action" type="button" :disabled="!selectedKpId" @click="openGeneration">
          <Sparkles :size="16" />基于知识点生成内容
        </button>
      </div>

      <div v-if="!courses.length" class="empty-state knowledge-empty">
        <Network :size="32" />
        <strong>当前租户暂无权威课程</strong>
        <span>Topic1 数据由服务端租户上下文过滤；前端不会用本地样例填充或跨租户读取。</span>
      </div>

      <div v-if="errorMessage" class="inline-error"><ErrorState :message="errorMessage" /></div>
      <div v-if="graph" class="metric-grid metric-grid-four">
        <MetricTile label="知识点" :value="graph.knowledge_points.length" detail="当前冻结图谱" :icon="Network" tone="positive" />
        <MetricTile label="先修关系" :value="graph.prerequisites.length" detail="有向依赖边" :icon="Filter" />
        <MetricTile label="教材映射" :value="graph.textbook_mappings?.length ?? 0" detail="可追溯章节" :icon="BookOpen" />
        <MetricTile label="图谱版本" :value="activeSnapshot ? `v${activeSnapshot.graph_version}` : '当前'" detail="内容不可变" :icon="ShieldCheck" />
      </div>

      <div v-if="graph" class="knowledge-layout">
        <section class="panel graph-panel">
          <div class="panel-heading">
            <div><h2>拓扑画布</h2><p>拖动与缩放由浏览器原生视图承载，节点点击查看完整权威属性。</p></div>
            <StatusBadge :value="activeSnapshot ? 'FROZEN' : 'LIVE'" :label="activeSnapshot ? '冻结快照' : '当前视图'" />
          </div>
          <div class="graph-canvas" role="img" aria-label="知识点先修关系图谱">
            <svg viewBox="0 0 960 400" preserveAspectRatio="xMidYMid meet">
              <defs><marker id="knowledge-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#88aaa0" /></marker></defs>
              <g class="graph-edges">
                <line v-for="edge in graph.prerequisites" :key="edge.edge_id" :x1="pointPosition.get(edge.prerequisite_kp_id)?.x ?? 0" :y1="pointPosition.get(edge.prerequisite_kp_id)?.y ?? 0" :x2="pointPosition.get(edge.dependent_kp_id)?.x ?? 0" :y2="pointPosition.get(edge.dependent_kp_id)?.y ?? 0" marker-end="url(#knowledge-arrow)" />
              </g>
              <g v-for="item in graphPoints" :key="item.point.kp_id" class="graph-node" :class="{ selected: selectedKpId === item.point.kp_id }" @click="selectedKpId = item.point.kp_id">
                <circle :cx="item.x" :cy="item.y" :r="selectedKpId === item.point.kp_id ? 22 : 17" />
                <text :x="item.x" :y="item.y + 4" text-anchor="middle">{{ item.point.topology_level + 1 }}</text>
                <foreignObject :x="item.x - 66" :y="item.y + 25" width="132" height="42"><div class="graph-node-label">{{ item.point.title }}</div></foreignObject>
              </g>
            </svg>
          </div>
          <TraceValue :value="traceId" />
        </section>

        <aside class="panel detail-panel">
          <div class="panel-heading"><div><h2>知识点详情</h2><p>学术属性与权威来源</p></div><Search :size="18" /></div>
          <div v-if="selectedPoint" class="detail-content">
            <div class="detail-title"><strong>{{ selectedPoint.title }}</strong><StatusBadge :value="selectedPoint.status" /></div>
            <p>{{ selectedPoint.summary }}</p>
            <dl class="property-list">
              <div><dt>知识点编号</dt><dd>{{ selectedPoint.kp_id }}</dd></div>
              <div><dt>分类</dt><dd>{{ selectedPoint.category }}</dd></div>
              <div><dt>难度</dt><dd>{{ selectedPoint.difficulty_level }}/5 · {{ Math.round(selectedPoint.difficulty_score * 100) }}%</dd></div>
              <div><dt>预计学习</dt><dd>{{ selectedPoint.estimated_minutes }} 分钟</dd></div>
              <div><dt>先修数量</dt><dd>{{ prerequisiteCount(selectedPoint) }}</dd></div>
            </dl>
            <div class="tag-row"><span v-for="tag in selectedPoint.tags" :key="tag" class="soft-tag">{{ tag }}</span></div>
            <div class="authority-list"><h3>教材映射</h3><span v-for="mapping in selectedMappings" :key="mapping.mapping_id">{{ mapping.section_id }} · {{ mapping.mapping_type }}</span><span v-if="!selectedMappings.length" class="muted-value">暂无映射</span></div>
          </div>
          <div v-else class="empty-state compact-empty">选择一个知识点查看详情</div>
        </aside>
      </div>

      <section v-if="graph" class="panel knowledge-table-panel">
        <div class="panel-heading"><div><h2>知识点目录</h2><p>支持标题、摘要、分类和标签检索；结果仍受当前冻结快照约束。</p></div><div class="table-tools"><label class="search-field"><Search :size="15" /><input v-model="query" type="search" placeholder="检索知识点" /></label><select v-model="difficulty"><option value="ALL">全部难度</option><option v-for="level in 5" :key="level" :value="String(level)">难度 {{ level }}</option></select></div></div>
        <div class="table-scroll"><table class="data-table"><thead><tr><th>知识点</th><th>分类</th><th>难度</th><th>先修依赖</th><th>状态</th><th>更新时间</th></tr></thead><tbody><tr v-for="point in filteredPoints" :key="point.kp_id" :class="{ 'row-selected': point.kp_id === selectedKpId }" @click="selectedKpId = point.kp_id"><td><strong>{{ point.title }}</strong><small>{{ point.kp_id }}</small></td><td>{{ point.category }}</td><td><span class="difficulty-bars"><i v-for="level in 5" :key="level" :class="{ active: level <= point.difficulty_level }" /></span></td><td>{{ prerequisiteCount(point) }}</td><td><StatusBadge :value="point.status" /></td><td>{{ new Date(point.updated_at).toLocaleDateString("zh-CN") }}</td></tr><tr v-if="!filteredPoints.length"><td colspan="6"><div class="empty-state compact-empty">没有匹配的知识点</div></td></tr></tbody></table></div>
        <div class="table-footer"><span>显示 {{ filteredPoints.length }} / {{ graph.knowledge_points.length }} 个知识点</span><HashValue :value="activeSnapshot?.content_sha256" label="Snapshot SHA" /></div>
      </section>
    </template>
  </section>
</template>
