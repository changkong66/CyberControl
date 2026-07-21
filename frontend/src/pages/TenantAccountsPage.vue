<script setup lang="ts">
import type { AccountAdminViewV1, IdentityAuditEntryV1 } from "@liyans/contracts"
import { Ban, ChevronLeft, ChevronRight, History, RefreshCw, RotateCcw, Search, ShieldCheck, UserRound } from "@lucide/vue"
import { computed, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"

import { useAppServices } from "../app/services"
import { isIdentityConflict, localizedIdentityError } from "../identity/errors"
import { createPayloadIdempotency } from "../identity/idempotency"
import ConfirmDialog from "../shared/components/ConfirmDialog.vue"
import ErrorState from "../shared/components/ErrorState.vue"
import HashValue from "../shared/components/HashValue.vue"
import LoadingState from "../shared/components/LoadingState.vue"
import PageHeader from "../shared/components/PageHeader.vue"
import StatusBadge from "../shared/components/StatusBadge.vue"
import { useAuthStore } from "../stores/auth"

const PAGE_SIZE = 50
const { t, d } = useI18n()
const { workbench } = useAppServices()
const auth = useAuthStore()

const accounts = ref<AccountAdminViewV1[]>([])
const selected = ref<AccountAdminViewV1 | null>(null)
const auditEntries = ref<IdentityAuditEntryV1[]>([])
const offset = ref(0)
const search = ref("")
const loading = ref(true)
const detailLoading = ref(false)
const actionLoading = ref(false)
const errorMessage = ref("")
const successMessage = ref("")
const pendingAction = ref<"disable" | "restore" | null>(null)
const reasonCode = ref("ADMIN_ACTION")
const statusOperation = createPayloadIdempotency("identity-account-status")

const canWrite = computed(() => auth.hasScope("account:admin:write"))
const currentPage = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const filteredAccounts = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return accounts.value
  return accounts.value.filter((account) =>
    `${account.display_name} ${account.account_id}`.toLowerCase().includes(query),
  )
})

async function loadAccounts(): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  try {
    const result = await workbench.listTenantAccounts(offset.value, PAGE_SIZE)
    accounts.value = result.data
    if (selected.value) {
      selected.value = result.data.find((account) => account.account_id === selected.value?.account_id) ?? null
    }
  } catch (error) {
    errorMessage.value = localizedIdentityError(error, "accounts.loadFailed")
  } finally {
    loading.value = false
  }
}

async function selectAccount(account: AccountAdminViewV1): Promise<void> {
  selected.value = account
  detailLoading.value = true
  errorMessage.value = ""
  try {
    const [detail, audit] = await Promise.all([
      workbench.getTenantAccount(account.account_id),
      workbench.listTenantAccountAudit(account.account_id),
    ])
    selected.value = detail.data
    auditEntries.value = audit.data
  } catch (error) {
    errorMessage.value = localizedIdentityError(error, "accounts.loadFailed")
  } finally {
    detailLoading.value = false
  }
}

function requestStatusChange(action: "disable" | "restore"): void {
  if (!selected.value || !canWrite.value) return
  pendingAction.value = action
}

async function applyStatusChange(): Promise<void> {
  if (!selected.value || !pendingAction.value || !canWrite.value) return
  actionLoading.value = true
  errorMessage.value = ""
  successMessage.value = ""
  const accountId = selected.value.account_id
  try {
    const enabled = pendingAction.value === "restore"
    const input = {
      account_id: accountId,
      enabled,
      expected_version: selected.value.profile_version,
      reason_code: enabled ? null : reasonCode.value.trim() || "ADMIN_ACTION",
    }
    const result = await workbench.setTenantAccountEnabled(
      accountId,
      enabled,
      {
        expected_version: input.expected_version,
        reason_code: input.reason_code,
      },
      statusOperation.keyFor(input),
    )
    statusOperation.complete()
    selected.value = result.data
    accounts.value = accounts.value.map((account) => (account.account_id === accountId ? result.data : account))
    auditEntries.value = (await workbench.listTenantAccountAudit(accountId)).data
    successMessage.value = t("accounts.statusUpdated")
    pendingAction.value = null
  } catch (error) {
    pendingAction.value = null
    if (isIdentityConflict(error)) {
      statusOperation.complete()
      const detail = await workbench.getTenantAccount(accountId)
      selected.value = detail.data
      accounts.value = accounts.value.map((account) => (account.account_id === accountId ? detail.data : account))
      errorMessage.value = t("accounts.conflict")
    } else {
      errorMessage.value = localizedIdentityError(error, "accounts.actionFailed")
    }
  } finally {
    actionLoading.value = false
  }
}

