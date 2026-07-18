import type { EnvelopeKind } from "./schemas"
import { assertEnvelope, assertReadiness, isErrorDocument } from "./schemas"

const TRACE_PATTERN = /^[a-fA-F0-9]{16,64}$/u
const RESERVED_REQUEST_HEADERS = [
  "authorization",
  "last-event-id",
  "x-permissions",
  "x-role",
  "x-roles",
  "x-scope",
  "x-scopes",
  "x-session-id",
  "x-subject-ref",
  "x-tenant-id",
  "x-trace-id",
] as const

export interface ApiResult<T> {
  data: T
  traceId: string
  response: Response
}

export interface ApiClientOptions {
  baseUrl?: string
  fetcher?: typeof fetch
  getAccessToken?: () => Promise<string | null> | string | null
  getSessionId?: () => string | null
  onAuthorizationFailure?: (status: 401 | 403) => void
}

export interface ApiRequestOptions {
  method?: string
  json?: unknown
  headers?: HeadersInit
  traceId?: string
  envelope?: EnvelopeKind | "none"
  signal?: AbortSignal
}

export class ApiClientError extends Error {
  readonly status: number
  readonly code: string
  readonly traceId: string | null
  readonly details: unknown

  constructor(status: number, code: string, message: string, traceId: string | null, details?: unknown) {
    super(message)
    this.name = "ApiClientError"
    this.status = status
    this.code = code
    this.traceId = traceId
    this.details = details
  }
}

export function createTraceId(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")
}

function safeTraceId(candidate?: string): string {
  return candidate && TRACE_PATTERN.test(candidate) ? candidate : createTraceId()
}

function joinUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//u.test(path)) return path
  return `${baseUrl.replace(/\/$/u, "")}/${path.replace(/^\//u, "")}`
}

function rejectReservedHeaders(headers: Headers): void {
  const reserved = RESERVED_REQUEST_HEADERS.find((name) => headers.has(name))
  if (reserved) {
    throw new TypeError(`The ${reserved} header is managed by the trusted client runtime.`)
  }
}

export class ApiClient {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch
  private readonly getAccessToken: NonNullable<ApiClientOptions["getAccessToken"]>
  private readonly getSessionId: NonNullable<ApiClientOptions["getSessionId"]>
  private readonly onAuthorizationFailure: NonNullable<ApiClientOptions["onAuthorizationFailure"]>

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? ""
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
    this.getAccessToken = options.getAccessToken ?? (() => null)
    this.getSessionId = options.getSessionId ?? (() => null)
    this.onAuthorizationFailure = options.onAuthorizationFailure ?? (() => undefined)
  }

  async request<T>(path: string, options: ApiRequestOptions = {}): Promise<ApiResult<T>> {
    const traceId = safeTraceId(options.traceId)
    const headers = new Headers(options.headers)
    rejectReservedHeaders(headers)
    headers.set("Accept", "application/json")
    headers.set("X-Trace-ID", traceId)
    const sessionId = this.getSessionId()
    if (sessionId) headers.set("X-Session-ID", sessionId)
    const accessToken = await this.getAccessToken()
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`)

    let body: BodyInit | undefined
    if (options.json !== undefined) {
      headers.set("Content-Type", "application/json")
      body = JSON.stringify(options.json)
    }

    const response = await this.fetcher(joinUrl(this.baseUrl, path), {
      method: options.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      signal: options.signal,
    })
    const responseTraceId = response.headers.get("x-trace-id") ?? traceId
    const document = await this.readDocument(response)

    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        this.onAuthorizationFailure(response.status)
      }
      const errorDocument = isErrorDocument(document) ? document : null
      const error = errorDocument?.error as { error_code?: string; safe_message?: string } | undefined
      throw new ApiClientError(
        response.status,
        error?.error_code ?? "HTTP_ERROR",
        error?.safe_message ?? `Request failed with status ${response.status}.`,
        typeof errorDocument?.trace_id === "string" ? errorDocument.trace_id : responseTraceId,
        document,
      )
    }

    if (options.envelope === "topic1" || options.envelope === "topic3") {
      assertEnvelope(document, options.envelope)
    }
    return { data: document as T, traceId: responseTraceId, response }
  }

  requestEnvelope<T>(path: string, options: Omit<ApiRequestOptions, "envelope"> & { envelope?: EnvelopeKind } = {}) {
    return this.request<T>(path, { ...options, envelope: options.envelope ?? "topic3" })
  }

  async readiness(signal?: AbortSignal): Promise<ApiResult<Record<string, unknown>>> {
    const result = await this.request<Record<string, unknown>>("/health/ready", {
      envelope: "none",
      signal,
    })
    assertReadiness(result.data)
    return result
  }

  private async readDocument(response: Response): Promise<unknown> {
    const text = await response.text()
    if (!text) return null
    try {
      return JSON.parse(text) as unknown
    } catch {
      return { raw: text }
    }
  }
}
