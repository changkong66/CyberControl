# Phase 7 Gate C Fifth Remediation Failure Analysis

## Proven Boundary

The fifth remediation removed the prior durable-consumer authorization defect:
all 103 Outbox rows reached `PUBLISHED`, no row reached `DEAD`, and workflow
publication recorded no failure. The unchanged workload then passed 20, 200
and 500 authenticated streams and failed at 1,000 streams only after sustaining
the required 603 seconds.

The run preserved connection and replay success of `1.0`, zero committed-event
loss, zero duplicate final rendering, zero cross-tenant leakage, zero HTTP 5xx,
zero pool acquisition timeout and zero unplanned restart or OOM. These controls
must not be weakened during remediation.

## Failed Controls

- Commit-to-client p95/p99: `1,532/4,985 ms`, required
  `<= 1,000/3,000 ms`.
- Outbox created-to-published p95/p99: `5,830.700/8,434.789 ms`, required
  `<= 2,000/5,000 ms`.
- The 2,000-stream and ten-minute recovery stages were not executed.

## Evidence-Backed Hypotheses

The API reached `127.604%` p95 and `131.840%` maximum CPU in one-core units
while host CPU remained below the frozen host limit. PostgreSQL had no pool
timeout and ended with no open Outbox work. This narrows the next measurement
to API event-loop scheduling, notification dispatch and per-subscriber SSE
fan-out, but does not by itself prove one root cause.

The current broker performs ordered `put_nowait` delivery to each subscriber
while holding the tenant lock. At 1,000 streams this is an O(subscriber count)
critical section for every committed event. Gauge calculation, event-size
accounting, replay buffering and slow-consumer closure also execute on this
path. The sixth remediation must measure lock hold time, fan-out time per
subscriber, event-loop delay, queue operations, serialization and socket drain
before selecting a fix.

The fail-fast snapshot showed `826` closing subscription owners even though
active subscribers, queues, replay caches and replay tasks were zero. Because
the fixed recovery observation did not run, this is not proof of a retained
leak. The next tests must prove that close ownership drains within a bounded
period without reintroducing `aclose()` races.

## Disproof Requirements

A valid remediation must be rejected if any of the following occurs:

- fan-out or Outbox latency remains above the frozen p95/p99 controls;
- event ordering, signed cursor tenant binding or durable replay is weakened;
- event loss, duplicate final rendering or cross-tenant visibility becomes
  nonzero;
- finalized workflow events become `DEAD` or authorization is bypassed;
- cleanup requires forced GC, increased client timeout or a client-only grace
  period;
- the result depends on reduced events, connections or changed aggregation.

Gate D through Gate G remain locked until an independent complete Gate C pass
is archived and merged through protected-main CI.
