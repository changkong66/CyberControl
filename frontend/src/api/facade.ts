import type {
  CandidateV1,
  ClaimV1,
  EvidenceRefV1,
  HumanReviewTaskV1,
  ReleaseAuthorizationPayloadV1,
  Topic1CourseV1,
  Topic1GraphContentV1,
  Topic1GraphSnapshotV1,
  Topic2AgentContextV1,
  Topic2LearningPathRecordV1,
  Topic2MemoryStateV1,
  Topic2StudentProfileV1,
  Topic3EnvelopeV1,
  VerificationReportV1,
} from "@liyans/contracts"

import { type ApiClient, type ApiResult } from "./client"
import {
  type CourseGraphView,
  type GenerationView,
  type JsonObject,
  type PublicationHistoryItem,
  type ReleaseCommitResult,
  type ReleaseDerivationInput,
  type RevisionCommandInput,
  type RevisionHistoryItem,
  type ReviewDecisionInput,
  type ReviewDecisionResult,
  type Topic3GenerationInput,
  type Topic4HealthView,
  type VerificationSnapshot,
  type VerificationTraceView,
  newIdempotencyKey,
  queryString,
  requireData,
  requirePayload,
} from "./types"

export class WorkbenchApi {
  constructor(private readonly client: ApiClient) {}

  private async topic1<T>(path: string, options: Parameters<ApiClient["request"]>[1] = {}): Promise<ApiResult<T>> {
    const result = await this.client.request<unknown>(path, { ...options, envelope: "topic1" })
    return { ...result, data: requireData<T>(result.data, "Topic 1") }
  }

  private async topic3<T>(path: string, options: Parameters<ApiClient["request"]>[1] = {}): Promise<ApiResult<T>> {
    const result = await this.client.request<unknown>(path, { ...options, envelope: "topic3" })
    return { ...result, data: requirePayload<T>(result.data, "Topic 3") }
  }

  async listCourses(): Promise<ApiResult<Topic1CourseV1[]>> {
    const result = await this.topic1<{ courses: Topic1CourseV1[] }>("/internal/topic1/courses")
    return { ...result, data: result.data.courses }
  }

  async getCourseGraph(courseId: string): Promise<ApiResult<CourseGraphView>> {
    const result = await this.topic1<{ graph: Topic1GraphContentV1 }>(
      `/internal/topic1/courses/${encodeURIComponent(courseId)}/graph`,
    )
    return { ...result, data: result.data.graph }
  }

  async listGraphSnapshots(courseId: string): Promise<ApiResult<Topic1GraphSnapshotV1[]>> {
    const result = await this.topic1<{ snapshots: Topic1GraphSnapshotV1[] }>(
      `/internal/topic1/courses/${encodeURIComponent(courseId)}/snapshots`,
    )
    return { ...result, data: result.data.snapshots }
  }

  async getLatestProfile(learnerRef: string, courseId: string): Promise<ApiResult<Topic2StudentProfileV1>> {
    const result = await this.topic3<{ profile: Topic2StudentProfileV1 }>(
      `/internal/topic2/learners/${encodeURIComponent(learnerRef)}/courses/${encodeURIComponent(courseId)}/profiles/latest`,
    )
    return { ...result, data: result.data.profile }
  }

  async getProfileHistory(learnerRef: string, courseId: string): Promise<ApiResult<Topic2StudentProfileV1[]>> {
    const result = await this.topic3<{ profiles: Topic2StudentProfileV1[] }>(
      `/internal/topic2/learners/${encodeURIComponent(learnerRef)}/courses/${encodeURIComponent(courseId)}/profiles`,
    )
    return { ...result, data: result.data.profiles }
  }

  async getMemoryStates(learnerRef: string, courseId: string): Promise<ApiResult<Topic2MemoryStateV1[]>> {
    const result = await this.topic3<{ memory_states: Topic2MemoryStateV1[] }>(
      `/internal/topic2/learners/${encodeURIComponent(learnerRef)}/courses/${encodeURIComponent(courseId)}/memory`,
    )
    return { ...result, data: result.data.memory_states }
  }

  async getLearningPath(learnerRef: string, courseId: string): Promise<ApiResult<Topic2LearningPathRecordV1>> {
    const result = await this.topic3<{ learning_path: Topic2LearningPathRecordV1 }>(
      `/internal/topic2/learners/${encodeURIComponent(learnerRef)}/courses/${encodeURIComponent(courseId)}/paths/latest`,
    )
    return { ...result, data: result.data.learning_path }
  }

