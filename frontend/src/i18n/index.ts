import { createI18n } from "vue-i18n"

import { enUS, zhCN, zhTW } from "./messages"

export const SUPPORTED_LOCALES = ["zh-CN", "zh-TW", "en-US"] as const
export type AppLocale = (typeof SUPPORTED_LOCALES)[number]
export const DEFAULT_LOCALE: AppLocale = "zh-CN"
export const LOCALE_STORAGE_KEY = "cybercontrol:ui:locale"

export function normalizeLocale(value: unknown): AppLocale {
  if (typeof value !== "string") return DEFAULT_LOCALE
  const exact = SUPPORTED_LOCALES.find((locale) => locale === value)
  if (exact) return exact
  const normalized = value.replaceAll("_", "-").toLowerCase()
  if (normalized === "zh-tw" || normalized === "zh-hant") return "zh-TW"
  if (normalized === "en" || normalized.startsWith("en-")) return "en-US"
  return DEFAULT_LOCALE
}

export function storedLocale(): AppLocale {
  if (typeof window === "undefined") return DEFAULT_LOCALE
  return normalizeLocale(window.sessionStorage.getItem(LOCALE_STORAGE_KEY))
}

export function keycloakLocale(locale: AppLocale): "zh-CN" | "zh-TW" | "en" {
  return locale === "en-US" ? "en" : locale
}

export const i18n = createI18n({
  legacy: false,
  locale: storedLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { "zh-CN": zhCN, "zh-TW": zhTW, "en-US": enUS },
  datetimeFormats: {
    "zh-CN": { short: { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" } },
    "zh-TW": { short: { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" } },
    "en-US": { short: { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" } },
  },
  numberFormats: {
    "zh-CN": { integer: { maximumFractionDigits: 0 } },
    "zh-TW": { integer: { maximumFractionDigits: 0 } },
    "en-US": { integer: { maximumFractionDigits: 0 } },
  },
  missingWarn: false,
  fallbackWarn: false,
})

export function activeLocale(): AppLocale {
  return normalizeLocale(i18n.global.locale.value)
}

export function setAppLocale(value: unknown): AppLocale {
  const locale = normalizeLocale(value)
  i18n.global.locale.value = locale
  if (typeof window !== "undefined") window.sessionStorage.setItem(LOCALE_STORAGE_KEY, locale)
  if (typeof document !== "undefined") document.documentElement.lang = locale
  return locale
}

export function translate(key: string, parameters?: Record<string, unknown>): string {
  return String(i18n.global.t(key, parameters ?? {}))
}

setAppLocale(storedLocale())
