# ADR-0015: Auditable Python SBOM License Evidence Completion

## Status

Accepted for Phase 7 Gate C tooling.

## Context

The locked `sseclient-py==1.9.0` wheel declares `Apache Software License v2`
and carries an embedded `LICENSE` file, but its metadata is not an SPDX
expression. CycloneDX generation therefore leaves the component license field
empty even though the exact artifact contains verifiable license evidence.

## Decision

Keep the already tested and locked SSE parser. Before the Python license policy
gate, run `tools/complete_python_sbom_license_evidence.py` with the committed
evidence manifest. The verifier must prove all of the following before adding
`Apache-2.0` to the SBOM:

1. the package name and version are present exactly once in `uv.lock`;
2. the evidence URL, wheel digest, and wheel size match the locked PyPI wheel;
3. the downloaded wheel digest is exact;
4. wheel metadata declares the expected package, version, license, and license
   file;
5. the embedded license file digest matches the evidence manifest; and
6. the installed distribution has the same identity, metadata, and license-file
   digest.

The completed SBOM records the artifact and license-file digests as properties.
No package is placed on a license allowlist without artifact and file evidence,
and the existing prohibited-license and unknown-license checks remain active.

## Consequences

The supply-chain gate performs a small, hash-verified download of the exact
locked wheel. A changed upstream artifact, installed package, or license file
fails closed and requires a reviewed evidence update. The load harness retains
the parser path already validated by the Gate C Smoke run.
