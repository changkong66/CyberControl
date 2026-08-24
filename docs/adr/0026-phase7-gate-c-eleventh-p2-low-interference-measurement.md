# ADR 0026: Phase 7 Gate C Eleventh P2 Low-Interference Measurement

Process Version: `Gate-C-11-v1.0`

- Status: Proposed; design review only
- Root-cause domain: P2 RSS recovery
- Classification: measurement design only
- Formal Gate C attempt: no
- Acceptance claim: no
- Current engineering baseline:
  `c96a648f97c6033fd3ce027dc166942a3d48f373`
- Current engineering tree:
  `846708b227c3949b856cec864f0a8a48537161b2`
- Current product source:
  `a57d0ce57427804ede3f3c620fda2a93b3a300ff`
- Current product tree:
  `963fcf73113e39a1e5868fae3957f4adfc102a4c`
- Last formally evaluated Gate C source:
  `5fcb917b63889cb6da8dd019efdd133f4ec3fb60`
- Last formally evaluated Gate C tree:
  `f721fca017c247aee93765d5f11fcbc37e12fcfc`
- Current protected-main CI:
  [Run 32676982606](https://github.com/changkong66/CyberControl/actions/runs/32676982606),
  8/8
- Frozen threshold SHA256:
  `d2b8c8c450934cc5341c815f497a5581370a20644fdb9d0a511e3e7c0ff1e855`
- Frozen workload SHA256:
  `38f4dbf0ce34726a30833f235c8b5aa66c62c6012e296e01ce0ea34d7dac57ea`

PR #88 changed only the four current-state documents. It advanced the
engineering baseline from its recorded parent `90a8cbc0e73a...` to
`c96a648f97c...` without changing the product source. In accordance with the
repository's no-self-reference rule, the committed status snapshot records its
verified parent; the PR merge and post-merge CI above provide the external
closure. The `a57d0ce57427...` product source contains diagnostic
instrumentation but has not been formally evaluated by Gate C. The last formal
workload remains bound to `5fcb917b6388...`.

## Decision Boundary

ADR 0025 is rejected because enabling tracemalloc from process start materially
changed the workload and the RSS residual it was intended to explain. This ADR
defines a lower-interference experiment based on jemalloc's sampled native heap
profiler. It does not add that capability, select an RSS remediation, change a
production runtime setting or authorize a diagnostic execution.

The next eligible change is a separate, disabled-by-default profiling-capability
PR. That PR may implement only the build and control surface approved here. It
must complete push, pull-request, Squash Merge and protected-main 8/8 before any
A/measurement/A' run starts.

P2 product-behavior changes remain frozen. No formal replay, `gate_c_attempts`
entry or Gate C acceptance claim is allowed. The formal state remains
`RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`; Gate D-G remain
locked.

## Rejected Measurement Evidence

ADR 0025 used the same application image for its A2 and measurement arms, but
the measurement arm enabled tracemalloc from process start and captured complete
Python traceback snapshots. The real frozen 200-stream diagnostic produced the
following comparison against the median of A2 and A' controls:

| Metric | Control median | Measurement | Result |
| --- | ---: | ---: | --- |
| Connection p95 | `673ms` | `17,989ms` | rejected |
| Delivery p95 | `45.5ms` | `1,175ms` | rejected |
| API CPU p95 | `25.165` | `101.98` | rejected |
| Process RSS delta | `30,613,504` bytes | `59,334,656` bytes | rejected |
| Monitor completeness | `1.0` | `187/192` | stage incomplete |
| Sustained duration | `304s` | `285s` | stage failed |

The measurement RSS delta exceeded the control by `28,721,152` bytes, while
ADR 0025 permitted `8,388,608` bytes. Its `5,241` traceback groups are real,
but they are not admissible for choosing a product change because the profiler
altered CPU, connection latency, delivery latency, monitor behavior and the
residual itself. The immutable rejected package is `5,676,313` bytes with
SHA256 `10fb9477558ad203e1163198d8e28a941d16d922b6919d2711fdf6f69e22d92b`.

## Remaining Unknown And Hypothesis

The formal 2,000-stream run left `109,993,984` bytes of anonymous RSS and a
cgroup recovery ratio of `1.417200`. Point-in-time jemalloc accounting split
the growth into `40,065,416` bytes of additional live allocation and
`66,950,776` bytes of additional active-minus-allocated memory. At 200 streams,
the independent controls in ADR 0025 still retained approximately `30.6 MiB`
of process RSS after recovery even without tracemalloc.

The falsifiable measurement hypothesis is that sparse jemalloc allocation
sampling, activated only after a stable idle baseline, can attribute the live
post-workload allocation to native call-stack families without materially
changing latency, CPU, event-loop scheduling or the recovery residual. A
synchronized profile plus allocator bin/extent and bounded lifecycle inventory
can then distinguish:

1. a repeatable live allocation owner with a concrete caller stack;
2. live allocation spread across several bounded owners;
3. allocator page/size-class accounting that remains dominant after separating
   sampled post-baseline survivors, without assigning that difference to an
   unproved code owner;
4. an unresolved residual, in which case no remediation candidate is allowed.

The hypothesis is rejected if sampling exceeds the interference limits below,
if caller stacks cannot be resolved, or if the result cannot identify one
bounded and testable ownership mechanism. A plausible stack name alone is not
an actionable root cause.

## Reproducible Profiler Build Design

The evaluated API image is based on
`python:3.11-alpine@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4`
and reports Alpine `3.24.1`. Its pinned `jemalloc=5.3.0-r6` reports
`config.prof=false` and `config.stats=true`, so the existing library cannot
produce allocation call stacks.

The capability PR must build a diagnostic-only library and image. It must not
replace the normal API runtime image. The approved source inputs are:

- jemalloc `5.3.0` source:
  `https://github.com/jemalloc/jemalloc/releases/download/5.3.0/jemalloc-5.3.0.tar.bz2`;
- source size: `736,023` bytes;
- source SHA256:
  `2db82d1e7119df3e71b7640219b6dfe84789bc0537983c3b7ac4f7189aecfeaa`;
- Alpine aports `3.24-stable` commit:
  `fa59839ba07b53b11d12e849222439c785125d6a`;
- aports `APKBUILD` SHA256:
  `0ea64e064dc73516526337dcde8b86b2ac6d82d3f9806b3b2cd18799f4ab4ad9`;
- `musl-exception-specification-errors.patch` SHA256:
  `555b08620f00919e9b99c98a433cfcb755359395d62622cc8ae967d6717d43a0`;
- `pkgconf.patch` SHA256:
  `487908875c68b8ceb3fbd2c88f04eb2ddf8dd212272a2b3898e5e4fbd885623d`.

Every downloaded input must be checked before extraction or patching. The
direct Alpine build inputs must be version-pinned and the resulting installed
package manifest retained. The verified direct package set is:

- `autoconf-2.73-r0`;
- `build-base-0.5-r4`;
- `gcc-15.2.0-r5` and `g++-15.2.0-r5`;
- `binutils-2.45.1-r1` and `make-4.4.1-r4`;
- `musl-dev-1.2.6-r2`;
- `libunwind-1.8.3-r0` and `libunwind-dev-1.8.3-r0`;
- `linux-headers-7.0.0-r1`;
- `patch-2.8-r0` and `bzip2-1.0.8-r6`.

The proposed configure contract is:

```text
./autogen.sh \
  --enable-xmalloc \
  --enable-prof \
  --enable-prof-libunwind \
  --disable-prof-libgcc \
  --disable-prof-gcc \
  --enable-stats \
  --enable-shared \
  --prefix=/opt/cybercontrol/jemalloc-prof \
  --localstatedir=/var \
  --sysconfdir=/etc \
  --with-lg-page=12 \
  --with-lg-hugepage=21
```

The capability build must run the upstream allocator tests before copying only
the required runtime library, profiling tool and license into the derived
diagnostic image. Build logs must preserve the compiler/linker versions,
configure summary, package manifest and input hashes. The final library SHA256,
ELF build ID, image ID/digest and SBOM do not yet exist and must not be inferred
from this design. They become evidence only after the capability PR performs a
real no-cache build and validation.

## Runtime Configuration Contract

All three experimental arms must use the same exact profiling-capable API image
ID and digest. The image must retain the current process-start allocator
settings and add only these profiling options:

```text
background_thread:true,
dirty_decay_ms:1000,
muzzy_decay_ms:1000,
narenas:1,
retain:false,
prof:true,
prof_active:false,
lg_prof_sample:19,
prof_accum:false,
prof_gdump:false,
prof_final:false,
prof_leak:false
```

`config.prof=true` is a compile-time capability. `prof:true` initializes that
capability for the process, while `prof_active:false` ensures no allocation is
sampled before the approved activation point. Keeping initialization identical
in A, measurement and A' controls isolates runtime sampling as the only
experimental variable. The sampling interval remains jemalloc's `2^19`-byte
default; a denser interval is not authorized by this ADR.

Because activation occurs after the idle baseline, the final profile is a
cohort of allocations created after activation and still live at recovery end.
It is not a complete heap snapshot. Baseline objects may be freed or replaced
during the run, so profile-estimated bytes must not be equated to the simple
baseline-to-recovery `stats.allocated` delta or reported as a percentage of the
RSS residual. Synchronized allocator counters provide accounting context, not
an invented conservation equation.

The image must start with the legacy periodic memory diagnostic and ADR 0025
checkpoint modes disabled. In particular, the experiment must not start
tracemalloc or call `gc.get_objects()`, `asyncio.all_tasks()`, task stack/frame
enumeration or periodic object scans.

## Process-Local Control And Artifact Contract

No HTTP route, request header, Token scope or service role may control the
profiler. A disabled-by-default, process-local controller may own one dedicated
signal that does not conflict with the existing checkpoint signal. It must use
a fixed two-transition state machine:

1. `inactive -> sampling`: after the 300-second idle baseline, reset profiling
   counters and set `prof.active=true` before the load starts;
2. `sampling -> complete`: after the full 600-second recovery, first set
   `prof.active=false`, then call `prof.dump` once to a contained fixed path.

The controller must not dump a heap profile during load. Disabling sampling
before the final dump prevents profile-writing allocations from entering the
measured set. Duplicate, out-of-order, unsupported or concurrent transitions
must fail closed. Shutdown must wait for an in-flight transition and may not
create an implicit final dump. No profiling signal registration, background
task or live controller state may exist when the diagnostic mode is disabled.

Each transition must write an atomic manifest containing its monotonic and UTC
timestamps, action, previous/final state, mallctl result, duration, source/tree,
dual baselines, process version, library SHA/build ID, image ID/digest and the
SHA256/size of every artifact. The fixed output directory must already exist,
be mounted only for the diagnostic run and pass real-path containment checks.
No artifact may contain Tokens, credentials, tenant IDs, subject references,
cursors, SQL text or PII.

The immutable diagnostic package must retain the raw heap profile, synchronized
`/proc` memory accounting and maps, jemalloc stats, bin/extent inventory,
external monitor stream, redacted logs, symbolized reports, image/SBOM/build
provenance and SHA256 manifest. Symbolization must use the exact executable and
shared-library build IDs from the measured image. Repository evidence may store
bounded redacted summaries; raw artifacts remain in the immutable external
package.

## Capability Preconditions

Before any real A/measurement/A' diagnostic, deterministic and container tests
must prove all of the following:

1. the diagnostic image loads the newly built library, not Alpine's normal
   `/usr/lib/libjemalloc.so.2`;
2. `config.prof=true`, `config.stats=true`, `opt.prof=true` and startup
   `prof.active=false` are read back through mallctl;
3. the real image begins with tracemalloc disabled and no heavy sampler or
   memory-checkpoint owner active;
4. the first approved transition activates profiling once, the second
   deactivates and produces one parseable heap profile, and every invalid
   transition fails closed;
5. activation, dump failure, cancellation and shutdown leave the controller in
   an explicit terminal state and preserve the original error;
6. manifests are atomic, source-bound, path-contained and reject pre-existing
   artifacts;
7. offline symbolization resolves at least one caller frame above jemalloc for
   at least `90%` of estimated sampled live bytes in a deterministic allocation
   cohort;
8. the normal production image has no active profiling controller, signal
   registration or task and retains its existing library and allocator
   configuration;
9. image labels bind source/tree, product source, engineering baseline and
   `Gate-C-11-v1.0`, and the SBOM/license and vulnerability gates cover the
   added source-built library.

A capability test demonstrates that the instrument works. It does not establish
low interference, identify the RSS owner or authorize a behavior fix.

## A / Measurement / A' Protocol

All arms use the same exact capability commit, profiling-capable API image
digest, frozen threshold/workload hashes, real Keycloak issuance, two tenants,
twenty provisioned subjects and real frozen `ramp-200` stage. Each arm receives
an independent Compose project, run directory, network and fresh PostgreSQL
volume. No prior container, cache, credential or database state is reused.

Before every arm, the hard environment fingerprint and five-sample stable idle
baseline must pass. A and A' are independent executions, not image rebuilds or
candidate reverts. This deliberate design keeps the image constant because the
single variable under test is runtime sampling:

1. **A control:** hold a 300-second idle baseline; keep `prof.active=false`
   throughout the 200-stream stage and 600-second recovery.
2. **Measurement:** hold the same idle baseline; activate sampling immediately
   before the stage; run the unchanged stage and forced-disconnect path; keep
   sampling active through the complete recovery; deactivate and dump once at
   recovery end.
3. **A' control:** repeat A with fresh isolated resources and profiling inactive
   throughout.

The existing external monitor records synchronized cgroup RSS, process
RSS/USS/PSS, anonymous/file RSS, map count, jemalloc allocated/active/resident/
retained values, event-loop lag, CPU, FDs, pools/sessions, subscribers, queues,
replay state and all frozen stage controls. The profile is interpreted only
after A' completes and control stability is proven.

This is a diagnostic run, not `PreflightSmoke` or a formal Gate C attempt. It
must not invoke the formal finalizer, create a formal summary, update acceptance
state or append `gate_c_attempts`. A 2,000-stream diagnostic and a formal replay
remain prohibited.

## Quantitative Interference Rejection

Let `C` be the median of independent A and A' controls. Reject the experiment
without interpreting heap ownership if either control is invalid or if any of
the following is true:

- A and A' differ by more than `10%` for connection, delivery, API CPU or
  event-loop lag p95, or their RSS deltas differ by more than
  `max(8 MiB, 10% of their median)`;
- measurement connection p95, delivery p95, API CPU p95 or event-loop lag p95
  is more than `1.10 * C`;
- measurement baseline-to-recovery process RSS delta differs from `C` by more
  than `max(8 MiB, 10% of C)`;
- monitor completeness is below `0.95` in any arm, any required monitor field
  is absent, or the 200-stream stage does not sustain its frozen duration;
- any arm fails a frozen stage threshold or produces loss, final duplicates,
  cross-tenant visibility, invalid-cursor acceptance, HTTP 5xx, Outbox `DEAD`,
  pool timeout, OOM, unplanned restart, ordering failure or close race;
- terminal subscriber, queue, replay, pool/session or task gauges do not return
  to their required state, or FDs do not return near baseline;
- the activation/deactivation state, profile manifest, image identity or source
  binding is incomplete or inconsistent.

When a p95 control is zero, the absolute measurement value must also be zero;
division by zero may not be hidden by changing the metric. Any host,
Docker/PostgreSQL hard-redline or unexplained idle-baseline difference is an
environment abort, not a reason to relax these limits.

## Ownership Admissibility And Disproof

Passing the interference limits makes the profile eligible for analysis; it
does not make its conclusion true. Ownership evidence is admissible only if:

- at least `90%` of estimated live sampled bytes resolve to a caller frame
  above jemalloc using exact measured-image build IDs;
- every normalized stack family reports raw sample count, estimated live bytes
  and a predeclared sampling-error interval; no estimate is presented as an
  exact allocation count;
- at least one causally coherent stack family has at least `10` independent
  samples and at least `20%` of estimated post-activation live bytes; otherwise
  the profile is underpowered and no owner may be selected;
- stack families are normalized by build ID and instruction offset rather than
  unstable text or path matching;
- the dominant live stack families, bin/extent growth and bounded lifecycle
  inventories support one concrete owner or show only an allocator-accounting
  difference that still requires a separate hypothesis;
- the proposed owner is reachable by a deterministic regression and a minimal
  change that does not cross a semantic redline.

The design is disproved if those conditions fail, if sampling changes the RSS
shape, or if the output remains ambiguous between unrelated owners. In that
case archive the real diagnostic result, retain the P2 freeze and return to a
new reviewed measurement design. Do not select a cache, pool, allocator,
streaming or framework change by intuition.

## Change Impact And Semantic Redlines

This ADR changes documentation only. The maximum scope of the later capability
PR is a diagnostic-only source-built jemalloc image, a disabled process-local
profile controller, runner support for the fixed diagnostic protocol, an
offline symbolizer/comparator and focused tests. It may not alter normal image
behavior or any application request, persistence, identity, streaming or
publication path.

The capability and experiment must not modify migrations 0001-0010, RLS,
`TenantContext`, SERIALIZABLE transactions, C12, frozen contracts, thresholds,
workload, timeouts or aggregation. They must preserve `FOR UPDATE SKIP LOCKED`,
claim tokens, leases, retries, partition order, idempotent durable acceptance,
published cursors, atomic Outbox publication, signed tenant-bound
`Last-Event-ID`, strict replay order, duplicate suppression and fail-closed
authorization/cursor validation.

Tracemalloc, `gc.get_objects()`, `asyncio.all_tasks()`, task stack/frame
enumeration, periodic object scans, forced GC, allocator purge, `malloc_trim`,
restart recovery, cache-limit changes, extra workers, timeout/grace changes,
lower load, changed aggregation, identity headers and broadened roles remain
prohibited. Heap profiling must never be enabled in a formal Gate C or
production execution.

## Required Tests And Quality Gates

The later capability PR must include positive regressions for source/hash
verification, profiler capability readback, inactive startup, activation,
deactivation, profile generation, symbolization and source-bound manifests. It
must include negative regressions for missing capability, invalid state order,
duplicate/concurrent signals, path escape, pre-existing artifacts, dump error,
cancellation, shutdown and accidental enablement in the normal image.

All existing RLS, tenant isolation, identity authority, signed cursor,
partition ordering, idempotency, atomic publication, cancellation, ContextVar,
session/pool, subscriber, replay and FD tests remain mandatory. Python coverage
must remain at least `90%` without exclusions or empty assertions. Performance
tests may use real measured operations but may not claim fabricated scale.

The complete Release Quality Gates remain required: Python and real PostgreSQL
integration, frontend typecheck/build/unit/coverage, Playwright, Go
fmt/vet/race/test/build, contract drift, SBOM/license, dependency audit, Trivy
and Gitleaks. Capability push, pull-request and protected-main runs must each
pass 8/8, with Squash Merge only.

## Evidence Index

- Formal Gate C failure ADR:
  `docs/adr/0024-phase7-gate-c-eleventh-p2-rss-remediation.md`
- Rejected measurement ADR:
  `docs/adr/0025-phase7-gate-c-eleventh-p2-measurement-redesign.md`
- Round-three structured comparison:
  `docs/diagnostics/phase7-gate-c-eleventh-p2/round3-comparison.json`
- Round-three root-cause report:
  `docs/diagnostics/phase7-gate-c-eleventh-p2/round3-root-cause.md`
- Round-three package reference:
  `docs/diagnostics/phase7-gate-c-eleventh-p2/round3-package-reference.json`
- Round-three A infra abort / A2 / measurement / A' run IDs:
  `gate-c-diagnostic-20260823T213855Z`,
  `gate-c-diagnostic-20260823T214537Z`,
  `gate-c-diagnostic-20260823T220844Z`, and
  `gate-c-diagnostic-20260823T223248Z`
- Immutable rejected package SHA256:
  `10fb9477558ad203e1163198d8e28a941d16d922b6919d2711fdf6f69e22d92b`
- Immutable rejected package Release:
  https://github.com/changkong66/CyberControl/releases/tag/phase7-gate-c-11-p2-adr0025-measurement-rejected-20260824-v1
- Round-three evidence archive PR:
  [#87](https://github.com/changkong66/CyberControl/pull/87)
- Round-three evidence protected-main CI:
  [Run 32674327220](https://github.com/changkong66/CyberControl/actions/runs/32674327220),
  8/8
- Round-three current-state closure PR:
  [#88](https://github.com/changkong66/CyberControl/pull/88)
- PR #88 push / pull-request / protected-main runs:
  [32676245119](https://github.com/changkong66/CyberControl/actions/runs/32676245119),
  [32676665813](https://github.com/changkong66/CyberControl/actions/runs/32676665813), and
  [32676982606](https://github.com/changkong66/CyberControl/actions/runs/32676982606),
  each 8/8

No ADR 0026 diagnostic run, package, compiled-library digest or image digest
exists at design time. The capability PR and any later diagnostic evidence must
append their real identifiers through a new record; this proposed ADR must not
be rewritten to fabricate future results.

## Stop Conditions

Any source provenance, build reproducibility, profiler capability, environment,
interference, security, semantic, zero-tolerance or evidence-integrity failure
stops the applicable capability or diagnostic phase. Preserve the real failure
evidence and do not proceed to heap interpretation, a behavior candidate or a
formal replay.

Even if this design and its future capability pass, P2 remains frozen until a
real A/measurement/A' package passes every interference limit and identifies
one bounded, falsifiable owner. A subsequent behavior ADR and separately gated
minimal candidate would still be required. Gate C remains failed and Gate D-G
remain locked.
