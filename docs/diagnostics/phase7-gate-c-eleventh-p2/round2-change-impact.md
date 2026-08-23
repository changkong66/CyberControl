# Gate C Eleventh P2 Round 2 Change Impact

Process Version: `Gate-C-11-v1.0`

## Scope

Round 2 added one diagnostic-harness capability: `DiagnosticStages` can hold a
bounded idle window and capture a separate baseline monitor before starting the
selected stage. The parameter is rejected in every non-diagnostic mode and
defaults to zero. A focused runner-contract test covers both the parameter and
the baseline monitor path.

No API, database, streaming, identity, authorization, Outbox, contract,
migration or production runtime behavior was changed. No allocator candidate
is active. The round-1 `PYTHONMALLOC` experiment was reverted before this
branch and is not present in its product tree.

## Files And Interfaces

| File | Impact |
| --- | --- |
| `tools/windows/run-phase7-gate-c.ps1` | Adds diagnostic-only `DiagnosticIdleSeconds`, metadata and baseline monitor lifecycle |
| `backend/tests/test_gate_c_load_tools.py` | Verifies mode isolation and baseline monitor wiring |
| `docs/adr/0024-phase7-gate-c-eleventh-p2-rss-remediation.md` | Records hypotheses, evidence, stop rule and P2 freeze |
| `docs/diagnostics/phase7-gate-c-eleventh-p2/*` | Stores append-only diagnostic summaries and package references |

The executable diff is `26` lines added across the runner and its focused
test. It is not a deployable-product remediation and must not be represented as
one.

## Semantic Redlines

The branch does not touch migrations `0001-0010`, RLS, `TenantContext`,
SERIALIZABLE transactions, C12, frozen contracts, thresholds, workload,
timeouts, Keycloak authority, cursor signing, replay order, Outbox claim/lease/
retry/partition ordering, durable acceptance or atomic publication.

The diagnostic used real Keycloak-issued tokens but no token or credential is
stored in the package. No client-supplied tenant, subject, role or scope header
was introduced.

## Risks And Disposition

The opt-in sampler caused substantial GIL and event-loop interference. The
result is suitable for ownership diagnostics only and cannot support latency,
throughput or formal acceptance claims. The invalid terminal pool gauge `-2`
is recorded as a separate observability anomaly and is not used as proof of a
pool leak.

Because two P2 root-cause rounds did not prove an actionable owner, this branch
is evidence-preservation only. It must not be merged as the eleventh P2
remediation. A new candidate requires a reviewed root-cause measurement design
and explicit continuation after the P2 code freeze.

Formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; Gate D-G remain
locked.
