# Domain ownership

```text
topic1/         frozen data model and course topology
topic2/         profile extraction and learning path
generation/     blueprints, agents, candidates, staging
verification/   C1 state machine, claims, scheduling, decisions, release
knowledge/      C2 verifier knowledge assets and retrieval
academic/       C3 mathematical and factual verification
graph/          C4 Mermaid Graph IR verification
quiz/           C5 quiz verification
code/           C6 code verification client and policies
extension/      C7 source, citation, and license verification
revision/       C8 restricted self-correction
security/       C9 prompt injection and content security
privacy/        C10 PII, tenant policy, tokenization, and encryption
compliance/     C11 SBOM, licenses, vulnerabilities, and shared audit services
qa/             C12 runtime invariants and acceptance support
```

Domain packages may depend on shared contracts and core protocols. They must not
import another domain's infrastructure implementation.
