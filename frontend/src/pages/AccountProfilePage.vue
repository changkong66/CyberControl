<script setup lang="ts">
import type { AccountProfileV1, VerificationChallengeRequestV1, VerificationChallengeVerifyV1 } from "@liyans/contracts"
import { AtSign, CheckCircle2, KeyRound, Mail, Phone, Save, ShieldCheck, UserRound } from "@lucide/vue"
import { computed, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"

import { useAppServices } from "../app/services"
import { useChallengeState } from "../identity/challenge"
import { isIdentityConflict, localizedIdentityError } from "../identity/errors"
import { createPayloadIdempotency } from "../identity/idempotency"
import { normalizeContact, type ContactChannel, validContact, validDisplayName, validVerificationCode } from "../identity/validation"
import { setAppLocale, type AppLocale } from "../i18n"
import ErrorState from "../shared/components/ErrorState.vue"
import LoadingState from "../shared/components/LoadingState.vue"
import PageHeader from "../shared/components/PageHeader.vue"
import StatusBadge from "../shared/components/StatusBadge.vue"
import { useAuthStore } from "../stores/auth"

const { t, d } = useI18n()
const { workbench } = useAppServices()
const auth = useAuthStore()
const challenge = useChallengeState("identity-contact")

const profile = ref<AccountProfileV1 | null>(null)
const displayName = ref("")
const preferredLocale = ref<AppLocale>("zh-CN")
const contactChannel = ref<ContactChannel>("EMAIL")
const contactIdentifier = ref("")
const loading = ref(true)
const saving = ref(false)
const contactBusy = ref(false)
const errorMessage = ref("")
const successMessage = ref("")
const contactChangeOperation = createPayloadIdempotency("identity-contact-change")
const profileUpdateOperation = createPayloadIdempotency("identity-profile")

const canEdit = computed(() => auth.hasScope("account:profile:write"))
const canChangeContact = computed(() => auth.hasScope("account:contact:write"))
const contactValid = computed(() => validContact(contactChannel.value, contactIdentifier.value))
const codeValid = computed(() => validVerificationCode(challenge.code.value))
const profileValid = computed(() => validDisplayName(displayName.value))

watch([contactChannel, contactIdentifier], () => {
  challenge.reset()
  errorMessage.value = ""
})

function applyProfile(next: AccountProfileV1, overwriteDraft = true): void {
  profile.value = next
  if (overwriteDraft) {
    displayName.value = next.display_name
    preferredLocale.value = next.preferred_locale as AppLocale
  }
}

async function loadProfile(preserveDraft = false): Promise<void> {
  const draft = { displayName: displayName.value, locale: preferredLocale.value }
  loading.value = true
  errorMessage.value = ""
  try {
    const result = await workbench.getAccountProfile()
    applyProfile(result.data, !preserveDraft)
    if (preserveDraft) {
      displayName.value = draft.displayName
      preferredLocale.value = draft.locale
    } else {
      setAppLocale(result.data.preferred_locale)
    }
  } catch (error) {
    errorMessage.value = localizedIdentityError(error, "profile.loadFailed")
  } finally {
    loading.value = false
  }
}

async function saveProfile(): Promise<void> {
  if (!profile.value || !canEdit.value || !profileValid.value) {
    if (!profileValid.value) errorMessage.value = t("validation.displayName")
    return
  }
  saving.value = true
  errorMessage.value = ""
  successMessage.value = ""
  const input = {
    display_name: displayName.value.trim(),
    preferred_locale: preferredLocale.value,
    expected_version: profile.value.profile_version,
  }
  try {
    const result = await workbench.updateAccountProfile(input, profileUpdateOperation.keyFor(input))
    applyProfile(result.data)
    profileUpdateOperation.complete()
    setAppLocale(result.data.preferred_locale)
    successMessage.value = t("profile.saved")
  } catch (error) {
    if (isIdentityConflict(error)) {
      profileUpdateOperation.complete()
      await loadProfile(true)
      errorMessage.value = t("profile.conflict")
    } else {
      errorMessage.value = localizedIdentityError(error, "profile.updateFailed")
    }
  } finally {
    saving.value = false
  }
}

async function requestContactCode(): Promise<void> {
  if (!contactValid.value || !challenge.canRequest.value) {
    if (!contactValid.value) errorMessage.value = t(contactChannel.value === "EMAIL" ? "validation.email" : "validation.phone")
    return
  }
  contactBusy.value = true
  errorMessage.value = ""
  try {
    const command: VerificationChallengeRequestV1 = {
      channel: contactChannel.value,
      purpose: contactChannel.value === "EMAIL" ? "CHANGE_EMAIL" : "CHANGE_PHONE",
      identifier: normalizeContact(contactChannel.value, contactIdentifier.value),
    }
    const result = await workbench.requestContactChallenge(command, challenge.requestKeyFor(command))
    challenge.acceptReceipt(result.data)
  } catch (error) {
    errorMessage.value = localizedIdentityError(error, "profile.updateFailed")
  } finally {
    contactBusy.value = false
  }
}

async function verifyAndChangeContact(): Promise<void> {
  if (!profile.value || !challenge.receipt.value || !codeValid.value || !canChangeContact.value) {
    if (!codeValid.value) errorMessage.value = t("validation.code")
    return
  }
  contactBusy.value = true
  errorMessage.value = ""
  successMessage.value = ""
  try {
    if (!challenge.verified.value) {
      const verifyCommand: VerificationChallengeVerifyV1 = {
        challenge_id: challenge.receipt.value.challenge_id,
        code: challenge.code.value,
      }
      const verified = await workbench.verifyContactChallenge(verifyCommand, challenge.verifyKeyFor(verifyCommand))
      challenge.acceptVerification(verified.data)
    }
    const input = {
      channel: contactChannel.value,
      identifier: normalizeContact(contactChannel.value, contactIdentifier.value),
      challenge_id: challenge.receipt.value.challenge_id,
      expected_version: profile.value.profile_version,
    }
    const changed = await workbench.changeAccountContact(input, contactChangeOperation.keyFor(input))
    applyProfile(changed.data)
    contactIdentifier.value = ""
    challenge.reset()
    contactChangeOperation.complete()
    successMessage.value = t("profile.contactUpdated")
  } catch (error) {
    if (isIdentityConflict(error)) {
      contactChangeOperation.complete()
      await loadProfile(true)
      errorMessage.value = t("profile.conflict")
    } else {
      errorMessage.value = localizedIdentityError(error, "profile.updateFailed")
    }
  } finally {
    contactBusy.value = false
  }
}

onMounted(() => loadProfile())
</script>

<template>
  <div class="page-stack">
    <PageHeader :title="t('profile.title')" :description="t('profile.description')" />
    <LoadingState v-if="loading" :label="t('profile.loading')" />
    <ErrorState v-else-if="!profile" :message="errorMessage || t('profile.loadFailed')" retryable @retry="loadProfile()" />

    <template v-else>
      <div class="profile-layout">
        <section class="panel profile-editor">
          <div class="panel-heading"><div><h2>{{ t("profile.title") }}</h2><p>{{ t("profile.profileVersion") }} {{ profile.profile_version }}</p></div><StatusBadge :value="profile.status" /></div>
          <form class="identity-form panel-body" @submit.prevent="saveProfile">
            <label class="field-group"><span>{{ t("profile.displayName") }}</span><input v-model="displayName" type="text" autocomplete="name" maxlength="255" :disabled="saving || !canEdit" /></label>
            <label class="field-group"><span>{{ t("profile.preferredLocale") }}</span><select v-model="preferredLocale" :disabled="saving || !canEdit"><option value="zh-CN">{{ t("locale.zhCN") }}</option><option value="zh-TW">{{ t("locale.zhTW") }}</option><option value="en-US">{{ t("locale.enUS") }}</option></select></label>
            <dl class="property-list identity-properties">
              <div><dt>{{ t("profile.tenant") }}</dt><dd>{{ profile.tenant_id }}</dd></div>
              <div><dt>{{ t("profile.accountId") }}</dt><dd><code>{{ profile.account_id }}</code></dd></div>
              <div><dt>{{ t("common.createdAt") }}</dt><dd>{{ d(new Date(profile.created_at), "short") }}</dd></div>
              <div><dt>{{ t("common.updatedAt") }}</dt><dd>{{ d(new Date(profile.updated_at), "short") }}</dd></div>
            </dl>
            <p v-if="!canEdit" class="security-note"><ShieldCheck :size="15" />{{ t("profile.readOnly") }}</p>
            <button class="primary-button" type="submit" :disabled="saving || !canEdit || !profileValid"><Save :size="16" />{{ saving ? t("common.saving") : t("profile.save") }}</button>
          </form>
        </section>

        <aside class="panel contact-summary">
          <div class="panel-heading"><div><h2>{{ t("profile.contactTitle") }}</h2><p>{{ t("profile.contactDescription") }}</p></div><AtSign :size="18" /></div>
          <div class="contact-cards">
            <article><Mail :size="18" /><div><span>{{ t("profile.email") }}</span><strong>{{ profile.email_hint ?? t("common.notAvailable") }}</strong></div><StatusBadge :value="profile.email_verified ? 'VERIFIED' : 'UNVERIFIED'" :label="t(profile.email_verified ? 'common.verified' : 'common.unverified')" /></article>
            <article><Phone :size="18" /><div><span>{{ t("profile.phone") }}</span><strong>{{ profile.phone_hint ?? t("common.notAvailable") }}</strong></div><StatusBadge :value="profile.phone_verified ? 'VERIFIED' : 'UNVERIFIED'" :label="t(profile.phone_verified ? 'common.verified' : 'common.unverified')" /></article>
          </div>
        </aside>
      </div>

      <section class="panel contact-change-panel">
        <div class="panel-heading"><div><h2>{{ t("profile.contactTitle") }}</h2><p>{{ t("profile.contactDescription") }}</p></div><KeyRound :size="18" /></div>
        <div class="identity-form panel-body">
          <div class="segmented-control compact-segments" role="group" :aria-label="t('profile.contactType')">
            <button type="button" :class="{ active: contactChannel === 'EMAIL' }" @click="contactChannel = 'EMAIL'"><Mail :size="15" />{{ t("profile.email") }}</button>
            <button type="button" :class="{ active: contactChannel === 'PHONE' }" @click="contactChannel = 'PHONE'"><Phone :size="15" />{{ t("profile.phone") }}</button>
          </div>
          <label class="field-group"><span>{{ t("profile.newContact") }}</span><div class="field-action-row"><input v-model="contactIdentifier" :type="contactChannel === 'EMAIL' ? 'email' : 'tel'" :autocomplete="contactChannel === 'EMAIL' ? 'email' : 'tel'" :disabled="contactBusy || !canChangeContact || challenge.verified.value" /><button class="secondary-button" type="button" :disabled="contactBusy || !canChangeContact || !contactValid || !challenge.canRequest.value" @click="requestContactCode"><Mail :size="16" />{{ challenge.remainingSeconds.value > 0 ? t("register.resendIn", { seconds: challenge.remainingSeconds.value }) : t("profile.sendCode") }}</button></div></label>
          <p v-if="challenge.receipt.value" class="inline-status"><CheckCircle2 :size="16" />{{ t("register.deliverySent", { hint: challenge.receipt.value.delivery_hint }) }}</p>
          <label v-if="challenge.receipt.value" class="field-group"><span>{{ t("register.code") }}</span><div class="field-action-row"><input v-model="challenge.code.value" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" :disabled="contactBusy || !canChangeContact" /><button class="primary-button" type="button" :disabled="contactBusy || !canChangeContact || !codeValid" @click="verifyAndChangeContact"><KeyRound :size="16" />{{ t("profile.verifyCode") }}</button></div></label>
          <p v-if="!canChangeContact" class="security-note"><ShieldCheck :size="15" />{{ t("profile.readOnly") }}</p>
        </div>
      </section>

      <p v-if="successMessage" class="form-message success" role="status">{{ successMessage }}</p>
      <p v-if="errorMessage" class="form-message error" role="alert">{{ errorMessage }}</p>
    </template>
  </div>
</template>
