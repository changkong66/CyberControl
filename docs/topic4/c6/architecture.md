# Topic4 C6 Control-Code Verification Runtime

## 1. Scope and Safety Boundary

C6 validates the frozen Topic3 CodeSandboxContentV1 contract for Python and
MATLAB automatic-control simulation resources. The verifier never imports,
evaluates, spawns, or executes Candidate source in the API or worker process.
Execution state is recorded explicitly as NOT_RUN for statically accepted code and
POLICY_BLOCKED for code rejected by the safety policy. A future hardened sandbox
runner may be attached behind the existing boundary without changing C6 contracts
or C1 ownership.

C6 therefore proves syntax, boundedness, dangerous-capability absence, dependency
allow-list membership, control-model presence, simulation-flow presence, literal
pole stability where coefficients are available, and consistency between computed
stability and the generated explanation. It never claims that a non-executed
arbitrary program has been run successfully.

## 2. Runtime Flow

~~~mermaid
flowchart LR
    C1["C1 code Claim"] --> B["Tenant-scoped read adapter"]
    B --> T3["Exact immutable Topic3 Candidate"]
    B --> C2["C2 EvidenceBundle"]
    C2 --> T1["Topic1 graph snapshot"]
    T3 --> P["Frozen code-block parser"]
    P --> S["Immutable source bundle"]
    S --> PY["Python AST analyzer"]
    S --> M["MATLAB bounded parser"]
    PY --> A["Control and safety analysis"]
    M --> A
    A --> CP["CodeArtifact + SandboxPolicy"]
    CP --> R["CodeVerificationResult"]
    R --> O["Canonical SHA-addressed artifact"]
    O --> F["C1 ModuleFinding"]
~~~

## 3. Binding Invariants

1. Candidate tenant, Claim tenant, dispatch tenant, database tenant context, and
   artifact tenant must be identical.
2. Candidate identity, version, SHA, block ID, block ordinal, content SHA, and Claim
   JSON pointer are checked before contract parsing.
3. EvidenceBundle, KnowledgeBaseVersion, EvidenceRef, Trace ID, Claim ID, excerpt
   SHA, record SHA, and Topic1 snapshot version are checked before analysis.
4. PostgreSQL reads retain explicit tenant predicates and existing FORCE RLS.
5. A positive finding requires authoritative C2 evidence.
6. Source files are stored as canonical immutable JSON before result generation;
   source and result SHA values are independently recorded.

## 4. Static Analysis Rules

### 4.1 Python

The analyzer uses only Python AST parsing. It blocks dangerous imports and calls
including filesystem mutation, process spawning, networking, dynamic evaluation,
native extension loading, and package installation. Dunder access, unbounded while
loops, dynamic or oversized for loops, non-finite/oversized numeric constants,
unseeded NumPy randomness, AST node exhaustion, and oversized time grids are
rejected.

Approved imports are limited to the local control-analysis allow-list: math,
NumPy, SciPy, python-control, and Matplotlib namespaces. Dependency names and
licenses are emitted into frozen CodeDependencyV1 records for later C11 supply
chain verification.

Transfer-function calls with literal or top-level assigned coefficients are
analyzed with local NumPy root calculation. Step/LSIM/ODE calls and bounded time
grids establish the static simulation flow. No generated function body is called.

### 4.2 MATLAB

The analyzer accepts a bounded script subset and rejects delimiter errors,
dangerous commands, dynamic evaluation, filesystem/network/process operations,
unbounded while loops, dynamic for ranges, block terminator mismatch, and
oversized time grids. Literal tf numerator/denominator vectors are analyzed with
the same local root calculation. MATLAB is parsed only; MATLAB Engine is never
loaded by the verifier.

### 4.3 Stability and Verdicts

Stable explanations are compared with computed poles. A stable claim with a pole
in the closed right half-plane is contradictory. An unstable claim for a model
whose literal poles are all stable is contradictory. A dynamic model with a
stability claim but no resolvable coefficients is insufficient evidence, not a
guessed positive result. Missing model/simulation flow is contradictory for a
control-code resource.

## 5. Sandbox Policy

Every result contains a frozen SandboxPolicyV1 with:

- network access disabled;
- read-only root filesystem;
- no allowed commands;
- denied network, write, process, dynamic-evaluation, native-extension,
  package-install, and GUI capabilities;
- bounded 256 MiB memory, 1000 CPU quota milliseconds, 32 process IDs, and
  10-second timeout metadata;
- runtime image digest and deterministic syscall-profile SHA.

The policy is evidence and deployment metadata. It does not imply that untrusted
source was executed in-process.

## 6. Verdict Policy

| Condition | Verdict |
| --- | --- |
| Syntax, static safety, control flow, stability, and evidence pass | SUPPORTED |
| Dynamic stability cannot be proven from local structure | INSUFFICIENT_EVIDENCE |
| Missing Candidate, Topic1 snapshot, or C2 evidence | INSUFFICIENT_EVIDENCE |
| Wrong answer-like stability conclusion or missing control flow | CONTRADICTED |
| Dangerous import, call, loop, randomness, resource exhaustion, or capability | UNSAFE |
| Tenant, Claim, Candidate, Trace, SHA, or artifact binding failure | UNSAFE/ERROR |

## 7. Recovery and Persistence

C6 writes no database rows directly. C1 owns state, retries, transaction rollback,
audit, Outbox, and publication. Content-addressed source and result objects are
idempotent and collision checked by the existing object store. Replaying a Claim
recreates the same static analysis and artifact document for the same immutable
Candidate version.

## 8. Explicit Boundary

C6 does not implement C7 extension provenance, C8 revision, C9-C11 cross-cutting
security/compliance, C12 release authorization, final Topic4 API/worker wiring, or
frontend behavior. A real isolated container execution service remains an explicit
future adapter boundary and is not represented as a successful execution in C6.
