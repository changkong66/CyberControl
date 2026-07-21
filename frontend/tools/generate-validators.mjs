import { createHash } from "node:crypto"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"

import Ajv from "ajv"
import standaloneCode from "ajv/dist/standalone/index.js"

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const repositoryRoot = path.resolve(frontendRoot, "..")
const outputDirectory = path.join(frontendRoot, "src", "api", "generated")
const javascriptOutput = path.join(outputDirectory, "validators.js")
const declarationOutput = path.join(outputDirectory, "validators.d.ts")
const checkOnly = process.argv.includes("--check")

const schemaFiles = [
  ["validateIdentityEnvelope", "identity.api-envelope.v1.schema.json"],
  ["validateAccountAdmin", "account.admin-view.v1.schema.json"],
  ["validateAccountProfile", "account.profile.v1.schema.json"],
  ["validateIdentityAuditEntry", "identity.audit-entry.v1.schema.json"],
  ["validateRegistrationReceipt", "registration.receipt.v1.schema.json"],
  ["validateRegistrationStatus", "registration.status.v1.schema.json"],
  ["validateRegisterEmail", "user-register-by-email.command.v1.schema.json"],
  ["validateRegisterPhone", "user-register-by-phone.command.v1.schema.json"],
  ["validateChallengeReceipt", "verification-challenge.receipt.v1.schema.json"],
  ["validateChallengeRequest", "verification-challenge.request.v1.schema.json"],
  ["validateChallengeVerify", "verification-challenge.verify.v1.schema.json"],
]

const inlineSchemas = [
  [
    "validateTopic3",
    {
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
    },
  ],
  [
    "validateTopic1",
    {
      type: "object",
      required: ["request_id", "trace_id", "data"],
      properties: {
        schema_version: { type: "string" },
        request_id: { type: "string", minLength: 1 },
        trace_id: { type: "string", minLength: 16, maxLength: 64 },
        data: { type: "object" },
      },
      additionalProperties: true,
    },
  ],
  [
    "validateErrorDocument",
    {
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
    },
  ],
  [
    "validateReadiness",
    {
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
    },
  ],
]

const definitions = []
for (const [exportName, fileName] of schemaFiles) {
  const relativePath = `schemas/${fileName}`
  const source = await readFile(path.join(repositoryRoot, "schemas", fileName), "utf8")
  definitions.push({ exportName, schema: JSON.parse(source), source: `${relativePath}\0${source}` })
}
for (const [exportName, schema] of inlineSchemas) {
  definitions.push({ exportName, schema, source: `inline:${exportName}\0${JSON.stringify(schema)}` })
}

const sourceDigest = createHash("sha256")
  .update(definitions.map(({ source }) => source).join("\0"))
  .digest("hex")

const ajv = new Ajv({
  allErrors: true,
  strict: false,
  code: { source: true, esm: true, lines: true },
})
ajv.addFormat("uuid", /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu)
ajv.addFormat(
  "date-time",
  /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/u,
)
ajv.addFormat("password", /^[\s\S]*$/u)

const exportsBySchemaId = {}
for (const definition of definitions) {
  const schemaId = `urn:cybercontrol:frontend:${definition.exportName}`
  ajv.addSchema({ ...definition.schema, $id: schemaId }, schemaId)
  exportsBySchemaId[definition.exportName] = schemaId
}

const banner = `// Generated by tools/generate-validators.mjs. Do not edit.\n// Source SHA-256: ${sourceDigest}\n`
const standaloneJavascript = standaloneCode(ajv, exportsBySchemaId).replace(
  /^const ([A-Za-z_$][\w$]*) = require\("([^"]+)"\)\.default;$/gmu,
  (_match, identifier, moduleName) =>
    `import ${identifier} from "${moduleName.endsWith(".js") ? moduleName : `${moduleName}.js`}";`,
)
if (/\brequire\s*\(/u.test(standaloneJavascript)) {
  throw new Error("AJV standalone output contains an unsupported CommonJS runtime dependency.")
}
const javascript = `${banner}${standaloneJavascript.trimEnd()}\n`
const declarations = `${banner}export interface GeneratedValidator {\n  (value: unknown): boolean\n  errors?: ReadonlyArray<Record<string, unknown>> | null\n}\n\n${definitions
  .map(({ exportName }) => `export declare const ${exportName}: GeneratedValidator`)
  .join("\n")}\n`

async function emit(filePath, expected) {
  if (!checkOnly) {
    await mkdir(path.dirname(filePath), { recursive: true })
    await writeFile(filePath, expected, "utf8")
    return true
  }

  let actual = null
  try {
    actual = await readFile(filePath, "utf8")
  } catch {
    // A missing generated file is reported as drift below.
  }
  if (actual === expected) return true
  console.error(`Generated validator drift detected: ${path.relative(repositoryRoot, filePath)}`)
  return false
}

const results = await Promise.all([
  emit(javascriptOutput, javascript),
  emit(declarationOutput, declarations),
])
if (results.every(Boolean)) {
  console.log(checkOnly ? "Generated validators are current." : "Generated validators updated.")
} else {
  console.error("Run `pnpm run generate:validators` and commit the generated files.")
  process.exitCode = 1
}
