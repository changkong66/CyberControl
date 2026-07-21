<script setup lang="ts">
import type {
  UserRegisterByEmailCommandV1,
  UserRegisterByPhoneCommandV1,
  VerificationChallengeRequestV1,
  VerificationChallengeVerifyV1,
} from "@liyans/contracts"
import { Check, KeyRound, Mail, Phone, Send, ShieldCheck, UserPlus } from "@lucide/vue"
import { computed, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useRoute, useRouter } from "vue-router"

import { useAppServices } from "../app/services"
import { useChallengeState } from "../identity/challenge"
import { localizedIdentityError } from "../identity/errors"
import { createPayloadIdempotency } from "../identity/idempotency"
import {
  normalizeContact,
  type ContactChannel,
  validContact,
  validDisplayName,
  validPassword,
  validVerificationCode,
} from "../identity/validation"
import { activeLocale } from "../i18n"
import LocaleSwitcher from "../shared/components/LocaleSwitcher.vue"

const PRIVACY_VERSION = import.meta.env.VITE_PRIVACY_POLICY_VERSION ?? "privacy-v1"
const TERMS_VERSION = import.meta.env.VITE_TERMS_OF_SERVICE_VERSION ?? "terms-v1"

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { workbench } = useAppServices()
const challenge = useChallengeState("identity-register")

const channel = ref<ContactChannel>("EMAIL")
const identifier = ref("")
const displayName = ref("")
const password = ref("")
const passwordConfirm = ref("")
const privacyAccepted = ref(false)
const termsAccepted = ref(false)
const busy = ref<"request" | "verify" | "register" | null>(null)
const errorMessage = ref("")
const registrationOperation = createPayloadIdempotency("identity-register")

function readInvitationToken(): string | null {
  const candidate = route.query.invitation ?? route.query.invitation_token
  return typeof candidate === "string" && candidate.length >= 32 ? candidate : null
}
const invitationToken = ref(readInvitationToken())
const normalizedIdentifier = computed(() => normalizeContact(channel.value, identifier.value))
const identifierValid = computed(() => validContact(channel.value, identifier.value))
const codeValid = computed(() => validVerificationCode(challenge.code.value))
const passwordValid = computed(() => validPassword(password.value))
const passwordsMatch = computed(() => password.value === passwordConfirm.value && password.value.length > 0)
const formValid = computed(
  () =>
    challenge.verified.value &&
    identifierValid.value &&
    validDisplayName(displayName.value) &&
    passwordValid.value &&
    passwordsMatch.value &&
    privacyAccepted.value &&
    termsAccepted.value,
)

watch([channel, identifier], () => {
  challenge.reset()
  errorMessage.value = ""
})

onMounted(() => {
  if (!invitationToken.value) return
  const query = { ...route.query }
  delete query.invitation
  delete query.invitation_token
  void router.replace({ query })
})

function switchChannel(next: ContactChannel): void {
  channel.value = next
  identifier.value = ""
}

async function requestCode(): Promise<void> {
  errorMessage.value = ""
  if (!identifierValid.value || !challenge.canRequest.value) {
    if (!identifierValid.value) errorMessage.value = t(channel.value === "EMAIL" ? "validation.email" : "validation.phone")
    return
  }
  busy.value = "request"
  try {
    const command: VerificationChallengeRequestV1 = {
      channel: channel.value,
      purpose: "REGISTER",
      identifier: normalizedIdentifier.value,
      invitation_token: invitationToken.value,
    }
    const result = await workbench.requestRegistrationChallenge(command, challenge.requestKeyFor(command))
    challenge.acceptReceipt(result.data)
  } catch (error) {
    errorMessage.value = localizedIdentityError(error, "register.genericFailure")
  } finally {
    busy.value = null
  }
}

async function verifyCode(): Promise<void> {
  errorMessage.value = ""
  if (!challenge.receipt.value || !codeValid.value) {
    errorMessage.value = t("validation.code")
    return
  }
  busy.value = "verify"
  try {
    const command: VerificationChallengeVerifyV1 = {
      challenge_id: challenge.receipt.value.challenge_id,
      code: challenge.code.value,
      invitation_token: invitationToken.value,
    }
    const result = await workbench.verifyRegistrationChallenge(command, challenge.verifyKeyFor(command))
    challenge.acceptVerification(result.data)
  } catch (error) {
    errorMessage.value = localizedIdentityError(error, "register.challengeFailure")
  } finally {
    busy.value = null
  }
}

function validateRegistration(): string | null {
  if (!identifierValid.value) return t(channel.value === "EMAIL" ? "validation.email" : "validation.phone")
  if (!challenge.verified.value) return t("register.challengeFailure")
  if (!validDisplayName(displayName.value)) return t("validation.displayName")
  if (!passwordValid.value) return t("validation.password")
  if (!passwordsMatch.value) return t("validation.passwordMismatch")
  if (!privacyAccepted.value || !termsAccepted.value) return t("validation.consent")
  return null
}

