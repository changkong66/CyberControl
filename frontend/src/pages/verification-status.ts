import type {
  AggregateDecision,
  ModuleRunState,
  VerificationModule,
  VerificationState,
} from "@liyans/contracts"

export interface VerificationMatrixModule {
  code: string
  module?: VerificationModule
}

export interface VerificationMatrixSnapshot {
  state: { current_state: VerificationState }
  dispatch_plan: { items: Array<{ module: VerificationModule }> } | null
  module_runs: Array<{ module: VerificationModule; state: ModuleRunState }>
  module_results: Array<{ module: VerificationModule }>
  report: { decision: AggregateDecision } | null
}

const revisionStates = new Set<VerificationState>([
  "REVISION_PLANNING",
  "REVISION_WAITING",
  "REVERIFYING",
])

const releaseDecisions = new Set<AggregateDecision>([
  "RELEASE",
  "RELEASE_WITH_DISCLOSURE",
])

export function verificationMatrixState(
  module: VerificationMatrixModule,
  snapshot: VerificationMatrixSnapshot | null,
  revisionCount: number,
): string {
  if (!snapshot) return "PENDING"

  if (module.code === "C1") return "SUCCEEDED"
  if (module.code === "C8") {
    if (revisionCount > 0) return "SUCCEEDED"
    if (revisionStates.has(snapshot.state.current_state)) return "RUNNING"
    return snapshot.report ? "NOT_REQUIRED" : "PENDING"
  }
  if (module.code === "C12") {
    if (snapshot.state.current_state === "RELEASED") return "SUCCEEDED"
    if (snapshot.state.current_state === "RELEASE_PENDING") return "RUNNING"
    if (snapshot.report && !releaseDecisions.has(snapshot.report.decision)) {
      return "NOT_REQUIRED"
    }
    return "PENDING"
  }
  if (!module.module) return snapshot.report ? "NOT_REQUIRED" : "PENDING"

  if (snapshot.module_results.some((result) => result.module === module.module)) {
    return "SUCCEEDED"
  }
  const activeRun = snapshot.module_runs.find((run) => run.module === module.module)
  if (activeRun) return activeRun.state

  const planned = snapshot.dispatch_plan?.items.some((item) => item.module === module.module)
  if (snapshot.report && !planned) return "NOT_REQUIRED"
  return "PENDING"
}