  async getAgentContext(learnerRef: string, courseId: string): Promise<ApiResult<Topic2AgentContextV1>> {
    return this.topic3<Topic2AgentContextV1>(
      `/internal/topic2/learners/${encodeURIComponent(learnerRef)}/courses/${encodeURIComponent(courseId)}/agent-context`,
    )
  }

  async refreshMemory(
    learnerRef: string,
    courseId: string,
    idempotencyKey = newIdempotencyKey("topic2-memory"),
  ): Promise<ApiResult<JsonObject>> {
    return this.topic3<JsonObject>(
      `/internal/topic2/learners/${encodeURIComponent(learnerRef)}/courses/${encodeURIComponent(courseId)}/memory/refresh`,
      {
        method: "POST",
        json: { operation_id: crypto.randomUUID(), requested_at: new Date().toISOString() },
        headers: { "Idempotency-Key": idempotencyKey },
      },
    )
  }

  async generateLearningPath(
    learnerRef: string,
    courseId: string,
    targetGoal: string,
    idempotencyKey = newIdempotencyKey("topic2-path"),
  ): Promise<ApiResult<JsonObject>> {
    return this.topic3<JsonObject>(
      `/internal/topic2/learners/${encodeURIComponent(learnerRef)}/courses/${encodeURIComponent(courseId)}/paths/generate`,
      {
        method: "POST",
        json: {
          operation_id: crypto.randomUUID(),
          requested_at: new Date().toISOString(),
          target_goal: targetGoal,
          change_type: "MANUAL_OVERRIDE",
          trigger_reason: "learner-workbench",
        },
        headers: { "Idempotency-Key": idempotencyKey },
      },
    )
  }

  async createGeneration(
    command: Topic3GenerationInput,
    idempotencyKey = newIdempotencyKey("topic3-generation"),
  ): Promise<ApiResult<JsonObject>> {
    return this.topic3<JsonObject>("/internal/topic3/generations", {
      method: "POST",
      json: command,
      headers: { "Idempotency-Key": idempotencyKey },
    })
  }

  async getGeneration(sessionId: string): Promise<ApiResult<GenerationView>> {
    const result = await this.topic3<JsonObject>(`/internal/topic3/generations/${encodeURIComponent(sessionId)}`)
    return {
      ...result,
      data: {
        session: result.data.session as GenerationView["session"],
        blueprint: result.data.blueprint as GenerationView["blueprint"],
        tasks: result.data.tasks as GenerationView["tasks"],
        candidates: result.data.candidates as CandidateV1[],
      },
    }
  }

  async listGenerations(learnerRef: string, courseId: string): Promise<ApiResult<JsonObject[]>> {
    const result = await this.topic3<{ sessions: JsonObject[] }>(
      `/internal/topic3/learners/${encodeURIComponent(learnerRef)}/courses/${encodeURIComponent(courseId)}/generations`,
    )
    return { ...result, data: result.data.sessions }
  }

  async listStreamChunks(streamId: string, afterIndex = -1): Promise<ApiResult<JsonObject[]>> {
    const result = await this.topic3<{ chunks: JsonObject[] }>(
      `/internal/topic3/streams/${encodeURIComponent(streamId)}/chunks${queryString({ after_index: afterIndex })}`,
    )
    return { ...result, data: result.data.chunks }
  }

  async topic4Health(): Promise<ApiResult<Topic4HealthView>> {
    return this.topic3<Topic4HealthView>("/internal/topic4/health")
  }

  async getVerification(verificationId: string): Promise<ApiResult<VerificationSnapshot>> {
    return this.topic3<VerificationSnapshot>(
      `/internal/topic4/verifications/${encodeURIComponent(verificationId)}`,
    )
  }

  async executeVerification(verificationId: string): Promise<ApiResult<JsonObject>> {
    return this.topic3<JsonObject>(
      `/internal/topic4/verifications/${encodeURIComponent(verificationId)}/execute`,
      { method: "POST" },
    )
  }

  async listClaims(verificationId: string): Promise<ApiResult<ClaimV1[]>> {
    const result = await this.topic3<{ claims: ClaimV1[] }>(
      `/internal/topic4/verifications/${encodeURIComponent(verificationId)}/claims`,
    )
    return { ...result, data: result.data.claims }
  }

