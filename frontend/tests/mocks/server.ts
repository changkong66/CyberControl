import { http, HttpResponse } from "msw"
import { setupServer } from "msw/node"

export function topic3Envelope(payload: Record<string, unknown> = {}) {
  return {
    schema_version: "topic3.envelope.v1",
    envelope_id: "00000000-0000-4000-8000-000000000001",
    event_type: "topic4.test.result",
    message_kind: "RESULT",
    tenant_id: "demo-academy",
    session_id: "00000000-0000-4000-8000-000000000002",
    subject_ref: "user:learner",
    correlation_id: "00000000-0000-4000-8000-000000000003",
    causation_id: null,
    sequence: 0,
    partition_key: "demo-academy:test",
    producer: { service: "frontend-test", version: "1.0.0" },
    delivery: { attempt: 1, max_attempts: 3 },
    resource: null,
    trace_id: "a".repeat(32),
    span_id: null,
    created_at: "2026-07-18T00:00:00Z",
    error: null,
    payload,
  }
}

export const server = setupServer(
  http.get("http://localhost/internal/topic1/ping", () => HttpResponse.json(topic3Envelope({ topic: 1 }))),
  http.get("http://localhost/internal/topic2/ping", () => HttpResponse.json(topic3Envelope({ topic: 2 }))),
  http.get("http://localhost/internal/topic3/ping", () => HttpResponse.json(topic3Envelope({ topic: 3 }))),
  http.get("http://localhost/internal/topic4/ping", () => HttpResponse.json(topic3Envelope({ topic: 4 }))),
  http.get("http://localhost/health/ready", () =>
    HttpResponse.json({
      status: "ready",
      database: { status: "up", latency_ms: 2 },
      authentication: "configured",
      provider_policy_version: "local",
      enabled_external_providers: [],
      task_queue_running: true,
      message_bus_open: true,
      outbox_publisher: "healthy",
      sse_notification_bridge: "connected",
      config_digest: "b".repeat(64),
    }),
  ),
)
