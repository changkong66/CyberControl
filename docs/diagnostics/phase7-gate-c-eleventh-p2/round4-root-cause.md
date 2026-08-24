# Gate C Eleventh P2 Measurement Round 4

Process Version: `Gate-C-11-v1.0`

## Decision

The valid A/measurement/A' experiment rejected the ADR 0026 low-interference
measurement design. A2 and the new A' control completed the real 200-stream
stage and fixed 600-second recovery independently. The measurement arm also
completed its stage and produced the four expected profile artifacts, but it
materially changed the workload and the RSS residual. Its heap output is not
admissible for choosing a product owner.

This is a diagnostic result, not a formal Gate C attempt. No product behavior,
migration, RLS policy, TenantContext, transaction, Outbox, identity authority,
threshold or workload was changed. P2 behavior remains frozen.

## Quantitative Disproof

The controls were within the predeclared A/A' limits. Their connection p95
values were `637/591 ms`, delivery p95 values were `45/43 ms`, and RSS deltas
were `18,497,536/19,709,952` bytes. The RSS delta difference was `1,212,416`
bytes, below the `8,388,608`-byte control limit. Both controls had complete
monitor samples and passed the frozen 200-stream stage.

The measurement arm failed the disproof limits:

| Metric | A/A' control median | Measurement | Limit | Result |
| --- | ---: | ---: | ---: | --- |
| Connection p95 | 614 ms | 702 ms | <= 1.10x | rejected, 1.143322x |
| Delivery p95 | 44 ms | 53 ms | <= 1.10x | rejected, 1.204545x |
| API CPU p95 | 22.69 | 25.32 | <= 1.10x | rejected, 1.11591x |
| RSS delta | 19,103,744 B | 32,808,960 B | difference <= 8,388,608 B | rejected, +13,705,216 B |

All three arms had complete monitor samples (`194/194`, `193/193` and
`194/194`) and all stage-local functional/security controls passed. This does
not rescue the measurement arm: the causal experiment requires the sampling
arm to remain within the latency, CPU and RSS interference bounds.

## What Is And Is Not Proven

The measurement profile was source-bound and generated an activation manifest,
completion manifest, `profile.heap` and `symbolized.txt` from the exact image
digest `sha256:e7d0db88369011eb4ce181a49a7224db4b35f4c49c28f24cf492b9322b5b8d86`.
The control arms produced no profile artifacts. The measured arm ended with
zero subscribers, queued events, replay tasks, checked-out API pool members and
active application PostgreSQL connections; Outbox state was `PUBLISHED=26`.
These are useful integrity observations, not proof of an RSS owner.

The symbolized report is not converted into an owner claim. Ownership
admissibility analysis stops before stack-family interpretation because the
interference precondition failed. Any apparent stack association is therefore
inadmissible. No cache, pool, allocator, serializer, task or framework change
is justified by this run.

## Preserved Resources And Boundary

All five ADR 0026 PostgreSQL volumes remain present, including the incomplete
A' volume from the disk-capacity abort and the new valid A' volume. All five
Compose projects have zero remaining containers and networks. The earlier A'
abort is separately recorded in
`adr0026-aprime-infra-abort.json`; it is not used as the valid A' control.

The completed A2, measurement and A' raw runs remain under:

- `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c-diagnostic-20260824T055055Z-ff4f3b9d33ef`
- `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c-diagnostic-20260824T061346Z-ff4f3b9d33ef`
- `D:/CyberControlAcceptance/phase7/gate-c/diagnostics/gate-c-diagnostic-20260824T071349Z-ff4f3b9d33ef`

The raw credential-bearing incomplete run is preserved locally but is not
included in the external package. Published evidence contains only redacted
summaries and hashes.

## Stop Rule

The ADR 0026 measurement hypothesis is rejected for this implementation. No
P2 behavior candidate, formal Gate C replay, Gate C acceptance decision or Gate
D-G activity may start. A new lower-interference measurement design requires a
separate review and evidence closure. The formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`.