async function previousPage(): Promise<void> {
  offset.value = Math.max(0, offset.value - PAGE_SIZE)
  selected.value = null
  auditEntries.value = []
  await loadAccounts()
}

async function nextPage(): Promise<void> {
  offset.value += PAGE_SIZE
  selected.value = null
  auditEntries.value = []
  await loadAccounts()
}

onMounted(loadAccounts)
</script>

<template>
  <div class="page-stack">
    <PageHeader :title="t('accounts.title')" :description="t('accounts.description')">
      <template #actions><button class="secondary-button" type="button" :disabled="loading" @click="loadAccounts"><RefreshCw :size="16" :class="{ spin: loading }" />{{ t("common.refresh") }}</button></template>
    </PageHeader>
    <ErrorState v-if="errorMessage && !accounts.length" :message="errorMessage" retryable @retry="loadAccounts" />
    <LoadingState v-else-if="loading" :label="t('accounts.loading')" />

    <template v-else>
      <section class="panel account-table-panel">
        <div class="toolbar-row"><label class="search-field"><Search :size="16" /><input v-model="search" type="search" :placeholder="t('accounts.search')" /></label><span>{{ t("accounts.page", { page: currentPage }) }}</span></div>
        <div class="table-scroll">
          <table class="data-table account-table">
            <thead><tr><th>{{ t("accounts.account") }}</th><th>{{ t("accounts.contact") }}</th><th>{{ t("common.status") }}</th><th>{{ t("accounts.locale") }}</th><th>{{ t("accounts.version") }}</th><th>{{ t("accounts.actions") }}</th></tr></thead>
            <tbody>
              <tr v-for="account in filteredAccounts" :key="account.account_id" :class="{ 'row-selected': selected?.account_id === account.account_id }">
                <td><button class="table-link" type="button" @click="selectAccount(account)"><strong>{{ account.display_name }}</strong><small>{{ account.account_id }}</small></button></td>
                <td><strong>{{ account.email_hint ?? account.phone_hint ?? t("common.notAvailable") }}</strong><small>{{ account.email_verified || account.phone_verified ? t("common.verified") : t("common.unverified") }}</small></td>
                <td><StatusBadge :value="account.status" /></td>
                <td>{{ account.preferred_locale }}</td>
                <td>v{{ account.profile_version }}</td>
                <td><button class="icon-button" type="button" :title="t('common.details')" :aria-label="t('common.details')" @click="selectAccount(account)"><UserRound :size="17" /></button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!filteredAccounts.length" class="empty-state compact-empty">{{ t("accounts.empty") }}</div>
        <footer class="table-footer"><button class="secondary-button" type="button" :disabled="offset === 0" @click="previousPage"><ChevronLeft :size="16" />{{ t("common.previous") }}</button><span>{{ t("accounts.page", { page: currentPage }) }}</span><button class="secondary-button" type="button" :disabled="accounts.length < PAGE_SIZE" @click="nextPage">{{ t("common.next") }}<ChevronRight :size="16" /></button></footer>
      </section>

      <div class="account-detail-grid">
        <section class="panel account-detail-panel">
          <div class="panel-heading"><div><h2>{{ t("common.details") }}</h2><p>{{ selected?.account_id ?? t("accounts.select") }}</p></div><StatusBadge v-if="selected" :value="selected.status" /></div>
          <LoadingState v-if="detailLoading" :label="t('common.loading')" />
          <div v-else-if="selected" class="panel-body">
            <dl class="property-list identity-properties">
              <div><dt>{{ t("accounts.account") }}</dt><dd>{{ selected.display_name }}</dd></div>
              <div><dt>{{ t("profile.email") }}</dt><dd>{{ selected.email_hint ?? t("common.notAvailable") }}</dd></div>
              <div><dt>{{ t("profile.phone") }}</dt><dd>{{ selected.phone_hint ?? t("common.notAvailable") }}</dd></div>
              <div><dt>{{ t("profile.preferredLocale") }}</dt><dd>{{ selected.preferred_locale }}</dd></div>
              <div><dt>{{ t("common.updatedAt") }}</dt><dd>{{ d(new Date(selected.updated_at), "short") }}</dd></div>
            </dl>
            <label v-if="canWrite && selected.status === 'ACTIVE'" class="field-group"><span>{{ t("accounts.reason") }}</span><input v-model="reasonCode" type="text" maxlength="128" :placeholder="t('accounts.reasonPlaceholder')" /></label>
            <div class="account-actions">
              <button v-if="selected.status === 'ACTIVE'" class="danger-button" type="button" :disabled="!canWrite || actionLoading" @click="requestStatusChange('disable')"><Ban :size="16" />{{ t("accounts.disable") }}</button>
              <button v-else class="primary-button" type="button" :disabled="!canWrite || actionLoading" @click="requestStatusChange('restore')"><RotateCcw :size="16" />{{ t("accounts.restore") }}</button>
            </div>
            <p v-if="!canWrite" class="security-note"><ShieldCheck :size="15" />{{ t("accounts.readOnly") }}</p>
          </div>
          <div v-else class="empty-state compact-empty"><UserRound :size="28" /><span>{{ t("accounts.select") }}</span></div>
        </section>

        <section class="panel audit-panel">
          <div class="panel-heading"><div><h2>{{ t("accounts.audit") }}</h2><p>{{ t("accounts.auditIntegrity") }}</p></div><History :size="18" /></div>
          <div v-if="auditEntries.length" class="audit-list">
            <article v-for="entry in auditEntries" :key="entry.event_id"><div class="audit-heading"><div><strong>{{ entry.action }}</strong><span>#{{ entry.sequence }} · {{ d(new Date(entry.occurred_at), "short") }}</span></div><StatusBadge :value="entry.outcome" /></div><dl class="property-list"><div><dt>{{ t("accounts.actor") }}</dt><dd>{{ entry.actor_ref }}</dd></div><div><dt>{{ t("common.traceId") }}</dt><dd>{{ entry.trace_id ?? t("common.notAvailable") }}</dd></div></dl><HashValue :value="entry.event_hash" :label="t('accounts.hash')" /></article>
          </div>
          <div v-else class="empty-state compact-empty"><History :size="28" /><span>{{ t("accounts.auditEmpty") }}</span></div>
        </section>
      </div>

      <p v-if="successMessage" class="form-message success" role="status">{{ successMessage }}</p>
      <p v-if="errorMessage" class="form-message error" role="alert">{{ errorMessage }}</p>
    </template>

    <ConfirmDialog
      :open="pendingAction !== null"
      :title="t(pendingAction === 'disable' ? 'accounts.disableTitle' : 'accounts.restoreTitle')"
      :message="t(pendingAction === 'disable' ? 'accounts.disableMessage' : 'accounts.restoreMessage')"
      :confirm-label="t(pendingAction === 'disable' ? 'accounts.disable' : 'accounts.restore')"
      :cancel-label="t('common.cancel')"
      @confirm="applyStatusChange"
      @cancel="pendingAction = null"
    />
  </div>
</template>
