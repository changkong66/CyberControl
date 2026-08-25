# ADR 0028: Phase 7 Gate C Twelfth Alpine Package Lock Reproducibility

Process Version: `Gate-C-12-v1.0`

- Status: Build reproducibility repair; no acceptance conclusion
- Formal Gate C attempt: no
- Acceptance claim: no
- Formal state: `RELEASE_CANDIDATE / PHASE7_GATE_C_FAILED_GATE_D_LOCKED`
- Root-cause domain: Phase 0 container build reproducibility
- Capacity policy revision: `Gate-C-12-capacity-v1.1`

## Observed Failure

The local Release Quality container build from the exact committed candidate
failed before an image was produced. The Dockerfile requested the mutable
Alpine `v3.24/main/x86_64/APKINDEX.tar.gz` URL with the recorded SHA256
`a50305859677aa2d293a6373b5ad0beb01e75f4b438d223a455c7156b41c913c`, while
the URL returned content with SHA256
`3c96cc80e3bd44a91d28954022df1ecb4603a575a3a247a1b162b8f5a0718090`.

The runtime stage does not resolve packages from that index. It installs only
the three explicitly downloaded APK files with `apk add --no-network
--allow-untrusted`, and each file already has a filename and SHA256 binding in
`tests/load/gate-c-build-inputs.v1.json`. Therefore the index download was an
unused mutable input and a direct source of false build failures.

## Decision

Remove the unused APKINDEX download and its standalone input-hash requirement.
Keep the exact content locks for `jemalloc-5.3.0-r6.apk`, `libgcc-15.2.0-r5.apk`
and `libstdc++-15.2.0-r5.apk`, and retain the offline installation and checksum
verification in the Dockerfile. Add tests that reject reintroduction of the
APKINDEX dependency. This is a build-input repair only; it does not change
application behavior, runtime allocator configuration, thresholds, workload,
aggregation, identity, PostgreSQL, RLS, Outbox or streaming semantics.

## Verification Contract

The repair is not accepted from static inspection alone. The exact new commit
must pass the complete Release Quality Gates and two independent clean
BuildKit builds. The resulting backend, frontend, mock-provider and load image
IDs must match between builders, carry the exact source/tree labels and receive
a new image lock and build receipt. The prior `567e3b4` lock remains historical
and cannot be reused after this commit.

If either builder still diverges, a package checksum fails, or any service
cannot be built from the exact commit, stop Phase 0 and archive the real build
failure as infrastructure evidence. Do not update a checksum to follow a
mutable remote response without a new content-addressed package source.

## Semantic Boundary

No migration `0001-0010`, RLS, `TenantContext`, SERIALIZABLE transaction,
C12 authorization, frozen threshold, frozen workload, Outbox atomicity,
idempotency, lease, retry, partition ordering, signed cursor or durable replay
behavior is changed. Gate D-G remain locked.
