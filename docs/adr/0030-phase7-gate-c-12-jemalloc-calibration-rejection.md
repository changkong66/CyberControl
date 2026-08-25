# ADR-0030: Reject The Gate C Twelfth Jemalloc Calibration

- Status: Accepted
- Date: 2026-08-25
- Process version: `Gate-C-12-v1.0`
- Decision domain: non-acceptance P2 diagnostic instrumentation
- Product source SHA: `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Engineering baseline SHA: `d0c6e0c4097e3410e1b6a53c7ca679770b67bc77`
- Source tree: `c6813510c4031f314145adf2f23d812521c88ce2`

## Decision

Reject the first Gate-C-12 jemalloc A/Measurement/A' calibration. The A control
arm completed the frozen `ramp-200` stage and every zero-tolerance control
passed. The Measurement arm produced one real HTTP 500 while sampling was
active. The zero-tolerance stop rule therefore prohibited A', the fixed
600-second Measurement recovery, profile completion, heap interpretation and
any P2 behavior candidate.

This diagnostic is not a formal Gate C attempt. It does not append
`gate_c_attempts`, does not change the formal release state and does not support
an RSS ownership claim. Gate C remains failed and Gate D-G remain locked.

## Falsified Hypothesis

The hypothesis under test was that runtime jemalloc sampling could be activated
for the real frozen `ramp-200` workload without changing functional behavior or
crossing the predeclared interference limits. That hypothesis is falsified for
this image and activation protocol because the Measurement arm crossed a
zero-tolerance functional boundary.

The evidence does not prove that sampling caused the native address fault. It
proves that this experiment cannot exclude such interference and is therefore
inadmissible for owner attribution.

## Measured Evidence

Both executed arms used the same profiling-capable API image digest
`sha256:60ca42674fdbdd66c774ec777756cd630682877342787ab3412197a83079b824`,
image lock SHA256
`7fd28b88fed9bfa6edab48b8568be29e06087c307a037db4fa1f880e7c43cc3f`,
frozen threshold/workload hashes, real Keycloak issuance, two tenants, twenty
principals, independent Compose projects and fresh PostgreSQL volumes.

The A arm `gate-c-diagnostic-20260825T070253Z` recorded:

- 200 sustained streams for 304 seconds;
- 400 SSE requests and zero request failures;
- zero committed event loss, final duplicate render, cross-tenant leakage,
  HTTP 5xx, Outbox `DEAD`, database pool timeout and workflow failure;
- monitor completeness `194/194` (`1.0`);
- connection p95/p99 `665/703 ms` and delivery p95/p99 `45/191 ms`;
- capacity `19.291 -> 19.282 GiB`, always `NORMAL`.

The Measurement arm `gate-c-diagnostic-20260825T072739Z` activated sampling at
`2026-08-25T07:33:42.444042Z`. At `2026-08-25T07:33:52.675092Z`, approximately
10.231 seconds later, one of 401 SSE requests returned HTTP 500. The captured
ASGI traceback terminates at:

```text
tenant authorization -> database transaction -> SQLAlchemy pool checkout
-> asyncpg connect -> ssl.load_cert_chain
-> OSError: [Errno 14] Bad address
```

The capacity snapshot at failure was `19.271 GiB / NORMAL`; containers showed
no OOM or restart evidence. The runner stopped on Locust exit code 1 and
destroyed the Compose containers and network. It did not execute the recovery
window or write a completion manifest, heap profile or symbolization output.

## Causality Boundary

The temporal relationship, successful A control and native fault make sampling
interference a concrete next hypothesis. They do not establish its mechanism.
No conclusion may be stated about signal interruption, OpenSSL, asyncpg,
jemalloc internals, allocator fragmentation or the Gate C RSS owner without a
new deterministic, lower-cost reproducer and an independent control.

The following would falsify the next sampling-interference hypothesis:

- a deterministic connection-creation regression reproduces the native fault
  with profiling inactive at the same rate;
- repeated activated runs do not reproduce the fault while matched inactive
  controls do; or
- a native stack and exact build-ID trace assigns the fault to a component
  independent of the profiling state transition.

## Semantic Impact

No application behavior, request path, RLS policy, `TenantContext`, identity
derivation, SERIALIZABLE transaction, C12 authorization, migration 0001-0010,
Outbox publication, lease, retry, partition order, cursor, workload, threshold,
timeout, grace period or aggregation changed during this diagnostic.

No production or formal image enables profiling. A future instrumentation
change must remain diagnostic-only and must pass positive and negative tests
for cancellation, connection creation, transaction/session return, signal
transitions, failure preservation and absence from normal images.

## Evidence Index

- Structured rejection:
  `docs/diagnostics/phase7-gate-c-twelfth-p2/calibration-rejection.json`
- External package reference:
  `docs/diagnostics/phase7-gate-c-twelfth-p2/package-reference.json`
- A arm package SHA256:
  `ff328e7bce3e86255a730cb9129068e335a276d60f13d4afb854eb418cd9c212`
- Measurement rejected package SHA256:
  `8fd910637bd650f2f4fc5b70f92c2f2cb696d90510591db35de987ccd34b313c`
- Combined rejected package SHA256:
  `99d6fb8ed47950ea142def94c2fd3a6388ec0091e517ee6737ad5d2cdff7d423`
- Combined content manifest SHA256:
  `c6506e3eabe4e1e82d1a544e9f03aaa2d1834342bcd20b596e187d5be0ef5bc5`
- Redaction scan SHA256:
  `04355a2e2156d2b437c91403ae2611e6f61afd3866566ee786d0535d2f67fc20`
- Resource cleanup SHA256:
  `eaab5fd6d3e94c2dadb23812d06807e97bdfd28dd0396a892d48d0f1043aa57e`

## Stop And Next Decision

Do not run A', a 2,000-connection diagnostic, a behavior fix, PreflightSmoke or
a formal Gate C replay from this result. The next permitted work is a new
diagnostic design that deterministically tests the sampling/connection-creation
interaction below formal load, with a separate ADR and unchanged semantic
redlines. Gate D requires separate authorization even after future Gate C
eligibility.
