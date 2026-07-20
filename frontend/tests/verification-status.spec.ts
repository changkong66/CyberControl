import { describe, expect, it } from "vitest"

import {
  verificationMatrixState,
  type VerificationMatrixSnapshot,
} from "../src/pages/verification-status"

function snapshot(
  overrides: Partial<VerificationMatrixSnapshot> = {},
): VerificationMatrixSnapshot {
  return {
    state: { current_state: "RELEASED" },
    dispatch_plan: { items: [] },
    module_runs: [],
    module_results: [],
    report: { decision: "RELEASE" },
    ...overrides,
  }
}

describe("verification matrix status", () => {
  it("marks modules omitted from a terminal report plan as not required", () => {
    const terminal = snapshot({
      dispatch_plan: { items: [{ module: "C2_RAG" }, { module: "C3_ACADEMIC" }] },
      module_results: [{ module: "C2_RAG" }],
    })

    expect(verificationMatrixState({ code: "C2", module: "C2_RAG" }, terminal, 0)).toBe(
      "SUCCEEDED",
    )
    expect(
      verificationMatrixState({ code: "C4", module: "C4_GRAPH" }, terminal, 0),
    ).toBe("NOT_REQUIRED")
  })

  it("does not hide planned work or an active module run", () => {
    const active = snapshot({
      state: { current_state: "VERIFYING" },
      report: null,
      dispatch_plan: { items: [{ module: "C4_GRAPH" }] },
      module_runs: [{ module: "C4_GRAPH", state: "RUNNING" }],
    })
    const plannedWithoutRun = snapshot({
      dispatch_plan: { items: [{ module: "C5_QUIZ" }] },
    })

    expect(verificationMatrixState({ code: "C4", module: "C4_GRAPH" }, active, 0)).toBe(
      "RUNNING",
    )
    expect(
      verificationMatrixState({ code: "C5", module: "C5_QUIZ" }, plannedWithoutRun, 0),
    ).toBe("PENDING")
  })

  it("distinguishes optional revision and release stages", () => {
    expect(verificationMatrixState({ code: "C8" }, snapshot(), 0)).toBe("NOT_REQUIRED")
    expect(verificationMatrixState({ code: "C8" }, snapshot(), 1)).toBe("SUCCEEDED")
    expect(
      verificationMatrixState(
        { code: "C8" },
        snapshot({ state: { current_state: "REVISION_WAITING" }, report: null }),
        0,
      ),
    ).toBe("RUNNING")

    expect(
      verificationMatrixState(
        { code: "C12" },
        snapshot({ state: { current_state: "RELEASE_PENDING" } }),
        0,
      ),
    ).toBe("RUNNING")
    expect(verificationMatrixState({ code: "C12" }, snapshot(), 0)).toBe("SUCCEEDED")
    expect(
      verificationMatrixState(
        { code: "C12" },
        snapshot({ state: { current_state: "BLOCKED" }, report: { decision: "BLOCK" } }),
        0,
      ),
    ).toBe("NOT_REQUIRED")
  })

  it("keeps unknown pre-report modules pending", () => {
    expect(
      verificationMatrixState(
        { code: "C7", module: "C7_EXTENSION" },
        snapshot({ state: { current_state: "VERIFYING" }, report: null }),
        0,
      ),
    ).toBe("PENDING")
    expect(verificationMatrixState({ code: "C7", module: "C7_EXTENSION" }, null, 0)).toBe(
      "PENDING",
    )
  })
})
