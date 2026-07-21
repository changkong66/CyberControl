import { readFileSync } from "node:fs"
import { fileURLToPath, URL } from "node:url"

import { describe, expect, it } from "vitest"

import {
  activeLocale,
  DEFAULT_LOCALE,
  keycloakLocale,
  LOCALE_STORAGE_KEY,
  normalizeLocale,
  setAppLocale,
  translate,
} from "../src/i18n"
import { enUS, zhCN, zhTW } from "../src/i18n/messages"

function flatten(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof child === "string" ? [path] : flatten(child as object, path)
  })
}

describe("three-language runtime", () => {
  it("keeps all locale catalogs structurally complete", () => {
    const expected = flatten(zhCN).sort()
    expect(flatten(zhTW).sort()).toEqual(expected)
    expect(flatten(enUS).sort()).toEqual(expected)
    expect(expected.length).toBeGreaterThan(150)
  })

  it("normalizes locales, persists only a session preference and maps Keycloak English", () => {
    expect(normalizeLocale("zh_Hant")).toBe("zh-TW")
    expect(normalizeLocale("en-GB")).toBe("en-US")
    expect(normalizeLocale("unsupported")).toBe(DEFAULT_LOCALE)
    expect(keycloakLocale("en-US")).toBe("en")
    setAppLocale("zh-TW")
    expect(activeLocale()).toBe("zh-TW")
    expect(window.sessionStorage.getItem(LOCALE_STORAGE_KEY)).toBe("zh-TW")
    expect(document.documentElement.lang).toBe("zh-TW")
    expect(translate("auth.signIn")).toContain("統一身分")
  })

  it("keeps new identity surfaces free of hard-coded CJK display text", () => {
    const files = [
      "../src/pages/RegisterPage.vue",
      "../src/pages/AccountProfilePage.vue",
      "../src/pages/TenantAccountsPage.vue",
      "../src/pages/AccountRecoveryPage.vue",
      "../src/shared/components/LocaleSwitcher.vue",
    ]
    for (const relative of files) {
      const source = readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8")
      expect(source, relative).not.toMatch(/[\u3400-\u9fff]/u)
    }
  })
})
