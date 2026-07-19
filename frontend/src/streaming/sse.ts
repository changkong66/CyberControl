import { createParser, type EventSourceMessage } from "eventsource-parser"

import { clearAllTenantCaches } from "../shared/cache"
import { createTraceId } from "../api/client"

interface CursorState {
  lastEventId: string | null
  sequence: number
  seenIds: string[]
}

export interface StreamEvent<T = unknown> {
  id: string | null
  eventType: string
  data: T
  sequence: number | null
}

export interface SseClientOptions {
  baseUrl?: string
  fetcher?: typeof fetch
  getAccessToken?: () => Promise<string | null> | string | null
  getSessionId?: () => string | null
  getTenantId?: () => string | null
  onAuthorizationFailure?: (status: 401 | 403) => void
  sleep?: (milliseconds: number) => Promise<void>
  maxRetries?: number
}

export interface SseRunOptions<T> {
  streamKey: string
  onEvent: (event: StreamEvent<T>) => void
  onHeartbeat?: () => void
  onError?: (error: unknown) => void
  signal?: AbortSignal
  maxRetries?: number
}

export class SseHttpError extends Error {
  constructor(readonly status: number) {
    super(`SSE request failed with status ${status}.`)
    this.name = "SseHttpError"
  }
}

function cursorKey(tenantId: string, streamKey: string): string {
  return `cybercontrol:sse:${encodeURIComponent(tenantId)}:${encodeURIComponent(streamKey)}`
}

function loadCursor(tenantId: string, streamKey: string): CursorState {
  const raw = window.sessionStorage.getItem(cursorKey(tenantId, streamKey))
  if (!raw) return { lastEventId: null, sequence: -1, seenIds: [] }
  try {
    const parsed = JSON.parse(raw) as Partial<CursorState>
    return {
      lastEventId: typeof parsed.lastEventId === "string" ? parsed.lastEventId : null,
      sequence: typeof parsed.sequence === "number" ? parsed.sequence : -1,
      seenIds: Array.isArray(parsed.seenIds)
        ? parsed.seenIds.filter((value): value is string => typeof value === "string").slice(-500)
        : [],
    }
  } catch {
    window.sessionStorage.removeItem(cursorKey(tenantId, streamKey))
    return { lastEventId: null, sequence: -1, seenIds: [] }
  }
}

function saveCursor(tenantId: string, streamKey: string, cursor: CursorState): void {
  window.sessionStorage.setItem(cursorKey(tenantId, streamKey), JSON.stringify(cursor))
}

function streamUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//u.test(path)) return path
  return `${baseUrl.replace(/\/$/u, "")}/${path.replace(/^\//u, "")}`
}

function eventSequence(data: unknown): number | null {
  if (!data || typeof data !== "object") return null
  const record = data as Record<string, unknown>
  if (typeof record.sequence === "number") return record.sequence
  const payload = record.payload
  if (payload && typeof payload === "object" && typeof (payload as Record<string, unknown>).sequence === "number") {
    return (payload as Record<string, number>).sequence
  }
  return null
}

export class SseClient {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch
  private readonly getAccessToken: NonNullable<SseClientOptions["getAccessToken"]>
  private readonly getSessionId: NonNullable<SseClientOptions["getSessionId"]>
  private readonly getTenantId: NonNullable<SseClientOptions["getTenantId"]>
  private readonly onAuthorizationFailure: NonNullable<SseClientOptions["onAuthorizationFailure"]>
  private readonly sleep: NonNullable<SseClientOptions["sleep"]>
  private readonly maxRetries: number

  constructor(options: SseClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? ""
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
    this.getAccessToken = options.getAccessToken ?? (() => null)
    this.getSessionId = options.getSessionId ?? (() => null)
    this.getTenantId = options.getTenantId ?? (() => null)
    this.onAuthorizationFailure = options.onAuthorizationFailure ?? ((status) => {
      if (status === 401 || status === 403) clearAllTenantCaches()
    })
    this.sleep = options.sleep ?? ((milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds)))
    this.maxRetries = options.maxRetries ?? Number.POSITIVE_INFINITY
  }

  async run<T>(path: string, options: SseRunOptions<T>): Promise<void> {
    const tenantId = this.getTenantId()
    if (!tenantId) throw new Error("An authenticated tenant is required for SSE streams.")
    const cursor = loadCursor(tenantId, options.streamKey)
    let retries = 0
    let retryAfter = 500
    const maxRetries = options.maxRetries ?? this.maxRetries

    while (!options.signal?.aborted) {
      try {
        retryAfter = await this.consumeOnce(path, tenantId, options.streamKey, cursor, options)
        retries = 0
      } catch (error) {
        if (error instanceof SseHttpError && (error.status === 401 || error.status === 403)) throw error
        options.onError?.(error)
      }
      if (options.signal?.aborted) return
      retries += 1
      if (retries > maxRetries) throw new Error("SSE reconnect limit exceeded.")
      await this.sleep(Math.min(retryAfter * 2 ** Math.min(retries - 1, 5), 30_000))
    }
  }

  private async consumeOnce<T>(
    path: string,
    tenantId: string,
    streamKey: string,
    cursor: CursorState,
    options: SseRunOptions<T>,
  ): Promise<number> {
    const headers = new Headers({
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Trace-ID": createTraceId(),
    })
    const accessToken = await this.getAccessToken()
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`)
    const sessionId = this.getSessionId()
    if (sessionId) headers.set("X-Session-ID", sessionId)
    if (cursor.lastEventId) headers.set("Last-Event-ID", cursor.lastEventId)

    const response = await this.fetcher(streamUrl(this.baseUrl, path), {
      method: "GET",
      headers,
      signal: options.signal,
    })
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) this.onAuthorizationFailure(response.status)
      throw new SseHttpError(response.status)
    }
    if (!response.body) throw new Error("The SSE response has no readable body.")

    let retryAfter = 500
    let parseError: unknown = null
    const parser = createParser({
      onRetry: (milliseconds) => {
        retryAfter = milliseconds
      },
      onComment: () => options.onHeartbeat?.(),
      onError: (error) => {
        parseError = error
      },
      onEvent: (message: EventSourceMessage) => {
        if (!message.data) return
        let data: T
        try {
          data = JSON.parse(message.data) as T
        } catch (error) {
          parseError = error
          return
        }
        const id = message.id ?? null
        const sequence = eventSequence(data)
        if (id && cursor.seenIds.includes(id)) return
        if (!id && sequence !== null && sequence <= cursor.sequence) return
        if (id) cursor.seenIds = [...cursor.seenIds, id].slice(-500)
        if (sequence !== null) cursor.sequence = Math.max(cursor.sequence, sequence)
        cursor.lastEventId = id ?? cursor.lastEventId
        saveCursor(tenantId, streamKey, cursor)
        options.onEvent({ id, eventType: message.event ?? "message", data, sequence })
      },
    })
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    try {
      while (!options.signal?.aborted) {
        const chunk = await reader.read()
        if (chunk.done) break
        parser.feed(decoder.decode(chunk.value, { stream: true }))
      }
      parser.feed(decoder.decode())
    } finally {
      reader.releaseLock()
    }
    if (parseError) throw parseError
    return retryAfter
  }
}

export function readSseCursor(tenantId: string, streamKey: string): CursorState {
  return loadCursor(tenantId, streamKey)
}
