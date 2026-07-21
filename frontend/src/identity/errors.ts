import { ApiClientError } from "../api/client"
import { translate } from "../i18n"

const ERROR_KEYS: Readonly<Record<string, string>> = {
  "LIYAN-IDENTITY-CHALLENGE-INVALID": "register.challengeFailure",
  "LIYAN-IDENTITY-CHALLENGE-EXPIRED": "register.challengeFailure",
  "LIYAN-RATE-LIMITED": "register.rateLimited",
  "LIYAN-DATABASE-UNAVAILABLE": "register.networkFailure",
  "LIYAN-IDENTITY-REGISTRATION-UNAVAILABLE": "register.networkFailure",
}

export function localizedIdentityError(error: unknown, fallbackKey: string): string {
  if (error instanceof ApiClientError) {
    return translate(ERROR_KEYS[error.code] ?? fallbackKey)
  }
  return translate(fallbackKey)
}

export function isIdentityConflict(error: unknown): boolean {
  return (
    error instanceof ApiClientError &&
    (error.status === 409 ||
      error.code === "LIYAN-IDENTITY-ACCOUNT-CONFLICT" ||
      error.code === "LIYAN-DATABASE-SERIALIZATION-FAILURE")
  )
}
