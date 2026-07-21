import { config } from "@vue/test-utils"
import { afterEach, beforeAll, beforeEach, afterAll, vi } from "vitest"

import { i18n, setAppLocale } from "../src/i18n"
import { server } from "./mocks/server"

config.global.plugins = [i18n]

if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.open = true
  }
}
if (!HTMLDialogElement.prototype.close) {
  HTMLDialogElement.prototype.close = function close() {
    this.open = false
  }
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }))
beforeEach(() => setAppLocale("zh-CN"))

afterEach(() => {
  server.resetHandlers()
  window.sessionStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

afterAll(() => server.close())
