import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import ConfirmDialog from "../src/shared/components/ConfirmDialog.vue"
import ErrorState from "../src/shared/components/ErrorState.vue"
import MarkdownPreview from "../src/shared/components/MarkdownPreview.vue"
import LoadingState from "../src/shared/components/LoadingState.vue"
import PlaceholderPage from "../src/pages/PlaceholderPage.vue"
import ProgressBar from "../src/shared/components/ProgressBar.vue"
import RiskBadge from "../src/shared/components/RiskBadge.vue"
import StatusBadge from "../src/shared/components/StatusBadge.vue"

describe("shared interface states", () => {
  it("renders stable loading and empty states", () => {
    expect(mount(LoadingState, { props: { label: "正在检查" } }).text()).toContain("正在检查")
    const placeholder = mount(PlaceholderPage, {
      props: { title: "可信核验", status: "暂无核验记录" },
    })
    expect(placeholder.text()).toContain("可信核验")
    expect(placeholder.text()).toContain("暂无核验记录")
  })

  it("emits retry from error state", async () => {
    const wrapper = mount(ErrorState, { props: { message: "请求失败", retryable: true } })
    await wrapper.get("button").trigger("click")
    expect(wrapper.emitted("retry")).toHaveLength(1)
  })

  it("uses a modal confirmation contract", async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { open: true, title: "确认发布", message: "发布后不可撤回。" },
    })
    await wrapper.vm.$nextTick()
    expect((wrapper.get("dialog").element as HTMLDialogElement).open).toBe(true)
    await wrapper.findAll("button")[1]?.trigger("click")
    expect(wrapper.emitted("confirm")).toHaveLength(1)
  })

  it("renders trusted status controls without inventing values", () => {
    expect(mount(RiskBadge, { props: { level: "HIGH" } }).text()).toContain("高风险")
    expect(mount(StatusBadge, { props: { value: "RELEASED" } }).text()).toContain("RELEASED")
    expect(mount(ProgressBar, { props: { value: 42, label: "核验" } }).get('[role="progressbar"]').attributes("aria-valuenow")).toBe("42")
    expect(mount(MarkdownPreview, { props: { source: "# 标题\n\n- 证据" } }).text()).toContain("标题")
  })
})
