# Phase 7 Gate C Tenth Replay Failure Analysis

## Evidence Binding

- Source: 64792b0420f436d18beea2a301bd4017bc7e7a82
- Tree: 61da331c23a5d5b6988aff70d0db5455732886cc
- Run: gate-c-20260815T050434Z-64792b0420f4
- Compose: cybercontrol-gate-c-tenth-main-64792b-20260815050434
- PostgreSQL volume: cybercontrol_gate_c_tenth_main_64792b_20260815050434
- Threshold SHA256: d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855
- Workload SHA256: 38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea

## Proven Failure Boundary

The first unchanged stage, smoke-20, completed with real Keycloak-issued
credentials, two tenants and twenty real principals. It failed two frozen
stage controls:

1. Delivery p99 was 6850 ms, above the frozen 3000 ms limit. Delivery p95 was
   439 ms.
2. Monitor completeness was 0.7948717949, below the frozen 0.95 minimum. Seven
   samples recorded ReadTimeout while reading /metrics; the final sample
   recorded a Docker inspection CalledProcessError.

The merged delivery histogram had 3380 observations. Seventy exceeded 1000 ms
and forty exceeded 3000 ms. The measured tail included ten observations at
6850 ms, ten at 8979 ms, ten at 9276 ms and ten around 9609-9613 ms. No
aggregation or timeout was changed.

The smoke stage retained connection/reconnect 1.0/1.0, zero committed loss,
zero duplicate final rendering, zero cross-tenant leakage, zero HTTP 5xx, zero
pool acquisition timeout and zero Outbox DEAD. Security controls rejected
unauthenticated and invalid Token requests with 401, and rejected tampered and
cross-tenant cursors with 400.

## Disproof Plan For The Next Remediation

- Correlate each smoke delivery tail observation with publisher ordinal,
  transaction/outbox segments, notification bridge, SSE enqueue and client
  receipt timestamps. Disproof is delivery p99 <= 3000 ms under the unchanged
  workload with zero loss, duplicate render or tenant leakage.
- Trace the seven periodic /metrics timeouts to event-loop runnable delay,
  diagnostics collection, metrics serialization and request scheduling.
  Disproof is monitor completeness >= 0.95 without relaxing monitor timeout,
  sample interval, workload or aggregation.
- Preserve the existing signed cursor, ordered replay, close ownership, RLS,
  Outbox lease/claim/partition/atomic semantics and all passed controls.
- Do not claim RSS recovery. The required recovery phase was not executed.

## Terminal Database Evidence

Migration head 20260720_0010, FORCE RLS 74/74, append-only triggers 57,
foreign-tenant visibility 0 and terminal Outbox PUBLISHED=25 with no
PENDING/CLAIMED/DEAD.
