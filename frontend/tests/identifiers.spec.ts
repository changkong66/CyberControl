import { describe, expect, it } from "vitest"

import { uuidV5 } from "../src/shared/identifiers"

describe("trusted identifier projection", () => {
  it("matches the frozen Topic4 UUIDv5 derivation", async () => {
    await expect(
      uuidV5(
        "12345678-1234-5678-1234-567812345678",
        `topic4-verification:1:${"a".repeat(64)}`,
      ),
    ).resolves.toBe("5e6b9241-dd2a-556c-a424-5e393b489b64")
  })

  it("rejects non-UUID candidate namespaces", async () => {
    await expect(uuidV5("candidate-1", "topic4-verification:1:test")).rejects.toThrow(/valid UUID/u)
  })
})
