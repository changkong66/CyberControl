# Phase 7 Academic Golden Facts

This directory contains the candidate accuracy set and its hash-bound reviewer
attestation for Phase 7 Gate B.

- `phase7-academic-golden-facts.v1.jsonl`: 72 original paraphrased C3 academic
  claims covering 24 automatic-control topics. The expected outcomes are
  balanced across `SUPPORTED`, `CONTRADICTED`, and
  `INSUFFICIENT_EVIDENCE`.
- `phase7-academic-golden-review.v1.json`: the reviewer identity, qualification,
  disclosed owner conflict, policy version, source-ledger hash, facts hash, and
  decision.

The source and rights ledger is
`docs/system-acceptance/evidence/phase7-academic-source-ledger.v1.json`.
The governing policy is
`docs/system-acceptance/phase7-academic-review-policy.md`.

The human review decision is `ACCEPTED` and is valid only for the exact facts,
source-ledger, and review-policy SHA256 values recorded in the review file. Any
byte change to one of those files invalidates the attestation and requires a new
human review.

The set is scoped to Topic4 `C3_ACADEMIC` accuracy. It does not convert the
100,000-record synthetic retrieval corpus or Topic1 demonstration fixture into
academic evidence, and it does not by itself establish system acceptance.

Validate with:

```powershell
python tools/acceptance/build-phase7-dataset-inventory.py `
  --output docs/system-acceptance/evidence/phase7-dataset-inventory.json `
  --require-human-reviewed-golden
```

For the current hash-bound files, the human-review requirement must pass. This
does not by itself satisfy clean-source, accuracy, PostgreSQL isolation, CI,
protected-main merge, or mainline-replay gates.