async function register(): Promise<void> {
  errorMessage.value = validateRegistration() ?? ""
  if (errorMessage.value || !challenge.receipt.value) return
  busy.value = "register"
  const common = {
    challenge_id: challenge.receipt.value.challenge_id,
    password: password.value,
    display_name: displayName.value.trim(),
    preferred_locale: activeLocale(),
    consent: {
      privacy_policy_version: PRIVACY_VERSION,
      terms_of_service_version: TERMS_VERSION,
      privacy_policy_accepted: true as const,
      terms_of_service_accepted: true as const,
    },
    invitation_token: invitationToken.value,
  }
  try {
    if (channel.value === "EMAIL") {
      const command: UserRegisterByEmailCommandV1 = { ...common, email: normalizedIdentifier.value }
      await workbench.registerByEmail(command, registrationOperation.keyFor(command))
    } else {
      const command: UserRegisterByPhoneCommandV1 = { ...common, phone: normalizedIdentifier.value }
      await workbench.registerByPhone(command, registrationOperation.keyFor(command))
    }
    registrationOperation.complete()
    password.value = ""
    passwordConfirm.value = ""
    challenge.code.value = ""
    await router.replace({ name: "login", query: { registered: "1" } })
  } catch (error) {
    errorMessage.value = localizedIdentityError(error, "register.genericFailure")
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <main class="identity-public-page">
    <div class="public-locale-row"><LocaleSwitcher /></div>
    <section class="identity-auth-surface registration-surface" aria-labelledby="register-title">
      <header class="identity-brand-header">
        <span class="auth-mark"><ShieldCheck :size="28" /></span>
        <div><strong>CyberControl</strong><span>{{ t("app.tagline") }}</span></div>
      </header>
      <div class="identity-title-block">
        <h1 id="register-title">{{ t("register.title") }}</h1>
        <p>{{ t("register.description") }}</p>
      </div>

      <div class="segmented-control" role="group" :aria-label="t('register.title')">
        <button type="button" :class="{ active: channel === 'EMAIL' }" @click="switchChannel('EMAIL')"><Mail :size="16" />{{ t("register.emailMode") }}</button>
        <button type="button" :class="{ active: channel === 'PHONE' }" @click="switchChannel('PHONE')"><Phone :size="16" />{{ t("register.phoneMode") }}</button>
      </div>

      <form class="identity-form" novalidate @submit.prevent="register">
        <label class="field-group">
          <span>{{ t(channel === "EMAIL" ? "register.email" : "register.phone") }}</span>
          <div class="field-action-row">
            <input v-model="identifier" :type="channel === 'EMAIL' ? 'email' : 'tel'" :autocomplete="channel === 'EMAIL' ? 'email' : 'tel'" :placeholder="t(channel === 'EMAIL' ? 'register.emailPlaceholder' : 'register.phonePlaceholder')" :disabled="busy !== null || challenge.verified.value" required />
            <button class="secondary-button" type="button" :disabled="busy !== null || !identifierValid || !challenge.canRequest.value || challenge.verified.value" @click="requestCode"><Send :size="16" />{{ challenge.remainingSeconds.value > 0 ? t("register.resendIn", { seconds: challenge.remainingSeconds.value }) : challenge.receipt.value ? t("register.resendCode") : t("register.sendCode") }}</button>
          </div>
        </label>

        <p v-if="challenge.receipt.value" class="inline-status" :class="{ success: challenge.verified.value }"><Check v-if="challenge.verified.value" :size="16" /><Mail v-else :size="16" />{{ challenge.verified.value ? t("register.verified") : t("register.deliverySent", { hint: challenge.receipt.value.delivery_hint }) }}</p>

        <label v-if="challenge.receipt.value && !challenge.verified.value" class="field-group">
          <span>{{ t("register.code") }}</span>
          <div class="field-action-row">
            <input v-model="challenge.code.value" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" :placeholder="t('register.codePlaceholder')" :disabled="busy !== null" required />
            <button class="secondary-button" type="button" :disabled="busy !== null || !codeValid" @click="verifyCode"><KeyRound :size="16" />{{ t("register.verifyCode") }}</button>
          </div>
        </label>

        <div class="identity-form-grid">
          <label class="field-group"><span>{{ t("register.displayName") }}</span><input v-model="displayName" type="text" autocomplete="name" maxlength="255" :placeholder="t('register.displayNamePlaceholder')" :disabled="busy !== null" required /></label>
          <label class="field-group"><span>{{ t("register.password") }}</span><input v-model="password" type="password" autocomplete="new-password" minlength="8" maxlength="128" :disabled="busy !== null" required /></label>
          <label class="field-group"><span>{{ t("register.passwordConfirm") }}</span><input v-model="passwordConfirm" type="password" autocomplete="new-password" minlength="8" maxlength="128" :disabled="busy !== null" required /></label>
        </div>

        <ul class="password-checks" aria-live="polite">
          <li :class="{ complete: passwordValid }"><Check :size="14" />{{ t("register.passwordRuleLength") }}</li>
          <li :class="{ complete: passwordsMatch }"><Check :size="14" />{{ t("register.passwordRuleMatch") }}</li>
        </ul>

        <div class="consent-list">
          <label><input v-model="privacyAccepted" type="checkbox" :disabled="busy !== null" /><span>{{ t("register.privacyConsent") }}</span></label>
          <label><input v-model="termsAccepted" type="checkbox" :disabled="busy !== null" /><span>{{ t("register.termsConsent") }}</span></label>
        </div>
        <p v-if="invitationToken" class="security-note"><ShieldCheck :size="15" />{{ t("register.invitationApplied") }}</p>
        <p v-if="errorMessage" class="form-message error" role="alert">{{ errorMessage }}</p>
        <button class="primary-button full-width" type="submit" :disabled="busy !== null || !formValid"><UserPlus :size="17" />{{ busy === "register" ? t("register.submitting") : t("register.submit") }}</button>
      </form>
      <RouterLink class="text-link" :to="{ name: 'login' }">{{ t("register.signInInstead") }}</RouterLink>
    </section>
  </main>
</template>
