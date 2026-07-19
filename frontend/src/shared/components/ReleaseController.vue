<script setup lang="ts">
import { Clock3, LockKeyhole, Send } from "@lucide/vue"
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

import type { ReleaseAuthorizationPayloadV1 } from "@liyans/contracts"
import type { WorkbenchApi } from "../../api/facade"
import { ApiClientError } from "../../api/client"
import { newIdempotencyKey } from "../../api/types"
import ErrorState from "./ErrorState.vue"
import HashValue from "./HashValue.vue"
import StatusBadge from "./StatusBadge.vue"

const props = defineProps<{
  api: WorkbenchApi
  verificationId: string
  allowedBlockIds?: string[]
  disabled?: boolean
}>()

const authorization = ref<ReleaseAuthorizationPayloadV1 | null>(null)
const mode = ref<"FULL" | "FULL_WITH_DISCLOSURE">("FULL")
const ttl = ref(300)
const loading = ref(false)
const error = ref<string | null>(null)
const committed = ref(false)
const now = ref(Date.now())
const deriveOperationKey = ref<string | null>(null)
const deriveFingerprint = ref<string | null>(null)
const commitOperationKey = ref<string | null>(null)
let clock: number | null = null
const expiresIn = computed(() => {
  void now.value
  if (!authorization.value) return null
  return Math.max(0, Math.floor((Date.parse(authorization.value.expires_at) - Date.now()) / 1000))
})
const expired = computed(() => expiresIn.value !== null && expiresIn.value <= 0)

function currentDerivationFingerprint(): string {
  return JSON.stringify({
    verificationId: props.verificationId,
    mode: mode.value,
    allowedBlockIds: props.allowedBlockIds ?? [],
    ttl: Math.min(300, Math.max(1, ttl.value)),
  })
}

async function derive(): Promise<void> {
  if (props.disabled) return
  loading.value = true
  error.value = null
  committed.value = false
  const fingerprint = currentDerivationFingerprint()
  if (deriveFingerprint.value !== fingerprint || !deriveOperationKey.value) {
    deriveFingerprint.value = fingerprint
    deriveOperationKey.value = newIdempotencyKey("topic4-release-derive")
  }
  try {
    const result = await props.api.deriveAuthorization({
      verification_id: props.verificationId,
      requested_release_mode: mode.value,
      requested_block_ids: props.allowedBlockIds ?? [],
      ttl_seconds: Math.min(300, Math.max(1, ttl.value)),
    }, deriveOperationKey.value)
    authorization.value = result.data.authorization
    commitOperationKey.value = newIdempotencyKey("topic4-release-commit")
  } catch (reason) {
    error.value = reason instanceof ApiClientError ? reason.message : reason instanceof Error ? reason.message : "授权派生失败。"
  } finally {
    loading.value = false
  }
}

async function commit(): Promise<void> {
  if (props.disabled || !authorization.value || expired.value) return
  loading.value = true
  error.value = null
  try {
    const operationKey = commitOperationKey.value ?? newIdempotencyKey("topic4-release-commit")
    commitOperationKey.value = operationKey
    await props.api.commitPublication(
      authorization.value.authorization_id,
      operationKey,
    )
    committed.value = true
  } catch (reason) {
    error.value = reason instanceof ApiClientError ? reason.message : reason instanceof Error ? reason.message : "发布提交失败。"
  } finally {
    loading.value = false
  }
}

watch(
  () => props.verificationId,
  () => {
    authorization.value = null
    committed.value = false
    deriveOperationKey.value = null
    deriveFingerprint.value = null
    commitOperationKey.value = null
    error.value = null
  },
)

onMounted(() => { clock = window.setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (clock !== null) window.clearInterval(clock) })
</script>

<template>
  <section class="release-controller">
    <div class="section-title-row">
      <div>
        <h2>原子发布闸门</h2>
        <p>客户端只提交核验编号和发布意图，授权与报告指纹由服务端重新派生。</p>
      </div>
      <LockKeyhole :size="20" aria-hidden="true" />
    </div>
    <div class="release-form">
      <label>发布策略
        <select v-model="mode">
          <option value="FULL">FULL · 完整披露</option>
          <option value="FULL_WITH_DISCLOSURE">FULL_WITH_DISCLOSURE · 受控披露</option>
        </select>
      </label>
      <label>授权有效期（秒）
        <input v-model.number="ttl" type="number" min="1" max="300" step="1" />
      </label>
      <button class="primary-button" type="button" :disabled="disabled || loading || committed" @click="derive">
        <LockKeyhole :size="16" />派生一次性授权
      </button>
    </div>
    <ErrorState v-if="error" :message="error" />
    <div v-if="authorization" class="authorization-receipt">
      <div class="receipt-header">
        <div><strong>服务端授权已派生</strong><small>仅可消费一次，过期后自动失效</small></div>
        <StatusBadge :value="committed ? 'RELEASED' : expired ? 'EXPIRED' : 'PENDING'" />
      </div>
      <div class="receipt-grid">
        <div><span>授权编号</span><code>{{ authorization.authorization_id }}</code></div>
        <div><span>发布策略</span><code>{{ authorization.release_mode }}</code></div>
        <div><span>剩余时间</span><strong><Clock3 :size="14" />{{ expiresIn }} 秒</strong></div>
        <div><span>候选版本</span><code>{{ authorization.candidate_id }} · v{{ authorization.candidate_version }}</code></div>
        <div><span>允许区块</span><code>{{ authorization.allowed_block_ids.length || "全部" }}</code></div>
      </div>
      <HashValue :value="authorization.candidate_sha256" label="Candidate SHA" />
      <HashValue :value="authorization.report_sha256" label="Report SHA" />
      <button class="primary-button" type="button" :disabled="disabled || loading || expired || committed" @click="commit">
        <Send :size="16" />{{ committed ? "已完成原子发布" : "提交原子发布" }}
      </button>
      <p v-if="committed" class="success-note">发布事务已由服务端完成，状态已追加为 RELEASED。</p>
      <p v-else-if="disabled" class="security-note">当前身份仅可查看发布记录，缺少 topic4:release:write。</p>
    </div>
  </section>
</template>
