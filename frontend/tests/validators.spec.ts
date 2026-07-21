import { readFileSync } from "node:fs"
import path from "node:path"

import { describe, expect, it } from "vitest"

import {
  assertEnvelope,
  assertIdentityContract,
  assertReadiness,
  isErrorDocument,
} from "../src/api/schemas"

describe("standalone contract validators", () => {
  it("contains no runtime code generation forbidden by the production CSP", () => {
    const generated = readFileSync(
      path.join(process.cwd(), "src", "api", "generated", "validators.js"),
      "utf8",
    )
    const facade = readFileSync(path.join(process.cwd(), "src", "api", "schemas.ts"), "utf8")

    expect(generated).not.toMatch(/\beval\s*\(/u)
    expect(generated).not.toMatch(/\bnew\s+Function\s*\(/u)
    expect(generated).not.toMatch(/\brequire\s*\(/u)
    expect(facade).not.toContain('from "ajv"')
    expect(facade).not.toMatch(/\bnew\s+Ajv\b/u)
  })

  it("preserves envelope, readiness, and error fail-closed behavior", () => {
    expect(() =>
      assertEnvelope(
        { request_id: "request-1", trace_id: "a".repeat(32), data: {} },
        "topic1",
      ),
    ).not.toThrow()
    expect(() => assertEnvelope({ request_id: "request-1", data: {} }, "topic1")).toThrow(
      /response envelope is invalid/u,
    )

    expect(() =>
      assertReadiness({ status: "ready", database: {}, authentication: "oidc" }),
    ).not.toThrow()
    expect(() => assertReadiness({ status: "ready" })).toThrow(/readiness response/u)
    expect(
      isErrorDocument({
        error: { error_code: "LIYAN-TEST", safe_message: "Rejected" },
        trace_id: "b".repeat(32),
      }),
    ).toBe(true)
    expect(isErrorDocument({ error: { error_code: "LIYAN-TEST" }, trace_id: null })).toBe(false)
  })

  it("uses the frozen identity schema and serialized custom formats", () => {
    expect(() =>
      assertIdentityContract(
        {
          schema_version: "verification-challenge.verify.v1",
          challenge_id: "33333333-3333-4333-8333-333333333333",
          code: "123456",
          invitation_token: null,
        },
        "challengeVerify",
      ),
    ).not.toThrow()
    expect(() =>
      assertIdentityContract(
        {
          schema_version: "verification-challenge.verify.v1",
          challenge_id: "not-a-uuid",
          code: "123456",
          invitation_token: null,
        },
        "challengeVerify",
      ),
    ).toThrow(/identity challengeVerify contract is invalid/u)
  })
})
