<script setup lang="ts">
import { Activity, Database, KeyRound, RefreshCw } from "@lucide/vue"
import { computed, onMounted, ref } from "vue"

import { useAppServices } from "../app/services"
import ErrorState from "../shared/components/ErrorState.vue"
import LoadingState from "../shared/components/LoadingState.vue"

const services = useAppServices()
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const readiness = ref<Record<string, unknown> | null>(null)
const traceId = ref<string | null>(null)
const ready = computed(() => readiness.value?.status === "ready")

async function refresh(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const result = await services.api.readiness()
    readiness.value = result.data
    traceId.value = result.traceId
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "健康检查失败。"
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <section class="page-section">
    <header class="page-heading page-heading-with-action">
      <div>
        <h1>工作台</h1>
        <p>运行状态</p>
      </div>
      <button class="icon-button" type="button" title="刷新状态" :disabled="loading" @click="refresh">
        <RefreshCw :class="{ spin: loading }" :size="18" />
      </button>
    </header>

    <LoadingState v-if="loading && !readiness" label="正在检查服务状态" />
    <ErrorState v-else-if="errorMessage" :message="errorMessage" retryable @retry="refresh" />
    <div v-else class="readiness-panel">
      <div class="readiness-summary" :class="ready ? 'is-ready' : 'is-degraded'">
        <Activity :size="22" aria-hidden="true" />
        <div>
          <strong>{{ ready ? "系统就绪" : "服务降级" }}</strong>
          <span>{{ traceId }}</span>
        </div>
      </div>
      <dl class="readiness-list">
        <div>
          <dt><Database :size="18" />数据库</dt>
          <dd>{{ (readiness?.database as Record<string, unknown>)?.status }}</dd>
        </div>
        <div>
          <dt><KeyRound :size="18" />身份服务</dt>
          <dd>{{ readiness?.authentication }}</dd>
        </div>
      </dl>
    </div>
  </section>
</template>