  async getReport(verificationId: string): Promise<ApiResult<VerificationReportV1>> {
    const result = await this.topic3<{ report: VerificationReportV1 }>(
      `/internal/topic4/verifications/${encodeURIComponent(verificationId)}/report`,
    )
    return { ...result, data: result.data.report }
  }

  async listEvidence(claimId: string): Promise<ApiResult<EvidenceRefV1[]>> {
    const result = await this.topic3<{ evidence: EvidenceRefV1[] }>(
      `/internal/topic4/claims/${encodeURIComponent(claimId)}/evidence`,
    )
    return { ...result, data: result.data.evidence }
  }

  async getTrace(traceId: string, limit = 500): Promise<ApiResult<VerificationTraceView>> {
    return this.topic3<VerificationTraceView>(
      `/internal/topic4/traces/${encodeURIComponent(traceId)}${queryString({ limit })}`,
    )
  }

  async listRevisions(verificationId: string): Promise<ApiResult<RevisionHistoryItem[]>> {
    const result = await this.topic3<{ revisions: RevisionHistoryItem[] }>(
      `/internal/topic4/verifications/${encodeURIComponent(verificationId)}/revisions`,
    )
    return { ...result, data: result.data.revisions }
  }

  async createRevision(
    command: RevisionCommandInput,
    idempotencyKey = newIdempotencyKey("topic4-revision"),
  ): Promise<ApiResult<JsonObject>> {
    return this.topic3<JsonObject>("/internal/topic4/revisions", {
      method: "POST",
      json: command,
      headers: { "Idempotency-Key": idempotencyKey },
    })
  }

  async deriveAuthorization(
    input: ReleaseDerivationInput,
    idempotencyKey = newIdempotencyKey("topic4-release-derive"),
  ): Promise<ApiResult<{ authorization: ReleaseAuthorizationPayloadV1 }>> {
    const result = await this.topic3<{ authorization: ReleaseAuthorizationPayloadV1 }>(
      "/internal/topic4/release/authorizations/derive",
      {
        method: "POST",
        json: input,
        headers: { "Idempotency-Key": idempotencyKey },
      },
    )
    return result
  }

  async commitPublication(
    authorizationId: string,
    idempotencyKey = newIdempotencyKey("topic4-release-commit"),
  ): Promise<ApiResult<ReleaseCommitResult>> {
    return this.topic3<ReleaseCommitResult>("/internal/topic4/release/publications/commit", {
      method: "POST",
      json: { authorization_id: authorizationId },
      headers: { "Idempotency-Key": idempotencyKey },
    })
  }

  async listPublicationHistory(verificationId?: string): Promise<ApiResult<PublicationHistoryItem[]>> {
    const result = await this.topic3<{ records: PublicationHistoryItem[] }>(
      `/internal/topic4/release/history${queryString({ verification_id: verificationId })}`,
    )
    return { ...result, data: result.data.records }
  }

  async listReviewTasks(state = "OPEN"): Promise<ApiResult<HumanReviewTaskV1[]>> {
    const result = await this.topic3<{ tasks: HumanReviewTaskV1[] }>(
      `/internal/topic4/reviews/tasks${queryString({ state })}`,
    )
    return { ...result, data: result.data.tasks }
  }

  async submitReview(
    verificationId: string,
    input: ReviewDecisionInput,
    idempotencyKey = newIdempotencyKey("topic4-review"),
  ): Promise<ApiResult<ReviewDecisionResult>> {
    return this.topic3<ReviewDecisionResult>(
      `/internal/topic4/verifications/${encodeURIComponent(verificationId)}/reviews/decisions`,
      {
        method: "POST",
        json: input,
        headers: { "Idempotency-Key": idempotencyKey },
      },
    )
  }

  async replayPublicEvents(afterSequence?: number): Promise<ApiResult<JsonObject[]>> {
    const result = await this.topic3<{ events: JsonObject[] }>(
      `/internal/topic4/sse/replay${queryString({ after_sequence: afterSequence })}`,
    )
    return { ...result, data: result.data.events }
  }

}

export function useWorkbenchApi(client: ApiClient): WorkbenchApi {
  return new WorkbenchApi(client)
}
