import Ajv, { type ValidateFunction } from "ajv"

const ajv = new Ajv({ allErrors: true, strict: false })

const topic3Schema = {
  type: "object",
  required: [
    "envelope_id",
    "event_type",
    "message_kind",
    "tenant_id",
    "session_id",
    "subject_ref",
    "correlation_id",
    "sequence",
    "partition_key",
    "producer",
    "delivery",
    "trace_id",
    "created_at",
  ],
  properties: {
    schema_version: { type: "string" },
    envelope_id: { type: "string", minLength: 1 },
    event_type: { type: "string", minLength: 1 },
    message_kind: { type: "string", minLength: 1 },
    tenant_id: { type: "string", minLength: 1 },
    session_id: { type: "string", minLength: 1 },
    subject_ref: { type: "string", minLength: 1 },
    correlation_id: { type: "string", minLength: 1 },
    causation_id: { type: ["string", "null"] },
    sequence: { type: "integer", minimum: 0 },
    partition_key: { type: "string", minLength: 1 },
    producer: { type: "object" },
    delivery: { type: "object" },
    resource: { type: ["object", "null"] },
    trace_id: { type: "string", minLength: 16, maxLength: 64 },
    span_id: { type: ["string", "null"] },
    created_at: { type: "string", minLength: 1 },
    error: { type: ["object", "null"] },
    payload: { type: "object" },
  },
  additionalProperties: true,
}

const topic1Schema = {
  type: "object",
  required: ["request_id", "trace_id", "data"],
  properties: {
    schema_version: { type: "string" },
    request_id: { type: "string", minLength: 1 },
    trace_id: { type: "string", minLength: 16, maxLength: 64 },
    data: { type: "object" },
  },
  additionalProperties: true,
}

const errorSchema = {
  type: "object",
  required: ["error", "trace_id"],
  properties: {
    error: {
      type: "object",
      required: ["error_code", "safe_message"],
      properties: {
        schema_version: { type: "string" },
        error_code: { type: "string" },
        category: { type: "string" },
        severity: { type: "string" },
        retriable: { type: "boolean" },
        safe_message: { type: "string" },
        details_ref: { type: ["object", "null"] },
        occurred_at: { type: "string" },
      },
      additionalProperties: true,
    },
    trace_id: { type: ["string", "null"] },
  },
  additionalProperties: true,
}

const readinessSchema = {
  type: "object",
  required: ["status", "database", "authentication"],
  properties: {
    status: { enum: ["ready", "degraded"] },
    database: { type: "object" },
    authentication: { type: "string" },
    provider_policy_version: { type: "string" },
    enabled_external_providers: { type: "array" },
    task_queue_running: { type: "boolean" },
    message_bus_open: { type: "boolean" },
    outbox_publisher: { type: "string" },
    sse_notification_bridge: { type: "string" },
    config_digest: { type: "string" },
  },
  additionalProperties: true,
}

const validators: Record<string, ValidateFunction> = {
  topic3: ajv.compile(topic3Schema),
  topic1: ajv.compile(topic1Schema),
  error: ajv.compile(errorSchema),
  readiness: ajv.compile(readinessSchema),
}

export type EnvelopeKind = "topic1" | "topic3"

export function assertEnvelope(value: unknown, kind: EnvelopeKind): void {
  const validator = validators[kind]
  if (!validator(value)) {
    throw new Error(`The ${kind} response envelope is invalid.`)
  }
}

export interface ErrorDocument {
  error: { error_code?: string; safe_message?: string }
  trace_id?: string | null
}

export function isErrorDocument(value: unknown): value is ErrorDocument {
  return validators.error(value) === true
}

export function assertReadiness(value: unknown): void {
  if (!validators.readiness(value)) {
    throw new Error("The readiness response contract is invalid.")
  }
}
