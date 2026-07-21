import {
  validateAccountAdmin,
  validateAccountProfile,
  validateChallengeReceipt,
  validateChallengeRequest,
  validateChallengeVerify,
  validateErrorDocument,
  validateIdentityAuditEntry,
  validateIdentityEnvelope,
  validateReadiness,
  validateRegisterEmail,
  validateRegisterPhone,
  validateRegistrationReceipt,
  validateRegistrationStatus,
  validateTopic1,
  validateTopic3,
  type GeneratedValidator,
} from "./generated/validators.js"

const validators = {
  topic3: validateTopic3,
  topic1: validateTopic1,
  identity: validateIdentityEnvelope,
  error: validateErrorDocument,
  readiness: validateReadiness,
} satisfies Record<string, GeneratedValidator>

const identityValidators = {
  accountAdmin: validateAccountAdmin,
  accountProfile: validateAccountProfile,
  auditEntry: validateIdentityAuditEntry,
  challengeReceipt: validateChallengeReceipt,
  challengeRequest: validateChallengeRequest,
  challengeVerify: validateChallengeVerify,
  registrationReceipt: validateRegistrationReceipt,
  registrationStatus: validateRegistrationStatus,
  registerEmail: validateRegisterEmail,
  registerPhone: validateRegisterPhone,
} satisfies Record<string, GeneratedValidator>

export type EnvelopeKind = "topic1" | "topic3" | "identity"
export type IdentityContractKind = keyof typeof identityValidators

export function assertEnvelope(value: unknown, kind: EnvelopeKind): void {
  const validator = validators[kind]
  if (!validator(value)) {
    throw new Error(`The ${kind} response envelope is invalid.`)
  }
}

export function assertIdentityContract(value: unknown, kind: IdentityContractKind): void {
  if (!identityValidators[kind](value)) {
    throw new Error(`The identity ${kind} contract is invalid.`)
  }
}

export function assertIdentityContractList(value: unknown, kind: IdentityContractKind): void {
  if (!Array.isArray(value) || value.some((item) => !identityValidators[kind](item))) {
    throw new Error(`The identity ${kind} list contract is invalid.`)
  }
}

export interface ErrorDocument {
  error: { error_code?: string; safe_message?: string }
  trace_id?: string | null
}

export function isErrorDocument(value: unknown): value is ErrorDocument {
  return validators.error(value) === true
}

export function assertReadiness(value: unknown): void {
  if (!validators.readiness(value)) {
    throw new Error("The readiness response contract is invalid.")
  }
}
