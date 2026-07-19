import type {
  AggregationResultV1,
  CandidateV1,
  ClaimRiskV1,
  ClaimV1,
  ClaimVerdictV1,
  EvidenceRefV1,
  HumanReviewTaskV1,
  ModuleDispatchPlanV1,
  ModuleRunResultV1,
  ModuleRunV1,
  ReleaseAuthorizationPayloadV1,
  RevisionPatchV1,
  RevisionRequestV1,
  Topic1CourseV1,
  Topic1GraphContentV1,
  Topic1GraphSnapshotV1,
  Topic2AgentContextV1,
  Topic2LearningPathRecordV1,
  Topic2MemoryStateV1,
  Topic2StudentProfileV1,
  Topic3AgentTaskSnapshotV1,
  Topic3ExecutionBlueprintV1,
  Topic3GenerationSessionV1,
  Topic3EnvelopeV1,
  VerificationAcceptedPayloadV1,
  VerificationReportV1,
  VerificationStateChangedPayloadV1,
} from "@liyans/contracts"

export type JsonObject = Record<string, unknown>

export interface Topic3PayloadEnvelope<T> extends Omit<Topic3EnvelopeV1, "payload"> {
  payload: T
}

export interface Topic1DataEnvelope<T> {
  schema_version?: "topic1.api-envelope.v1"
  request_id: string
  trace_id: string
  data: T
}

export interface CourseGraphView extends Topic1GraphContentV1 {}

export interface GenerationView {
  session: Topic3GenerationSessionV1 & { result?: JsonObject | null }
  blueprint: Topic3ExecutionBlueprintV1
  tasks: Topic3AgentTaskSnapshotV1[]
  candidates: CandidateV1[]
}

export interface VerificationSnapshot {
  verification: VerificationAcceptedPayloadV1
  state: VerificationStateChangedPayloadV1
  claims: ClaimV1[]
  risks: ClaimRiskV1[]
  dispatch_plan: ModuleDispatchPlanV1 | null
  module_runs: ModuleRunV1[]
  module_results: ModuleRunResultV1[]
  claim_verdicts: ClaimVerdictV1[]
  aggregation: AggregationResultV1 | null
  report: VerificationReportV1 | null
  review_task: HumanReviewTaskV1 | null
}

export interface VerificationTraceView {
  trace_id: string
  tenant_id: string
  records: JsonObject[]
  record_count: number
}

export interface RevisionHistoryItem extends JsonObject {
  revision_cycle_id?: string
  verification_id?: string
  revision_round?: number
  state?: string
  candidate_id?: string
  base_candidate_version?: number
  base_candidate_sha256?: string
  created_at?: string
}

export interface PublicationHistoryItem extends JsonObject {
  table?: string
  record_id?: string
  trace_id?: string
  record_sha256?: string
  created_at?: string
  document?: JsonObject | null
}

export interface Topic4HealthView {
  ready: boolean
  verification_task_registered: boolean
  local_rag: string
  external_embedding: string
  release_isolation: string
}

export interface ReviewDecisionInput {
  review_task_id: string
  decision: "APPROVE" | "APPROVE_WITH_DISCLOSURE" | "REVISE" | "BLOCK"
  rationale: string
  disclosure_codes: string[]
  waived_finding_ids: string[]
  expected_task_version: number
  expected_state_version: number
}

export interface ReviewDecisionResult {
  decision: JsonObject
  review_task: HumanReviewTaskV1
  state: JsonObject
}

export interface ReleaseDerivationInput {
  verification_id: string
  requested_release_mode: "FULL" | "FULL_WITH_DISCLOSURE"
  requested_block_ids: string[]
  ttl_seconds: number
}

export interface ReleaseCommitResult {
  batch: JsonObject
  public_event: JsonObject
  public_artifact: JsonObject
  state: "RELEASED"
}

export interface Topic3GenerationInput {
  operation_id: string
  generation_session_id: string
  learner_ref: string
  course_id: string
  target_kp_ids: string[]
  requested_resources: Array<
    "Lecturer_Doc" | "MindMap" | "Gradient_Quiz" | "Simulation_Code" | "Extension_Material"
  >
  lecturer_depth?: "FOUNDATION" | "EXAM_FOCUS" | "POSTGRADUATE" | "ENGINEERING"
  learning_goal: string
  locale?: "zh-CN" | "en-US"
  max_parallelism?: number
  allow_partial?: boolean
  requested_at: string
}

export interface VerificationLaunchPayload extends JsonObject {
  verification_id: string
  idempotency_key: string
}

export interface RevisionCommandInput {
  request: RevisionRequestV1
  patches: RevisionPatchV1[]
  prompt_bundle_version: string
}

export interface ClaimDetailView {
  claim: ClaimV1
  risk?: ClaimRiskV1
  verdict?: ClaimVerdictV1
  evidence: EvidenceRefV1[]
}

export interface LearnerContext {
  learnerRef: string
  courseId: string
  profile: Topic2StudentProfileV1 | null
  memoryStates: Topic2MemoryStateV1[]
  learningPath: Topic2LearningPathRecordV1 | null
  agentContext: Topic2AgentContextV1 | null
}

export function isRecord(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function requireRecord(value: unknown, label: string): JsonObject {
  if (!isRecord(value)) throw new Error(`${label} response is not an object.`)
  return value
}

export function requirePayload<T>(value: unknown, label: string): T {
  const envelope = requireRecord(value, label)
  if (!("payload" in envelope)) throw new Error(`${label} response has no payload.`)
  return envelope.payload as T
}

export function requireData<T>(value: unknown, label: string): T {
  const envelope = requireRecord(value, label)
  if (!("data" in envelope)) throw new Error(`${label} response has no data.`)
  return envelope.data as T
}

export function queryString(parameters: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams()
  Object.entries(parameters).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value))
  })
  const encoded = query.toString()
  return encoded ? `?${encoded}` : ""
}

export function newIdempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`
}
