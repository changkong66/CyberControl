export type ContactChannel = "EMAIL" | "PHONE"

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/u
const PHONE_PATTERN = /^\+[1-9][0-9]{7,14}$/u
const CODE_PATTERN = /^[0-9]{6}$/u

export function normalizeEmail(value: string): string {
  return value.trim().toLowerCase()
}

export function normalizePhone(value: string): string {
  return value.replace(/[\s().-]/gu, "")
}

export function normalizeContact(channel: ContactChannel, value: string): string {
  return channel === "EMAIL" ? normalizeEmail(value) : normalizePhone(value)
}

export function validContact(channel: ContactChannel, value: string): boolean {
  const normalized = normalizeContact(channel, value)
  return channel === "EMAIL" ? EMAIL_PATTERN.test(normalized) : PHONE_PATTERN.test(normalized)
}

export function validVerificationCode(value: string): boolean {
  return CODE_PATTERN.test(value)
}

export function validPassword(value: string): boolean {
  return value.length >= 8 && value.length <= 128
}

export function validDisplayName(value: string): boolean {
  const length = value.trim().length
  return length >= 1 && length <= 255
}
