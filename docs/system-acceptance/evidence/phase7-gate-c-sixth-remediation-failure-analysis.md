# Phase 7 Gate C Sixth Remediation Failure Analysis

## Proven Boundary

The sixth remediation was merged through protected-main Release Quality Gates
8/8 and evaluated from its exact merge commit. The unchanged workload passed
20, 200 and 500 authenticated streams, then sustained 1,000 streams for 603
seconds and failed the frozen latency controls. The harness correctly stopped
before 2,000 streams and recovery.

The run retained connection and reconnect success of `1.0`, zero committed
event loss, zero duplicate final rendering, zero cross-tenant leakage, zero
HTTP 5xx, zero Outbox `DEAD`, zero pool acquisition timeout, and zero OOM or
unplanned restart. It also retained zero asynchronous-generator close races and
ended the fail-fast snapshot with all subscriber, queue and replay gauges at
zero. These controls must not be weakened.

## Failed Controls

- Commit-to-client p95/p99: `1,805/7,190 ms`, required
  `<= 1,000/3,000 ms`.
- Outbox created-to-published p95/p99: `10,102.261/11,812.566 ms`, required
  `<= 2,000/5,000 ms`.
- The 2,000-stream and ten-minute recovery stages were not executed.

## Evidence-Backed Direction

The immutable-event serialization reuse and notification coalescing changes did
not satisfy the latency controls. Outbox created-to-published latency regressed
relative to the fifth run, while the database ended with all 105 messages
`PUBLISHED`, no `DEAD`, and no pool timeout. The next investigation must use
the sixth-remediation stage histograms and transaction timestamps to separate
claim polling, claim-batch execution, authorization, durable acceptance,
published marking, notification synchronization, fan-out and socket delivery.
No single stage is proven to be the root cause yet.

API CPU remained near one saturated core at p95 and reached `145.910` one-core
units. Peak file descriptors remained `1,038`. The next remediation must profile
Python event-loop runnable time, serialization and metrics overhead outside the
tenant lock, per-event fan-out cost, and slow-consumer socket scheduling. Adding
workers, changing the workload or widening client timeouts would not disprove
the current defect.

Connection admission p95/p99 increased to `21,888/25,735 ms` despite zero Token
issuance failure. Token acquisition, HTTP authentication, replay acquisition,
subscriber registration, LIVE handoff and first-event readiness must remain
separately measured.

## Disproof Requirements

A valid seventh remediation must be rejected if any of these occur:

- delivery or Outbox latency remains above the frozen p95/p99 controls;
- event ordering, signed cursor tenant binding or durable replay is weakened;
- event loss, duplicate final rendering, cross-tenant visibility or Outbox
  `DEAD` becomes nonzero;
- successful publication is acknowledged before durable acceptance;
- cleanup requires forced GC, increased timeout or a client-only grace period;
- performance depends on reduced events, connections or changed aggregation.

Gate D through Gate G remain locked until one complete same-run Gate C pass is
archived by an independent evidence PR and protected-main CI.
