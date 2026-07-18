import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { ApiClient, ApiClientError } from "../src/api/client"
import { server, topic3Envelope } from "./mocks/server"

describe("ApiClient", () => {
  it("binds the platform fetch implementation to the global context", async () => {
    const platformFetch = vi.fn(function (this: unknown) {
      expect(this).toBe(globalThis)
      return Promise.resolve(HttpResponse.json(topic3Envelope()))
    }) as unknown as typeof fetch
    vi.stubGlobal("fetch", platformFetch)

    await new ApiClient().requestEnvelope("/internal/topic4/ping")
    expect(platformFetch).toHaveBeenCalledOnce()
  })

  it("validates MSW responses for Topic1 through Topic4", async () => {
    const client = new ApiClient({ baseUrl: "http://localhost", getAccessToken: () => "token" })
    for (const topic of [1, 2, 3, 4]) {
      const result = await client.requestEnvelope<{ payload: { topic: number } }>(
        `/internal/topic${topic}/ping`,
      )
      expect(result.data.payload.topic).toBe(topic)
    }
  })

  it("sends only approved identity-adjacent headers", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      expect(headers.get("authorization")).toBe("Bearer token")
      expect(headers.get("x-trace-id")).toMatch(/^[a-f0-9]{32}$/u)
      expect(headers.get("x-session-id")).toBe("11111111-1111-4111-8111-111111111111")
      expect(headers.has("x-tenant-id")).toBe(false)
      expect(headers.has("x-subject-ref")).toBe(false)
      expect(headers.has("x-roles")).toBe(false)
      return HttpResponse.json(topic3Envelope())
    }) as typeof fetch
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => "token",
      getSessionId: () => "11111111-1111-4111-8111-111111111111",
    })
    await client.requestEnvelope("/internal/topic4/ping")
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it.each(["Authorization", "X-Tenant-ID", "X-Subject-Ref", "X-Roles", "X-Scopes", "X-Session-ID"])(
    "rejects caller-controlled reserved header %s",
    async (header) => {
      const fetcher = vi.fn() as unknown as typeof fetch
      const client = new ApiClient({ fetcher })
      await expect(
        client.request("/internal/topic4/ping", {
          envelope: "none",
          headers: { [header]: "untrusted" },
        }),
      ).rejects.toThrow(/managed by the trusted client runtime/u)
      expect(fetcher).not.toHaveBeenCalled()
    },
  )

  it("maps safe error receipts and clears identity state on 401 and 403", async () => {
    const onAuthorizationFailure = vi.fn()
    server.use(
      http.get("http://localhost/internal/topic4/protected", () =>
        HttpResponse.json(
          {
            error: { error_code: "AUTH_FORBIDDEN", safe_message: "Access denied." },
            trace_id: "c".repeat(32),
          },
          { status: 403 },
        ),
      ),
    )
    const client = new ApiClient({ baseUrl: "http://localhost", onAuthorizationFailure })
    await expect(client.requestEnvelope("/internal/topic4/protected")).rejects.toMatchObject({
      status: 403,
      code: "AUTH_FORBIDDEN",
      traceId: "c".repeat(32),
    } satisfies Partial<ApiClientError>)
    expect(onAuthorizationFailure).toHaveBeenCalledWith(403)
  })

  it("rejects malformed successful envelopes", async () => {
    server.use(http.get("http://localhost/internal/topic4/malformed", () => HttpResponse.json({ ok: true })))
    const client = new ApiClient({ baseUrl: "http://localhost" })
    await expect(client.requestEnvelope("/internal/topic4/malformed")).rejects.toThrow(
      /response envelope is invalid/u,
    )
  })

  it("validates readiness and exposes the server trace ID", async () => {
    server.use(
      http.get("http://localhost/health/ready", () =>
        HttpResponse.json(
          { status: "ready", database: { status: "up" }, authentication: "configured" },
          { headers: { "X-Trace-ID": "d".repeat(32) } },
        ),
      ),
    )
    const result = await new ApiClient({ baseUrl: "http://localhost" }).readiness()
    expect(result.traceId).toBe("d".repeat(32))
    expect(result.data.status).toBe("ready")
  })

  it("supports Topic1 envelopes and preserves a valid caller trace ID", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("x-trace-id")).toBe("f".repeat(32))
      return new Response(
        JSON.stringify({
          schema_version: "topic1.api-envelope.v1",
          request_id: "request-1",
          trace_id: "f".repeat(32),
          data: {},
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      )
    }) as typeof fetch
    await new ApiClient({ fetcher }).requestEnvelope("https://api.example.invalid/topic1", {
      envelope: "topic1",
      traceId: "f".repeat(32),
    })
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it("handles empty and non-JSON platform responses without inventing an envelope", async () => {
    const responses = [
      new Response(null, { status: 204 }),
      new Response("not-json", { status: 200, headers: { "Content-Type": "text/plain" } }),
    ]
    const client = new ApiClient({
      fetcher: vi.fn().mockImplementation(async () => responses.shift() as Response) as typeof fetch,
    })
    expect((await client.request("/empty", { envelope: "none" })).data).toBeNull()
    expect((await client.request<{ raw: string }>("/text", { envelope: "none" })).data.raw).toBe(
      "not-json",
    )
  })

  it("falls back to a generic safe HTTP error for malformed error bodies", async () => {
    const client = new ApiClient({
      fetcher: vi.fn().mockResolvedValue(new Response("failure", { status: 500 })) as typeof fetch,
    })
    await expect(client.requestEnvelope("/failure")).rejects.toMatchObject({
      status: 500,
      code: "HTTP_ERROR",
    })
  })
})
