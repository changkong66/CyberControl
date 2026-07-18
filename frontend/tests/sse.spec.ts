import { describe, expect, it, vi } from "vitest"

import { readSseCursor, SseClient, SseHttpError, type StreamEvent } from "../src/streaming/sse"

function streamResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  })
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } })
}

describe("SseClient", () => {
  it("binds the platform fetch implementation to the global context", async () => {
    const platformFetch = vi.fn(function (this: unknown) {
      expect(this).toBe(globalThis)
      return Promise.resolve(streamResponse([]))
    }) as unknown as typeof fetch
    vi.stubGlobal("fetch", platformFetch)
    const client = new SseClient({
      getTenantId: () => "demo-academy",
      maxRetries: 0,
      sleep: async () => undefined,
    })

    await expect(
      client.run("/internal/topic4/sse", { streamKey: "bound-fetch", onEvent: vi.fn() }),
    ).rejects.toThrow(/reconnect limit/u)
    expect(platformFetch).toHaveBeenCalledOnce()
  })

  it("parses chunked events, heartbeat comments and suppresses duplicates", async () => {
    const heartbeat = vi.fn()
    const events: StreamEvent[] = []
    const client = new SseClient({
      fetcher: vi.fn().mockResolvedValue(
        streamResponse([
          ": ping\n\nid: event-1\nevent: update\ndata: {\"sequence\":1,",
          "\"value\":\"ok\"}\n\nid: event-1\nevent: update\ndata: {\"sequence\":1}\n\n",
        ]),
      ) as typeof fetch,
      getTenantId: () => "demo-academy",
      getAccessToken: () => "token",
      maxRetries: 0,
      sleep: async () => undefined,
    })
    await expect(
      client.run("/internal/topic4/sse", {
        streamKey: "verification",
        onEvent: (event) => events.push(event),
        onHeartbeat: heartbeat,
      }),
    ).rejects.toThrow(/reconnect limit/u)
    expect(events).toHaveLength(1)
    expect(events[0]?.sequence).toBe(1)
    expect(heartbeat).toHaveBeenCalledOnce()
    expect(readSseCursor("demo-academy", "verification").lastEventId).toBe("event-1")
  })

  it("reconnects with Last-Event-ID and resumes from the saved cursor", async () => {
    const controller = new AbortController()
    const requests: Headers[] = []
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      requests.push(new Headers(init?.headers))
      return requests.length === 1
        ? streamResponse(["id: event-10\ndata: {\"sequence\":10}\n\n"])
        : streamResponse(["id: event-11\ndata: {\"sequence\":11}\n\n"])
    }) as typeof fetch
    const events: StreamEvent[] = []
    const client = new SseClient({
      fetcher,
      getTenantId: () => "demo-academy",
      getSessionId: () => "11111111-1111-4111-8111-111111111111",
      sleep: async () => undefined,
      maxRetries: 2,
    })
    await client.run("/internal/topic4/sse", {
      streamKey: "publication",
      signal: controller.signal,
      onEvent: (event) => {
        events.push(event)
        if (event.id === "event-11") controller.abort()
      },
    })
    expect(events.map((event) => event.id)).toEqual(["event-10", "event-11"])
    expect(requests[1]?.get("last-event-id")).toBe("event-10")
    expect(requests[1]?.has("x-tenant-id")).toBe(false)
  })

  it("fails closed on authorization errors", async () => {
    const denied = vi.fn()
    const client = new SseClient({
      fetcher: vi.fn().mockResolvedValue(streamResponse([], 401)) as typeof fetch,
      getTenantId: () => "demo-academy",
      onAuthorizationFailure: denied,
      maxRetries: 0,
    })
    await expect(
      client.run("/internal/topic4/sse", { streamKey: "denied", onEvent: vi.fn() }),
    ).rejects.toBeInstanceOf(SseHttpError)
    expect(denied).toHaveBeenCalledWith(401)
  })

  it("rejects streams without a trusted tenant", async () => {
    const client = new SseClient({ getTenantId: () => null })
    await expect(
      client.run("/internal/topic4/sse", { streamKey: "missing", onEvent: vi.fn() }),
    ).rejects.toThrow(/authenticated tenant/u)
  })

  it("recovers a corrupted cursor and reads nested sequence values", async () => {
    window.sessionStorage.setItem("cybercontrol:sse:demo-academy:nested", "not-json")
    const events: StreamEvent[] = []
    const client = new SseClient({
      fetcher: vi
        .fn()
        .mockResolvedValue(streamResponse(["data: {\"payload\":{\"sequence\":7}}\n\n"])) as typeof fetch,
      getTenantId: () => "demo-academy",
      maxRetries: 0,
      sleep: async () => undefined,
    })
    await expect(
      client.run("/internal/topic4/sse", { streamKey: "nested", onEvent: (event) => events.push(event) }),
    ).rejects.toThrow(/reconnect limit/u)
    expect(events[0]?.sequence).toBe(7)
  })
})
