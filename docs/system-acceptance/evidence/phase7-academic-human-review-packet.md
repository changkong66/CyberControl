# Phase 7 Gate B Human Review Packet

## Review State

- Dataset: `phase7-academic-human-reviewed-facts.v1`
- Target module: `C3_ACADEMIC`
- Decision: `ACCEPTED`
- Reviewed at: `2026-07-21T19:04:42Z`
- Facts: 72
- Topics: 24
- Outcome balance: 24 `SUPPORTED`, 24 `CONTRADICTED`, 24
  `INSUFFICIENT_EVIDENCE`
- Difficulty balance: 30 foundational, 27 intermediate, 15 advanced
- Personal data: none
- Source prose, figures, and tables reproduced: none

## Exact Hash Binding

- Facts SHA256:
  `c6f70ff86b7803fa6a0a82bcf5742019c495d8941ed95e62f5e52ea9cf0332dd`
- Source ledger SHA256:
  `f683441fe1b23057e525fc839f5495d358e03bc3d8dd8f26aa2b8ca6a81b88cc`
- Review policy SHA256:
  `bc7a0ca0ca21b2e06bfa869e4d86a80e33ddaa1402df947df7c209c4f77fc12e`

Any byte change to one of these three files invalidates this `ACCEPTED`
decision and requires a new human review.

## Sources And Rights

| Source | Facts | License | Commercial use | Evidence |
| --- | ---: | --- | --- | --- |
| 2012 PID controller-design chapter | 30 | CC BY 3.0 | permitted with attribution | publisher PDF page 4 |
| 2025 digital PI implementation chapter | 21 | CC BY 4.0 | permitted with attribution | publisher PDF page 20 |
| 2025 unstable-system identification chapter | 18 | CC BY 4.0 | permitted with attribution | publisher PDF page 56 |
| 2025 negative-feedback estimator chapter | 3 | CC BY 4.0 | permitted with attribution | publisher PDF page 68 |

Both publisher PDFs were downloaded again on 2026-07-21 UTC. Their byte sizes
and SHA256 values matched the source ledger. Crossref metadata was checked for
both DOIs. The 2025 work has an explicitly documented metadata difference:
Crossref records an issued date in 2024, while the publisher PDF uses a 2025
copyright and first-publication year.

Noncommercial Caltech feedback-systems and Engineering LibreTexts materials were
excluded. The included set relies on two books from one publisher but four
independently authored chapters. This publisher concentration is a disclosed
v1 limitation; a later dataset version should add independently published
commercial-use sources before claiming broad external academic representativeness.

## Reviewer Disclosure

The reviewer is Wu Chuhan (吴楚涵), identified by the minimal repository subject
reference `github:changkong66`. The reviewer has self-attested the following
roles:

- project owner;
- dataset owner;
- responsible human reviewer;
- automatic-control subject-matter expert;
- education-technology subject-matter expert.

The ownership conflict is disclosed and accepted under the single-maintainer
policy. This is not represented as institutionally independent peer review.

## Review Checklist

The human reviewer confirmed:

1. every expected outcome is academically correct;
2. every insufficient-evidence case is genuinely under-specified;
3. each citation locator is adequate for the adjudication;
4. CC BY attribution and commercial-use boundaries are acceptable;
5. no source text, image, table, personal data, or production tenant data is
   embedded;
6. the exact three hashes above are the reviewed versions;
7. the disclosed owner conflict is acceptable for this Gate B decision.

## Recorded Confirmation

On 2026-07-22 Asia/Shanghai, Wu Chuhan supplied the following hash-bound
decision in the project task:

```text
I confirm and ACCEPT facts SHA256
c6f70ff86b7803fa6a0a82bcf5742019c495d8941ed95e62f5e52ea9cf0332dd,
source-ledger SHA256
f683441fe1b23057e525fc839f5495d358e03bc3d8dd8f26aa2b8ca6a81b88cc,
and review-policy SHA256
bc7a0ca0ca21b2e06bfa869e4d86a80e33ddaa1402df947df7c209c4f77fc12e.

I make this ACCEPTED decision as project owner, dataset owner, responsible
human reviewer, and an automatic-control and education-technology subject-matter
expert. I acknowledge and accept the disclosed owner conflict under the
single-maintainer policy, and I do not represent this as institutionally
independent peer review.
```

The attestation records both `decision` and `rights_review_decision` as
`ACCEPTED`. Gate B still requires clean-commit validation, module-specific
accuracy execution, real PostgreSQL tenant-isolation evidence, full CI,
protected-main merge, and mainline replay before Gate B itself can be marked
accepted.
